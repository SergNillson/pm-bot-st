"""Odds monitoring module for tracking market prices."""
import logging
import time
from typing import Dict, Optional

logger = logging.getLogger(__name__)


class OddsMonitor:
    """Monitor and track odds/prices for market tokens."""
    
    def __init__(self, clob_client=None):
        """Initialize with optional CLOB client for direct price fetching.
        
        Args:
            clob_client: CLOBClient instance for fetching prices via REST API
        """
        self.clob = clob_client
        self.price_history: Dict[str, list] = {}
        self.last_prices: Dict[str, float] = {}
        self.last_fetch_time: Dict[str, float] = {}
        self.fetch_interval = 2.0  # Fetch prices every 2 seconds
    
    def record_price(self, asset_id: str, price: float) -> None:
        """Record a price for an asset."""
        if price is None or price <= 0:
            return
        
        self.last_prices[asset_id] = price
        
        if asset_id not in self.price_history:
            self.price_history[asset_id] = []
        
        self.price_history[asset_id].append({
            'price': price,
            'timestamp': time.time()
        })
        
        # Keep only last 100 prices
        if len(self.price_history[asset_id]) > 100:
            self.price_history[asset_id] = self.price_history[asset_id][-100:]
    
    def fetch_price(self, asset_id: str) -> Optional[float]:
        """Fetch price from CLOB API if available.
        
        Args:
            asset_id: Token ID
            
        Returns:
            Price (0.0-1.0) or None
        """
        if not self.clob:
            return None
        
        now = time.time()
        last_fetch = self.last_fetch_time.get(asset_id, 0)
        
        # Rate limit: don't fetch more than once per fetch_interval
        if now - last_fetch < self.fetch_interval:
            return self.last_prices.get(asset_id)
        
        price = self.clob.get_price(asset_id)
        
        if price is not None:
            self.record_price(asset_id, price)
            self.last_fetch_time[asset_id] = now
            logger.debug(f"Fetched price for {asset_id[:20]}...: {price:.4f}")
        
        return price
    
    def get_last_price(self, asset_id: str) -> Optional[float]:
        """Get last recorded price for an asset, fetching if needed.
        
        Args:
            asset_id: Token ID
            
        Returns:
            Price (0.0-1.0) or None
        """
        # Try to fetch fresh price from CLOB
        if self.clob:
            price = self.fetch_price(asset_id)
            if price is not None:
                return price
        
        # Fallback to cached price
        return self.last_prices.get(asset_id)
    
    def get_current_odds(self, up_token: str, down_token: str) -> Dict:
        """Get current odds for Up and Down tokens.
        
        Args:
            up_token: Up token ID
            down_token: Down token ID
            
        Returns:
            {
                'up': float,        # Normalized probability 0.0-1.0
                'down': float,      # Normalized probability 0.0-1.0
                'imbalance': float, # abs(up - down)
                'valid': bool       # Whether data is valid
            }
        """
        up_price = self.get_last_price(up_token)
        down_price = self.get_last_price(down_token)
        
        if up_price is None or down_price is None:
            logger.debug(f"Missing prices: up={up_price}, down={down_price}")
            return {'up': 0, 'down': 0, 'imbalance': 1.0, 'valid': False}
        
        # Normalize to ensure sum = 1.0
        total = up_price + down_price
        if total <= 0:
            logger.debug(f"Invalid total: {total}")
            return {'up': 0, 'down': 0, 'imbalance': 1.0, 'valid': False}
        
        up_norm = up_price / total
        down_norm = down_price / total
        
        imbalance = abs(up_norm - down_norm)
        
        return {
            'up': up_norm,
            'down': down_norm,
            'imbalance': imbalance,
            'valid': True
        }
    
    def check_entry_conditions(self, up_token: str, down_token: str, max_imbalance: float = 0.20) -> bool:
        """Check if market conditions are suitable for entry.
        
        Args:
            up_token: Up token ID
            down_token: Down token ID
            max_imbalance: Maximum allowed imbalance (default 0.20 = 20%)
        
        Returns:
            True if conditions are good for entry
        """
        odds = self.get_current_odds(up_token, down_token)
        
        if not odds['valid']:
            logger.debug("Odds not valid")
            return False
        
        if odds['imbalance'] > max_imbalance:
            logger.debug(
                f"Imbalance too high: {odds['imbalance']:.3f} > {max_imbalance:.3f}"
            )
            return False
        
        return True
    
    def get_entry_size_category(self, imbalance: float) -> str:
        """Categorize entry based on imbalance.
        
        Returns: 'optimal', 'good', 'fair', or 'risky'
        """
        if imbalance <= 0.05:
            return 'optimal'
        elif imbalance <= 0.10:
            return 'good'
        elif imbalance <= 0.15:
            return 'fair'
        else:
            return 'risky'
    
    def get_price_trend(self, asset_id: str, lookback_seconds: float = 60.0) -> Optional[float]:
        """Calculate price trend (slope) over recent history.
        
        Returns:
            Positive = uptrend, Negative = downtrend, None = insufficient data
        """
        if asset_id not in self.price_history:
            return None
        
        history = self.price_history[asset_id]
        if len(history) < 2:
            return None
        
        now = time.time()
        recent = [h for h in history if now - h['timestamp'] <= lookback_seconds]
        
        if len(recent) < 2:
            return None
        
        # Simple linear regression slope
        prices = [h['price'] for h in recent]
        n = len(prices)
        
        x_mean = (n - 1) / 2
        y_mean = sum(prices) / n
        
        numerator = sum((i - x_mean) * (prices[i] - y_mean) for i in range(n))
        denominator = sum((i - x_mean) ** 2 for i in range(n))
        
        if denominator == 0:
            return 0.0
        
        slope = numerator / denominator
        return slope