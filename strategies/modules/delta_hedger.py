"""
Delta Hedger Module - Dynamic delta hedging logic.
"""

import asyncio
import logging
import time
from typing import Dict, Optional, Tuple

logger = logging.getLogger(__name__)

# Hedging parameters
HEDGE_THRESHOLD = 0.15   # Rebalance when delta > 15% of total value
SELL_FRACTION = 0.60     # Sell 60% of overweight side
BUY_FRACTION = 1.50      # Buy 150% on underweight side


class DeltaHedger:
    """Dynamic delta hedging for delta-neutral positions.
    
    Monitors UP and DOWN position values and rebalances when the
    delta (difference) exceeds a threshold.
    
    Delta = pos_up.value - pos_down.value
    When |delta| > HEDGE_THRESHOLD * total_value:
        - Sell 60% of overweight side
        - Buy 150% on underweight side
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
    
    def get_price(self, token_id: str) -> float:
        """Get current price for a token.
        
        Uses CLOB API if available, otherwise falls back to WebSocket or default.
        
        Args:
            token_id: Token ID
            
        Returns:
            Price (0.0-1.0)
        """
        if self.clob:
            price = self.clob.get_price(token_id)
            if price is not None:
                return price
        
        if self.ws and hasattr(self.ws, 'get_mid_price'):
            price = self.ws.get_mid_price(token_id)
            if price is not None:
                return price
        
        return 0.50  # Default to 50/50
    
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
        
        # Check cooldown (don't hedge more than once per 10 seconds)
        last_hedge_time = position.get("last_hedge_time", 0)
        if time.time() - last_hedge_time < 10:
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
        
        Sells 60% of overweight side and buys 150% on underweight side.
        
        Args:
            overweight_token: Token to reduce
            underweight_token: Token to increase
            overweight_size: Current size of overweight position
            underweight_size: Current size of underweight position
            market_id: Market identifier for position updates
        """
        # Calculate trade sizes
        sell_size = overweight_size * SELL_FRACTION
        buy_size = (underweight_size * BUY_FRACTION) - underweight_size
        
        if sell_size < 0.50:
            logger.debug(f"Sell size too small ({sell_size:.2f}), skipping rebalance")
            return
        
        logger.info(
            f"Rebalancing: SELL {sell_size:.2f} overweight, "
            f"BUY {buy_size:.2f} underweight"
        )
        
        # Get current prices
        overweight_price = self.get_price(overweight_token)
        underweight_price = self.get_price(underweight_token)
        
        # Execute sell on overweight side
        sell_result = await self.pm._place_order(
            overweight_token, overweight_price, sell_size, "SELL"
        )
        
        if sell_result.get("success"):
            # Execute buy on underweight side
            buy_result = await self.pm._place_order(
                underweight_token, underweight_price, buy_size, "BUY"
            )
            
            self.hedge_count += 1
            
            if buy_result.get("success"):
                logger.info(f"✅ Rebalanced successfully (hedge #{self.hedge_count})")
                
                # UPDATE POSITION SIZES AFTER HEDGING
                position = self.pm.get_position(market_id)
                if position:
                    # Determine which side is up/down
                    if position.get("up", {}).get("token") == overweight_token:
                        # UP was overweight
                        position["up"]["size"] -= sell_size
                        position["down"]["size"] += buy_size
                    else:
                        # DOWN was overweight
                        position["down"]["size"] -= sell_size
                        position["up"]["size"] += buy_size
                    
                    logger.debug(
                        f"Updated position sizes: up={position['up']['size']:.2f}, "
                        f"down={position['down']['size']:.2f}"
                    )
            else:
                logger.warning(
                    f"⚠️ Sell succeeded but buy failed: {buy_result.get('message', '')}"
                )
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
        }