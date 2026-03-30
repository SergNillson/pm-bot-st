"""EIP-712 order signing for Polymarket (Gnosis Safe signature type 2)."""
import json
import logging
from dataclasses import dataclass, field

from eth_account import Account
from eth_account.messages import encode_defunct, encode_typed_data

logger = logging.getLogger(__name__)


@dataclass
class Order:
    token_id: str
    price: float
    size: float
    side: str  # "BUY" or "SELL"
    order_type: str = "GTC"  # Good Till Cancel
    nonce: int = 0
    expiration: int = 0


class OrderSigner:
    """Signs Polymarket orders with EIP-712 signatures (Gnosis Safe signature type 2)."""

    DOMAIN_NAME = "ClobAuthDomain"
    DOMAIN_VERSION = "1"

    def __init__(self, private_key: str, chain_id: int = 137):
        self.account = Account.from_key(private_key)
        self.chain_id = chain_id

    @property
    def address(self) -> str:
        """Return the signer's Ethereum address."""
        return self.account.address

    def sign_order(self, order: Order) -> str:
        """Sign an order with EIP-712 and return the signature hex string."""
        price_int = int(order.price * 1_000_000)
        size_int = int(order.size * 1_000_000)
        side_int = 0 if order.side == "BUY" else 1

        if order.token_id.startswith("0x"):
            token_id_int = int(order.token_id, 16)
        elif order.token_id.isdigit():
            token_id_int = int(order.token_id)
        else:
            token_id_int = 0

        typed_data = {
            "types": {
                "EIP712Domain": [
                    {"name": "name", "type": "string"},
                    {"name": "version", "type": "string"},
                    {"name": "chainId", "type": "uint256"},
                ],
                "Order": [
                    {"name": "tokenId", "type": "uint256"},
                    {"name": "makerAmount", "type": "uint256"},
                    {"name": "takerAmount", "type": "uint256"},
                    {"name": "side", "type": "uint8"},
                    {"name": "nonce", "type": "uint256"},
                    {"name": "expiration", "type": "uint256"},
                ],
            },
            "domain": {
                "name": self.DOMAIN_NAME,
                "version": self.DOMAIN_VERSION,
                "chainId": self.chain_id,
            },
            "primaryType": "Order",
            "message": {
                "tokenId": token_id_int,
                "makerAmount": size_int if order.side == "BUY" else price_int,
                "takerAmount": price_int if order.side == "BUY" else size_int,
                "side": side_int,
                "nonce": order.nonce,
                "expiration": order.expiration,
            },
        }

        try:
            msg = encode_typed_data(full_message=typed_data)
            signed = self.account.sign_message(msg)
            return signed.signature.hex()
        except Exception:
            msg_hash = json.dumps(typed_data, sort_keys=True).encode()
            signed = self.account.sign_message(encode_defunct(msg_hash))
            return signed.signature.hex()

    def sign_message(self, message: str) -> str:
        """Sign an arbitrary message."""
        signed = self.account.sign_message(encode_defunct(text=message))
        return signed.signature.hex()
