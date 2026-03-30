"""Tests for utility functions from src/utils.py."""
import pytest
from src.utils import validate_address, format_price, format_size


class TestValidateAddress:
    def test_valid_address(self):
        assert validate_address("0x" + "b" * 40) is True

    def test_valid_address_uppercase(self):
        assert validate_address("0xAbCd" + "e" * 36) is True

    def test_invalid_no_0x(self):
        assert validate_address("b" * 40) is False

    def test_invalid_too_short(self):
        assert validate_address("0x" + "b" * 39) is False

    def test_invalid_too_long(self):
        assert validate_address("0x" + "b" * 41) is False

    def test_empty_string(self):
        assert validate_address("") is False

    def test_invalid_characters(self):
        assert validate_address("0x" + "g" * 40) is False

    def test_valid_mixed_case(self):
        assert validate_address("0xABCDEF1234567890abcdef1234567890ABCDEF12") is True

    def test_valid_all_zeros(self):
        assert validate_address("0x" + "0" * 40) is True


class TestFormatFunctions:
    def test_format_price_default_decimals(self):
        assert format_price(0.6543) == "0.6543"

    def test_format_price_custom_decimals(self):
        assert format_price(0.5, 2) == "0.50"

    def test_format_price_zero(self):
        assert format_price(0.0) == "0.0000"

    def test_format_price_one(self):
        assert format_price(1.0) == "1.0000"

    def test_format_size_default(self):
        assert format_size(10.5) == "10.50"

    def test_format_size_zero_decimals(self):
        assert format_size(5.0, 0) == "5"

    def test_format_size_zero(self):
        assert format_size(0.0) == "0.00"


class TestCreateBotFromEnv:
    def test_creates_bot_with_credentials(self, monkeypatch):
        monkeypatch.setenv("POLY_SAFE_ADDRESS", "0x" + "b" * 40)
        monkeypatch.setenv("POLY_PRIVATE_KEY", "0x" + "a" * 64)

        from src.utils import create_bot_from_env
        bot = create_bot_from_env()
        assert bot is not None

    def test_creates_bot_without_credentials(self, monkeypatch):
        monkeypatch.delenv("POLY_SAFE_ADDRESS", raising=False)
        monkeypatch.delenv("POLY_PRIVATE_KEY", raising=False)

        from src.utils import create_bot_from_env
        bot = create_bot_from_env()
        assert bot is not None

    def test_bot_is_initialized_with_credentials(self, monkeypatch):
        monkeypatch.setenv("POLY_SAFE_ADDRESS", "0x" + "b" * 40)
        monkeypatch.setenv("POLY_PRIVATE_KEY", "0x" + "a" * 64)

        from src.utils import create_bot_from_env
        bot = create_bot_from_env()
        assert bot.is_initialized() is True

    def test_bot_not_initialized_without_credentials(self, monkeypatch):
        monkeypatch.delenv("POLY_SAFE_ADDRESS", raising=False)
        monkeypatch.delenv("POLY_PRIVATE_KEY", raising=False)

        from src.utils import create_bot_from_env
        bot = create_bot_from_env()
        assert bot.is_initialized() is False
