"""WebSocket client for Polymarket CLOB order book subscriptions."""
import asyncio
import json
import logging
import time
from typing import Any, Callable, Dict, List, Optional, Set

import websockets
from websockets.exceptions import ConnectionClosed

logger = logging.getLogger(__name__)


class OrderBookSnapshot:
    """Represents an order book snapshot."""

    def __init__(self, asset_id: str, timestamp: float, bids: List, asks: List):
        self.asset_id = asset_id
        self.timestamp = timestamp
        self.bids = bids  # List of [price, size]
        self.asks = asks  # List of [price, size]

    def best_bid(self) -> Optional[float]:
        """Get best bid price."""
        if self.bids:
            return float(self.bids[0][0]) if self.bids[0] else None
        return None

    def best_ask(self) -> Optional[float]:
        """Get best ask price."""
        if self.asks:
            return float(self.asks[0][0]) if self.asks[0] else None
        return None

    def mid_price(self) -> Optional[float]:
        """Calculate mid price."""
        bid = self.best_bid()
        ask = self.best_ask()
        if bid is not None and ask is not None:
            return (bid + ask) / 2.0
        return None


class PolymarketWebSocketClient:
    """WebSocket client for Polymarket CLOB."""

    def __init__(self, ws_url: str = "wss://ws-subscriptions-clob.polymarket.com/ws/market"):
        self.ws_url = ws_url
        self._ws: Optional[websockets.WebSocketClientProtocol] = None
        self._subscribed_assets: Set[str] = set()
        self._callbacks: Dict[str, List[Callable]] = {
            "book": [],
            "price": [],
            "trade": [],
        }
        self._running = False
        self._reconnect_delay = 5
        self._last_message_time = 0

    async def connect(self):
        """Connect to WebSocket."""
        try:
            self._ws = await websockets.connect(
                self.ws_url,
                ping_interval=20,
                ping_timeout=10,
                close_timeout=10,
            )
            self._running = True
            logger.info(f"WebSocket connected to {self.ws_url}")
            return True
        except Exception as e:
            logger.error(f"Failed to connect to WebSocket: {e}")
            return False

    async def disconnect(self):
        """Disconnect from WebSocket."""
        self._running = False
        if self._ws:
            try:
                await self._ws.close()
                logger.info("WebSocket disconnected")
            except Exception as e:
                logger.error(f"Error disconnecting WebSocket: {e}")

    async def subscribe(self, asset_ids: List[str]):
        """Subscribe to asset order books.
        
        Args:
            asset_ids: List of token IDs to subscribe to
        """
        if not self._ws:
            logger.error("WebSocket not connected")
            return False

        try:
            # Subscribe to each asset
            for asset_id in asset_ids:
                subscribe_msg = {
                    "type": "subscribe",
                    "channel": "book",
                    "asset_id": asset_id,
                }
                await self._ws.send(json.dumps(subscribe_msg))
                self._subscribed_assets.add(asset_id)
                logger.debug(f"Subscribed to asset: {asset_id[:30]}...")

            logger.info(f"Subscribed to {len(asset_ids)} assets")
            return True

        except Exception as e:
            logger.error(f"Failed to subscribe: {e}")
            return False

    async def unsubscribe(self, asset_ids: List[str]):
        """Unsubscribe from asset order books."""
        if not self._ws:
            return

        try:
            for asset_id in asset_ids:
                unsubscribe_msg = {
                    "type": "unsubscribe",
                    "channel": "book",
                    "asset_id": asset_id,
                }
                await self._ws.send(json.dumps(unsubscribe_msg))
                self._subscribed_assets.discard(asset_id)

            logger.info(f"Unsubscribed from {len(asset_ids)} assets")

        except Exception as e:
            logger.error(f"Failed to unsubscribe: {e}")

    def on_book_update(self, callback: Callable):
        """Register callback for order book updates."""
        self._callbacks["book"].append(callback)

    def on_price_update(self, callback: Callable):
        """Register callback for price updates."""
        self._callbacks["price"].append(callback)

    def on_trade(self, callback: Callable):
        """Register callback for trades."""
        self._callbacks["trade"].append(callback)

    async def _handle_message(self, msg_str: str):
        """Handle incoming WebSocket message."""
        try:
            msg = json.loads(msg_str)
            
            # ИСПРАВЛЕНО: Проверяем тип данных
            if isinstance(msg, list):
                # Если пришёл список, обрабатываем каждый элемент
                for item in msg:
                    if isinstance(item, dict):
                        await self._process_single_message(item)
            elif isinstance(msg, dict):
                await self._process_single_message(msg)
            else:
                logger.debug(f"Unexpected message type: {type(msg)}")
        
        except json.JSONDecodeError as e:
            logger.warning(f"Could not parse message: {str(e)[:100]}")
        except Exception as e:
            logger.error(f"Error handling message: {e}")
            import traceback
            logger.debug(traceback.format_exc())

    async def _process_single_message(self, msg: dict):
        """Process a single message dictionary."""
        self._last_message_time = time.time()
        
        event_type = msg.get("event_type") or msg.get("type") or msg.get("channel")
        
        if not event_type:
            # Может быть это ответ на подписку
            if msg.get("success") or msg.get("subscribed"):
                logger.debug(f"Subscription confirmed: {msg}")
                return
            logger.debug(f"Message without event_type: {msg}")
            return
        
        if event_type == "book" or event_type == "orderbook":
            # Order book update
            asset_id = msg.get("asset_id") or msg.get("market")
            
            if asset_id and asset_id in self._subscribed_assets:
                snapshot = OrderBookSnapshot(
                    asset_id=asset_id,
                    timestamp=msg.get("timestamp", time.time()),
                    bids=msg.get("bids", []),
                    asks=msg.get("asks", []),
                )
                
                # Call registered callbacks
                for callback in self._callbacks.get("book", []):
                    try:
                        await callback(snapshot)
                    except Exception as e:
                        logger.error(f"Error in book callback: {e}")
        
        elif event_type == "price_change" or event_type == "price":
            # Price update
            asset_id = msg.get("asset_id") or msg.get("market")
            
            if asset_id:
                for callback in self._callbacks.get("price", []):
                    try:
                        await callback(msg)
                    except Exception as e:
                        logger.error(f"Error in price callback: {e}")
        
        elif event_type == "trade" or event_type == "match":
            # Trade event
            for callback in self._callbacks.get("trade", []):
                try:
                    await callback(msg)
                except Exception as e:
                    logger.error(f"Error in trade callback: {e}")
        
        else:
            logger.debug(f"Unhandled event type: {event_type}")

    async def run(self):
        """Run WebSocket message loop with auto-reconnect."""
        while self._running:
            try:
                if not self._ws:
                    await self.connect()
                    if not self._ws:
                        await asyncio.sleep(self._reconnect_delay)
                        continue

                # Receive and handle messages
                async for message in self._ws:
                    if not self._running:
                        break
                    
                    await self._handle_message(message)

            except ConnectionClosed:
                logger.warning("WebSocket connection closed, reconnecting...")
                self._ws = None
                await asyncio.sleep(self._reconnect_delay)

            except Exception as e:
                logger.error(f"WebSocket error: {e}")
                import traceback
                logger.error(traceback.format_exc())
                self._ws = None
                await asyncio.sleep(self._reconnect_delay)

        # Cleanup
        await self.disconnect()

    def is_connected(self) -> bool:
        """Check if WebSocket is connected."""
        return self._ws is not None and self._ws.open

    def get_subscribed_assets(self) -> Set[str]:
        """Get set of subscribed asset IDs."""
        return self._subscribed_assets.copy()

    async def wait_for_message(self, timeout: float = 30.0) -> bool:
        """Wait for at least one message to arrive."""
        start_time = time.time()
        initial_time = self._last_message_time
        
        while time.time() - start_time < timeout:
            if self._last_message_time > initial_time:
                return True
            await asyncio.sleep(0.1)
        
        return False