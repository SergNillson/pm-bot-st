"""Tests for MarketWebSocket and OrderbookSnapshot from src/websocket_client.py."""
import asyncio
import json
import pytest
from src.websocket_client import MarketWebSocket, OrderbookSnapshot


class TestOrderbookSnapshot:
    def make_snapshot(self, bids, asks):
        return OrderbookSnapshot(
            asset_id="test_token",
            bids=[{"price": str(p), "size": "10"} for p in bids],
            asks=[{"price": str(p), "size": "10"} for p in asks],
        )

    def test_mid_price(self):
        snap = self.make_snapshot([0.48, 0.47], [0.52, 0.53])
        assert snap.mid_price == pytest.approx(0.50, abs=0.001)

    def test_best_bid(self):
        snap = self.make_snapshot([0.49, 0.48], [0.51])
        assert snap.best_bid == pytest.approx(0.49)

    def test_best_ask(self):
        snap = self.make_snapshot([0.49], [0.51, 0.52])
        assert snap.best_ask == pytest.approx(0.51)

    def test_spread(self):
        snap = self.make_snapshot([0.48], [0.52])
        assert snap.spread == pytest.approx(0.04)

    def test_empty_orderbook(self):
        snap = OrderbookSnapshot(asset_id="test", bids=[], asks=[])
        assert snap.mid_price == 0.0
        assert snap.best_bid == 0.0
        assert snap.best_ask == 0.0
        assert snap.spread == 0.0

    def test_liquidity_calculation(self):
        snap = OrderbookSnapshot(
            asset_id="test",
            bids=[{"price": "0.5", "size": "100"}],
            asks=[{"price": "0.6", "size": "200"}],
        )
        assert snap.get_total_bid_liquidity() == pytest.approx(50.0)
        assert snap.get_total_ask_liquidity() == pytest.approx(120.0)

    def test_one_sided_mid_price_bids_only(self):
        snap = OrderbookSnapshot(
            asset_id="test",
            bids=[{"price": "0.45", "size": "10"}],
            asks=[],
        )
        assert snap.mid_price == pytest.approx(0.45)

    def test_one_sided_mid_price_asks_only(self):
        snap = OrderbookSnapshot(
            asset_id="test",
            bids=[],
            asks=[{"price": "0.55", "size": "10"}],
        )
        assert snap.mid_price == pytest.approx(0.55)

    def test_spread_one_sided_is_zero(self):
        snap = OrderbookSnapshot(
            asset_id="test",
            bids=[{"price": "0.48", "size": "10"}],
            asks=[],
        )
        assert snap.spread == 0.0

    def test_empty_liquidity(self):
        snap = OrderbookSnapshot(asset_id="test", bids=[], asks=[])
        assert snap.get_total_bid_liquidity() == 0.0
        assert snap.get_total_ask_liquidity() == 0.0


class TestMarketWebSocket:
    def test_initialization(self):
        ws = MarketWebSocket()
        assert ws._orderbooks == {}
        assert ws._subscribed_ids == []
        assert ws._running is False

    @pytest.mark.asyncio
    async def test_subscribe_adds_ids(self):
        ws = MarketWebSocket()
        await ws.subscribe(["token_1", "token_2"])
        assert "token_1" in ws._subscribed_ids
        assert "token_2" in ws._subscribed_ids

    @pytest.mark.asyncio
    async def test_subscribe_no_duplicates(self):
        ws = MarketWebSocket()
        await ws.subscribe(["token_1"])
        await ws.subscribe(["token_1", "token_2"])
        assert ws._subscribed_ids.count("token_1") == 1
        assert len(ws._subscribed_ids) == 2

    @pytest.mark.asyncio
    async def test_subscribe_replace(self):
        ws = MarketWebSocket()
        await ws.subscribe(["token_1", "token_2"])
        await ws.subscribe(["token_3"], replace=True)
        assert ws._subscribed_ids == ["token_3"]

    def test_on_book_decorator(self):
        ws = MarketWebSocket()

        @ws.on_book
        async def handler(snapshot):
            pass

        assert handler in ws._book_handlers

    def test_on_price_change_decorator(self):
        ws = MarketWebSocket()

        @ws.on_price_change
        async def handler(data):
            pass

        assert handler in ws._price_change_handlers

    def test_on_trade_decorator(self):
        ws = MarketWebSocket()

        @ws.on_trade
        async def handler(data):
            pass

        assert handler in ws._trade_handlers

    def test_get_orderbook_returns_none_for_unknown(self):
        ws = MarketWebSocket()
        assert ws.get_orderbook("unknown_token") is None

    def test_get_mid_price_returns_none_for_unknown(self):
        ws = MarketWebSocket()
        assert ws.get_mid_price("unknown_token") is None

    @pytest.mark.asyncio
    async def test_handle_book_message(self):
        ws = MarketWebSocket()
        received = []

        @ws.on_book
        async def handler(snapshot):
            received.append(snapshot)

        book_msg = json.dumps({
            "event_type": "book",
            "asset_id": "test_token",
            "bids": [{"price": "0.49", "size": "100"}],
            "asks": [{"price": "0.51", "size": "100"}],
        })

        await ws._handle_message(book_msg)

        assert len(received) == 1
        assert received[0].asset_id == "test_token"
        assert received[0].best_bid == pytest.approx(0.49)
        assert received[0].best_ask == pytest.approx(0.51)

    @pytest.mark.asyncio
    async def test_get_orderbook_after_book_message(self):
        ws = MarketWebSocket()

        book_msg = json.dumps({
            "event_type": "book",
            "asset_id": "test_token_123",
            "bids": [{"price": "0.48", "size": "50"}],
            "asks": [{"price": "0.52", "size": "50"}],
        })

        await ws._handle_message(book_msg)

        ob = ws.get_orderbook("test_token_123")
        assert ob is not None
        assert ob.mid_price == pytest.approx(0.50)

    @pytest.mark.asyncio
    async def test_get_mid_price_after_book_message(self):
        ws = MarketWebSocket()

        book_msg = json.dumps({
            "event_type": "book",
            "asset_id": "token_456",
            "bids": [{"price": "0.49", "size": "100"}],
            "asks": [{"price": "0.51", "size": "100"}],
        })

        await ws._handle_message(book_msg)

        price = ws.get_mid_price("token_456")
        assert price == pytest.approx(0.50)

    @pytest.mark.asyncio
    async def test_handle_invalid_json(self):
        ws = MarketWebSocket()
        # Should not raise
        await ws._handle_message("not valid json {{{")

    @pytest.mark.asyncio
    async def test_handle_unknown_event_type(self):
        ws = MarketWebSocket()
        msg = json.dumps({"event_type": "unknown_type", "data": "x"})
        # Should not raise
        await ws._handle_message(msg)

    @pytest.mark.asyncio
    async def test_multiple_book_messages_update_state(self):
        ws = MarketWebSocket()

        msg1 = json.dumps({
            "event_type": "book",
            "asset_id": "tok_a",
            "bids": [{"price": "0.40", "size": "10"}],
            "asks": [{"price": "0.60", "size": "10"}],
        })
        msg2 = json.dumps({
            "event_type": "book",
            "asset_id": "tok_a",
            "bids": [{"price": "0.45", "size": "10"}],
            "asks": [{"price": "0.55", "size": "10"}],
        })

        await ws._handle_message(msg1)
        await ws._handle_message(msg2)

        ob = ws.get_orderbook("tok_a")
        assert ob.mid_price == pytest.approx(0.50)

    @pytest.mark.asyncio
    async def test_subscribe_empty_list(self):
        ws = MarketWebSocket()
        await ws.subscribe([])
        assert ws._subscribed_ids == []
