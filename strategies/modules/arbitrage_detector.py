"""
Arbitrage Detector Module - Detect two-sided arbitrage opportunities.

Identifies markets where up_price + down_price < threshold, meaning
both outcomes can be bought for less than $1.00 (guaranteed settlement value).
"""

import logging
from typing import Dict, Optional

logger = logging.getLogger(__name__)


class ArbitrageDetector:
    """Detect arbitrage opportunities when total price < threshold.

    In binary prediction markets, UP and DOWN prices must sum to 1.00 at
    settlement.  When the sum is meaningfully below 1.00 (e.g. 0.93), buying
    both sides locks in a risk-free profit once the market resolves.
    """

    def __init__(self, clob_client, threshold: float = 0.95, dry_run: bool = False):
        """
        Args:
            clob_client: CLOBClient instance for price lookups (reserved for
                future use – prices are currently passed directly).
            threshold: Maximum total price to trigger an arbitrage signal.
                Default 0.95 means buy both if up + down < 0.95.
            dry_run: When True, log intended orders without placing real ones.
        """
        self.clob = clob_client
        self.threshold = threshold
        self.dry_run = dry_run

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

    async def execute(
        self,
        bot,
        up_token: str,
        down_token: str,
        up_price: float,
        down_price: float,
        size: float,
    ) -> Dict:
        """Execute arbitrage trade (buy both sides).

        Args:
            bot: TradingBot instance for order execution.
            up_token: UP token ID.
            down_token: DOWN token ID.
            up_price: Current UP price.
            down_price: Current DOWN price.
            size: Position size in USDC for each side.

        Returns:
            Dict with ``'up'`` and ``'down'`` order results.
        """
        total = up_price + down_price
        expected_profit = size - (size * total)

        logger.info(
            f"💎 ARB ENTRY: total={total:.4f} | size=${size:.2f} each | "
            f"expected_profit=+${expected_profit:.2f}"
        )

        if self.dry_run:
            logger.info(f"🛡️ DRY RUN: Would BUY {size} UP @ {up_price:.4f}")
            logger.info(f"🛡️ DRY RUN: Would BUY {size} DOWN @ {down_price:.4f}")
            return {
                "up": {"success": True, "order_id": "dry_run_up"},
                "down": {"success": True, "order_id": "dry_run_down"},
            }

        up_result = await bot.place_order(up_token, up_price, size, "BUY")
        down_result = await bot.place_order(down_token, down_price, size, "BUY")

        return {
            "up": up_result,
            "down": down_result,
        }
