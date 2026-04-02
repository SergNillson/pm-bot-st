"""
Delta Hedger Module - Dynamic delta hedging logic.
"""

import asyncio
import logging
import time
from typing import Dict, Optional, Tuple

from strategies.modules.odds_monitor import OddsMonitor

logger = logging.getLogger(__name__)

# Hedging parameters - OPTIMIZED FOR PROFITABILITY
HEDGE_THRESHOLD = 0.25          # Rebalance when delta > 25% (was 5%) - much less frequent
SELL_FRACTION = 0.50            # Sell 50% of overweight side (was 40%) - capture more profit
BUY_FRACTION = 1.00             # Kept for reference only - buy side is DISABLED in sell-only strategy
MAX_HEDGES_PER_POSITION = 1     # Maximum 1 hedge per position to cap spread costs
MIN_HEDGE_COOLDOWN = 90         # 90 seconds between hedges (was 20) - prevent overtrading


class DeltaHedger:
    """Dynamic delta hedging for delta-neutral positions.
    
    Monitors UP and DOWN position values and rebalances when the
    delta (difference) exceeds a threshold.
    
    Delta = pos_up.value - pos_down.value
    When |delta| > HEDGE_THRESHOLD * total_value:
        - Sell 50% of overweight side ONLY (no buy on underweight)
        - At most MAX_HEDGES_PER_POSITION hedges per position
    """
    
    def __init__(self, bot, websocket_client, position_manager, clob_client=None):
        """
        Args:
            bot: TradingBot instance for order execution
            websocket_client: MarketWebSocket for price data (deprecated)
            position_manager: PositionManager for position tracking
            clob_client: CLOBClient for price data via REST API
        """
        self.bot = bot
        self.ws = websocket_client
        self.pm = position_manager
        self.clob = clob_client
        self.hedge_count = 0
        # Initialize OddsMonitor with the best available CLOB client
        _clob = clob_client or (getattr(position_manager, 'clob', None))
        self._odds_monitor = OddsMonitor(_clob) if _clob else None
    
    def get_price(self, token_id: str) -> float:
        """Get current price for a token using OddsMonitor.
        
        Args:
            token_id: Token ID
            
        Returns:
            Price (0.0-1.0)
        """
        # Use pre-initialized OddsMonitor (handles caching/rate-limiting)
        if self._odds_monitor:
            price = self._odds_monitor.get_last_price(token_id)
            if price is not None:
                logger.debug(f"Price from OddsMonitor: {token_id[:8]}... = {price:.4f}")
                return price
        
        # Fallback to CLOB client directly
        if self.clob:
            price = self.clob.get_price(token_id)
            if price is not None:
                logger.debug(f"Price from CLOB: {token_id[:8]}... = {price:.4f}")
                return price
        
        logger.warning(f"⚠️ No price available for {token_id[:8]}..., defaulting to 0.50")
        return 0.50  # Last resort
    
    def calculate_delta(
        self,
        up_token: str,
        down_token: str,
        up_size: float,
        down_size: float,
    ) -> Tuple[float, float, float]:
        """Calculate the current delta between UP and DOWN positions.
        
        Args:
            up_token: Token ID for UP outcome
            down_token: Token ID for DOWN outcome
            up_size: Current size of UP position
            down_size: Current size of DOWN position
        
        Returns:
            Tuple of (delta, up_value, down_value) where:
                delta = up_value - down_value
                up_value = up_price * up_size
                down_value = down_price * down_size
        """
        up_price = self.get_price(up_token)
        down_price = self.get_price(down_token)
        
        up_value = up_price * up_size
        down_value = down_price * down_size
        delta = up_value - down_value
        
        logger.debug(
            f"Delta calc: up={up_price:.4f}×{up_size:.2f}=${up_value:.2f}, "
            f"down={down_price:.4f}×{down_size:.2f}=${down_value:.2f}, "
            f"delta=${delta:.2f}"
        )
        
        return delta, up_value, down_value
    
    async def check_and_rebalance(
        self, market_id: str, up_token: str, down_token: str
    ) -> bool:
        """Check delta and rebalance if needed.
        
        Args:
            market_id: Market identifier
            up_token: Token ID for UP outcome
            down_token: Token ID for DOWN outcome
        
        Returns:
            True if rebalancing was performed
        """
        position = self.pm.get_position(market_id)
        if not position:
            return False
        
        # Check hedge count limit - cap at MAX_HEDGES_PER_POSITION to prevent runaway costs
        hedge_count = position.get("hedge_count", 0)
        if hedge_count >= MAX_HEDGES_PER_POSITION:
            logger.debug(
                f"Max hedges reached ({MAX_HEDGES_PER_POSITION}), "
                f"skipping further rebalancing for {market_id}"
            )
            return False
        
        # Check cooldown (don't hedge more than once per MIN_HEDGE_COOLDOWN seconds)
        last_hedge_time = position.get("last_hedge_time", 0)
        if time.time() - last_hedge_time < MIN_HEDGE_COOLDOWN:
            return False
        
        # Don't hedge if less than 30 seconds remain in the window
        # Default to time.time() so positions without entry_time are always eligible
        entry_time = position.get("up", {}).get("entry_time", time.time())
        time_elapsed = time.time() - entry_time

        if time_elapsed > 270:  # More than 4.5 minutes elapsed (5min window)
            logger.debug("Too close to settlement, skipping hedge")
            return False
        
        up_size = position.get("up", {}).get("size", 0)
        down_size = position.get("down", {}).get("size", 0)
        
        if up_size <= 0 or down_size <= 0:
            return False
        
        delta, up_value, down_value = self.calculate_delta(
            up_token, down_token, up_size, down_size
        )
        total_value = up_value + down_value
        
        if total_value <= 0:
            return False
        
        relative_delta = abs(delta) / total_value
        
        if relative_delta > HEDGE_THRESHOLD:
            logger.info(
                f"⚖️ Delta imbalance detected: delta={delta:.4f} "
                f"({relative_delta:.1%} of total ${total_value:.2f})"
            )
            
            if delta > 0:
                # UP side is overweight
                overweight_token = up_token
                underweight_token = down_token
                overweight_size = up_size
                underweight_size = down_size
            else:
                # DOWN side is overweight
                overweight_token = down_token
                underweight_token = up_token
                overweight_size = down_size
                underweight_size = up_size
            
            await self.rebalance(
                overweight_token, underweight_token,
                overweight_size, underweight_size,
                market_id
            )
            
            # Update last hedge time
            position["last_hedge_time"] = time.time()
            
            return True
        
        return False
    
    async def rebalance(
        self,
        overweight_token: str,
        underweight_token: str,
        overweight_size: float,
        underweight_size: float,
        market_id: str,
    ) -> None:
        """Execute rebalancing trades.
        
        OPTIMIZED: Only sells overweight side, doesn't buy underweight.
        This captures profit from mean reversion without paying double spreads.
        
        Args:
            overweight_token: Token to reduce
            underweight_token: Token to increase (NOT USED in optimized version)
            overweight_size: Current size of overweight position
            underweight_size: Current size of underweight position (IGNORED)
            market_id: Market identifier for position updates
        """
        # Calculate sell size only - no buy on underweight side
        sell_size = overweight_size * SELL_FRACTION
        
        if sell_size < 0.50:
            logger.debug(f"Sell size too small ({sell_size:.2f}), skipping rebalance")
            return
        
        logger.info(
            f"Rebalancing: SELL {sell_size:.2f} overweight @ current price, "
            f"NOT buying underweight (let position settle naturally)"
        )
        
        # Get current price for overweight side
        overweight_price = self.get_price(overweight_token)
        
        # Execute sell on overweight side ONLY
        sell_result = await self.pm._place_order(
            overweight_token, overweight_price, sell_size, "SELL"
        )
        
        if sell_result.get("success"):
            self.hedge_count += 1
            logger.info(f"✅ Rebalanced successfully (hedge #{self.hedge_count}) - SELL ONLY strategy")
            
            # UPDATE POSITION SIZES AFTER HEDGING
            position = self.pm.get_position(market_id)
            if position:
                # Reduce the sold (overweight) side
                if position.get("up", {}).get("token") == overweight_token:
                    position["up"]["size"] -= sell_size
                else:
                    position["down"]["size"] -= sell_size
                
                logger.debug(
                    f"Updated position sizes: up={position['up']['size']:.2f}, "
                    f"down={position['down']['size']:.2f}"
                )
                
                # Track hedge revenue.
                # _place_order returns cost = -(price*size) for SELL (negative = received),
                # so subtracting it adds the received amount to total_received.
                sell_cost = sell_result.get("cost", 0)
                position["total_received"] -= sell_cost  # sell_cost is negative, so this adds
                
                # Record hedge transaction
                self.pm.record_hedge_sell(market_id, sell_size, overweight_price)
        else:
            logger.error(
                f"❌ Rebalance sell failed: {sell_result.get('message', '')}"
            )
    
    def get_hedge_stats(self) -> Dict:
        """Get hedging statistics."""
        return {
            "hedge_count": self.hedge_count,
            "hedge_threshold": HEDGE_THRESHOLD,
            "sell_fraction": SELL_FRACTION,
            "buy_fraction": BUY_FRACTION,
            "max_hedges_per_position": MAX_HEDGES_PER_POSITION,
            "min_hedge_cooldown": MIN_HEDGE_COOLDOWN,
        }