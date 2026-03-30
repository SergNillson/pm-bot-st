#!/usr/bin/env python3
"""
Flash Crash Strategy for Polymarket 15-Minute Markets

Monitors BTC/ETH/SOL/XRP 15-minute Up/Down markets for sudden probability
drops and executes trades automatically.

Usage:
    python strategies/flash_crash_strategy.py --coin BTC
    python strategies/flash_crash_strategy.py --coin ETH --drop 0.25 --size 10
    
Options:
    --coin          BTC, ETH, SOL, XRP (default: ETH)
    --drop          Drop threshold as absolute change (default: 0.30)
    --size          Trade size in USDC (default: 5.0)
    --lookback      Detection window in seconds (default: 10)
    --take-profit   TP in dollars (default: 0.10)
    --stop-loss     SL in dollars (default: 0.05)
    --dry-run       Simulate trades without executing
"""

import argparse
import asyncio
import logging
import time
from collections import defaultdict, deque
from typing import Optional, Dict, List
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.gamma_client import GammaClient
from src.websocket_client import MarketWebSocket, OrderbookSnapshot
from src.utils import create_bot_from_env, setup_logging

logger = logging.getLogger(__name__)


class FlashCrashStrategy:
    """
    Flash Crash Strategy for Polymarket 15-minute markets.
    
    Strategy Logic:
    1. Auto-discover current 15-minute market for the selected coin
    2. Monitor orderbook prices via WebSocket in real-time
    3. When probability drops by threshold in lookback window, buy the crashed side
    4. Exit at take profit or stop loss
    """
    
    def __init__(
        self,
        coin: str = "ETH",
        drop_threshold: float = 0.30,
        size: float = 5.0,
        lookback: int = 10,
        take_profit: float = 0.10,
        stop_loss: float = 0.05,
        dry_run: bool = False,
    ):
        self.coin = coin.upper()
        self.drop_threshold = drop_threshold
        self.size = size
        self.lookback = lookback
        self.take_profit = take_profit
        self.stop_loss = stop_loss
        self.dry_run = dry_run
        
        self.gamma = GammaClient()
        self.ws = MarketWebSocket()
        self.bot = None
        
        # Price history: {token_id: deque of (timestamp, price)}
        self.price_history: Dict[str, deque] = defaultdict(lambda: deque(maxlen=1000))
        
        # Open positions: {token_id: {'entry_price': float, 'size': float, 'entry_time': float}}
        self.positions: Dict[str, dict] = {}
        
        self.market_info = None
        self.up_token = None
        self.down_token = None
    
    async def initialize(self):
        """Initialize the strategy - find market, create bot."""
        logger.info(f"Initializing Flash Crash Strategy for {self.coin}")
        
        # Find active market
        self.market_info = self.gamma.get_market_info(self.coin)
        if not self.market_info:
            raise RuntimeError(f"No active 15-minute market found for {self.coin}")
        
        self.up_token = self.market_info["token_ids"]["up"]
        self.down_token = self.market_info["token_ids"]["down"]
        
        logger.info(f"Market: {self.market_info['question']}")
        logger.info(f"Up token: {self.up_token}")
        logger.info(f"Down token: {self.down_token}")
        
        # Create trading bot
        try:
            self.bot = create_bot_from_env()
            if not self.bot.is_initialized():
                logger.warning("Bot not fully initialized - running in monitor-only mode")
        except Exception as e:
            logger.warning(f"Could not create bot: {e} - running in monitor-only mode")
        
        # Subscribe to market data
        await self.ws.subscribe([self.up_token, self.down_token])
        
        # Register handlers
        self.ws.on_book(self._on_book_update)
        
        logger.info(f"Strategy initialized. Drop threshold: {self.drop_threshold:.2f}")
        if self.dry_run:
            logger.info("🛡️ DRY RUN MODE - No real trades will be placed")
    
    async def _on_book_update(self, snapshot: OrderbookSnapshot):
        """Handle orderbook updates."""
        token_id = snapshot.asset_id
        price = snapshot.mid_price
        
        if price <= 0:
            return
        
        now = time.time()
        self.price_history[token_id].append((now, price))
        
        # Check for flash crash
        await self._check_flash_crash(token_id, price, now)
        
        # Check exit conditions for open positions
        await self._check_exit_conditions(token_id, price)
    
    async def _check_flash_crash(self, token_id: str, current_price: float, now: float):
        """Check if a flash crash has occurred."""
        if token_id in self.positions:
            return  # Already have a position
        
        history = self.price_history[token_id]
        if len(history) < 2:
            return
        
        # Find price from lookback seconds ago
        cutoff = now - self.lookback
        past_prices = [p for t, p in history if t >= cutoff]
        
        if not past_prices:
            return
        
        max_price = max(past_prices)
        drop = max_price - current_price
        
        if drop >= self.drop_threshold:
            logger.info(
                f"⚡ FLASH CRASH DETECTED: {token_id[:20]}... "
                f"dropped {drop:.3f} from {max_price:.3f} to {current_price:.3f}"
            )
            await self._enter_position(token_id, current_price)
    
    async def _enter_position(self, token_id: str, price: float):
        """Enter a position on the crashed token."""
        logger.info(f"🔵 ENTERING: token={token_id[:20]}... price={price:.4f} size={self.size}")
        
        if self.dry_run:
            logger.info(f"🛡️ DRY RUN: Would BUY {self.size} @ {price:.4f}")
            self.positions[token_id] = {
                "entry_price": price,
                "size": self.size,
                "entry_time": time.time(),
            }
            return
        
        if self.bot and self.bot.is_initialized():
            result = await self.bot.place_order(token_id, price, self.size, "BUY")
            if result.success:
                self.positions[token_id] = {
                    "entry_price": price,
                    "size": self.size,
                    "entry_time": time.time(),
                    "order_id": result.order_id,
                }
                logger.info(f"✅ Order placed: {result.order_id}")
            else:
                logger.error(f"❌ Order failed: {result.message}")
        else:
            logger.warning("Bot not available, skipping entry")
    
    async def _check_exit_conditions(self, token_id: str, current_price: float):
        """Check take profit / stop loss conditions."""
        if token_id not in self.positions:
            return
        
        pos = self.positions[token_id]
        entry_price = pos["entry_price"]
        size = pos["size"]
        
        pnl = (current_price - entry_price) * size
        
        should_exit = False
        reason = ""
        
        if pnl >= self.take_profit:
            should_exit = True
            reason = f"TAKE PROFIT: +${pnl:.2f}"
        elif pnl <= -self.stop_loss:
            should_exit = True
            reason = f"STOP LOSS: -${abs(pnl):.2f}"
        
        if should_exit:
            logger.info(f"🔴 EXITING: {reason} | price={current_price:.4f}")
            await self._exit_position(token_id, current_price, pnl)
    
    async def _exit_position(self, token_id: str, price: float, pnl: float):
        """Exit a position."""
        pos = self.positions.pop(token_id, {})
        size = pos.get("size", self.size)
        
        if self.dry_run:
            logger.info(f"🛡️ DRY RUN: Would SELL {size} @ {price:.4f} | P&L: ${pnl:+.2f}")
            return
        
        if self.bot and self.bot.is_initialized():
            result = await self.bot.place_order(token_id, price, size, "SELL")
            if result.success:
                logger.info(f"✅ Exit order placed: {result.order_id} | P&L: ${pnl:+.2f}")
            else:
                logger.error(f"❌ Exit failed: {result.message}")
    
    async def run(self):
        """Main strategy loop."""
        await self.initialize()
        
        logger.info("🚀 Strategy running. Press Ctrl+C to stop.")
        
        try:
            await self.ws.run(auto_reconnect=True)
        except KeyboardInterrupt:
            logger.info("Strategy stopped by user")
        finally:
            await self.ws.disconnect()


def parse_args():
    parser = argparse.ArgumentParser(description="Flash Crash Strategy for Polymarket")
    parser.add_argument("--coin", default="ETH", choices=["BTC", "ETH", "SOL", "XRP"],
                       help="Asset to trade (default: ETH)")
    parser.add_argument("--drop", type=float, default=0.30,
                       help="Drop threshold as absolute change (default: 0.30)")
    parser.add_argument("--size", type=float, default=5.0,
                       help="Trade size in USDC (default: 5.0)")
    parser.add_argument("--lookback", type=int, default=10,
                       help="Detection window in seconds (default: 10)")
    parser.add_argument("--take-profit", type=float, default=0.10, dest="take_profit",
                       help="Take profit in dollars (default: 0.10)")
    parser.add_argument("--stop-loss", type=float, default=0.05, dest="stop_loss",
                       help="Stop loss in dollars (default: 0.05)")
    parser.add_argument("--dry-run", action="store_true",
                       help="Simulate trades without executing")
    return parser.parse_args()


if __name__ == "__main__":
    setup_logging("INFO")
    args = parse_args()
    
    strategy = FlashCrashStrategy(
        coin=args.coin,
        drop_threshold=args.drop,
        size=args.size,
        lookback=args.lookback,
        take_profit=args.take_profit,
        stop_loss=args.stop_loss,
        dry_run=args.dry_run,
    )
    
    asyncio.run(strategy.run())
