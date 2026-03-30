"""Polymarket Gamma API client for discovering markets."""
import logging
from datetime import datetime, timezone
from typing import Dict, List, Optional

import requests

logger = logging.getLogger(__name__)


class GammaClient:
    """Client for Polymarket Gamma API - discovers 15-minute and 5-minute markets."""

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

    def get_current_15m_market(self, coin: str = "BTC") -> Optional[Dict]:
        """Get the current active 15-minute Up/Down market for a coin."""
        markets = self.get_all_15m_markets()
        coin_upper = coin.upper()
        keywords = self.MARKET_KEYWORDS.get(coin_upper, [coin.lower()])
        now = datetime.now(timezone.utc)

        for market in markets:
            question = market.get("question", "").lower()
            if not any(kw in question for kw in keywords):
                continue

            end_date_str = market.get("end_date_iso", "") or market.get("endDate", "")
            end_date = self._parse_end_date(end_date_str)
            if end_date is not None and end_date < now:
                continue

            return market

        return None

    def get_market_info(self, coin: str = "BTC") -> Optional[Dict]:
        """Get market info with token IDs for Up and Down outcomes.

        Returns:
            {
                'question': str,
                'accepting_orders': bool,
                'token_ids': {'up': str, 'down': str},
                'end_date': str,
                'condition_id': str,
            }
        """
        markets = self.get_all_15m_markets()
        coin_upper = coin.upper()
        keywords = self.MARKET_KEYWORDS.get(coin_upper, [coin.lower()])
        now = datetime.now(timezone.utc)

        for market in markets:
            question = market.get("question", "").lower()
            if not any(kw in question for kw in keywords):
                continue

            end_date_str = market.get("end_date_iso", "") or market.get("endDate", "")
            end_date = self._parse_end_date(end_date_str)
            if end_date is not None and end_date < now:
                continue

            tokens = market.get("tokens", [])
            up_token = None
            down_token = None

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

            return {
                "question": market.get("question", ""),
                "accepting_orders": market.get("accepting_orders", False),
                "token_ids": {"up": up_token, "down": down_token},
                "end_date": end_date_str,
                "condition_id": market.get("condition_id", ""),
            }

        return None

    def get_all_15m_markets(self) -> List[Dict]:
        """Get all active 15-minute markets from Gamma API."""
        try:
            params = {
                "active": "true",
                "closed": "false",
                "limit": 100,
                "tag_slug": "crypto",
            }
            resp = self.session.get(f"{self.BASE_URL}/markets", params=params, timeout=10)
            resp.raise_for_status()
            data = resp.json()

            markets = []
            for market in data:
                question = market.get("question", "").lower()
                if any(
                    kw in question
                    for kw in [
                        "15-min", "15 min", "5-min", "5 min",
                        "up or down", "higher or lower",
                        "15-minute", "5-minute",
                    ]
                ):
                    markets.append(market)

            return markets

        except Exception as e:
            logger.error(f"Error fetching markets: {e}")
            return []

    def find_active_windows(self, coin: str = "BTC", windows: List[str] = None) -> List[Dict]:
        """Find active 5-min and 15-min windows for a coin.

        Returns list of:
        {
            'window': '5min' or '15min',
            'up_token': str,
            'down_token': str,
            'end_date': str,
            'question': str,
            'condition_id': str,
        }
        """
        if windows is None:
            windows = ["5min", "15min"]

        all_markets = self.get_all_15m_markets()
        coin_upper = coin.upper()
        keywords = self.MARKET_KEYWORDS.get(coin_upper, [coin.lower()])
        now = datetime.now(timezone.utc)
        result = []

        for market in all_markets:
            question = market.get("question", "").lower()

            if not any(kw in question for kw in keywords):
                continue

            window = None
            if any(kw in question for kw in ["5-min", "5 min", "5-minute"]):
                window = "5min"
            elif any(kw in question for kw in ["15-min", "15 min", "15-minute"]):
                window = "15min"
            else:
                continue

            if window not in windows:
                continue

            end_date_str = market.get("end_date_iso", "") or market.get("endDate", "")
            end_date = self._parse_end_date(end_date_str)
            if end_date is not None and end_date < now:
                continue

            tokens = market.get("tokens", [])
            up_token = None
            down_token = None

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

            result.append({
                "window": window,
                "up_token": up_token or "",
                "down_token": down_token or "",
                "end_date": end_date_str,
                "question": market.get("question", ""),
                "condition_id": market.get("condition_id", ""),
            })

        return result
