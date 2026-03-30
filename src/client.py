"""Polymarket API clients: CLOB (order submission) and Relayer (gasless transactions)."""
import hashlib
import hmac
import json
import logging
import time
from typing import Any, Dict, List, Optional

import requests

logger = logging.getLogger(__name__)


class ClobClient:
    """Polymarket CLOB API client with Builder HMAC authentication."""

    def __init__(
        self,
        host: str,
        chain_id: int = 137,
        api_key: str = "",
        api_secret: str = "",
        api_passphrase: str = "",
        signature_type: int = 2,
    ):
        self.host = host.rstrip("/")
        self.chain_id = chain_id
        self.api_key = api_key
        self.api_secret = api_secret
        self.api_passphrase = api_passphrase
        self.signature_type = signature_type
        self.session = requests.Session()

    def _make_auth_headers(self, method: str, path: str, body: str = "") -> Dict[str, str]:
        """Generate Builder HMAC auth headers."""
        timestamp = str(int(time.time() * 1000))
        message = timestamp + method.upper() + path + body
        signature = hmac.new(
            self.api_secret.encode("utf-8"),
            message.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
        return {
            "POLY-API-KEY": self.api_key,
            "POLY-API-PASSPHRASE": self.api_passphrase,
            "POLY-API-TIMESTAMP": timestamp,
            "POLY-API-SIGNATURE": signature,
            "Content-Type": "application/json",
        }

    def post_order(self, order_data: Dict) -> Dict:
        """Submit an order to the CLOB."""
        path = "/order"
        body = json.dumps(order_data)
        headers = self._make_auth_headers("POST", path, body)
        try:
            resp = self.session.post(f"{self.host}{path}", data=body, headers=headers, timeout=10)
            resp.raise_for_status()
            return resp.json()
        except Exception as e:
            logger.error(f"post_order failed: {e}")
            return {}

    def cancel_order(self, order_id: str) -> Dict:
        """Cancel an order by ID."""
        path = f"/order/{order_id}"
        headers = self._make_auth_headers("DELETE", path)
        try:
            resp = self.session.delete(f"{self.host}{path}", headers=headers, timeout=10)
            resp.raise_for_status()
            return resp.json()
        except Exception as e:
            logger.error(f"cancel_order failed: {e}")
            return {}

    def cancel_all_orders(self) -> Dict:
        """Cancel all open orders."""
        path = "/orders"
        headers = self._make_auth_headers("DELETE", path)
        try:
            resp = self.session.delete(f"{self.host}{path}", headers=headers, timeout=10)
            resp.raise_for_status()
            return resp.json()
        except Exception as e:
            logger.error(f"cancel_all_orders failed: {e}")
            return {}

    def cancel_market_orders(self, market: str, asset_id: str) -> Dict:
        """Cancel orders for a specific market."""
        path = "/orders/market"
        body = json.dumps({"market": market, "asset_id": asset_id})
        headers = self._make_auth_headers("DELETE", path, body)
        try:
            resp = self.session.delete(f"{self.host}{path}", data=body, headers=headers, timeout=10)
            resp.raise_for_status()
            return resp.json()
        except Exception as e:
            logger.error(f"cancel_market_orders failed: {e}")
            return {}

    def get_open_orders(self) -> List[Dict]:
        """Get all open orders."""
        path = "/orders"
        headers = self._make_auth_headers("GET", path)
        try:
            resp = self.session.get(f"{self.host}{path}", headers=headers, timeout=10)
            resp.raise_for_status()
            return resp.json()
        except Exception as e:
            logger.error(f"get_open_orders failed: {e}")
            return []

    def get_trades(self, limit: int = 100) -> List[Dict]:
        """Get trade history."""
        path = f"/trades?limit={limit}"
        headers = self._make_auth_headers("GET", path)
        try:
            resp = self.session.get(f"{self.host}{path}", headers=headers, timeout=10)
            resp.raise_for_status()
            return resp.json()
        except Exception as e:
            logger.error(f"get_trades failed: {e}")
            return []

    def get_order_book(self, token_id: str) -> Dict:
        """Get the order book for a token."""
        path = f"/book?token_id={token_id}"
        try:
            resp = self.session.get(f"{self.host}{path}", timeout=10)
            resp.raise_for_status()
            return resp.json()
        except Exception as e:
            logger.error(f"get_order_book failed: {e}")
            return {"bids": [], "asks": []}

    def get_market_price(self, token_id: str) -> Optional[float]:
        """Get the current mid price for a token."""
        book = self.get_order_book(token_id)
        bids = book.get("bids", [])
        asks = book.get("asks", [])
        if bids and asks:
            return (float(bids[0]["price"]) + float(asks[0]["price"])) / 2.0
        elif bids:
            return float(bids[0]["price"])
        elif asks:
            return float(asks[0]["price"])
        return None


class RelayerClient:
    """Polymarket Relayer API client for gasless transactions."""

    def __init__(self, host: str, tx_type: str = "SAFE"):
        self.host = host.rstrip("/")
        self.tx_type = tx_type
        self.session = requests.Session()

    def submit_order(self, order_data: Dict) -> Dict:
        """Submit a gasless order via the relayer."""
        path = "/order"
        body = json.dumps(order_data)
        try:
            resp = self.session.post(
                f"{self.host}{path}",
                data=body,
                headers={"Content-Type": "application/json"},
                timeout=10,
            )
            resp.raise_for_status()
            return resp.json()
        except Exception as e:
            logger.error(f"submit_order (relayer) failed: {e}")
            return {}
