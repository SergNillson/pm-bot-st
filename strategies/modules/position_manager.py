"""
Position Manager Module - Track and manage open positions with compound interest.
"""

import asyncio
import logging
import uuid
from typing import Dict, Optional, List
import time

logger = logging.getLogger(__name__)

# Risk parameters
MAX_BANKROLL_PER_WINDOW = 0.15  # 15% max per window
MIN_POSITION_SIZE = 2.0         # $2 minimum
MAX_POSITION_SIZE = 8.0         # $8 maximum


class PositionManager:
    """Track and manage open positions for delta-neutral trading.
    
    Implements:
    - Ladder/DCA entry (split orders into multiple ticks)
    - Compound interest bankroll tracking
    - Kelly-inspired position sizing
    - Low-liquidity hours detection
    """
    
    def __init__(self, bot, websocket_client=None, clob_client=None, initial_capital: float = 40.0):
        """
        Args:
            bot: TradingBot instance for order execution
            websocket_client: MarketWebSocket for price data (deprecated)
            clob_client: CLOBClient for price data via REST API
            initial_capital: Starting capital in USDC (default $40)
        """
        self.bot = bot
        self.ws = websocket_client
        self.clob = clob_client
        self.initial_capital = initial_capital
        
        # Position tracking: {market_id: {'up': {...}, 'down': {...}}}
        self.positions: Dict[str, Dict] = {}
        
        # P&L tracking
        self.total_pnl: float = 0.0
        self.bankroll: float = initial_capital
        
        # Trade history
        self.trade_history: List[Dict] = []
        self.wins: int = 0
        self.losses: int = 0
        
        # Dry run mode
        self.dry_run: bool = False
    
    def calculate_size(self, imbalance: float, bankroll: Optional[float] = None) -> float:
        """Calculate position size using Kelly-inspired formula.
        
        Size is inversely proportional to odds extremity.
        Larger positions when odds are near 50/50, smaller when skewed.
        
        Args:
            imbalance: Absolute distance from 0.50 (e.g., 0.02 for 48-52%)
            bankroll: Current bankroll (uses self.bankroll if None)
        
        Returns:
            Position size in USDC
        """
        if bankroll is None:
            bankroll = self.bankroll
        
        if imbalance > 0.20:
            return 0.0  # Skip - too risky
        
        max_size = bankroll * 0.10  # 10% of capital
        size = max_size / (1 + imbalance * 10)
        
        # Clamp range scales with bankroll relative to initial capital
        scale = bankroll / self.initial_capital if self.initial_capital > 0 else 1.0
        min_size = max(MIN_POSITION_SIZE, MIN_POSITION_SIZE * scale)
        max_allowed = min(MAX_POSITION_SIZE * scale, bankroll * MAX_BANKROLL_PER_WINDOW)
        
        return max(min_size, min(size, max_allowed))
    
    def apply_time_multiplier(self, size: float, hour_et: int) -> float:
        """Apply 20% size increase during low-liquidity hours (2-4 AM ET).
        
        Args:
            size: Base position size
            hour_et: Current hour in ET timezone (0-23)
        
        Returns:
            Adjusted position size
        """
        if hour_et in [2, 3]:
            return size * 1.2
        return size
    
    async def place_straddle(
        self,
        market_id: str,
        up_token: str,
        down_token: str,
        size: float,
    ) -> Dict:
        """Place ladder entry on both sides (straddle).
        
        Args:
            market_id: Unique identifier for the market window
            up_token: Token ID for UP outcome
            down_token: Token ID for DOWN outcome
            size: Target size per side in USDC
        
        Returns:
            Dict with 'up_orders' and 'down_orders' lists
        """
        logger.info(
            f"Placing straddle: market={market_id[:20]} size={size:.2f} each side"
        )
        
        up_orders = await self.ladder_buy(up_token, size, "BUY")
        down_orders = await self.ladder_buy(down_token, size, "BUY")
        
        # Track position
        self.positions[market_id] = {
            "up": {
                "token": up_token,
                "orders": up_orders,
                "size": size,
                "entry_time": time.time(),
            },
            "down": {
                "token": down_token,
                "orders": down_orders,
                "size": size,
                "entry_time": time.time(),
            },
            "total_cost": 0.0,      # Total USDC spent
            "total_received": 0.0,  # Total USDC received from sells
            "hedge_sells": [],       # List of (size, price) for hedge sells
            "hedge_buys": [],        # List of (size, price) for hedge buys
            "hedge_count": 0,        # Number of hedges executed (for limit enforcement)
            "last_hedge_time": 0,    # Timestamp of last hedge (for cooldown enforcement)
        }
        
        # Accumulate entry costs from straddle orders
        for order in up_orders + down_orders:
            if order.get("success"):
                self.positions[market_id]["total_cost"] += order.get("cost", 0)
        
        return {"up_orders": up_orders, "down_orders": down_orders}
    
    async def ladder_buy(
        self,
        token_id: str,
        total_size: float,
        side: str,
        ticks: int = 3,
    ) -> List[Dict]:
        """Split an order into multiple ticks for better average price.
        
        Example for a $6 buy with 3 ticks:
        - Tick 1: $2 @ 0.50
        - Tick 2: $2 @ 0.51
        - Tick 3: $2 @ 0.52
        
        Args:
            token_id: Token to trade
            total_size: Total USDC amount to place
            side: 'BUY' or 'SELL'
            ticks: Number of price levels to split across
        
        Returns:
            List of order result dicts
        """
        orders = []
        size_per_tick = total_size / ticks
        
        # Get base price from CLOB API (preferred) or WebSocket (fallback)
        base_price = None
        
        if self.clob:
            base_price = self.clob.get_price(token_id)
            if base_price:
                logger.debug(f"Got price from CLOB: {base_price:.4f}")
        
        if base_price is None and self.ws and hasattr(self.ws, 'get_mid_price'):
            base_price = self.ws.get_mid_price(token_id)
        
        if base_price is None:
            base_price = 0.50  # Default to 50/50
            logger.warning(f"No price available for {token_id[:20]}..., using default 0.50")
        
        for i in range(ticks):
            price = round(base_price + (i * 0.01), 4)
            # Clamp price to valid range
            price = max(0.01, min(0.99, price))
            
            order = await self._place_order(token_id, price, size_per_tick, side)
            orders.append(order)
            
            if i < ticks - 1:
                await asyncio.sleep(0.5)  # Small delay between ticks
        
        return orders
    
    async def _place_order(
        self, token_id: str, price: float, size: float, side: str
    ) -> Dict:
        """Place a single order (with dry-run support)."""
        if self.dry_run:
            order_id = f"dry_run_{uuid.uuid4().hex[:8]}"
            logger.info(
                f"🛡️ DRY RUN: {side} {size:.2f} @ {price:.4f} | token={token_id[:20]}..."
            )
            return {
                "success": True,
                "order_id": order_id,
                "price": price,
                "size": size,
                "side": side,
                "token_id": token_id,
                "dry_run": True,
                "cost": price * size if side == "BUY" else -(price * size),
            }
        
        result = await self.bot.place_order(token_id, price, size, side)
        return {
            "success": result.success,
            "order_id": result.order_id,
            "price": price,
            "size": size,
            "side": side,
            "token_id": token_id,
            "message": result.message,
            "cost": price * size if side == "BUY" else -(price * size),
        }
    
    def record_hedge_sell(self, market_id: str, size: float, price: float) -> None:
        """Record a hedge SELL transaction.
        
        Args:
            market_id: Market identifier
            size: Size sold
            price: Price per unit
        """
        if market_id in self.positions:
            if 'hedge_sells' not in self.positions[market_id]:
                self.positions[market_id]['hedge_sells'] = []
            self.positions[market_id]['hedge_sells'].append((size, price))
            # Increment hedge counter to enforce MAX_HEDGES_PER_POSITION limit
            self.positions[market_id]['hedge_count'] = (
                self.positions[market_id].get('hedge_count', 0) + 1
            )
            logger.info(f"Recorded hedge SELL: {size} @ {price:.4f}")
    
    def record_hedge_buy(self, market_id: str, size: float, price: float) -> None:
        """Record a hedge BUY transaction.
        
        Args:
            market_id: Market identifier
            size: Size bought
            price: Price per unit
        """
        if market_id in self.positions:
            if 'hedge_buys' not in self.positions[market_id]:
                self.positions[market_id]['hedge_buys'] = []
            self.positions[market_id]['hedge_buys'].append((size, price))
            logger.info(f"Recorded hedge BUY: {size} @ {price:.4f}")
    
    def get_total_hedge_proceeds(self, market_id: str) -> float:
        """Calculate net proceeds from hedging (sells - buys).
        
        Args:
            market_id: Market identifier
        
        Returns:
            Net hedge proceeds (positive means net profit from hedging)
        """
        if market_id not in self.positions:
            return 0.0
        
        pos = self.positions[market_id]
        hedge_sells = sum(size * price for size, price in pos.get('hedge_sells', []))
        hedge_buys = sum(size * price for size, price in pos.get('hedge_buys', []))
        return hedge_sells - hedge_buys
    
    def update_bankroll(self, pnl: float) -> float:
        """Update bankroll with profit/loss (compound interest).
        
        Args:
            pnl: Profit or loss in USDC (positive = profit, negative = loss)
        
        Returns:
            New bankroll value
        """
        self.total_pnl += pnl
        self.bankroll = self.initial_capital + self.total_pnl
        
        if pnl > 0:
            self.wins += 1
        elif pnl < 0:
            self.losses += 1
        
        self.trade_history.append({
            "pnl": pnl,
            "bankroll": self.bankroll,
            "timestamp": time.time(),
        })
        
        logger.info(
            f"Bankroll updated: ${self.bankroll:.2f} (P&L: ${pnl:+.2f}, "
            f"Total P&L: ${self.total_pnl:+.2f})"
        )
        
        return self.bankroll
    
    def get_current_bankroll(self) -> float:
        """Get current capital including all profits (compound interest)."""
        return self.bankroll
    
    def get_win_rate(self) -> float:
        """Get current win rate as a fraction (0-1)."""
        total = self.wins + self.losses
        if total == 0:
            return 0.0
        return self.wins / total
    
    def get_position(self, market_id: str) -> Optional[Dict]:
        """Get position for a market."""
        return self.positions.get(market_id)
    
    def close_position(self, market_id: str) -> Optional[Dict]:
        """Remove and return a position."""
        return self.positions.pop(market_id, None)
    
    def get_stats(self) -> Dict:
        """Get performance statistics."""
        return {
            "bankroll": self.bankroll,
            "initial_capital": self.initial_capital,
            "total_pnl": self.total_pnl,
            "wins": self.wins,
            "losses": self.losses,
            "win_rate": self.get_win_rate(),
            "open_positions": len(self.positions),
            "total_trades": len(self.trade_history),
        }