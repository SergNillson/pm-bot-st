"""CLOB API client for fetching order book data."""
import logging
from typing import Dict, Optional
import requests

logger = logging.getLogger(__name__)


class CLOBClient:
    """Client for Polymarket CLOB API."""
    
    BASE_URL = "https://clob.polymarket.com"
    
    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({"Accept": "application/json"})
    
    def get_midpoint(self, token_id: str) -> Optional[float]:
        """Get midpoint price for a token.
        
        Args:
            token_id: Token ID
            
        Returns:
            Midpoint price (0.0-1.0) or None if unavailable
        """
        try:
            url = f"{self.BASE_URL}/midpoint"
            params = {"token_id": token_id}
            
            resp = self.session.get(url, params=params, timeout=5)
            
            if resp.status_code == 200:
                data = resp.json()
                midpoint = data.get('mid')
                
                if midpoint is not None:
                    return float(midpoint)
            
            return None
        
        except Exception as e:
            logger.debug(f"Error fetching midpoint for {token_id[:20]}...: {e}")
            return None
    
    def get_price(self, token_id: str) -> Optional[float]:
        """Get current price for a token (alias for get_midpoint)."""
        return self.get_midpoint(token_id)
    
    def get_order_book(self, token_id: str) -> Optional[Dict]:
        """Get order book for a token.
        
        Returns:
            {
                'bids': [[price, size], ...],
                'asks': [[price, size], ...],
                'timestamp': int
            }
        """
        try:
            url = f"{self.BASE_URL}/book"
            params = {"token_id": token_id}
            
            resp = self.session.get(url, params=params, timeout=5)
            
            if resp.status_code == 200:
                data = resp.json()
                
                return {
                    'bids': data.get('bids', []),
                    'asks': data.get('asks', []),
                    'timestamp': data.get('timestamp', 0)
                }
            
            return None
        
        except Exception as e:
            logger.debug(f"Error fetching order book for {token_id[:20]}...: {e}")
            return None