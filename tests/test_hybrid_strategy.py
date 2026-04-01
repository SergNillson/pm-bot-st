"""Tests for the hybrid strategy modules and HybridStrategy class."""
import asyncio
import pytest
import time
from unittest.mock import MagicMock, AsyncMock, patch

from strategies.modules.arbitrage_detector import ArbitrageDetector
from strategies.modules.mean_reversion_scanner import MeanReversionScanner
from strategies.modules.market_maker import MarketMaker
from strategies.hybrid_strategy import HybridStrategy


# ============================================================================
# ArbitrageDetector Tests
# ============================================================================
class TestArbitrageDetector:
    def make_detector(self, threshold=0.95):
        clob = MagicMock()
        return ArbitrageDetector(clob, threshold=threshold)

    def test_initialization(self):
        clob = MagicMock()
        detector = ArbitrageDetector(clob, threshold=0.95)
        assert detector.clob is clob
        assert detector.threshold == pytest.approx(0.95)
        assert detector.dry_run is False

    def test_initialization_dry_run(self):
        clob = MagicMock()
        detector = ArbitrageDetector(clob, threshold=0.95, dry_run=True)
        assert detector.dry_run is True

    def test_check_opportunity_detected(self):
        detector = self.make_detector(threshold=0.95)
        assert detector.check_opportunity(0.45, 0.48) is True   # total 0.93

    def test_check_opportunity_not_detected(self):
        detector = self.make_detector(threshold=0.95)
        assert detector.check_opportunity(0.50, 0.50) is False  # total 1.00

    def test_check_opportunity_at_threshold(self):
        detector = self.make_detector(threshold=0.95)
        # Total exactly equal to threshold is NOT below threshold
        assert detector.check_opportunity(0.475, 0.475) is False  # total 0.95

    def test_check_opportunity_just_below_threshold(self):
        detector = self.make_detector(threshold=0.95)
        assert detector.check_opportunity(0.47, 0.47) is True  # total 0.94

    def test_calculate_profit_potential_basic(self):
        detector = self.make_detector()
        # up=0.45, down=0.48, size=10
        # cost = 10 * 0.93 = 9.30, revenue = 10 → profit = 0.70
        profit = detector.calculate_profit_potential(0.45, 0.48, 10.0)
        assert profit == pytest.approx(0.70, abs=1e-9)

    def test_calculate_profit_potential_zero_size(self):
        detector = self.make_detector()
        assert detector.calculate_profit_potential(0.45, 0.45, 0.0) == pytest.approx(0.0)

    def test_calculate_profit_potential_no_gap(self):
        detector = self.make_detector()
        # total = 1.00, no profit
        profit = detector.calculate_profit_potential(0.50, 0.50, 5.0)
        assert profit == pytest.approx(0.0, abs=1e-9)

    def test_custom_threshold(self):
        detector = self.make_detector(threshold=0.90)
        # total = 0.92 → above the 0.90 threshold → no opportunity
        assert detector.check_opportunity(0.46, 0.46) is False
        # total = 0.89 → below the 0.90 threshold → opportunity
        assert detector.check_opportunity(0.44, 0.45) is True

    @pytest.mark.asyncio
    async def test_execute_dry_run(self):
        clob = MagicMock()
        detector = ArbitrageDetector(clob, threshold=0.95, dry_run=True)
        bot = MagicMock()

        result = await detector.execute(bot, "up_tok", "down_tok", 0.45, 0.48, 6.0)

        bot.place_order.assert_not_called()
        assert result["up"]["success"] is True
        assert result["down"]["success"] is True
        assert result["up"]["order_id"] == "dry_run_up"
        assert result["down"]["order_id"] == "dry_run_down"

    @pytest.mark.asyncio
    async def test_execute_live(self):
        clob = MagicMock()
        detector = ArbitrageDetector(clob, threshold=0.95, dry_run=False)
        bot = MagicMock()
        bot.place_order = AsyncMock(return_value=MagicMock())

        await detector.execute(bot, "up_tok", "down_tok", 0.45, 0.48, 6.0)

        assert bot.place_order.call_count == 2
        calls = bot.place_order.call_args_list
        assert calls[0].args[0] == "up_tok"
        assert calls[1].args[0] == "down_tok"


# ============================================================================
# MeanReversionScanner Tests
# ============================================================================
class TestMeanReversionScanner:
    def make_scanner(self, threshold=0.08):
        clob = MagicMock()
        return MeanReversionScanner(clob, threshold=threshold)

    def test_initialization(self):
        clob = MagicMock()
        scanner = MeanReversionScanner(clob, threshold=0.08)
        assert scanner.clob is clob
        assert scanner.threshold == pytest.approx(0.08)

    def test_check_signal_no_signal(self):
        scanner = self.make_scanner()
        # Both prices within 8 cents of 0.50 → no signal
        result = scanner.check_signal(0.48, 0.52)
        assert result is None

    def test_check_signal_up_underpriced(self):
        scanner = self.make_scanner()
        # up = 0.40 < 0.42 (0.50 - 0.08) → signal
        result = scanner.check_signal(0.40, 0.60)
        assert result is not None
        assert result["side"] == "UP"
        assert result["entry_price"] == pytest.approx(0.40)
        assert result["target"] == pytest.approx(0.50)
        assert result["token"] == "up"

    def test_check_signal_down_underpriced(self):
        scanner = self.make_scanner()
        # down = 0.38 < 0.42 → signal
        result = scanner.check_signal(0.62, 0.38)
        assert result is not None
        assert result["side"] == "DOWN"
        assert result["entry_price"] == pytest.approx(0.38)
        assert result["token"] == "down"

    def test_check_signal_at_boundary(self):
        scanner = self.make_scanner(threshold=0.08)
        # price exactly at 0.50 - 0.08 = 0.42 → NOT below → no signal
        result = scanner.check_signal(0.42, 0.58)
        assert result is None

    def test_check_signal_just_below_boundary(self):
        scanner = self.make_scanner(threshold=0.08)
        # up = 0.4199 < 0.42 → signal
        result = scanner.check_signal(0.4199, 0.58)
        assert result is not None
        assert result["side"] == "UP"

    def test_calculate_expected_profit(self):
        scanner = self.make_scanner()
        # entry=0.42, target=0.50, size=5
        # profit = (0.50 - 0.42) * 5 = 0.40
        profit = scanner.calculate_expected_profit(0.42, target=0.50, size=5.0)
        assert profit == pytest.approx(0.40, abs=1e-9)

    def test_calculate_expected_profit_default_params(self):
        scanner = self.make_scanner()
        # entry=0.42, default target=0.50, default size=5.0
        profit = scanner.calculate_expected_profit(0.42)
        assert profit == pytest.approx(0.40, abs=1e-9)

    def test_custom_threshold(self):
        scanner = self.make_scanner(threshold=0.10)
        # up = 0.41 > lower_bound (0.50 - 0.10 = 0.40), so no signal expected
        result = scanner.check_signal(0.41, 0.59)
        assert result is None
        # up = 0.39 < 0.40 → signal
        result = scanner.check_signal(0.39, 0.61)
        assert result is not None

    def test_initialization_dry_run(self):
        clob = MagicMock()
        scanner = MeanReversionScanner(clob, threshold=0.08, dry_run=True)
        assert scanner.dry_run is True

    @pytest.mark.asyncio
    async def test_execute_dry_run(self):
        clob = MagicMock()
        scanner = MeanReversionScanner(clob, threshold=0.08, dry_run=True)
        bot = MagicMock()

        result = await scanner.execute(bot, "tok_up", 0.42, 5.0, target=0.50)

        bot.place_order.assert_not_called()
        assert result["success"] is True
        assert result["order_id"] == "dry_run_mr"

    @pytest.mark.asyncio
    async def test_execute_live(self):
        clob = MagicMock()
        scanner = MeanReversionScanner(clob, threshold=0.08, dry_run=False)
        bot = MagicMock()
        bot.place_order = AsyncMock(return_value=MagicMock())

        await scanner.execute(bot, "tok_up", 0.42, 5.0, target=0.50)

        bot.place_order.assert_called_once_with("tok_up", 0.42, 5.0, "BUY")


# ============================================================================
# MarketMaker Tests
# ============================================================================
class TestMarketMaker:
    def make_mm(self, spread=0.03):
        bot = MagicMock()
        clob = MagicMock()
        return MarketMaker(bot, clob, spread=spread), bot, clob

    def test_initialization(self):
        bot = MagicMock()
        clob = MagicMock()
        mm = MarketMaker(bot, clob, spread=0.03)
        assert mm.bot is bot
        assert mm.clob is clob
        assert mm.spread == pytest.approx(0.03)
        assert mm.dry_run is False

    def test_initialization_dry_run(self):
        bot = MagicMock()
        clob = MagicMock()
        mm = MarketMaker(bot, clob, spread=0.03, dry_run=True)
        assert mm.dry_run is True

    def test_should_make_market_balanced(self):
        mm, _, _ = self.make_mm()
        assert mm.should_make_market(0.50, 0.50) is True
        assert mm.should_make_market(0.45, 0.55) is True
        assert mm.should_make_market(0.50, 0.45) is True

    def test_should_make_market_imbalanced(self):
        mm, _, _ = self.make_mm()
        assert mm.should_make_market(0.70, 0.30) is False
        assert mm.should_make_market(0.44, 0.56) is False
        assert mm.should_make_market(0.50, 0.56) is False

    def test_should_make_market_boundary(self):
        mm, _, _ = self.make_mm()
        # exactly at 0.45 and 0.55 → should return True
        assert mm.should_make_market(0.45, 0.55) is True

    @pytest.mark.asyncio
    async def test_place_orders_dry_run(self):
        bot = MagicMock()
        clob = MagicMock()
        mm = MarketMaker(bot, clob, spread=0.04, dry_run=True)

        result = await mm.place_orders("token_123", 0.50, 5.0)

        bot.place_order.assert_not_called()
        assert result["buy"]["success"] is True
        assert result["sell"]["success"] is True
        assert result["buy"]["order_id"] == "dry_run_buy"
        assert result["sell"]["order_id"] == "dry_run_sell"

    @pytest.mark.asyncio
    async def test_place_orders_calls_bot(self):
        mm, bot, _ = self.make_mm(spread=0.04)
        bot.place_order = AsyncMock(return_value=MagicMock())

        result = await mm.place_orders("token_123", 0.50, 5.0)

        assert bot.place_order.call_count == 2
        calls = bot.place_order.call_args_list

        # BUY @ 0.48, SELL @ 0.52
        buy_call = calls[0]
        sell_call = calls[1]

        assert buy_call.args[1] == pytest.approx(0.48)  # buy price
        assert sell_call.args[1] == pytest.approx(0.52)  # sell price
        assert buy_call.args[3] == "BUY"
        assert sell_call.args[3] == "SELL"

        assert "buy" in result
        assert "sell" in result

    @pytest.mark.asyncio
    async def test_place_orders_price_clamping(self):
        mm, bot, _ = self.make_mm(spread=0.04)
        bot.place_order = AsyncMock(return_value=MagicMock())

        # Mid price very close to 0.01 → buy price clamped at 0.01
        await mm.place_orders("token_x", 0.02, 1.0)
        buy_price = bot.place_order.call_args_list[0].args[1]
        assert buy_price >= 0.01

    @pytest.mark.asyncio
    async def test_place_orders_price_clamping_high(self):
        mm, bot, _ = self.make_mm(spread=0.04)
        bot.place_order = AsyncMock(return_value=MagicMock())

        # Mid price very close to 0.99 → sell price clamped at 0.99
        await mm.place_orders("token_x", 0.98, 1.0)
        sell_price = bot.place_order.call_args_list[1].args[1]
        assert sell_price <= 0.99


# ============================================================================
# HybridStrategy Tests
# ============================================================================
class TestHybridStrategy:
    def _make_strategy(self, dry_run=True, capital=40.0):
        """Build a HybridStrategy with all external dependencies mocked."""
        with (
            patch("strategies.hybrid_strategy.GammaClient"),
            patch("strategies.hybrid_strategy.CLOBClient"),
            patch("strategies.hybrid_strategy.create_bot_from_env"),
        ):
            strategy = HybridStrategy(capital=capital, dry_run=dry_run)
        return strategy

    def test_initialization(self):
        strategy = self._make_strategy()
        assert strategy.capital == pytest.approx(40.0)
        assert strategy.dry_run is True
        assert strategy.stats["total_trades"] == 0
        assert strategy.stats["arb_trades"] == 0
        assert strategy.stats["mr_trades"] == 0
        assert strategy.stats["mm_trades"] == 0

    def test_dry_run_propagates_to_modules(self):
        """dry_run flag should be forwarded to all sub-strategy modules."""
        strategy = self._make_strategy(dry_run=True)
        assert strategy.arb_detector.dry_run is True
        assert strategy.market_maker.dry_run is True
        assert strategy.mr_scanner.dry_run is True

    def test_live_mode_modules_not_dry_run(self):
        """Modules should have dry_run=False when strategy is in live mode."""
        strategy = self._make_strategy(dry_run=False)
        assert strategy.arb_detector.dry_run is False
        assert strategy.market_maker.dry_run is False
        assert strategy.mr_scanner.dry_run is False

    def test_calculate_size_arbitrage(self):
        strategy = self._make_strategy()
        size = strategy.calculate_size("arbitrage", imbalance=0.0)
        # base_size = 40 * 0.10 = 4.0, arb = min(4 * 1.5, 40 * 0.15) = min(6, 6) = 6
        # clamped to MAX_POSITION_SIZE = 8
        assert size >= 2.0  # at least MIN_POSITION_SIZE
        assert size <= 8.0  # at most MAX_POSITION_SIZE

    def test_calculate_size_mean_reversion(self):
        strategy = self._make_strategy()
        size_low_imbalance = strategy.calculate_size("mean_reversion", 0.02)
        size_high_imbalance = strategy.calculate_size("mean_reversion", 0.15)
        assert size_low_imbalance >= size_high_imbalance

    def test_calculate_size_market_making(self):
        strategy = self._make_strategy()
        size = strategy.calculate_size("market_making")
        # base_size = 4.0, mm = 4.0 * 0.5 = 2.0 → clamped to MIN_POSITION_SIZE
        assert size >= 2.0

    def test_can_make_market_delegates(self):
        strategy = self._make_strategy()
        assert strategy._can_make_market(0.50, 0.50) is True
        assert strategy._can_make_market(0.70, 0.30) is False

    @pytest.mark.asyncio
    async def test_execute_arbitrage_increments_stats(self):
        strategy = self._make_strategy(dry_run=True)

        strategy.pm.place_straddle = AsyncMock(return_value={
            "up_orders": [], "down_orders": []
        })

        await strategy._execute_arbitrage(
            "market_arb", "up_token", "down_token", 0.45, 0.48
        )

        assert strategy.stats["arb_trades"] == 1
        assert strategy.stats["total_trades"] == 1

    @pytest.mark.asyncio
    async def test_execute_mean_reversion_increments_stats(self):
        strategy = self._make_strategy(dry_run=True)
        strategy.pm.ladder_buy = AsyncMock(return_value=[
            {"success": True, "cost": 2.0}
        ])

        signal = {"side": "UP", "entry_price": 0.40, "target": 0.50, "token": "up"}
        await strategy._execute_mean_reversion(
            "market_mr", signal, "up_token", "down_token"
        )

        assert strategy.stats["mr_trades"] == 1
        assert strategy.stats["total_trades"] == 1
        assert "market_mr" in strategy.pm.positions

    @pytest.mark.asyncio
    async def test_execute_market_making_increments_stats(self):
        strategy = self._make_strategy(dry_run=True)
        strategy.market_maker.place_orders = AsyncMock(return_value={
            "buy": MagicMock(), "sell": MagicMock()
        })

        await strategy._execute_market_making(
            "market_mm", "up_token", "down_token", 0.50, 0.50
        )

        assert strategy.stats["mm_trades"] == 1
        assert strategy.stats["total_trades"] == 1

    @pytest.mark.asyncio
    async def test_report_stats_respects_interval(self):
        """Stats should not print on every call – only after STATS_INTERVAL."""
        strategy = self._make_strategy()
        # Set last stats time to just now so interval has NOT elapsed
        strategy._last_stats_time = time.time()

        with patch.object(strategy.pm, "get_stats", return_value={
            "bankroll": 40.0, "total_pnl": 0.0, "win_rate": 0.0,
            "open_positions": 0,
        }) as mock_stats:
            await strategy._report_stats()
            mock_stats.assert_not_called()

    @pytest.mark.asyncio
    async def test_report_stats_prints_after_interval(self):
        """Stats should print when STATS_INTERVAL has elapsed."""
        strategy = self._make_strategy()
        # Force interval to have elapsed
        strategy._last_stats_time = time.time() - 999

        with patch.object(strategy.pm, "get_stats", return_value={
            "bankroll": 40.0, "total_pnl": 1.0, "win_rate": 0.75,
            "open_positions": 1,
        }) as mock_stats:
            await strategy._report_stats()
            mock_stats.assert_called_once()

    @pytest.mark.asyncio
    async def test_run_loop_iterates_markets(self):
        """run() should call the closer and stat reporter on each iteration."""
        strategy = self._make_strategy()

        strategy.gamma.find_active_windows = MagicMock(return_value=[])
        strategy.closer.check_and_close_expired = AsyncMock(return_value=[])
        strategy._report_stats = AsyncMock()

        # Run just one iteration then cancel
        iteration_count = 0

        async def fake_sleep(_):
            nonlocal iteration_count
            iteration_count += 1
            if iteration_count >= 1:
                raise asyncio.CancelledError

        with patch("asyncio.sleep", side_effect=fake_sleep):
            await strategy.run()

        strategy.closer.check_and_close_expired.assert_called()
        strategy._report_stats.assert_called()

    @pytest.mark.asyncio
    async def test_run_loop_priority_arbitrage(self):
        """Arbitrage should be executed before mean-reversion when both signal."""
        strategy = self._make_strategy()

        market = {
            "condition_id": "mkt1",
            "up_token": "up_token",
            "down_token": "down_token",
        }
        strategy.gamma.find_active_windows = MagicMock(return_value=[market])
        # Prices that trigger arbitrage (total 0.93 < 0.95)
        strategy.clob.get_price = MagicMock(side_effect=[0.45, 0.48])

        strategy._execute_arbitrage = AsyncMock()
        strategy._execute_mean_reversion = AsyncMock()
        strategy._execute_market_making = AsyncMock()
        strategy.closer.check_and_close_expired = AsyncMock(return_value=[])
        strategy._report_stats = AsyncMock()

        iteration = 0

        async def fake_sleep(_):
            nonlocal iteration
            iteration += 1
            raise asyncio.CancelledError

        with patch("asyncio.sleep", side_effect=fake_sleep):
            await strategy.run()

        strategy._execute_arbitrage.assert_called_once()
        strategy._execute_mean_reversion.assert_not_called()
        strategy._execute_market_making.assert_not_called()

    @pytest.mark.asyncio
    async def test_run_loop_skips_existing_positions(self):
        """Markets already tracked in pm.positions should be skipped."""
        strategy = self._make_strategy()

        market = {
            "condition_id": "existing_market",
            "up_token": "up_token",
            "down_token": "down_token",
        }
        strategy.gamma.find_active_windows = MagicMock(return_value=[market])
        # Pre-populate position
        strategy.pm.positions["existing_market"] = {}

        strategy.clob.get_price = MagicMock(return_value=0.50)
        strategy._execute_arbitrage = AsyncMock()
        strategy._execute_mean_reversion = AsyncMock()
        strategy._execute_market_making = AsyncMock()
        strategy.closer.check_and_close_expired = AsyncMock(return_value=[])
        strategy._report_stats = AsyncMock()

        async def fake_sleep(_):
            raise asyncio.CancelledError

        with patch("asyncio.sleep", side_effect=fake_sleep):
            await strategy.run()

        strategy._execute_arbitrage.assert_not_called()
        strategy._execute_mean_reversion.assert_not_called()
        strategy._execute_market_making.assert_not_called()
