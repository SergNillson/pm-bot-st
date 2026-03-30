"""Tests for delta-neutral scalping strategy modules."""
import asyncio
import pytest
from unittest.mock import MagicMock, AsyncMock, patch
from strategies.modules.market_scanner import MarketScanner
from strategies.modules.odds_monitor import OddsMonitor
from strategies.modules.position_manager import PositionManager
from strategies.modules.delta_hedger import DeltaHedger


# ============================================================================
# Market Scanner Tests
# ============================================================================
class TestMarketScanner:
    def test_initialization(self):
        gamma = MagicMock()
        scanner = MarketScanner(gamma)
        assert scanner.gamma is gamma

    def test_find_active_windows_uses_gamma(self):
        gamma = MagicMock()
        gamma.find_active_windows.return_value = [
            {
                "window": "15min",
                "up_token": "up1",
                "down_token": "down1",
                "end_date": "2099-01-01T00:00:00Z",
                "question": "test?",
                "condition_id": "c1",
            }
        ]
        scanner = MarketScanner(gamma)

        result = scanner.find_active_windows("BTC")
        assert len(result) == 1
        assert result[0]["window"] == "15min"
        gamma.find_active_windows.assert_called_once_with(coin="BTC", windows=["5min", "15min"])

    def test_find_active_windows_empty(self):
        gamma = MagicMock()
        gamma.find_active_windows.return_value = []
        scanner = MarketScanner(gamma)

        result = scanner.find_active_windows("BTC")
        assert result == []

    def test_find_active_windows_error_returns_empty(self):
        gamma = MagicMock()
        gamma.find_active_windows.side_effect = Exception("API error")
        scanner = MarketScanner(gamma)

        result = scanner.find_active_windows("BTC")
        assert result == []

    def test_get_market_summary_no_markets(self):
        gamma = MagicMock()
        scanner = MarketScanner(gamma)
        summary = scanner.get_market_summary([])
        assert "No active" in summary

    def test_get_market_summary_with_markets(self):
        gamma = MagicMock()
        scanner = MarketScanner(gamma)
        markets = [{"window": "15min", "question": "Will BTC go up?", "end_date": "2099-01-01"}]
        summary = scanner.get_market_summary(markets)
        assert "15min" in summary
        assert "BTC" in summary

    def test_find_active_windows_custom_coin(self):
        gamma = MagicMock()
        gamma.find_active_windows.return_value = []
        scanner = MarketScanner(gamma)

        scanner.find_active_windows("ETH")
        gamma.find_active_windows.assert_called_once_with(coin="ETH", windows=["5min", "15min"])


# ============================================================================
# Odds Monitor Tests
# ============================================================================
class TestOddsMonitor:
    def make_ws(self, up_price=0.50, down_price=0.50, liquidity=200):
        ws = MagicMock()
        ws.get_mid_price.side_effect = lambda t: up_price if "up" in t else down_price

        mock_ob = MagicMock()
        mock_ob.get_total_bid_liquidity.return_value = liquidity / 2
        mock_ob.get_total_ask_liquidity.return_value = liquidity / 2
        ws.get_orderbook.return_value = mock_ob

        return ws

    def test_initialization(self):
        ws = MagicMock()
        monitor = OddsMonitor(ws)
        assert monitor.ws is ws

    def test_get_current_odds_50_50(self):
        ws = self.make_ws(up_price=0.50, down_price=0.50)
        monitor = OddsMonitor(ws)

        odds = monitor.get_current_odds("up_token", "down_token")
        assert odds["valid"] is True
        assert odds["up"] == pytest.approx(0.50)
        assert odds["down"] == pytest.approx(0.50)
        assert odds["imbalance"] == pytest.approx(0.0)

    def test_get_current_odds_imbalance(self):
        ws = self.make_ws(up_price=0.55, down_price=0.45)
        monitor = OddsMonitor(ws)

        odds = monitor.get_current_odds("up_token", "down_token")
        assert odds["imbalance"] == pytest.approx(0.05)

    def test_get_current_odds_no_data(self):
        ws = MagicMock()
        ws.get_mid_price.return_value = None
        monitor = OddsMonitor(ws)

        odds = monitor.get_current_odds("up_token", "down_token")
        assert odds["valid"] is False

    def test_get_current_odds_valid_flag(self):
        ws = self.make_ws(up_price=0.48, down_price=0.52)
        monitor = OddsMonitor(ws)
        odds = monitor.get_current_odds("up_token", "down_token")
        assert odds["valid"] is True

    def test_check_entry_conditions_valid(self):
        ws = self.make_ws(up_price=0.50, down_price=0.50, liquidity=300)
        monitor = OddsMonitor(ws)

        assert monitor.check_entry_conditions("up_token", "down_token") is True

    def test_check_entry_conditions_too_imbalanced(self):
        ws = self.make_ws(up_price=0.75, down_price=0.25, liquidity=300)
        monitor = OddsMonitor(ws)

        assert monitor.check_entry_conditions("up_token", "down_token") is False

    def test_check_entry_conditions_low_liquidity(self):
        ws = self.make_ws(up_price=0.50, down_price=0.50, liquidity=10)
        monitor = OddsMonitor(ws)

        assert monitor.check_entry_conditions("up_token", "down_token") is False

    def test_check_entry_conditions_no_data(self):
        ws = MagicMock()
        ws.get_mid_price.return_value = None
        monitor = OddsMonitor(ws)

        assert monitor.check_entry_conditions("up_token", "down_token") is False

    def test_get_entry_size_category(self):
        ws = MagicMock()
        monitor = OddsMonitor(ws)

        assert monitor.get_entry_size_category(0.01) == "optimal"
        assert monitor.get_entry_size_category(0.03) == "good"
        assert monitor.get_entry_size_category(0.08) == "fair"
        assert monitor.get_entry_size_category(0.12) == "poor"
        assert monitor.get_entry_size_category(0.25) == "skip"


# ============================================================================
# Position Manager Tests
# ============================================================================
class TestPositionManager:
    def make_pm(self, capital=40.0):
        bot = MagicMock()
        ws = MagicMock()
        ws.get_mid_price.return_value = 0.50
        pm = PositionManager(bot, ws, initial_capital=capital)
        pm.dry_run = True
        return pm

    def test_initialization(self):
        pm = self.make_pm()
        assert pm.bankroll == pytest.approx(40.0)
        assert pm.total_pnl == pytest.approx(0.0)
        assert pm.wins == 0
        assert pm.losses == 0

    def test_calculate_size_at_50_50(self):
        pm = self.make_pm(40.0)
        size = pm.calculate_size(0.0)
        assert size >= 2.0
        assert size <= 8.0

    def test_calculate_size_high_imbalance(self):
        pm = self.make_pm(40.0)
        size = pm.calculate_size(0.25)
        assert size == 0.0

    def test_calculate_size_decreases_with_imbalance(self):
        pm = self.make_pm(40.0)
        size_50_50 = pm.calculate_size(0.01)
        size_skewed = pm.calculate_size(0.10)
        assert size_50_50 >= size_skewed

    def test_calculate_size_scales_with_bankroll(self):
        pm_small = self.make_pm(40.0)
        pm_large = self.make_pm(200.0)

        size_small = pm_small.calculate_size(0.05)
        size_large = pm_large.calculate_size(0.05)
        assert size_large > size_small

    def test_update_bankroll_profit(self):
        pm = self.make_pm(40.0)
        new_bankroll = pm.update_bankroll(5.0)

        assert new_bankroll == pytest.approx(45.0)
        assert pm.bankroll == pytest.approx(45.0)
        assert pm.total_pnl == pytest.approx(5.0)
        assert pm.wins == 1

    def test_update_bankroll_loss(self):
        pm = self.make_pm(40.0)
        new_bankroll = pm.update_bankroll(-3.0)

        assert new_bankroll == pytest.approx(37.0)
        assert pm.losses == 1

    def test_compound_interest(self):
        pm = self.make_pm(40.0)
        pm.update_bankroll(10.0)
        pm.update_bankroll(5.0)

        assert pm.get_current_bankroll() == pytest.approx(55.0)
        assert pm.total_pnl == pytest.approx(15.0)

    def test_apply_time_multiplier_low_liquidity(self):
        pm = self.make_pm()
        size = pm.apply_time_multiplier(10.0, hour_et=2)
        assert size == pytest.approx(12.0)

        size = pm.apply_time_multiplier(10.0, hour_et=3)
        assert size == pytest.approx(12.0)

    def test_apply_time_multiplier_normal_hours(self):
        pm = self.make_pm()
        size = pm.apply_time_multiplier(10.0, hour_et=12)
        assert size == pytest.approx(10.0)

    def test_win_rate_calculation(self):
        pm = self.make_pm()
        pm.update_bankroll(1.0)
        pm.update_bankroll(1.0)
        pm.update_bankroll(-1.0)

        assert pm.get_win_rate() == pytest.approx(2 / 3)

    def test_win_rate_no_trades(self):
        pm = self.make_pm()
        assert pm.get_win_rate() == 0.0

    @pytest.mark.asyncio
    async def test_ladder_buy_dry_run(self):
        pm = self.make_pm()
        with patch("asyncio.sleep", new_callable=AsyncMock):
            orders = await pm.ladder_buy("up_token", 6.0, "BUY", ticks=3)

        assert len(orders) == 3
        for order in orders:
            assert order["success"] is True
            assert order["dry_run"] is True
            assert order["size"] == pytest.approx(2.0)

    @pytest.mark.asyncio
    async def test_place_straddle_creates_position(self):
        pm = self.make_pm()
        with patch("asyncio.sleep", new_callable=AsyncMock):
            result = await pm.place_straddle("market_1", "up_token", "down_token", 6.0)

        assert "up_orders" in result
        assert "down_orders" in result
        assert pm.get_position("market_1") is not None

    def test_close_position(self):
        pm = self.make_pm()
        pm.positions["market_1"] = {"up": {}, "down": {}}

        pos = pm.close_position("market_1")
        assert pos is not None
        assert pm.get_position("market_1") is None

    def test_close_nonexistent_position(self):
        pm = self.make_pm()
        pos = pm.close_position("nonexistent")
        assert pos is None

    def test_get_stats(self):
        pm = self.make_pm(40.0)
        pm.update_bankroll(5.0)

        stats = pm.get_stats()
        assert stats["bankroll"] == pytest.approx(45.0)
        assert stats["total_pnl"] == pytest.approx(5.0)
        assert stats["wins"] == 1
        assert stats["total_trades"] == 1

    def test_get_stats_initial(self):
        pm = self.make_pm(40.0)
        stats = pm.get_stats()
        assert stats["bankroll"] == pytest.approx(40.0)
        assert stats["total_pnl"] == pytest.approx(0.0)
        assert stats["wins"] == 0
        assert stats["losses"] == 0


# ============================================================================
# Delta Hedger Tests
# ============================================================================
class TestDeltaHedger:
    def make_hedger(self, up_price=0.60, down_price=0.40):
        bot = MagicMock()
        ws = MagicMock()
        ws.get_mid_price.side_effect = lambda t: up_price if "up" in t else down_price
        pm = PositionManager(bot, ws, initial_capital=40.0)
        pm.dry_run = True

        hedger = DeltaHedger(bot, ws, pm)
        return hedger, pm

    def test_initialization(self):
        bot, ws, pm = MagicMock(), MagicMock(), MagicMock()
        hedger = DeltaHedger(bot, ws, pm)
        assert hedger.hedge_count == 0

    def test_calculate_delta_balanced(self):
        hedger, pm = self.make_hedger(up_price=0.50, down_price=0.50)
        delta, up_val, down_val = hedger.calculate_delta("up_t", "down_t", 10.0, 10.0)
        assert delta == pytest.approx(0.0)
        assert up_val == pytest.approx(5.0)
        assert down_val == pytest.approx(5.0)

    def test_calculate_delta_imbalanced(self):
        hedger, pm = self.make_hedger(up_price=0.70, down_price=0.30)
        delta, up_val, down_val = hedger.calculate_delta("up_t", "down_t", 10.0, 10.0)
        # delta = 7.0 - 3.0 = 4.0
        assert delta == pytest.approx(4.0)

    def test_calculate_delta_values(self):
        hedger, pm = self.make_hedger(up_price=0.60, down_price=0.40)
        delta, up_val, down_val = hedger.calculate_delta("up_t", "down_t", 20.0, 20.0)
        assert up_val == pytest.approx(12.0)
        assert down_val == pytest.approx(8.0)
        assert delta == pytest.approx(4.0)

    @pytest.mark.asyncio
    async def test_check_and_rebalance_no_position(self):
        hedger, pm = self.make_hedger()
        result = await hedger.check_and_rebalance("no_market", "up_t", "down_t")
        assert result is False

    @pytest.mark.asyncio
    async def test_check_and_rebalance_balanced_position(self):
        hedger, pm = self.make_hedger(up_price=0.50, down_price=0.50)
        pm.positions["market_1"] = {
            "up": {"token": "up_t", "size": 10.0},
            "down": {"token": "down_t", "size": 10.0},
        }

        result = await hedger.check_and_rebalance("market_1", "up_t", "down_t")
        assert result is False
        assert hedger.hedge_count == 0

    @pytest.mark.asyncio
    async def test_check_and_rebalance_triggers_rebalance(self):
        # UP at 80%, DOWN at 20% → large delta
        hedger, pm = self.make_hedger(up_price=0.80, down_price=0.20)
        pm.positions["market_1"] = {
            "up": {"token": "up_t", "size": 20.0},
            "down": {"token": "down_t", "size": 20.0},
        }

        with patch("asyncio.sleep", new_callable=AsyncMock):
            result = await hedger.check_and_rebalance("market_1", "up_t", "down_t")

        assert result is True
        assert hedger.hedge_count == 1

    def test_get_hedge_stats(self):
        hedger, pm = self.make_hedger()
        stats = hedger.get_hedge_stats()
        assert "hedge_count" in stats
        assert "hedge_threshold" in stats

    def test_get_hedge_stats_initial_count(self):
        hedger, pm = self.make_hedger()
        stats = hedger.get_hedge_stats()
        assert stats["hedge_count"] == 0
