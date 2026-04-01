"""
Position Closer Module - Monitor and close expired positions with P&L calculation.
"""

import logging
import time
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

# Close positions after 5.5 minutes to ensure market has resolved
POSITION_EXPIRY_SECONDS = 330

# Assumed average entry price for P&L calculation (50/50 straddle)
AVG_ENTRY_PRICE = 0.50


class PositionCloser:
    """Monitor open positions and close them when markets expire.

    Checks all positions in PositionManager every loop iteration.
    When a position has been open for more than POSITION_EXPIRY_SECONDS (330s),
    it fetches final prices, calculates P&L, updates the bankroll, and removes
    the position.
    """

    def __init__(self, gamma_client, clob_client, position_manager):
        """
        Args:
            gamma_client: GammaClient instance (reserved for future use)
            clob_client: CLOBClient for fetching final prices
            position_manager: PositionManager for position tracking and bankroll
        """
        self.gamma = gamma_client
        self.clob = clob_client
        self.pm = position_manager

    def _get_price(self, token_id: str) -> float:
        """Fetch current price from CLOB API, defaulting to 0.50.

        Args:
            token_id: Token ID to look up

        Returns:
            Price in range [0.0, 1.0]
        """
        if self.clob:
            price = self.clob.get_price(token_id)
            if price is not None:
                return float(price)
        return 0.50

    async def check_and_close_expired(self) -> List[str]:
        """Check all open positions and close any that have expired.

        Returns:
            List of market IDs that were closed
        """
        now = time.time()
        closed = []

        # Snapshot keys to avoid mutating dict during iteration
        for market_id in list(self.pm.positions.keys()):
            position = self.pm.positions.get(market_id)
            if position is None:
                continue

            entry_time = position.get("up", {}).get("entry_time", now)
            time_elapsed = now - entry_time

            if time_elapsed > POSITION_EXPIRY_SECONDS:
                await self.close_position(market_id, position)
                closed.append(market_id)

        return closed

    async def close_position(self, market_id: str, position: Dict) -> Optional[float]:
        """Close a single position and calculate P&L.

        Fetches final prices from the CLOB API, computes P&L using actual
        tracked costs (total_cost and total_received), updates the bankroll,
        and removes the position from PositionManager.

        Args:
            market_id: Market identifier
            position: Position dict with 'up', 'down', 'total_cost', and
                'total_received' sub-dicts/fields

        Returns:
            Total P&L for the closed position, or None on error
        """
        try:
            up_side = position.get("up", {})
            down_side = position.get("down", {})

            up_token = up_side.get("token", "")
            down_token = down_side.get("token", "")
            up_size = float(up_side.get("size", 0.0))
            down_size = float(down_side.get("size", 0.0))

            # Fetch final market prices
            up_price = self._get_price(up_token)
            down_price = self._get_price(down_token)

            # Get total money spent and received (tracks real entry + hedge costs)
            total_cost = position.get("total_cost", 0.0)
            total_received = position.get("total_received", 0.0)

            # Calculate final settlement value
            up_value = up_price * up_size
            down_value = down_price * down_size
            settlement_value = up_value + down_value

            # Compute hedge buy and sell totals for detailed logging
            hedge_sells = sum(s * p for s, p in position.get("hedge_sells", []))
            hedge_buys = sum(s * p for s, p in position.get("hedge_buys", []))

            # Real P&L = (settlement + hedge profits) - initial cost
            total_pnl = (settlement_value + total_received) - total_cost

            logger.info(
                f"💰 Closing position: market={market_id[:20]}... | "
                f"Initial spent: ${total_cost:.2f} | "
                f"Hedge buys: ${hedge_buys:.2f} | "
                f"Hedge sells: ${hedge_sells:.2f} | "
                f"Settlement: ${settlement_value:.2f} | "
                f"Total P&L: ${total_pnl:+.2f}"
            )

            # Update bankroll and remove position
            new_bankroll = self.pm.update_bankroll(total_pnl)
            self.pm.close_position(market_id)

            logger.info(
                f"✅ Position closed | New bankroll: ${new_bankroll:.2f}"
            )

            return total_pnl

        except Exception as e:
            logger.error(f"Error closing position {market_id}: {e}")
            return None
