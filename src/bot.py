"""Main Polymarket trading interface."""
import logging
from dataclasses import dataclass
from typing import List, Optional

logger = logging.getLogger(__name__)


@dataclass
class OrderResult:
    success: bool
    order_id: Optional[str] = None
    message: str = ""
    error: Optional[Exception] = None


class TradingBot:
    """Main Polymarket trading interface."""

    def __init__(self, config=None, private_key: str = "", config_path: str = None):
        from src.client import ClobClient, RelayerClient
        from src.config import Config
        from src.signer import OrderSigner

        if config_path is not None:
            self.config = Config.load_with_env(config_path)
        elif config is not None:
            self.config = config
        else:
            self.config = Config.from_env()

        self.private_key = private_key

        self.signer: Optional[OrderSigner] = None
        if private_key:
            try:
                self.signer = OrderSigner(private_key, chain_id=self.config.clob.chain_id)
            except Exception as e:
                logger.warning(f"Could not initialize OrderSigner: {e}")

        self.clob = ClobClient(
            host=self.config.clob.host,
            chain_id=self.config.clob.chain_id,
            api_key=self.config.builder.api_key,
            api_secret=self.config.builder.api_secret,
            api_passphrase=self.config.builder.api_passphrase,
            signature_type=self.config.clob.signature_type,
        )

        self.relayer = RelayerClient(
            host=self.config.relayer.host,
            tx_type=self.config.relayer.tx_type,
        )

    def is_initialized(self) -> bool:
        """Check if bot has valid credentials."""
        return bool(self.config.safe_address and self.private_key)

    async def place_order(
        self, token_id: str, price: float, size: float, side: str = "BUY"
    ) -> OrderResult:
        """Place a limit order."""
        from src.signer import Order

        try:
            order = Order(token_id=token_id, price=price, size=size, side=side)
            signature = self.signer.sign_order(order) if self.signer else ""
            order_data = {
                "token_id": token_id,
                "price": price,
                "size": size,
                "side": side,
                "nonce": order.nonce,
                "expiration": order.expiration,
                "signature": signature,
                "signature_type": self.config.clob.signature_type,
                "safe_address": self.config.safe_address,
            }
            result = self.clob.post_order(order_data)
            if result:
                return OrderResult(
                    success=True,
                    order_id=result.get("orderID") or result.get("order_id", ""),
                    message="Order placed",
                )
            return OrderResult(success=False, message="Empty response from CLOB")
        except Exception as e:
            logger.error(f"place_order error: {e}")
            return OrderResult(success=False, message=str(e), error=e)

    async def cancel_order(self, order_id: str) -> OrderResult:
        """Cancel a specific order."""
        try:
            result = self.clob.cancel_order(order_id)
            if result is not None:
                return OrderResult(success=True, order_id=order_id, message="Order cancelled")
            return OrderResult(success=False, message="Empty response from CLOB")
        except Exception as e:
            logger.error(f"cancel_order error: {e}")
            return OrderResult(success=False, message=str(e), error=e)

    async def cancel_all_orders(self) -> OrderResult:
        """Cancel all open orders."""
        try:
            result = self.clob.cancel_all_orders()
            if result is not None:
                return OrderResult(success=True, message="All orders cancelled")
            return OrderResult(success=False, message="Empty response from CLOB")
        except Exception as e:
            logger.error(f"cancel_all_orders error: {e}")
            return OrderResult(success=False, message=str(e), error=e)

    async def cancel_market_orders(self, market: str, asset_id: str) -> OrderResult:
        """Cancel all orders for a specific market."""
        try:
            result = self.clob.cancel_market_orders(market, asset_id)
            if result is not None:
                return OrderResult(success=True, message="Market orders cancelled")
            return OrderResult(success=False, message="Empty response from CLOB")
        except Exception as e:
            logger.error(f"cancel_market_orders error: {e}")
            return OrderResult(success=False, message=str(e), error=e)

    async def get_open_orders(self) -> List[dict]:
        """Get all open orders."""
        try:
            return self.clob.get_open_orders()
        except Exception as e:
            logger.error(f"get_open_orders error: {e}")
            return []

    async def get_trades(self, limit: int = 100) -> List[dict]:
        """Get trade history."""
        try:
            return self.clob.get_trades(limit=limit)
        except Exception as e:
            logger.error(f"get_trades error: {e}")
            return []

    async def get_order_book(self, token_id: str) -> dict:
        """Get the order book for a token."""
        try:
            return self.clob.get_order_book(token_id)
        except Exception as e:
            logger.error(f"get_order_book error: {e}")
            return {"bids": [], "asks": []}

    async def get_market_price(self, token_id: str) -> Optional[float]:
        """Get the current market price."""
        try:
            return self.clob.get_market_price(token_id)
        except Exception as e:
            logger.error(f"get_market_price error: {e}")
            return None
