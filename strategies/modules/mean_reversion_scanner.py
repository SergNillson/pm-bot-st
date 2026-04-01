"""
Mean Reversion Scanner Module - Detect price deviations from fair value.

Scans for situations where one outcome is priced significantly below 0.50,
signalling a potential mean-reversion trade back toward equilibrium.
"""

import logging
from typing import Dict, Optional

logger = logging.getLogger(__name__)


class MeanReversionScanner:
    """Scan for mean-reversion opportunities in binary prediction markets.

    In a balanced 50/50 market, both outcomes should trade near 0.50.
    When one side dips well below 0.50 without a corresponding fundamental
    reason, it tends to revert.  This scanner flags those situations.
    """

    def __init__(self, clob_client, threshold: float = 0.08, dry_run: bool = False):
        """
        Args:
            clob_client: CLOBClient instance (reserved for future lookups).
            threshold: Minimum distance from 0.50 to trigger a signal.
                Default 0.08 means flag if price < 0.42 or price > 0.58.
            dry_run: When True, log intended orders without placing real ones.
        """
        self.clob = clob_client
        self.threshold = threshold  # 0.08 = 8 cents from 0.50
        self.dry_run = dry_run

    def check_signal(
        self, up_price: float, down_price: float
    ) -> Optional[Dict]:
        """Check for a mean-reversion signal.

        Only one side is tested per call; the first underpriced side found
        takes priority (UP before DOWN).

        Args:
            up_price: Current price of the UP outcome token (0–1).
            down_price: Current price of the DOWN outcome token (0–1).

        Returns:
            A signal dict ``{'side', 'entry_price', 'target', 'token'}``
            when an opportunity is found, or ``None`` otherwise.
        """
        midpoint = 0.50
        lower_bound = midpoint - self.threshold

        # UP is underpriced
        if up_price < lower_bound:
            logger.info(
                f"📉 MEAN REVERSION: UP underpriced @ {up_price:.4f} "
                f"(target: {midpoint})"
            )
            return {
                "side": "UP",
                "entry_price": up_price,
                "target": midpoint,
                "token": "up",
            }

        # DOWN is underpriced
        if down_price < lower_bound:
            logger.info(
                f"📉 MEAN REVERSION: DOWN underpriced @ {down_price:.4f} "
                f"(target: {midpoint})"
            )
            return {
                "side": "DOWN",
                "entry_price": down_price,
                "target": midpoint,
                "token": "down",
            }

        return None

    def calculate_expected_profit(
        self, entry_price: float, target: float = 0.50, size: float = 5.0
    ) -> float:
        """Calculate expected profit if price reverts to *target*.

        Args:
            entry_price: Price at which the position is entered.
            target: Expected price at exit (default 0.50).
            size: Position size in USDC.

        Returns:
            Expected profit in USDC (negative if entry is above target).
        """
        profit_per_unit = target - entry_price
        return profit_per_unit * size

    async def execute(
        self,
        bot,
        token_id: str,
        price: float,
        size: float,
        target: float = 0.50,
    ) -> Dict:
        """Execute mean reversion trade (buy underpriced side).

        Args:
            bot: TradingBot instance for order execution.
            token_id: Token to buy.
            price: Entry price.
            size: Position size in USDC.
            target: Target price for profit (default 0.50).

        Returns:
            Order result dict.
        """
        expected_profit = (target - price) * size

        logger.info(
            f"📉 MR ENTRY: price={price:.4f} → target={target:.4f} | "
            f"size=${size:.2f} | expected_profit=+${expected_profit:.2f}"
        )

        if self.dry_run:
            logger.info(f"🛡️ DRY RUN: Would BUY {size} @ {price:.4f}")
            return {"success": True, "order_id": "dry_run_mr"}

        result = await bot.place_order(token_id, price, size, "BUY")
        return result
