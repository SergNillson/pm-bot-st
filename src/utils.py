"""Utility helpers for the Polymarket trading bot."""
import logging
import os
import re
from typing import Optional

logger = logging.getLogger(__name__)


def create_bot_from_env():
    """Create a TradingBot from environment variables."""
    from src.bot import TradingBot
    from src.config import Config

    config = Config.from_env()
    private_key = os.getenv("POLY_PRIVATE_KEY", "")
    return TradingBot(config=config, private_key=private_key)


def validate_address(address: str) -> bool:
    """Validate an Ethereum address."""
    if not address:
        return False
    pattern = r"^0x[0-9a-fA-F]{40}$"
    return bool(re.match(pattern, address))


def format_price(price: float, decimals: int = 4) -> str:
    """Format a price for display."""
    return f"{price:.{decimals}f}"


def format_size(size: float, decimals: int = 2) -> str:
    """Format a size for display."""
    return f"{size:.{decimals}f}"


def setup_logging(level: str = "INFO") -> None:
    """Configure logging for the bot."""
    numeric_level = getattr(logging, level.upper(), logging.INFO)
    logging.basicConfig(
        level=numeric_level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
