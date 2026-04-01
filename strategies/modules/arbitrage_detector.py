"""
Arbitrage Detector Module - Detect two-sided arbitrage opportunities.

Identifies markets where up_price + down_price < threshold, meaning
both outcomes can be bought for less than $1.00 (guaranteed settlement value).
"""

import logging
from typing import Optional

logger = logging.getLogger(__name__)


class ArbitrageDetector:
    """Detect arbitrage opportunities when total price < threshold.

    In binary prediction markets, UP and DOWN prices must sum to 1.00 at
    settlement.  When the sum is meaningfully below 1.00 (e.g. 0.93), buying
    both sides locks in a risk-free profit once the market resolves.
    """

    def __init__(self, clob_client, threshold: float = 0.95):
        """
        Args:
            clob_client: CLOBClient instance for price lookups (reserved for
                future use – prices are currently passed directly).
            threshold: Maximum total price to trigger an arbitrage signal.
                Default 0.95 means buy both if up + down < 0.95.
        """
        self.clob = clob_client
        self.threshold = threshold

    def check_opportunity(self, up_price: float, down_price: float) -> bool:
        """Check if an arbitrage opportunity exists.

        Args:
            up_price: Current price of the UP outcome token (0–1).
            down_price: Current price of the DOWN outcome token (0–1).

        Returns:
            True if up_price + down_price < threshold, False otherwise.
        """
        total = up_price + down_price

        if total < self.threshold:
            logger.info(
                f"💎 ARBITRAGE DETECTED: total={total:.4f} "
                f"(up={up_price:.4f} + down={down_price:.4f})"
            )
            return True

        return False

    def calculate_profit_potential(
        self, up_price: float, down_price: float, size: float
    ) -> float:
        """Calculate expected profit from an arbitrage trade.

        Buys *size* units of each outcome for a combined cost of
        ``size * (up_price + down_price)``.  At settlement one outcome pays
        $1.00 per unit, so the total revenue equals *size*.

        Example::

            up=0.45, down=0.48 → total=0.93
            cost  = 10 * 0.93 = $9.30
            value = 10 * 1.00 = $10.00
            profit = $0.70  (7.5 %)

        Args:
            up_price: Price of the UP outcome token.
            down_price: Price of the DOWN outcome token.
            size: Number of units (contracts) to buy on each side.

        Returns:
            Expected profit in USDC.
        """
        total = up_price + down_price
        cost = size * total
        revenue = size  # one outcome always settles at $1.00
        return revenue - cost
