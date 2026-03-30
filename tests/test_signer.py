"""Tests for OrderSigner and Order from src/signer.py."""
import pytest
from src.signer import OrderSigner, Order

TEST_PRIVATE_KEY = "0x" + "a" * 64


class TestOrder:
    def test_order_creation(self):
        order = Order(token_id="123", price=0.65, size=10.0, side="BUY")
        assert order.token_id == "123"
        assert order.price == 0.65
        assert order.size == 10.0
        assert order.side == "BUY"

    def test_order_defaults(self):
        order = Order(token_id="123", price=0.5, size=5.0, side="SELL")
        assert order.nonce == 0
        assert order.expiration == 0

    def test_order_type_default(self):
        order = Order(token_id="123", price=0.5, size=5.0, side="BUY")
        assert order.order_type == "GTC"

    def test_order_sell_side(self):
        order = Order(token_id="456", price=0.70, size=20.0, side="SELL")
        assert order.side == "SELL"


class TestOrderSigner:
    def test_initialization(self):
        signer = OrderSigner(TEST_PRIVATE_KEY, chain_id=137)
        assert signer is not None
        assert signer.chain_id == 137

    def test_default_chain_id(self):
        signer = OrderSigner(TEST_PRIVATE_KEY)
        assert signer.chain_id == 137

    def test_address_property(self):
        signer = OrderSigner(TEST_PRIVATE_KEY)
        address = signer.address
        assert address.startswith("0x")
        assert len(address) == 42

    def test_address_is_hex(self):
        signer = OrderSigner(TEST_PRIVATE_KEY)
        # Should be a valid hex string after the 0x prefix
        int(signer.address, 16)

    def test_sign_order_returns_hex(self):
        signer = OrderSigner(TEST_PRIVATE_KEY, chain_id=137)
        order = Order(token_id="12345", price=0.60, size=5.0, side="BUY")
        signature = signer.sign_order(order)

        assert isinstance(signature, str)
        assert len(signature) > 0

    def test_sign_order_hex_chars_only(self):
        signer = OrderSigner(TEST_PRIVATE_KEY, chain_id=137)
        order = Order(token_id="12345", price=0.60, size=5.0, side="BUY")
        signature = signer.sign_order(order)
        # Should be valid hex (possibly with 0x prefix)
        sig_hex = signature.lstrip("0x")
        int(sig_hex, 16)

    def test_sign_message(self):
        signer = OrderSigner(TEST_PRIVATE_KEY)
        sig = signer.sign_message("test message")
        assert isinstance(sig, str)
        assert len(sig) > 0

    def test_deterministic_signing(self):
        signer = OrderSigner(TEST_PRIVATE_KEY, chain_id=137)
        order = Order(token_id="12345", price=0.60, size=5.0, side="BUY")
        sig1 = signer.sign_order(order)
        sig2 = signer.sign_order(order)
        # EIP-712 signing should be deterministic for the same order
        assert sig1 == sig2

    def test_sign_sell_order(self):
        signer = OrderSigner(TEST_PRIVATE_KEY, chain_id=137)
        order = Order(token_id="99999", price=0.40, size=3.0, side="SELL")
        signature = signer.sign_order(order)
        assert isinstance(signature, str)
        assert len(signature) > 0

    def test_different_orders_different_signatures(self):
        signer = OrderSigner(TEST_PRIVATE_KEY, chain_id=137)
        order1 = Order(token_id="111", price=0.50, size=5.0, side="BUY")
        order2 = Order(token_id="222", price=0.50, size=5.0, side="BUY")
        assert signer.sign_order(order1) != signer.sign_order(order2)
