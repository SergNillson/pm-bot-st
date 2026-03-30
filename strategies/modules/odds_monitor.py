"""
Odds Monitor Module - Real-time odds tracking and entry condition checking.
"""

import logging
from typing import Optional, Dict, Tuple
from collections import defaultdict, deque
import time

logger = logging.getLogger(__name__)

# Risk parameters
ENTRY_IMBALANCE_MAX = 0.20   # Only enter within 20% of 50/50
MIN_LIQUIDITY = 100          # Minimum $100 in orderbook


class OddsMonitor:
    """Real-time odds tracking via WebSocket.
    
    Monitors bid/ask prices for Up and Down tokens and provides:
    - Current odds and imbalance calculations
    - Entry condition checks (odds gates)
    - Liquidity checks
    - Price history tracking
    """
    
    def __init__(self, websocket_client):
        """
        Args:
            websocket_client: An instance of MarketWebSocket
        """
        self.ws = websocket_client
        # Price history: {token_id: deque of (timestamp, price)}
        self.price_history: Dict[str, deque] = defaultdict(lambda: deque(maxlen=500))
    
    def get_current_odds(
        self, up_token: str, down_token: str
    ) -> Dict[str, Optional[float]]:
        """Get current odds for both sides of a market.
        
        Args:
            up_token: Token ID for the UP outcome
            down_token: Token ID for the DOWN outcome
        
        Returns:
            {
                'up': float or None,
                'down': float or None,
                'imbalance': float,  # abs(up_price - 0.50)
                'valid': bool,       # True if we have prices for both sides
            }
        """
        up_price = self.ws.get_mid_price(up_token)
        down_price = self.ws.get_mid_price(down_token)
        
        if up_price is not None and down_price is not None:
            imbalance = abs(up_price - 0.50)
            return {
                "up": up_price,
                "down": down_price,
                "imbalance": imbalance,
                "valid": True,
            }
        
        return {
            "up": up_price,
            "down": down_price,
            "imbalance": 1.0,  # Max imbalance if no data
            "valid": False,
        }
    
    def check_entry_conditions(self, up_token: str, down_token: str) -> bool:
        """Check whether current odds allow entry.
        
        Entry conditions:
        1. Both prices available
        2. Imbalance <= ENTRY_IMBALANCE_MAX (within 20% of 50/50)
        3. Sufficient liquidity in orderbook
        
        Args:
            up_token: Token ID for the UP outcome
            down_token: Token ID for the DOWN outcome
        
        Returns:
            True if entry conditions are met
        """
        odds = self.get_current_odds(up_token, down_token)
        
        if not odds["valid"]:
            logger.debug("Entry rejected: no price data available")
            return False
        
        if odds["imbalance"] > ENTRY_IMBALANCE_MAX:
            logger.debug(
                f"Entry rejected: imbalance {odds['imbalance']:.3f} > {ENTRY_IMBALANCE_MAX}"
            )
            return False
        
        # Check liquidity
        if not self._check_liquidity(up_token) or not self._check_liquidity(down_token):
            logger.debug("Entry rejected: insufficient liquidity")
            return False
        
        return True
    
    def _check_liquidity(self, token_id: str) -> bool:
        """Check if there is sufficient liquidity in the orderbook."""
        ob = self.ws.get_orderbook(token_id)
        if ob is None:
            return False
        
        total_liquidity = ob.get_total_bid_liquidity() + ob.get_total_ask_liquidity()
        return total_liquidity >= MIN_LIQUIDITY
    
    def get_entry_size_category(self, imbalance: float) -> str:
        """Get size category based on odds imbalance.
        
        Returns one of: 'optimal', 'good', 'fair', 'poor', 'skip'
        """
        if imbalance <= 0.02:
            return "optimal"   # 48-52%
        elif imbalance <= 0.05:
            return "good"      # 45-55%
        elif imbalance <= 0.10:
            return "fair"      # 40-60%
        elif imbalance <= 0.15:
            return "poor"      # 35-65%
        else:
            return "skip"      # Too risky
    
    def record_price(self, token_id: str, price: float):
        """Record a price observation for historical tracking."""
        self.price_history[token_id].append((time.time(), price))
    
    def get_price_trend(self, token_id: str, seconds: int = 30) -> Optional[float]:
        """Get price trend over the last N seconds.
        
        Returns:
            Positive = price going up, Negative = going down, None = not enough data
        """
        history = self.price_history.get(token_id)
        if not history or len(history) < 2:
            return None
        
        cutoff = time.time() - seconds
        recent = [(t, p) for t, p in history if t >= cutoff]
        
        if len(recent) < 2:
            return None
        
        oldest_price = recent[0][1]
        newest_price = recent[-1][1]
        return newest_price - oldest_price
