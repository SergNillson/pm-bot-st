"""Polymarket Gamma API client for discovering markets."""
import logging
import json
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Optional

import requests

logger = logging.getLogger(__name__)


class GammaClient:
    """Client for Polymarket Gamma API - discovers 5-minute BTC markets."""

    BASE_URL = "https://gamma-api.polymarket.com"

    MARKET_KEYWORDS = {
        "BTC": ["bitcoin", "btc"],
        "ETH": ["ethereum", "eth"],
        "SOL": ["solana", "sol"],
        "XRP": ["xrp", "ripple"],
    }

    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({"Accept": "application/json"})

    @staticmethod
    def _parse_end_date(end_date_str: str):
        """Parse an ISO 8601 date string, returning a timezone-aware datetime or None."""
        if not end_date_str:
            return None
        try:
            return datetime.fromisoformat(end_date_str.replace("Z", "+00:00"))
        except (ValueError, TypeError):
            return None

    def _get_current_5m_window_timestamp(self) -> int:
        """Calculate the Unix timestamp for the CURRENT active 5-minute window end time."""
        now = datetime.now(timezone.utc)
        minute = now.minute
        
        # Calculate the end of the current 5-minute window
        current_window_end_minute = ((minute // 5) + 1) * 5
        window_end = now.replace(minute=0, second=0, microsecond=0)
        window_end += timedelta(minutes=current_window_end_minute)
        
        return int(window_end.timestamp())

    def get_current_15m_market(self, coin: str = "BTC") -> Optional[Dict]:
        """Get the current active 5-minute Up/Down market for BTC."""
        return self.get_market_info(coin)

    def get_market_info(self, coin: str = "BTC") -> Optional[Dict]:
        """Get market info with token IDs for Up and Down outcomes.

        Returns:
            {
                'question': str,
                'accepting_orders': bool,
                'token_ids': {'up': str, 'down': str},
                'end_date': str,
                'condition_id': str,
                'active': bool,
                'closed': bool,
            }
        """
        if coin.upper() != "BTC":
            logger.warning(f"Only BTC is supported currently, got: {coin}")
            return None
        
        # Try current 5-minute window
        current_ts = self._get_current_5m_window_timestamp()
        
        logger.info(f"🔍 Looking for current 5m BTC market...")
        logger.info(f"   Current window end timestamp: {current_ts}")
        
        # Try current, next, and previous windows
        for offset, label in [(0, "current"), (-300, "previous"), (300, "next")]:
            ts = current_ts + offset
            slug = f"btc-updown-5m-{ts}"
            
            logger.info(f"   Trying {label} window: {slug}")
            
            try:
                resp = self.session.get(
                    f"{self.BASE_URL}/events",
                    params={"slug": slug},
                    timeout=10
                )
                
                if resp.status_code != 200:
                    logger.debug(f"   Status {resp.status_code} for {slug}")
                    continue
                
                data = resp.json()
                
                # Parse response
                if isinstance(data, list) and len(data) > 0:
                    event = data[0]
                elif isinstance(data, dict):
                    event = data
                else:
                    logger.debug(f"   Unexpected data format for {slug}")
                    continue
                
                # Check if closed
                if event.get('closed', False):
                    logger.debug(f"   Market is closed: {slug}")
                    continue
                
                logger.info(f"✅ Found active market: {event.get('title', 'N/A')}")
                
                # Get market data
                markets = event.get('markets', [])
                if not markets:
                    logger.error("   ❌ No markets in event")
                    continue
                
                market = markets[0]
                
                # ИСПРАВЛЕНО: Извлекаем token IDs из clobTokenIds
                clob_token_ids_str = market.get('clobTokenIds', '[]')
                
                try:
                    # Парсим JSON строку в список
                    clob_token_ids = json.loads(clob_token_ids_str)
                except (json.JSONDecodeError, TypeError):
                    logger.error(f"   ❌ Could not parse clobTokenIds: {clob_token_ids_str}")
                    continue
                
                # Извлекаем outcomes
                outcomes_str = market.get('outcomes', '[]')
                
                try:
                    outcomes = json.loads(outcomes_str)
                except (json.JSONDecodeError, TypeError):
                    logger.error(f"   ❌ Could not parse outcomes: {outcomes_str}")
                    continue
                
                if len(clob_token_ids) < 2:
                    logger.error(f"   ❌ Not enough token IDs: {len(clob_token_ids)}")
                    continue
                
                if len(outcomes) < 2:
                    logger.error(f"   ❌ Not enough outcomes: {len(outcomes)}")
                    continue
                
                # Сопоставляем outcomes с token IDs
                up_token = None
                down_token = None
                
                for i, outcome in enumerate(outcomes):
                    outcome_lower = str(outcome).lower()
                    
                    if outcome_lower in ("up", "yes", "higher"):
                        up_token = clob_token_ids[i]
                    elif outcome_lower in ("down", "no", "lower"):
                        down_token = clob_token_ids[i]
                
                # Если не нашли по названию, берём в порядке ["Up", "Down"]
                if not up_token or not down_token:
                    if "up" in str(outcomes[0]).lower():
                        up_token = clob_token_ids[0]
                        down_token = clob_token_ids[1]
                    else:
                        up_token = clob_token_ids[1]
                        down_token = clob_token_ids[0]
                
                if not up_token or not down_token:
                    logger.error("❌ Could not extract Up/Down token IDs")
                    logger.error(f"   Outcomes: {outcomes}")
                    logger.error(f"   Token IDs: {clob_token_ids}")
                    continue
                
                logger.info(f"   Up token: {up_token[:30]}...")
                logger.info(f"   Down token: {down_token[:30]}...")
                
                return {
                    "question": event.get('title', ''),
                    "accepting_orders": market.get('acceptingOrders', True),
                    "active": event.get('active', True),
                    "closed": event.get('closed', False),
                    "token_ids": {"up": up_token, "down": down_token},
                    "end_date": event.get('endDate', ''),
                    "condition_id": market.get('conditionId', ''),
                    "slug": slug,
                }
            
            except Exception as e:
                logger.debug(f"   Error trying {label} window: {e}")
                import traceback
                logger.debug(traceback.format_exc())
                continue
        
        logger.warning("❌ No active BTC 5m market found in any window")
        return None

    def get_all_15m_markets(self) -> List[Dict]:
        """Get current active 5-minute BTC market (backwards compatibility)."""
        market = self.get_market_info("BTC")
        return [market] if market else []

    def find_active_windows(self, coin: str = "BTC", windows: List[str] = None) -> List[Dict]:
        """Find active 5-min window for BTC."""
        if coin.upper() != "BTC":
            return []
        
        market_info = self.get_market_info("BTC")
        
        if not market_info:
            return []
        
        return [{
            "window": "5min",
            "up_token": market_info['token_ids']['up'],
            "down_token": market_info['token_ids']['down'],
            "end_date": market_info['end_date'],
            "question": market_info['question'],
            "condition_id": market_info['condition_id'],
            "accepting_orders": market_info['accepting_orders'],
        }]