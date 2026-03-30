"""
Market Scanner Module - Discovers active BTC 5-min and 15-min markets.
"""

import logging
from typing import List, Optional, Dict
from datetime import datetime, timezone

logger = logging.getLogger(__name__)


class MarketScanner:
    """Find current 5-min and 15-min BTC (or other coin) markets.
    
    Uses GammaClient to discover active markets and returns structured
    window data including token IDs for Up and Down outcomes.
    """
    
    def __init__(self, gamma_client):
        """
        Args:
            gamma_client: An instance of GammaClient for market discovery
        """
        self.gamma = gamma_client
    
    def find_active_windows(self, coin: str = "BTC", windows: Optional[List[str]] = None) -> List[Dict]:
        """Find all active market windows for the given coin.
        
        Args:
            coin: The asset symbol (BTC, ETH, SOL, XRP)
            windows: List of window types to look for ('5min', '15min').
                     Defaults to both ['5min', '15min']
        
        Returns:
            List of dicts:
            [
                {
                    'window': '5min' or '15min',
                    'up_token': '0x...',
                    'down_token': '0x...',
                    'end_date': '2024-01-01T00:00:00Z',
                    'question': 'Will BTC go up in the next 5 minutes?',
                    'condition_id': '0x...',
                }
            ]
        """
        if windows is None:
            windows = ["5min", "15min"]
        
        try:
            # Use GammaClient's find_active_windows if available
            if hasattr(self.gamma, 'find_active_windows'):
                return self.gamma.find_active_windows(coin=coin, windows=windows)
            
            # Fallback: use get_all_15m_markets with manual filtering
            return self._find_windows_fallback(coin, windows)
            
        except Exception as e:
            logger.error(f"Error finding active windows: {e}")
            return []
    
    def _find_windows_fallback(self, coin: str, windows: List[str]) -> List[Dict]:
        """Fallback market discovery using get_all_15m_markets."""
        all_markets = self.gamma.get_all_15m_markets()
        coin_lower = coin.lower()
        now = datetime.now(timezone.utc)
        result = []
        
        for market in all_markets:
            question = market.get("question", "").lower()
            
            # Check coin keyword
            if coin_lower not in question and coin_lower + "coin" not in question:
                btc_aliases = {"btc": ["bitcoin", "btc"], "eth": ["ethereum", "eth"],
                               "sol": ["solana", "sol"], "xrp": ["xrp", "ripple"]}
                aliases = btc_aliases.get(coin_lower, [coin_lower])
                if not any(a in question for a in aliases):
                    continue
            
            # Determine window
            window = None
            if any(kw in question for kw in ["5-min", "5 min", "5-minute"]):
                window = "5min"
            elif any(kw in question for kw in ["15-min", "15 min", "15-minute"]):
                window = "15min"
            else:
                continue
            
            if window not in windows:
                continue
            
            # Check end date
            end_date_str = market.get("end_date_iso", "") or market.get("endDate", "")
            if end_date_str:
                try:
                    end_date = datetime.fromisoformat(end_date_str.replace("Z", "+00:00"))
                    if end_date < now:
                        continue
                except (ValueError, TypeError):
                    pass
            
            # Extract token IDs
            tokens = market.get("tokens", [])
            up_token, down_token = None, None
            
            for token in tokens:
                outcome = token.get("outcome", "").lower()
                if outcome in ("up", "yes", "higher"):
                    up_token = token.get("token_id", "")
                elif outcome in ("down", "no", "lower"):
                    down_token = token.get("token_id", "")
            
            if not up_token or not down_token:
                if len(tokens) >= 2:
                    up_token = tokens[0].get("token_id", "")
                    down_token = tokens[1].get("token_id", "")
            
            if up_token and down_token:
                result.append({
                    "window": window,
                    "up_token": up_token,
                    "down_token": down_token,
                    "end_date": end_date_str,
                    "question": market.get("question", ""),
                    "condition_id": market.get("condition_id", ""),
                })
        
        logger.info(f"Found {len(result)} active {coin} market windows")
        return result
    
    def get_market_summary(self, markets: List[Dict]) -> str:
        """Get a human-readable summary of markets."""
        if not markets:
            return "No active markets found"
        
        lines = [f"Active markets ({len(markets)}):"]
        for m in markets:
            lines.append(
                f"  [{m['window']}] {m['question'][:50]} | "
                f"ends: {m.get('end_date', 'unknown')}"
            )
        return "\n".join(lines)
