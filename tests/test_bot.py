"""Tests for TradingBot and OrderResult from src/bot.py."""
import pytest
from unittest.mock import MagicMock, patch
from src.bot import TradingBot, OrderResult
from src.config import Config

TEST_PRIVATE_KEY = "0x" + "a" * 64
TEST_SAFE_ADDRESS = "0x" + "b" * 40


@pytest.fixture
def config():
    c = Config()
    c.safe_address = TEST_SAFE_ADDRESS
    return c


@pytest.fixture
def bot(config):
    return TradingBot(config=config, private_key=TEST_PRIVATE_KEY)


class TestOrderResult:
    def test_success_result(self):
        result = OrderResult(success=True, order_id="order_123", message="OK")
        assert result.success is True
        assert result.order_id == "order_123"

    def test_failure_result(self):
        result = OrderResult(success=False, message="Failed")
        assert result.success is False
        assert result.order_id is None

    def test_default_values(self):
        result = OrderResult(success=True)
        assert result.order_id is None
        assert result.message == ""
        assert result.error is None

    def test_failure_with_error(self):
        exc = ValueError("boom")
        result = OrderResult(success=False, message="boom", error=exc)
        assert result.error is exc


class TestTradingBot:
    def test_initialization(self, bot):
        assert bot is not None

    def test_is_initialized_with_credentials(self, bot):
        assert bot.is_initialized() is True

    def test_is_initialized_without_private_key(self, config):
        bot = TradingBot(config=config, private_key="")
        assert bot.is_initialized() is False

    def test_is_initialized_without_safe_address(self):
        config = Config()
        config.safe_address = ""
        bot = TradingBot(config=config, private_key=TEST_PRIVATE_KEY)
        assert bot.is_initialized() is False

    def test_is_initialized_both_missing(self):
        config = Config()
        config.safe_address = ""
        bot = TradingBot(config=config, private_key="")
        assert bot.is_initialized() is False

    def test_clob_client_exists(self, bot):
        assert bot.clob is not None

    def test_signer_initialized_with_key(self, bot):
        assert bot.signer is not None

    def test_signer_none_without_key(self, config):
        bot = TradingBot(config=config, private_key="")
        assert bot.signer is None

    @pytest.mark.asyncio
    async def test_get_open_orders_returns_list(self, bot):
        with patch.object(bot.clob, "get_open_orders", return_value=[]):
            orders = await bot.get_open_orders()
            assert isinstance(orders, list)

    @pytest.mark.asyncio
    async def test_get_trades_returns_list(self, bot):
        with patch.object(bot.clob, "get_trades", return_value=[]):
            trades = await bot.get_trades(limit=10)
            assert isinstance(trades, list)

    @pytest.mark.asyncio
    async def test_place_order_returns_order_result(self, bot):
        mock_result = {"order_id": "test_123", "status": "LIVE"}
        with patch.object(bot.clob, "post_order", return_value=mock_result):
            result = await bot.place_order("token_123", 0.5, 5.0, "BUY")
            assert isinstance(result, OrderResult)

    @pytest.mark.asyncio
    async def test_place_order_success(self, bot):
        mock_result = {"orderID": "abc123"}
        with patch.object(bot.clob, "post_order", return_value=mock_result):
            result = await bot.place_order("token_123", 0.5, 5.0, "BUY")
            assert result.success is True
            assert result.order_id == "abc123"

    @pytest.mark.asyncio
    async def test_place_order_none_response(self, bot):
        with patch.object(bot.clob, "post_order", return_value=None):
            result = await bot.place_order("token_123", 0.5, 5.0, "BUY")
            assert result.success is False

    @pytest.mark.asyncio
    async def test_place_order_exception(self, bot):
        with patch.object(bot.clob, "post_order", side_effect=Exception("network error")):
            result = await bot.place_order("token_123", 0.5, 5.0, "BUY")
            assert result.success is False
            assert result.error is not None

    @pytest.mark.asyncio
    async def test_cancel_order_returns_order_result(self, bot):
        with patch.object(bot.clob, "cancel_order", return_value={"deleted": True}):
            result = await bot.cancel_order("order_123")
            assert isinstance(result, OrderResult)

    @pytest.mark.asyncio
    async def test_cancel_order_success(self, bot):
        with patch.object(bot.clob, "cancel_order", return_value={"deleted": True}):
            result = await bot.cancel_order("order_123")
            assert result.success is True

    @pytest.mark.asyncio
    async def test_cancel_order_none_response(self, bot):
        with patch.object(bot.clob, "cancel_order", return_value=None):
            result = await bot.cancel_order("order_123")
            assert result.success is False

    @pytest.mark.asyncio
    async def test_cancel_all_orders_returns_order_result(self, bot):
        with patch.object(bot.clob, "cancel_all_orders", return_value={"deleted": True}):
            result = await bot.cancel_all_orders()
            assert isinstance(result, OrderResult)

    @pytest.mark.asyncio
    async def test_cancel_all_orders_success(self, bot):
        with patch.object(bot.clob, "cancel_all_orders", return_value={"deleted": True}):
            result = await bot.cancel_all_orders()
            assert result.success is True

    @pytest.mark.asyncio
    async def test_cancel_all_orders_exception(self, bot):
        with patch.object(bot.clob, "cancel_all_orders", side_effect=RuntimeError("fail")):
            result = await bot.cancel_all_orders()
            assert result.success is False

    @pytest.mark.asyncio
    async def test_get_order_book_returns_dict(self, bot):
        mock_ob = {"bids": [{"price": "0.49"}], "asks": [{"price": "0.51"}]}
        with patch.object(bot.clob, "get_order_book", return_value=mock_ob):
            ob = await bot.get_order_book("token_123")
            assert isinstance(ob, dict)

    @pytest.mark.asyncio
    async def test_get_order_book_exception_returns_empty(self, bot):
        with patch.object(bot.clob, "get_order_book", side_effect=Exception("fail")):
            ob = await bot.get_order_book("token_123")
            assert ob == {"bids": [], "asks": []}

    @pytest.mark.asyncio
    async def test_get_open_orders_exception_returns_empty(self, bot):
        with patch.object(bot.clob, "get_open_orders", side_effect=Exception("fail")):
            orders = await bot.get_open_orders()
            assert orders == []

    @pytest.mark.asyncio
    async def test_get_trades_exception_returns_empty(self, bot):
        with patch.object(bot.clob, "get_trades", side_effect=Exception("fail")):
            trades = await bot.get_trades()
            assert trades == []
