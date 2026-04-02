#!/usr/bin/env python3
"""
Delta-Neutral Scalping Strategy for Polymarket BTC 5-min and 15-min Markets

Optimized for $40 starting capital with compound interest reinvestment.
Operates 24/7 with enhanced activity during 2-4 AM ET (low liquidity).

Strategy Components:
  A. Delta-Neutral Straddle - Buy both UP and DOWN near 50/50
  B. Ladder/DCA Entry - Split orders across multiple price ticks
  C. Dynamic Delta Hedging - Rebalance when delta > 15%
  D. Odds-Gated Entries - Size based on proximity to 50/50
  E. Kelly-Inspired Sizing - Inversely proportional to imbalance
  F. Micro-Window Scalping - 2-4 trades within a single 5-min window
  G. Instant Capital Recycling - Reinvest profits immediately
  H. Low-Liquidity Hours Priority - 20% larger during 2-4 AM ET

Usage:
    python strategies/delta_neutral_scalping.py --dry-run
    python strategies/delta_neutral_scalping.py --capital 40 --coin BTC
    python strategies/delta_neutral_scalping.py --dry-run --capital 40 --coin BTC --config config/delta_neutral_config.yaml

Options:
    --dry-run       Simulate trades without executing (RECOMMENDED for testing)
    --capital       Starting capital in USDC (default: 40.0)
    --coin          Asset to trade (default: BTC)
    --config        Path to config YAML file
"""

import argparse
import asyncio
import logging
import sys
import time
import uuid
import yaml
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

import pytz

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.gamma_client import GammaClient
from src.websocket_client import PolymarketWebSocketClient
from src.clob_client import CLOBClient
from src.utils import create_bot_from_env, setup_logging
from strategies.modules.market_scanner import MarketScanner
from strategies.modules.odds_monitor import OddsMonitor
from strategies.modules.position_manager import PositionManager
from strategies.modules.delta_hedger import DeltaHedger
from strategies.modules.position_closer import PositionCloser

logger = logging.getLogger(__name__)

# ============================================================================
# Risk Management Constants
# ============================================================================
MAX_BANKROLL_PER_WINDOW = 0.15   # 15% of total capital
DAILY_DRAWDOWN_LIMIT    = 0.08   # 8% → pause bot for 4 hours
ORDER_TIMEOUT_SECONDS   = 10     # cancel unfilled orders
MIN_WIN_RATE            = 0.52   # pause if win rate drops below
ENTRY_IMBALANCE_MAX     = 0.10   # only enter within 10% of 50/50 (45-55% range) - STRICTER
MIN_SPREAD_THRESHOLD    = 0.06   # maximum spread to enter; wider spreads are too costly
HEDGE_THRESHOLD         = 0.15   # delta trigger for rebalancing
MIN_LIQUIDITY           = 100    # minimum $100 in orderbook to enter
EARLY_EXIT_PROFIT_THRESHOLD = 0.15   # exit early if position profit exceeds 15% of net cost
EARLY_EXIT_PRICE_ADJUSTMENT = 0.99   # apply 1% price haircut on early exit sells


# ============================================================================
# Telegram Notifier
# ============================================================================
class TelegramNotifier:
    """Send trade notifications to Telegram."""
    
    def __init__(self, token: str = "", chat_id: str = "", enabled: bool = True):
        self.token = token
        self.chat_id = chat_id
        self.enabled = enabled and bool(token) and bool(chat_id)
        self.pm: Optional[PositionManager] = None
    
    async def send(self, message: str) -> bool:
        """Send a message to Telegram."""
        if not self.enabled:
            logger.debug(f"Telegram (disabled): {message.strip()}")
            return True
        
        try:
            import aiohttp
            url = f"https://api.telegram.org/bot{self.token}/sendMessage"
            payload = {"chat_id": self.chat_id, "text": message, "parse_mode": "HTML"}
            async with aiohttp.ClientSession() as session:
                async with session.post(url, json=payload, timeout=5) as resp:
                    return resp.status_code == 200
        except ImportError:
            logger.debug("aiohttp not installed - Telegram disabled")
            return False
        except Exception as e:
            logger.warning(f"Telegram send failed: {e}")
            return False
    
    async def notify_entry(
        self, market: Dict, up_price: float, down_price: float, size: float
    ) -> None:
        """Notify on straddle entry."""
        bankroll = self.pm.get_current_bankroll() if self.pm else 0
        message = (
            f"🎯 <b>ENTRY</b>\n"
            f"Market: {market.get('window', '?')} BTC\n"
            f"Up: {up_price:.3f} × ${size:.2f}\n"
            f"Down: {down_price:.3f} × ${size:.2f}\n"
            f"Total: ${size * 2:.2f}\n"
            f"Bankroll: ${bankroll:.2f}"
        )
        await self.send(message)
    
    async def notify_pnl(self, pnl: float, new_bankroll: float) -> None:
        """Notify on position close."""
        emoji = "✅" if pnl > 0 else "❌"
        message = (
            f"{emoji} <b>CLOSED</b>\n"
            f"P&L: ${pnl:+.2f}\n"
            f"New Bankroll: ${new_bankroll:.2f}"
        )
        await self.send(message)
    
    async def notify_error(self, error: Exception) -> None:
        """Notify on errors."""
        message = f"⚠️ <b>ERROR</b>\n{type(error).__name__}: {str(error)[:200]}"
        await self.send(message)
    
    async def notify_pause(self, reason: str, duration_hours: float) -> None:
        """Notify when bot is pausing."""
        message = (
            f"⏸️ <b>PAUSED</b>\n"
            f"Reason: {reason}\n"
            f"Duration: {duration_hours:.1f} hours"
        )
        await self.send(message)
    
    async def notify_stats(self, stats: Dict) -> None:
        """Send periodic statistics."""
        message = (
            f"📊 <b>STATS</b>\n"
            f"Bankroll: ${stats.get('bankroll', 0):.2f}\n"
            f"Total P&L: ${stats.get('total_pnl', 0):+.2f}\n"
            f"Win Rate: {stats.get('win_rate', 0):.1%}\n"
            f"Trades: {stats.get('total_trades', 0)}\n"
            f"Open Positions: {stats.get('open_positions', 0)}"
        )
        await self.send(message)


# ============================================================================
# Main Strategy
# ============================================================================
class DeltaNeutralScalpingStrategy:
    """
    Delta-Neutral Scalping Strategy for Polymarket BTC markets.
    
    Implements all 8 core components for 24/7 operation with
    compound interest reinvestment optimized for $40 capital.
    """
    
    def __init__(
        self,
        capital: float = 40.0,
        coin: str = "BTC",
        dry_run: bool = False,
        config_path: Optional[str] = None,
        telegram_token: str = "",
        telegram_chat_id: str = "",
    ):
        self.capital = capital
        self.coin = coin.upper()
        self.dry_run = dry_run
        self.config_path = config_path
        
        # Load config if provided
        self.config_data = {}
        if config_path:
            try:
                with open(config_path) as f:
                    self.config_data = yaml.safe_load(f) or {}
                logger.info(f"Loaded config from {config_path}")
            except Exception as e:
                logger.warning(f"Could not load config {config_path}: {e}")
        
        # Core components
        self.gamma = GammaClient()
        self.ws = PolymarketWebSocketClient()
        self.clob = CLOBClient()
        self.bot = None
        
        self.scanner = MarketScanner(self.gamma)
        self.monitor = OddsMonitor(self.clob)
        self.pm = PositionManager(None, self.ws, self.clob, initial_capital=capital)
        
        self.pm.dry_run = dry_run
        self.hedger = None  # Initialized after bot is created
        self.closer = None  # Initialized after bot is created
        
        # Telegram
        self.notifier = TelegramNotifier(
            token=telegram_token,
            chat_id=telegram_chat_id,
            enabled=bool(telegram_token),
        )
        self.notifier.pm = self.pm
        
        # State
        self.is_running = False
        self.daily_loss = 0.0
        self.daily_start_bankroll = capital
        self.paused_until = 0.0
        self.last_stats_report = 0.0
        self.active_markets: List[Dict] = []
        
        # Per-market trade counting (micro-window scalping)
        self.market_trade_counts: Dict[str, int] = {}
        
        # Hedge tracking
        self.total_hedges: int = 0
        self.positions_hedged: int = 0
        self._hedged_market_ids: set = set()
    
    async def initialize(self) -> None:
        """Initialize strategy components."""
        logger.info(f"Initializing Delta-Neutral Scalping Strategy")
        logger.info(f"  Capital: ${self.capital:.2f}")
        logger.info(f"  Coin: {self.coin}")
        logger.info(f"  Dry Run: {self.dry_run}")
        
        if self.dry_run:
            logger.info("🛡️ DRY RUN MODE - All trades simulated")
        
        # Create trading bot
        try:
            self.bot = create_bot_from_env()
            self.pm.bot = self.bot
            if not self.bot.is_initialized():
                logger.warning("Bot not fully initialized - credentials may be missing")
        except Exception as e:
            logger.warning(f"Could not create bot ({e}) - using dry-run mode")
            self.dry_run = True
            self.pm.dry_run = True
        
        # Initialize delta hedger
        self.hedger = DeltaHedger(self.bot, self.ws, self.pm, self.clob)
        
        # Initialize position closer
        self.closer = PositionCloser(self.gamma, self.clob, self.pm)
        
        logger.info("✅ Strategy initialized")
    
    def _get_et_hour(self) -> int:
        """Get current hour in Eastern Time."""
        et = pytz.timezone("US/Eastern")
        return datetime.now(et).hour
    
    def _is_low_liquidity_hours(self) -> bool:
        """Check if we're in low-liquidity hours (2-4 AM ET)."""
        hour = self._get_et_hour()
        return hour in [2, 3]
    
    def _check_daily_drawdown(self) -> bool:
        """Check if daily drawdown limit has been hit.
        
        Returns True if OK to continue trading, False if should pause.
        """
        if self.daily_start_bankroll <= 0:
            return True
        daily_loss_pct = (self.daily_start_bankroll - self.pm.bankroll) / self.daily_start_bankroll
        
        if daily_loss_pct >= DAILY_DRAWDOWN_LIMIT:
            logger.warning(
                f"⚠️ Daily drawdown limit hit: {daily_loss_pct:.1%} >= {DAILY_DRAWDOWN_LIMIT:.1%}"
            )
            return False
        return True
    
    def _check_win_rate(self) -> bool:
        """Check if win rate is above minimum.
        
        Returns True if OK to continue, False if should pause.
        """
        win_rate = self.pm.get_win_rate()
        total_trades = self.pm.wins + self.pm.losses
        
        if total_trades >= 20 and win_rate < MIN_WIN_RATE:
            logger.warning(
                f"⚠️ Win rate too low: {win_rate:.1%} < {MIN_WIN_RATE:.1%}"
            )
            return False
        return True
    
    async def _find_and_subscribe(self) -> List[Dict]:
        """Find active markets and subscribe to WebSocket data."""
        markets = self.scanner.find_active_windows(
            coin=self.coin, windows=["5min", "15min"]
        )
        
        if not markets:
            logger.info(f"No active {self.coin} markets found, will retry...")
            return []
        
        logger.info(f"Found {len(markets)} active {self.coin} markets")
        
        return markets
    
    async def _process_market(self, market: Dict) -> None:
        """Process a single market for trading opportunities."""
        market_id = market.get("condition_id") or market.get("window", "") + "_" + market.get("up_token", "")[:8]
        up_token = market.get("up_token", "")
        down_token = market.get("down_token", "")
        
        if not up_token or not down_token:
            return
        
        # Micro-window scalping: max 4 trades per window
        trade_count = self.market_trade_counts.get(market_id, 0)
        if trade_count >= 4:
            logger.debug(f"Market {market.get('window')} reached max trades (4)")
            return
        
        # Check if we already have a position in this market
        if self.pm.get_position(market_id):
            # Run delta hedging on existing position
            hedged = await self.hedger.check_and_rebalance(market_id, up_token, down_token)
            if hedged:
                self.total_hedges += 1
                self._hedged_market_ids.add(market_id)
            return
        
        # Fetch current prices
        up_price_raw = self.monitor.get_last_price(up_token)
        down_price_raw = self.monitor.get_last_price(down_token)
        
        logger.debug(
            f"Market {market.get('window')}: "
            f"up_price={up_price_raw}, down_price={down_price_raw}"
        )
        
        if up_price_raw is None or down_price_raw is None:
            logger.warning(
                f"⚠️ No prices available yet for {market.get('window')} - "
                f"waiting for CLOB API data..."
            )
            return
        
        # Check entry conditions
        if not self.monitor.check_entry_conditions(up_token, down_token, max_imbalance=ENTRY_IMBALANCE_MAX):
            odds = self.monitor.get_current_odds(up_token, down_token)
            logger.debug(
                f"Entry conditions not met: up={odds['up']:.3f}, "
                f"down={odds['down']:.3f}, imbalance={odds['imbalance']:.3f} "
                f"(max={ENTRY_IMBALANCE_MAX:.3f})"
            )
            return
        
        # Check spread - avoid entering when transaction costs are too high
        spread = abs(up_price_raw - down_price_raw) if up_price_raw and down_price_raw else 1.0
        if spread > MIN_SPREAD_THRESHOLD:
            logger.debug(
                f"Spread too wide: {spread:.4f} > {MIN_SPREAD_THRESHOLD:.4f}, "
                f"skipping entry to avoid high transaction costs"
            )
            return
        
        # Get current odds
        odds = self.monitor.get_current_odds(up_token, down_token)
        if not odds["valid"]:
            logger.debug("Invalid odds")
            return
        
        up_price = odds["up"]
        down_price = odds["down"]
        imbalance = odds["imbalance"]
        
        # Calculate position size (Kelly-inspired)
        size = self.pm.calculate_size(imbalance)
        
        # Apply low-liquidity hours multiplier (H)
        et_hour = self._get_et_hour()
        size = self.pm.apply_time_multiplier(size, et_hour)
        
        if size < 2.0:
            logger.debug(f"Size too small ({size:.2f}), skipping")
            return
        
        # Check bankroll limit per window
        max_per_window = self.pm.bankroll * MAX_BANKROLL_PER_WINDOW
        if size * 2 > max_per_window:
            size = max_per_window / 2
        
        size_category = self.monitor.get_entry_size_category(imbalance)
        logger.info(
            f"🎯 Entry signal: market={market.get('window')} "
            f"up={up_price:.3f} down={down_price:.3f} "
            f"imbalance={imbalance:.3f} ({size_category}) "
            f"size=${size:.2f} "
            f"{'[LOW-LIQ HOURS +20%]' if et_hour in [2, 3] else ''}"
        )
        
        # Place straddle with ladder entry
        await self.pm.place_straddle(market_id, up_token, down_token, size)
        
        # Track trade count for micro-window scalping
        self.market_trade_counts[market_id] = trade_count + 1
        
        # Send Telegram notification
        await self.notifier.notify_entry(market, up_price, down_price, size)
    
    async def _check_early_exit(self, market_id: str, up_token: str, down_token: str) -> bool:
        """Check if we should exit position early at profit.
        
        Exits if both sides can be sold for > initial cost + 15% profit target.
        This captures opportunities when both sides rise (rare but profitable).
        
        Args:
            market_id: Market identifier
            up_token: UP token ID
            down_token: DOWN token ID
        
        Returns:
            True if position was closed early
        """
        position = self.pm.get_position(market_id)
        if not position:
            return False
        
        # Don't exit too early - need at least 2 minutes to allow price discovery
        entry_time = position.get("up", {}).get("entry_time", 0)
        time_in_position = time.time() - entry_time
        if time_in_position < 120:
            return False
        
        # Get current prices
        up_price = self.monitor.get_last_price(up_token) or 0.50
        down_price = self.monitor.get_last_price(down_token) or 0.50
        
        # Calculate potential exit value (apply EARLY_EXIT_PRICE_ADJUSTMENT to account for spread)
        up_size = position.get("up", {}).get("size", 0)
        down_size = position.get("down", {}).get("size", 0)
        exit_value = (
            (up_price * EARLY_EXIT_PRICE_ADJUSTMENT * up_size)
            + (down_price * EARLY_EXIT_PRICE_ADJUSTMENT * down_size)
        )
        
        total_cost = position.get("total_cost", 0)
        total_received = position.get("total_received", 0)
        net_cost = total_cost - total_received
        
        if net_cost <= 0:
            return False
        
        # Exit if we can lock in EARLY_EXIT_PROFIT_THRESHOLD (15%+) profit
        target_value = net_cost * (1 + EARLY_EXIT_PROFIT_THRESHOLD)
        
        if exit_value >= target_value:
            potential_pnl = exit_value - net_cost
            logger.info(
                f"💰 Early exit opportunity detected for {market_id}:\n"
                f"   Exit value: ${exit_value:.2f}\n"
                f"   Net cost: ${net_cost:.2f}\n"
                f"   Potential P&L: ${potential_pnl:.2f} ({potential_pnl/net_cost*100:.1f}%)\n"
                f"   Time in position: {time_in_position:.0f}s"
            )
            
            # Sell both sides with price adjustment to ensure fill
            up_result = await self.pm._place_order(
                up_token, up_price * EARLY_EXIT_PRICE_ADJUSTMENT, up_size, "SELL"
            )
            down_result = await self.pm._place_order(
                down_token, down_price * EARLY_EXIT_PRICE_ADJUSTMENT, down_size, "SELL"
            )
            
            if up_result.get("success") and down_result.get("success"):
                # Calculate actual P&L
                up_proceeds = up_result.get("cost", 0)    # Negative (received)
                down_proceeds = down_result.get("cost", 0)  # Negative (received)
                actual_exit_value = -up_proceeds - down_proceeds
                
                pnl = actual_exit_value + total_received - total_cost
                
                # Update bankroll and close position
                self.pm.update_bankroll(pnl)
                self.pm.close_position(market_id)
                
                logger.info(f"✅ Early exit successful: P&L=${pnl:+.2f}")
                await self.notifier.notify_pnl(pnl, self.pm.get_current_bankroll())
                
                return True
            else:
                logger.warning("⚠️ Early exit orders failed, position remains open")
        
        return False
    
    async def _report_stats_periodically(self) -> None:
        """Report stats every 30 minutes."""
        now = time.time()
        if now - self.last_stats_report >= 1800:  # 30 min
            stats = self.pm.get_stats()
            stats.update(self.hedger.get_hedge_stats() if self.hedger else {})
            
            total_trades = stats['total_trades']
            hedge_rate = (self.positions_hedged / total_trades * 100) if total_trades > 0 else 0
            
            logger.info(
                f"📊 Stats: bankroll=${stats['bankroll']:.2f} | "
                f"P&L=${stats['total_pnl']:+.2f} | "
                f"win_rate={stats['win_rate']:.1%} | "
                f"trades={total_trades} | "
                f"hedge_rate={hedge_rate:.1f}% | "
                f"total_hedges={self.total_hedges}"
            )
            await self.notifier.notify_stats(stats)
            self.last_stats_report = now
    
    async def run(self) -> None:
        """Main strategy loop.
        
        Runs continuously:
        1. Find active markets
        2. Monitor prices via CLOB API
        3. Trade when conditions are met
        4. Hedge positions
        5. Respect risk limits
        """
        await self.initialize()
        self.is_running = True
        self.daily_start_bankroll = self.pm.bankroll
        
        logger.info("🚀 Delta-Neutral Scalping Strategy running. Press Ctrl+C to stop.")
        
        try:
            iteration = 0
            
            while self.is_running:
                iteration += 1
                
                # Check if paused
                if time.time() < self.paused_until:
                    remaining = (self.paused_until - time.time()) / 3600
                    logger.info(f"⏸️ Paused for {remaining:.1f} more hours...")
                    await asyncio.sleep(60)
                    continue
                
                # Risk checks
                if not self._check_daily_drawdown():
                    pause_hours = 4.0
                    self.paused_until = time.time() + pause_hours * 3600
                    await self.notifier.notify_pause("Daily drawdown limit", pause_hours)
                    continue
                
                if not self._check_win_rate():
                    pause_hours = 2.0
                    self.paused_until = time.time() + pause_hours * 3600
                    await self.notifier.notify_pause("Win rate too low", pause_hours)
                    continue
                
                # Find markets (every 60 iterations = ~1 min)
                if iteration % 60 == 1 or not self.active_markets:
                    self.active_markets = await self._find_and_subscribe()
                    # Reset trade counts for new windows
                    if self.active_markets:
                        for m in self.active_markets:
                            market_id = m.get("condition_id") or m.get("window", "")
                            if market_id not in self.market_trade_counts:
                                self.market_trade_counts[market_id] = 0
                
                # Process each market
                for market in self.active_markets:
                    try:
                        await self._process_market(market)
                        
                        # Check for early exit opportunities on open positions
                        market_id = market.get("condition_id") or market.get("window", "")
                        up_token = market.get("up_token", "")
                        down_token = market.get("down_token", "")
                        if up_token and down_token:
                            await self._check_early_exit(market_id, up_token, down_token)
                    except Exception as e:
                        logger.error(f"Error processing market {market}: {e}")
                        import traceback
                        logger.error(traceback.format_exc())
                
                # Check and close expired positions
                try:
                    closed = await self.closer.check_and_close_expired()
                    for mid in closed:
                        if mid in self._hedged_market_ids:
                            self.positions_hedged += 1
                            self._hedged_market_ids.discard(mid)
                except Exception as e:
                    logger.error(f"Error closing positions: {e}")
                
                # Periodic stats report
                await self._report_stats_periodically()
                
                # Main loop tick rate: 1 second
                await asyncio.sleep(1)
        
        except KeyboardInterrupt:
            logger.info("Strategy stopped by user")
        except Exception as e:
            logger.error(f"Fatal error in main loop: {e}")
            import traceback
            logger.error(traceback.format_exc())
            await self.notifier.notify_error(e)
        finally:
            self.is_running = False
            
            # Final stats
            stats = self.pm.get_stats()
            total_trades = stats['total_trades']
            hedge_rate = (self.positions_hedged / total_trades * 100) if total_trades > 0 else 0
            logger.info(f"Final stats: {stats}")
            print(f"\n{'='*50}")
            print(f"  Final Statistics")
            print(f"{'='*50}")
            print(f"  Starting Capital: ${self.capital:.2f}")
            print(f"  Final Bankroll:   ${stats['bankroll']:.2f}")
            print(f"  Total P&L:        ${stats['total_pnl']:+.2f}")
            print(f"  Win Rate:         {stats['win_rate']:.1%}")
            print(f"  Total Trades:     {total_trades}")
            print(f"  Hedge Count:      {self.total_hedges}")
            print(f"  Hedge Rate:       {hedge_rate:.1f}%")


# ============================================================================
# CLI Entry Point
# ============================================================================
def parse_args():
    parser = argparse.ArgumentParser(
        description="Delta-Neutral Scalping Strategy for Polymarket BTC Markets",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Simulate trades without executing (RECOMMENDED for testing)"
    )
    parser.add_argument(
        "--capital", type=float, default=40.0,
        help="Starting capital in USDC (default: 40.0)"
    )
    parser.add_argument(
        "--coin", default="BTC", choices=["BTC", "ETH", "SOL", "XRP"],
        help="Asset to trade (default: BTC)"
    )
    parser.add_argument(
        "--config", default=None,
        help="Path to config YAML file"
    )
    parser.add_argument(
        "--telegram-token", default="",
        help="Telegram bot token for notifications"
    )
    parser.add_argument(
        "--telegram-chat-id", default="",
        help="Telegram chat ID for notifications"
    )
    return parser.parse_args()


async def main():
    """Main entry point."""
    args = parse_args()
    setup_logging("INFO")  # Изменено обратно на INFO
    
    strategy = DeltaNeutralScalpingStrategy(
        capital=args.capital,
        coin=args.coin,
        dry_run=args.dry_run,
        config_path=args.config,
        telegram_token=args.telegram_token,
        telegram_chat_id=args.telegram_chat_id,
    )
    
    await strategy.run()


if __name__ == "__main__":
    asyncio.run(main())