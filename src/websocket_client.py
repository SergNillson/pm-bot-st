"""Real-time WebSocket client for Polymarket market data."""
import asyncio
import json
import logging
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

import websockets

logger = logging.getLogger(__name__)


@dataclass
class OrderbookSnapshot:
    """Snapshot of the orderbook for a single asset."""

    asset_id: str
    bids: List[Dict] = field(default_factory=list)  # [{"price": "0.50", "size": "100.0"}, ...]
    asks: List[Dict] = field(default_factory=list)

    @property
    def mid_price(self) -> float:
        """Get the mid price (average of best bid and best ask)."""
        if self.bids and self.asks:
            return (float(self.bids[0]["price"]) + float(self.asks[0]["price"])) / 2.0
        elif self.bids:
            return float(self.bids[0]["price"])
        elif self.asks:
            return float(self.asks[0]["price"])
        return 0.0

    @property
    def best_bid(self) -> float:
        """Get the best (highest) bid price."""
        return float(self.bids[0]["price"]) if self.bids else 0.0

    @property
    def best_ask(self) -> float:
        """Get the best (lowest) ask price."""
        return float(self.asks[0]["price"]) if self.asks else 0.0

    @property
    def spread(self) -> float:
        """Get the bid-ask spread."""
        if self.bids and self.asks:
            return float(self.asks[0]["price"]) - float(self.bids[0]["price"])
        return 0.0

    def get_total_bid_liquidity(self) -> float:
        """Get total USD value of bids."""
        return sum(float(b["price"]) * float(b.get("size", 0)) for b in self.bids)

    def get_total_ask_liquidity(self) -> float:
        """Get total USD value of asks."""
        return sum(float(a["price"]) * float(a.get("size", 0)) for a in self.asks)


class MarketWebSocket:
    """Real-time WebSocket client for Polymarket market data."""

    WS_URL = "wss://ws-subscriptions-clob.polymarket.com/ws/market"

    def __init__(self):
        self._orderbooks: Dict[str, OrderbookSnapshot] = {}
        self._book_handlers: List[Callable] = []
        self._price_change_handlers: List[Callable] = []
        self._trade_handlers: List[Callable] = []
        self._subscribed_ids: List[str] = []
        self._ws = None
        self._running = False

    def on_book(self, func: Callable) -> Callable:
        """Decorator to register a handler for book updates."""
        self._book_handlers.append(func)
        return func

    def on_price_change(self, func: Callable) -> Callable:
        """Decorator to register a handler for price changes."""
        self._price_change_handlers.append(func)
        return func

    def on_trade(self, func: Callable) -> Callable:
        """Decorator to register a handler for trade events."""
        self._trade_handlers.append(func)
        return func

    async def subscribe(self, asset_ids: List[str], replace: bool = False) -> None:
        """Subscribe to market data for the given asset IDs.

        Args:
            asset_ids: List of token/asset IDs to subscribe to
            replace: If True, replace existing subscriptions; otherwise append
        """
        if replace:
            self._subscribed_ids = list(asset_ids)
        else:
            for aid in asset_ids:
                if aid not in self._subscribed_ids:
                    self._subscribed_ids.append(aid)

        if self._ws is not None:
            try:
                subscribe_msg = {"assets_ids": self._subscribed_ids, "type": "MARKET"}
                await self._ws.send(json.dumps(subscribe_msg))
            except Exception as e:
                logger.warning(f"Could not send subscription: {e}")

    async def run(self, auto_reconnect: bool = True) -> None:
        """Start the WebSocket connection and listen for messages.

        Args:
            auto_reconnect: If True, automatically reconnect on disconnection
        """
        self._running = True

        while self._running:
            try:
                async with websockets.connect(self.WS_URL) as ws:
                    self._ws = ws
                    logger.info(f"WebSocket connected to {self.WS_URL}")

                    if self._subscribed_ids:
                        subscribe_msg = {"assets_ids": self._subscribed_ids, "type": "MARKET"}
                        await ws.send(json.dumps(subscribe_msg))
                        logger.info(f"Subscribed to {len(self._subscribed_ids)} assets")

                    async for message in ws:
                        if not self._running:
                            break
                        await self._handle_message(message)

            except Exception as e:
                logger.error(f"WebSocket error: {e}")
                self._ws = None

                if not auto_reconnect or not self._running:
                    break

                logger.info("Reconnecting in 5 seconds...")
                await asyncio.sleep(5)

        self._ws = None

    async def disconnect(self) -> None:
        """Close the WebSocket connection."""
        self._running = False
        if self._ws is not None:
            try:
                await self._ws.close()
            except Exception:
                pass
            self._ws = None

    def get_orderbook(self, asset_id: str) -> Optional[OrderbookSnapshot]:
        """Get the cached orderbook for an asset."""
        return self._orderbooks.get(asset_id)

    def get_mid_price(self, asset_id: str) -> Optional[float]:
        """Get the current mid price for an asset."""
        ob = self._orderbooks.get(asset_id)
        if ob is not None:
            return ob.mid_price
        return None

    async def _handle_message(self, raw_message: str) -> None:
        """Parse and dispatch incoming WebSocket messages."""
        try:
            data = json.loads(raw_message)
            event_type = data.get("event_type", "")

            if event_type == "book":
                await self._handle_book(data)
            elif event_type == "price_change":
                await self._handle_price_change(data)
            elif event_type == "last_trade_price":
                await self._handle_trade(data)

        except json.JSONDecodeError:
            logger.warning(f"Could not parse message: {raw_message[:100]}")
        except Exception as e:
            logger.error(f"Error handling message: {e}")

    async def _handle_book(self, data: Dict) -> None:
        """Handle a full orderbook snapshot."""
        asset_id = data.get("asset_id", "")
        if not asset_id:
            return

        snapshot = OrderbookSnapshot(
            asset_id=asset_id,
            bids=data.get("bids", []),
            asks=data.get("asks", []),
        )
        self._orderbooks[asset_id] = snapshot

        for handler in self._book_handlers:
            try:
                if asyncio.iscoroutinefunction(handler):
                    await handler(snapshot)
                else:
                    handler(snapshot)
            except Exception as e:
                logger.error(f"Error in book handler: {e}")

    async def _handle_price_change(self, data: Dict) -> None:
        """Handle a price change event (incremental update)."""
        asset_id = data.get("asset_id", "")
        if not asset_id:
            return

        ob = self._orderbooks.get(asset_id)
        if ob:
            changes = data.get("price_changes", [])
            for change in changes:
                side = change.get("side", "").lower()
                price = change.get("price", "")
                size = change.get("size", "0")

                target_list = ob.bids if side == "buy" else ob.asks

                if float(size) == 0:
                    target_list[:] = [x for x in target_list if x.get("price") != price]
                else:
                    existing = next((x for x in target_list if x.get("price") == price), None)
                    if existing:
                        existing["size"] = size
                    else:
                        target_list.append({"price": price, "size": size})

            # Re-sort once after processing all changes (bids desc, asks asc)
            ob.bids.sort(key=lambda x: float(x["price"]), reverse=True)
            ob.asks.sort(key=lambda x: float(x["price"]))

        for handler in self._price_change_handlers:
            try:
                if asyncio.iscoroutinefunction(handler):
                    await handler(data)
                else:
                    handler(data)
            except Exception as e:
                logger.error(f"Error in price change handler: {e}")

    async def _handle_trade(self, data: Dict) -> None:
        """Handle a last trade price event."""
        for handler in self._trade_handlers:
            try:
                if asyncio.iscoroutinefunction(handler):
                    await handler(data)
                else:
                    handler(data)
            except Exception as e:
                logger.error(f"Error in trade handler: {e}")
