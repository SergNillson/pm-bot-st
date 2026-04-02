"""Tests for delta-neutral scalping strategy modules."""
import asyncio
import pytest
import time
from unittest.mock import MagicMock, AsyncMock, patch
from strategies.modules.market_scanner import MarketScanner
from strategies.modules.odds_monitor import OddsMonitor
from strategies.modules.position_manager import PositionManager
from strategies.modules.delta_hedger import DeltaHedger
from strategies.modules.position_closer import PositionCloser, POSITION_EXPIRY_SECONDS, AVG_ENTRY_PRICE


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

    def test_record_hedge_sell(self):
        pm = self.make_pm()
        pm.positions["market_1"] = {
            "up": {}, "down": {},
            "total_cost": 0.0, "total_received": 0.0,
        }
        pm.record_hedge_sell("market_1", 1.5, 0.625)
        sells = pm.positions["market_1"]["hedge_sells"]
        assert len(sells) == 1
        assert sells[0] == (1.5, 0.625)

    def test_record_hedge_sell_nonexistent_market(self):
        pm = self.make_pm()
        # Should not raise any exception and positions dict should remain unchanged
        pm.record_hedge_sell("no_market", 1.0, 0.50)
        assert "no_market" not in pm.positions

    def test_record_hedge_buy(self):
        pm = self.make_pm()
        pm.positions["market_1"] = {
            "up": {}, "down": {},
            "total_cost": 0.0, "total_received": 0.0,
        }
        pm.record_hedge_buy("market_1", 0.75, 0.375)
        buys = pm.positions["market_1"]["hedge_buys"]
        assert len(buys) == 1
        assert buys[0] == (0.75, 0.375)

    def test_record_hedge_buy_nonexistent_market(self):
        pm = self.make_pm()
        # Should not raise any exception and positions dict should remain unchanged
        pm.record_hedge_buy("no_market", 1.0, 0.50)
        assert "no_market" not in pm.positions

    def test_get_total_hedge_proceeds_no_hedges(self):
        pm = self.make_pm()
        pm.positions["market_1"] = {"up": {}, "down": {}}
        proceeds = pm.get_total_hedge_proceeds("market_1")
        assert proceeds == pytest.approx(0.0)

    def test_get_total_hedge_proceeds_with_hedges(self):
        pm = self.make_pm()
        pm.positions["market_1"] = {
            "up": {}, "down": {},
            "hedge_sells": [(1.2, 0.625)],   # sold 1.2 @ 0.625 = $0.75
            "hedge_buys": [(0.6, 0.375)],    # bought 0.6 @ 0.375 = $0.225
        }
        proceeds = pm.get_total_hedge_proceeds("market_1")
        # net = 0.75 - 0.225 = 0.525
        assert proceeds == pytest.approx(0.525)

    def test_get_total_hedge_proceeds_nonexistent_market(self):
        pm = self.make_pm()
        proceeds = pm.get_total_hedge_proceeds("no_market")
        assert proceeds == pytest.approx(0.0)

    def test_record_multiple_hedge_transactions(self):
        pm = self.make_pm()
        pm.positions["market_1"] = {
            "up": {}, "down": {},
            "total_cost": 0.0, "total_received": 0.0,
        }
        pm.record_hedge_sell("market_1", 1.0, 0.60)
        pm.record_hedge_sell("market_1", 0.5, 0.65)
        pm.record_hedge_buy("market_1", 0.8, 0.40)
        assert len(pm.positions["market_1"]["hedge_sells"]) == 2
        assert len(pm.positions["market_1"]["hedge_buys"]) == 1
        # net = (1.0*0.60 + 0.5*0.65) - (0.8*0.40) = (0.60 + 0.325) - 0.32 = 0.605
        proceeds = pm.get_total_hedge_proceeds("market_1")
        assert proceeds == pytest.approx(0.605)


# ============================================================================
# Delta Hedger Tests
# ============================================================================
class TestDeltaHedger:
    def make_hedger(self, up_price=0.60, down_price=0.40):
        bot = MagicMock()
        ws = MagicMock()
        clob = MagicMock()
        clob.get_price.side_effect = lambda t: up_price if "up" in t else down_price
        pm = PositionManager(bot, ws, clob_client=clob, initial_capital=40.0)
        pm.dry_run = True

        hedger = DeltaHedger(bot, ws, pm, clob_client=clob)
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
            "up": {"token": "up_t", "size": 20.0, "entry_time": time.time()},
            "down": {"token": "down_t", "size": 20.0},
            "total_cost": 20.0,
            "total_received": 0.0,
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

    def test_hedge_threshold_is_five_percent(self):
        from strategies.modules.delta_hedger import HEDGE_THRESHOLD
        assert HEDGE_THRESHOLD == pytest.approx(0.05)

    @pytest.mark.asyncio
    async def test_rebalance_records_hedge_transactions(self):
        # UP at 80%, DOWN at 20% → large delta triggers rebalance
        hedger, pm = self.make_hedger(up_price=0.80, down_price=0.20)
        pm.positions["market_1"] = {
            "up": {"token": "up_t", "size": 20.0, "entry_time": time.time()},
            "down": {"token": "down_t", "size": 20.0},
            "total_cost": 20.0,
            "total_received": 0.0,
        }

        with patch("asyncio.sleep", new_callable=AsyncMock):
            result = await hedger.check_and_rebalance("market_1", "up_t", "down_t")

        assert result is True
        position = pm.get_position("market_1")
        assert position is not None
        assert len(position.get("hedge_sells", [])) == 1
        assert len(position.get("hedge_buys", [])) == 1


# ============================================================================
# Position Closer Tests
# ============================================================================
class TestPositionCloser:
    def make_closer(self, up_price=0.98, down_price=0.02):
        gamma = MagicMock()
        clob = MagicMock()
        clob.get_price.side_effect = lambda t: up_price if "up" in t else down_price
        bot = MagicMock()
        ws = MagicMock()
        pm = PositionManager(bot, ws, initial_capital=40.0)
        pm.dry_run = True
        closer = PositionCloser(gamma, clob, pm)
        return closer, pm

    def _expired_position(self, up_token="up_t", down_token="down_t", size=2.0):
        """Return a position dict whose entry_time is in the past."""
        old_time = time.time() - POSITION_EXPIRY_SECONDS - 10
        return {
            "up": {"token": up_token, "size": size, "entry_time": old_time},
            "down": {"token": down_token, "size": size, "entry_time": old_time},
            "total_cost": size * 1.0,   # size shares bought at ~0.50 each side
            "total_received": 0.0,
        }

    def _fresh_position(self, up_token="up_t", down_token="down_t", size=2.0):
        """Return a position dict that has NOT expired yet."""
        return {
            "up": {"token": up_token, "size": size, "entry_time": time.time()},
            "down": {"token": down_token, "size": size, "entry_time": time.time()},
            "total_cost": size * 1.0,   # size shares bought at ~0.50 each side
            "total_received": 0.0,
        }

    def test_initialization(self):
        gamma, clob, pm = MagicMock(), MagicMock(), MagicMock()
        closer = PositionCloser(gamma, clob, pm)
        assert closer.gamma is gamma
        assert closer.clob is clob
        assert closer.pm is pm

    def test_get_price_uses_clob(self):
        closer, pm = self.make_closer(up_price=0.75)
        price = closer._get_price("up_t")
        assert price == pytest.approx(0.75)

    def test_get_price_defaults_when_clob_returns_none(self):
        closer, pm = self.make_closer()
        closer.clob.get_price.side_effect = None
        closer.clob.get_price.return_value = None
        price = closer._get_price("unknown_token")
        assert price == pytest.approx(0.50)

    def test_get_price_defaults_when_no_clob(self):
        gamma, pm = MagicMock(), MagicMock()
        closer = PositionCloser(gamma, None, pm)
        price = closer._get_price("some_token")
        assert price == pytest.approx(0.50)

    @pytest.mark.asyncio
    async def test_close_position_calculates_balanced_pnl(self):
        # up_price=0.98, down_price=0.02, size=2 each, total_cost=2.0
        # settlement  = 0.98*2 + 0.02*2 = 2.00
        # total_pnl   = (2.00 + 0.0) - 2.0 = 0.0
        closer, pm = self.make_closer(up_price=0.98, down_price=0.02)
        pm.positions["market_1"] = self._expired_position(size=2.0)
        position = pm.positions["market_1"]

        pnl = await closer.close_position("market_1", position)

        assert pnl == pytest.approx(0.0, abs=1e-9)

    @pytest.mark.asyncio
    async def test_close_position_zero_pnl_large_position(self):
        # up_price=0.80, down_price=0.20, size=5 each, total_cost=5.0
        # settlement  = 0.80*5 + 0.20*5 = 5.00
        # total_pnl   = (5.00 + 0.0) - 5.0 = 0.0
        closer, pm = self.make_closer(up_price=0.80, down_price=0.20)
        pm.positions["market_2"] = self._expired_position(size=5.0)
        position = pm.positions["market_2"]

        pnl = await closer.close_position("market_2", position)
        assert pnl == pytest.approx(0.0, abs=1e-9)

    @pytest.mark.asyncio
    async def test_close_position_updates_bankroll(self):
        # up_price=0.60, down_price=0.60 → both sides profitable
        # settlement  = 0.60*2 + 0.60*2 = 2.40, total_cost=2.0
        # total_pnl   = (2.40 + 0.0) - 2.0 = +0.40
        closer, pm = self.make_closer(up_price=0.60, down_price=0.60)
        pm.positions["market_3"] = self._expired_position(size=2.0)
        position = pm.positions["market_3"]
        initial_bankroll = pm.bankroll

        pnl = await closer.close_position("market_3", position)

        assert pnl == pytest.approx(0.40)
        assert pm.bankroll == pytest.approx(initial_bankroll + 0.40)

    @pytest.mark.asyncio
    async def test_close_position_removes_from_pm(self):
        closer, pm = self.make_closer()
        pm.positions["market_4"] = self._expired_position()
        position = pm.positions["market_4"]

        await closer.close_position("market_4", position)

        assert pm.get_position("market_4") is None

    @pytest.mark.asyncio
    async def test_check_and_close_expired_closes_expired(self):
        closer, pm = self.make_closer()
        pm.positions["old_market"] = self._expired_position()

        closed = await closer.check_and_close_expired()

        assert "old_market" in closed
        assert pm.get_position("old_market") is None

    @pytest.mark.asyncio
    async def test_check_and_close_expired_keeps_fresh(self):
        closer, pm = self.make_closer()
        pm.positions["fresh_market"] = self._fresh_position()

        closed = await closer.check_and_close_expired()

        assert "fresh_market" not in closed
        assert pm.get_position("fresh_market") is not None

    @pytest.mark.asyncio
    async def test_check_and_close_expired_mixed(self):
        closer, pm = self.make_closer()
        pm.positions["old"] = self._expired_position()
        pm.positions["new"] = self._fresh_position()

        closed = await closer.check_and_close_expired()

        assert "old" in closed
        assert "new" not in closed
        assert pm.get_position("old") is None
        assert pm.get_position("new") is not None

    @pytest.mark.asyncio
    async def test_check_and_close_expired_no_positions(self):
        closer, pm = self.make_closer()
        closed = await closer.check_and_close_expired()
        assert closed == []

    @pytest.mark.asyncio
    async def test_close_position_handles_error_gracefully(self):
        closer, pm = self.make_closer()
        # Pass a malformed position to trigger an error
        result = await closer.close_position("bad_market", None)
        assert result is None

