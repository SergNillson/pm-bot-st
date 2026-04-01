"""
Market Maker Module - Place limit orders around the mid price to capture spread.

Places simultaneous buy and sell limit orders a configurable spread apart.
When both fill the module earns the full spread as profit.
"""

import logging
from typing import Dict

logger = logging.getLogger(__name__)


class MarketMaker:
    """Place limit orders with a spread to capture bid-ask spread.

    Strategy::

        mid_price = 0.50
        → BUY  @ 0.485  (half-spread below)
        → SELL @ 0.515  (half-spread above)

        If both fill: profit = spread per unit.
    """

    def __init__(self, bot, clob_client, spread: float = 0.03):
        """
        Args:
            bot: TradingBot instance for order execution.
            clob_client: CLOBClient instance (reserved for future use).
            spread: Total bid-ask spread to apply (default 0.03 = 3 cents).
                Half is subtracted from mid for the buy price; half is added
                for the sell price.
        """
        self.bot = bot
        self.clob = clob_client
        self.spread = spread  # 3-cent total spread

    async def place_orders(
        self,
        token_id: str,
        mid_price: float,
        size: float,
    ) -> Dict:
        """Place a buy and a sell limit order around *mid_price*.

        Args:
            token_id: Token to trade.
            mid_price: Current fair-value estimate (0–1).
            size: Size in USDC for each leg.

        Returns:
            ``{'buy': order_result, 'sell': order_result}``
        """
        half_spread = self.spread / 2

        buy_price = max(0.01, mid_price - half_spread)
        sell_price = min(0.99, mid_price + half_spread)

        logger.info(
            f"📊 MARKET MAKING: BUY @ {buy_price:.4f} | SELL @ {sell_price:.4f}"
        )

        buy_result = await self.bot.place_order(token_id, buy_price, size, "BUY")
        sell_result = await self.bot.place_order(token_id, sell_price, size, "SELL")

        return {
            "buy": buy_result,
            "sell": sell_result,
        }

    def should_make_market(self, up_price: float, down_price: float) -> bool:
        """Check whether current market conditions are suitable for making.

        Market making works best in balanced, liquid markets.  Only returns
        ``True`` when both prices are in the 45–55 % range.

        Args:
            up_price: Current price of the UP outcome token.
            down_price: Current price of the DOWN outcome token.

        Returns:
            ``True`` if both prices are between 0.45 and 0.55 inclusive.
        """
        return 0.45 <= up_price <= 0.55 and 0.45 <= down_price <= 0.55
