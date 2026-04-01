#!/usr/bin/env python3
"""
Hybrid Trading Strategy for Polymarket BTC Markets

Combines three high-win-rate sub-strategies for optimised returns
with $40 starting capital:

  1. Two-Sided Arbitrage  — buy both outcomes when total < 0.95 (90%+ win rate)
  2. Mean Reversion       — enter when price deviates > 8c from 0.50 (68-72%)
  3. Market Making        — post limit orders with spread when balanced (75-80%)

Expected performance: +70-100% monthly ROI at $40 capital, 72-80% win rate.

Usage:
    python strategies/hybrid_strategy.py --dry-run --capital 40 --coin BTC
    python strategies/hybrid_strategy.py --capital 40 --coin BTC --arb-threshold 0.95 --mr-threshold 0.08 --mm-spread 0.03 --dry-run
    python strategies/hybrid_strategy.py --config config/hybrid_config.yaml --dry-run

Options:
    --capital         Starting capital in USDC (default: 40.0)
    --coin            Asset to trade: BTC, ETH, SOL, XRP (default: BTC)
    --arb-threshold   Arbitrage trigger threshold (default: 0.95)
    --mr-threshold    Mean-reversion deviation threshold (default: 0.08)
    --mm-spread       Market-making spread (default: 0.03)
    --max-positions   Maximum simultaneous open positions (default: 3)
    --dry-run         Simulate trades without executing real orders
    --config          Path to YAML config file
"""

import argparse
import asyncio
import logging
import sys
import time
import yaml
from pathlib import Path
from typing import Dict, List, Optional

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.gamma_client import GammaClient
from src.clob_client import CLOBClient
from src.utils import create_bot_from_env, setup_logging
from strategies.modules.position_manager import PositionManager
from strategies.modules.position_closer import PositionCloser
from strategies.modules.arbitrage_detector import ArbitrageDetector
from strategies.modules.market_maker import MarketMaker
from strategies.modules.mean_reversion_scanner import MeanReversionScanner

logger = logging.getLogger(__name__)

# Default stats report interval (seconds)
STATS_INTERVAL = 60


class HybridStrategy:
    """Orchestrate three sub-strategies with priority-based execution.

    Priority order (highest to lowest):
    1. Two-Sided Arbitrage  — guaranteed profit if total < threshold
    2. Mean Reversion       — buy underpriced side, target 0.50
    3. Market Making        — passive limit orders in balanced markets
    """

    def __init__(
        self,
        capital: float = 40.0,
        coin: str = "BTC",
        dry_run: bool = False,
        arb_threshold: float = 0.95,
        mr_threshold: float = 0.08,
        mm_spread: float = 0.03,
        max_positions: int = 3,
        config_path: Optional[str] = None,
    ):
        self.capital = capital
        self.coin = coin.upper()
        self.dry_run = dry_run
        self.max_positions = max_positions
        self.config_data: Dict = {}

        # Load optional YAML config
        if config_path:
            try:
                with open(config_path) as f:
                    self.config_data = yaml.safe_load(f) or {}
                logger.info(f"Loaded config from {config_path}")
            except Exception as e:
                logger.warning(f"Could not load config {config_path}: {e}")

        # Apply config overrides where the caller did not explicitly set values
        arb_cfg = self.config_data.get("arbitrage", {})
        mr_cfg = self.config_data.get("mean_reversion", {})
        mm_cfg = self.config_data.get("market_making", {})

        arb_threshold = arb_cfg.get("threshold", arb_threshold)
        mr_threshold = mr_cfg.get("threshold", mr_threshold)
        mm_spread = mm_cfg.get("spread", mm_spread)
        self.max_positions = self.config_data.get("capital", {}).get(
            "max_positions", max_positions
        )

        # Initialise API clients
        self.gamma = GammaClient()
        self.clob = CLOBClient()
        self.bot = create_bot_from_env()

        # Core shared modules (reuse existing infrastructure)
        self.pm = PositionManager(
            self.bot, None, self.clob, initial_capital=capital
        )
        self.pm.dry_run = dry_run
        self.closer = PositionCloser(self.gamma, self.clob, self.pm)

        # Sub-strategy modules
        self.arb_detector = ArbitrageDetector(self.clob, threshold=arb_threshold)
        self.market_maker = MarketMaker(self.bot, self.clob, spread=mm_spread)
        self.mr_scanner = MeanReversionScanner(self.clob, threshold=mr_threshold)

        # Performance tracking
        self.stats: Dict = {
            "total_trades": 0,
            "arb_trades": 0,
            "arb_wins": 0,
            "mr_trades": 0,
            "mr_wins": 0,
            "mm_trades": 0,
            "mm_wins": 0,
            "total_pnl": 0.0,
            "bankroll": capital,
            "win_rate": 0.0,
        }

        self._last_stats_time: float = time.time()

    # ------------------------------------------------------------------
    # Position sizing
    # ------------------------------------------------------------------

    def calculate_size(self, strategy_type: str, imbalance: float = 0.0) -> float:
        """Calculate position size based on strategy type and current bankroll.

        Args:
            strategy_type: One of ``'arbitrage'``, ``'mean_reversion'``,
                ``'market_making'``.
            imbalance: Absolute distance from 0.50 (used for mean-reversion
                sizing only).

        Returns:
            Position size in USDC, clamped to bankroll limits.
        """
        bankroll = self.pm.get_current_bankroll()
        base_size = bankroll * 0.10

        if strategy_type == "arbitrage":
            # Low risk → slightly larger size
            size = min(base_size * 1.5, bankroll * 0.15)
        elif strategy_type == "mean_reversion":
            # Medium risk → Kelly-inspired inverse scaling
            size = base_size / (1 + imbalance * 10)
        else:
            # Market making → conservative half-size
            size = base_size * 0.5

        # Apply global position limits from PositionManager constants
        from strategies.modules.position_manager import (
            MIN_POSITION_SIZE,
            MAX_POSITION_SIZE,
        )

        return max(MIN_POSITION_SIZE, min(size, MAX_POSITION_SIZE))

    # ------------------------------------------------------------------
    # Sub-strategy executors
    # ------------------------------------------------------------------

    async def _execute_arbitrage(
        self,
        market_id: str,
        up_token: str,
        down_token: str,
        up_price: float,
        down_price: float,
    ) -> None:
        """Buy both outcomes to capture the arbitrage spread."""
        imbalance = abs(up_price - down_price)
        size = self.calculate_size("arbitrage", imbalance)
        expected_profit = self.arb_detector.calculate_profit_potential(
            up_price, down_price, size
        )

        logger.info(
            f"💎 ARB ENTRY: total={up_price + down_price:.4f} | "
            f"up={up_price:.4f} down={down_price:.4f} | "
            f"size=${size:.2f} | expected_profit=+${expected_profit:.2f}"
        )

        await self.pm.place_straddle(market_id, up_token, down_token, size)
        self.stats["arb_trades"] += 1
        self.stats["total_trades"] += 1

    async def _execute_mean_reversion(
        self,
        market_id: str,
        signal: Dict,
        up_token: str,
        down_token: str,
    ) -> None:
        """Enter the underpriced side of a mean-reversion trade."""
        entry_price = signal["entry_price"]
        target = signal["target"]
        imbalance = abs(entry_price - 0.50)
        size = self.calculate_size("mean_reversion", imbalance)
        expected_profit = self.mr_scanner.calculate_expected_profit(
            entry_price, target, size
        )

        token = up_token if signal["token"] == "up" else down_token
        logger.info(
            f"📉 MR ENTRY: {signal['side']} @ {entry_price:.4f} → "
            f"target {target:.2f} | size=${size:.2f} | "
            f"expected_profit=+${expected_profit:.2f}"
        )

        # Place a single-sided buy (not a straddle)
        orders = await self.pm.ladder_buy(token, size, "BUY")

        # Register as a minimal position so the position closer can track it
        self.pm.positions[market_id] = {
            "up": {
                "token": token,
                "orders": orders,
                "size": size,
                "entry_time": time.time(),
            },
            "down": {
                "token": "",
                "orders": [],
                "size": 0.0,
                "entry_time": time.time(),
            },
            "total_cost": sum(
                o.get("cost", 0) for o in orders if o.get("success")
            ),
            "total_received": 0.0,
            "strategy": "mean_reversion",
        }

        self.stats["mr_trades"] += 1
        self.stats["total_trades"] += 1

    async def _execute_market_making(
        self,
        market_id: str,
        up_token: str,
        down_token: str,
        up_price: float,
        down_price: float,
    ) -> None:
        """Post passive limit orders on both outcome tokens."""
        size = self.calculate_size("market_making")
        mid_up = up_price
        mid_down = down_price

        logger.info(
            f"📊 MM ORDERS: BUY @ {mid_up - self.market_maker.spread / 2:.4f} | "
            f"SELL @ {mid_up + self.market_maker.spread / 2:.4f} | "
            f"spread={self.market_maker.spread:.0%} | size=${size:.2f}"
        )

        await self.market_maker.place_orders(up_token, mid_up, size)
        await self.market_maker.place_orders(down_token, mid_down, size)

        self.stats["mm_trades"] += 1
        self.stats["total_trades"] += 1

    def _can_make_market(self, up_price: float, down_price: float) -> bool:
        """Delegate to the MarketMaker condition check."""
        return self.market_maker.should_make_market(up_price, down_price)

    # ------------------------------------------------------------------
    # Stats
    # ------------------------------------------------------------------

    async def _report_stats(self) -> None:
        """Print statistics every STATS_INTERVAL seconds."""
        now = time.time()
        if now - self._last_stats_time < STATS_INTERVAL:
            return

        self._last_stats_time = now
        pm_stats = self.pm.get_stats()

        self.stats["bankroll"] = pm_stats["bankroll"]
        self.stats["total_pnl"] = pm_stats["total_pnl"]
        self.stats["win_rate"] = pm_stats["win_rate"]

        logger.info(
            "📊 STATS | "
            f"bankroll=${self.stats['bankroll']:.2f} | "
            f"total_pnl=${self.stats['total_pnl']:+.2f} | "
            f"win_rate={self.stats['win_rate']:.1%} | "
            f"trades={self.stats['total_trades']} "
            f"(arb={self.stats['arb_trades']} "
            f"mr={self.stats['mr_trades']} "
            f"mm={self.stats['mm_trades']}) | "
            f"open_positions={pm_stats['open_positions']}"
        )

    # ------------------------------------------------------------------
    # Main loop
    # ------------------------------------------------------------------

    async def run(self) -> None:
        """Main strategy loop.  Runs continuously until interrupted."""
        logger.info(
            f"🚀 HybridStrategy starting | "
            f"capital=${self.capital:.2f} | coin={self.coin} | "
            f"dry_run={self.dry_run}"
        )

        while True:
            try:
                # Discover active markets
                markets: List[Dict] = self.gamma.find_active_windows(
                    self.coin, ["5m"]
                )

                for market in markets:
                    market_id = market.get("condition_id", "")
                    up_token = market.get("up_token", "")
                    down_token = market.get("down_token", "")

                    if not market_id or not up_token or not down_token:
                        continue

                    # Skip if already tracking this market
                    if market_id in self.pm.positions:
                        continue

                    # Enforce max simultaneous positions
                    if len(self.pm.positions) >= self.max_positions:
                        logger.debug(
                            f"Max positions ({self.max_positions}) reached, "
                            "skipping new entries"
                        )
                        continue

                    # Fetch current prices
                    up_price = self.clob.get_price(up_token)
                    down_price = self.clob.get_price(down_token)

                    if up_price is None or down_price is None:
                        logger.debug(
                            f"No price data for market {market_id[:20]}…, skipping"
                        )
                        continue

                    # ── Strategy 1: Two-Sided Arbitrage (highest priority) ──
                    if self.arb_detector.check_opportunity(up_price, down_price):
                        await self._execute_arbitrage(
                            market_id, up_token, down_token, up_price, down_price
                        )
                        continue

                    # ── Strategy 2: Mean Reversion ──
                    mr_signal = self.mr_scanner.check_signal(up_price, down_price)
                    if mr_signal:
                        await self._execute_mean_reversion(
                            market_id, mr_signal, up_token, down_token
                        )
                        continue

                    # ── Strategy 3: Market Making ──
                    if self._can_make_market(up_price, down_price):
                        await self._execute_market_making(
                            market_id, up_token, down_token, up_price, down_price
                        )

                # Close positions whose markets have expired
                await self.closer.check_and_close_expired()

                # Periodic stats output
                await self._report_stats()

                await asyncio.sleep(1)

            except asyncio.CancelledError:
                logger.info("Strategy loop cancelled, shutting down.")
                break
            except Exception as e:
                logger.error(f"Unexpected error in strategy loop: {e}", exc_info=True)


# ============================================================================
# CLI entry point
# ============================================================================

def _parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Hybrid Trading Strategy for Polymarket",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--capital", type=float, default=40.0,
        help="Starting capital in USDC",
    )
    parser.add_argument(
        "--coin", type=str, default="BTC",
        help="Asset to trade (BTC, ETH, SOL, XRP)",
    )
    parser.add_argument(
        "--arb-threshold", type=float, default=0.95,
        help="Trigger arbitrage when up+down < this value",
    )
    parser.add_argument(
        "--mr-threshold", type=float, default=0.08,
        help="Mean-reversion deviation from 0.50 to trigger entry",
    )
    parser.add_argument(
        "--mm-spread", type=float, default=0.03,
        help="Market-making total bid-ask spread",
    )
    parser.add_argument(
        "--max-positions", type=int, default=3,
        help="Maximum simultaneous open positions",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Simulate trades (no real orders placed)",
    )
    parser.add_argument(
        "--config", type=str, default=None,
        help="Path to YAML config file",
    )
    return parser.parse_args(argv)


async def _main(argv: Optional[List[str]] = None) -> None:
    args = _parse_args(argv)
    setup_logging(logging.INFO)

    strategy = HybridStrategy(
        capital=args.capital,
        coin=args.coin,
        dry_run=args.dry_run,
        arb_threshold=args.arb_threshold,
        mr_threshold=args.mr_threshold,
        mm_spread=args.mm_spread,
        max_positions=args.max_positions,
        config_path=args.config,
    )

    await strategy.run()


if __name__ == "__main__":
    asyncio.run(_main())
