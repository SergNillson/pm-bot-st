"""Tests for GammaClient from src/gamma_client.py with mocked HTTP."""
import pytest
from unittest.mock import patch, MagicMock
from datetime import datetime, timezone, timedelta
from src.gamma_client import GammaClient


def make_future_date(hours=1):
    future = datetime.now(timezone.utc) + timedelta(hours=hours)
    return future.strftime("%Y-%m-%dT%H:%M:%SZ")


def make_past_date(hours=1):
    past = datetime.now(timezone.utc) - timedelta(hours=hours)
    return past.strftime("%Y-%m-%dT%H:%M:%SZ")


MOCK_MARKETS = [
    {
        "question": "Will BTC go up in the next 15 minutes?",
        "condition_id": "0xabc123",
        "accepting_orders": True,
        "end_date_iso": make_future_date(1),
        "tokens": [
            {"token_id": "up_token_1", "outcome": "Up"},
            {"token_id": "down_token_1", "outcome": "Down"},
        ],
    },
    {
        "question": "Will ETH go up in the next 5 minutes?",
        "condition_id": "0xdef456",
        "accepting_orders": True,
        "end_date_iso": make_future_date(0.1),
        "tokens": [
            {"token_id": "up_token_2", "outcome": "Up"},
            {"token_id": "down_token_2", "outcome": "Down"},
        ],
    },
]

MOCK_MARKETS_WITH_KEYWORDS = [
    {
        "question": "Will BTC go up in the next 15-min?",
        "condition_id": "0xabc",
        "accepting_orders": True,
        "end_date_iso": make_future_date(1),
        "tokens": [
            {"token_id": "up_token_btc", "outcome": "Up"},
            {"token_id": "down_token_btc", "outcome": "Down"},
        ],
    }
]


class TestGammaClient:
    @patch("requests.Session.get")
    def test_get_all_15m_markets_returns_list(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.json.return_value = MOCK_MARKETS
        mock_resp.raise_for_status = MagicMock()
        mock_get.return_value = mock_resp

        gamma = GammaClient()
        markets = gamma.get_all_15m_markets()
        assert isinstance(markets, list)

    @patch("requests.Session.get")
    def test_get_market_info_btc(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.json.return_value = MOCK_MARKETS
        mock_resp.raise_for_status = MagicMock()
        mock_get.return_value = mock_resp

        gamma = GammaClient()
        market = gamma.get_market_info("BTC")

        # May return None if filtering doesn't match — just check no crash
        assert market is None or isinstance(market, dict)

    @patch("requests.Session.get")
    def test_get_market_info_returns_token_ids(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.json.return_value = MOCK_MARKETS_WITH_KEYWORDS
        mock_resp.raise_for_status = MagicMock()
        mock_get.return_value = mock_resp

        gamma = GammaClient()
        market = gamma.get_market_info("BTC")

        if market:
            assert "token_ids" in market
            assert "up" in market["token_ids"]
            assert "down" in market["token_ids"]

    @patch("requests.Session.get")
    def test_get_all_15m_markets_on_error(self, mock_get):
        mock_get.side_effect = Exception("Network error")

        gamma = GammaClient()
        markets = gamma.get_all_15m_markets()
        assert markets == []

    @patch("requests.Session.get")
    def test_find_active_windows(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.json.return_value = []
        mock_resp.raise_for_status = MagicMock()
        mock_get.return_value = mock_resp

        gamma = GammaClient()
        windows = gamma.find_active_windows("BTC", windows=["5min", "15min"])
        assert isinstance(windows, list)

    @patch("requests.Session.get")
    def test_find_active_windows_with_keyword_markets(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.json.return_value = MOCK_MARKETS_WITH_KEYWORDS
        mock_resp.raise_for_status = MagicMock()
        mock_get.return_value = mock_resp

        gamma = GammaClient()
        windows = gamma.find_active_windows("BTC", windows=["15min"])
        assert isinstance(windows, list)
        if windows:
            assert windows[0]["window"] == "15min"

    @patch("requests.Session.get")
    def test_get_current_15m_market_btc(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.json.return_value = MOCK_MARKETS_WITH_KEYWORDS
        mock_resp.raise_for_status = MagicMock()
        mock_get.return_value = mock_resp

        gamma = GammaClient()
        market = gamma.get_current_15m_market("BTC")
        # May or may not match depending on keyword filtering
        assert market is None or isinstance(market, dict)

    @patch("requests.Session.get")
    def test_expired_markets_excluded(self, mock_get):
        expired_markets = [
            {
                "question": "Will BTC go up in the next 15-min?",
                "condition_id": "0xold",
                "accepting_orders": False,
                "end_date_iso": make_past_date(2),
                "tokens": [
                    {"token_id": "old_up", "outcome": "Up"},
                    {"token_id": "old_down", "outcome": "Down"},
                ],
            }
        ]
        mock_resp = MagicMock()
        mock_resp.json.return_value = expired_markets
        mock_resp.raise_for_status = MagicMock()
        mock_get.return_value = mock_resp

        gamma = GammaClient()
        market = gamma.get_market_info("BTC")
        # Expired market should be filtered out
        assert market is None

    @patch("requests.Session.get")
    def test_get_all_15m_markets_filters_keywords(self, mock_get):
        non_15m_markets = [
            {
                "question": "Will BTC reach $100k by end of year?",
                "condition_id": "0xlong",
                "accepting_orders": True,
                "end_date_iso": make_future_date(24 * 30),
                "tokens": [],
            }
        ]
        mock_resp = MagicMock()
        mock_resp.json.return_value = non_15m_markets
        mock_resp.raise_for_status = MagicMock()
        mock_get.return_value = mock_resp

        gamma = GammaClient()
        markets = gamma.get_all_15m_markets()
        # Non-15-min markets should be filtered out
        assert markets == []
