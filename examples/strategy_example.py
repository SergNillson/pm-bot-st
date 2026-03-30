#!/usr/bin/env python3
"""
Custom Strategy Example - Template for building your own strategies.

This shows the framework for creating a custom trading strategy.
Includes:
- Strategy base structure
- Event-driven design with WebSocket
- Position tracking
- Risk management hooks

Usage:
    python examples/strategy_example.py --dry-run
"""

import asyncio
import logging
import sys
from pathlib import Path
from abc import ABC, abstractmethod
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.gamma_client import GammaClient
from src.websocket_client import MarketWebSocket, OrderbookSnapshot
from src.utils import create_bot_from_env, setup_logging

logger = logging.getLogger(__name__)


class BaseStrategy(ABC):
    """Abstract base class for trading strategies."""
    
    def __init__(self, dry_run: bool = False):
        self.dry_run = dry_run
        self.is_running = False
        self.trades_count = 0
        self.total_pnl = 0.0
    
    @abstractmethod
    async def initialize(self) -> None:
        """Initialize the strategy (find markets, create bot, etc.)."""
        pass
    
    @abstractmethod
    async def on_price_update(self, snapshot: OrderbookSnapshot) -> None:
        """Called on each orderbook update."""
        pass
    
    async def run(self) -> None:
        """Main run loop."""
        await self.initialize()
        self.is_running = True
        logger.info(f"Strategy started (dry_run={self.dry_run})")
        
        # Override in subclasses to run your main loop
    
    def get_stats(self) -> dict:
        """Get strategy performance statistics."""
        return {
            "trades": self.trades_count,
            "total_pnl": self.total_pnl,
            "is_running": self.is_running,
        }


class ExampleMeanReversionStrategy(BaseStrategy):
    """
    Example: Mean Reversion Strategy
    
    Buys when price is below historical average,
    sells when price is above historical average.
    """
    
    def __init__(self, coin: str = "BTC", window: int = 30, dry_run: bool = False):
        super().__init__(dry_run=dry_run)
        self.coin = coin.upper()
        self.window = window  # seconds
        self.gamma = GammaClient()
        self.ws = MarketWebSocket()
        self.bot = None
        self.price_history = []
        self.position = None
    
    async def initialize(self):
        """Find market and set up WebSocket."""
        market = self.gamma.get_market_info(self.coin)
        if not market:
            raise RuntimeError(f"No market for {self.coin}")
        
        self.up_token = market["token_ids"]["up"]
        logger.info(f"Found market: {market['question']}")
        
        try:
            self.bot = create_bot_from_env()
        except Exception as e:
            logger.warning(f"Bot setup failed: {e}")
        
        await self.ws.subscribe([self.up_token])
        self.ws.on_book(self.on_price_update)
    
    async def on_price_update(self, snapshot: OrderbookSnapshot):
        """React to price changes."""
        price = snapshot.mid_price
        if price <= 0:
            return
        
        self.price_history.append(price)
        if len(self.price_history) > 1000:
            self.price_history.pop(0)
        
        # Need enough history
        if len(self.price_history) < 10:
            return
        
        avg_price = sum(self.price_history[-30:]) / min(30, len(self.price_history))
        deviation = price - avg_price
        
        if deviation < -0.05 and self.position is None:
            logger.info(f"Buy signal: price={price:.4f} avg={avg_price:.4f} dev={deviation:.4f}")
            await self._enter_long(price)
        elif deviation > 0.03 and self.position is not None:
            logger.info(f"Sell signal: price={price:.4f} avg={avg_price:.4f}")
            await self._exit_position(price)
    
    async def _enter_long(self, price: float):
        size = 2.0
        if self.dry_run:
            logger.info(f"🛡️ DRY RUN: BUY {size} @ {price:.4f}")
            self.position = {"price": price, "size": size}
            self.trades_count += 1
            return
        
        if self.bot and self.bot.is_initialized():
            result = await self.bot.place_order(self.up_token, price, size, "BUY")
            if result.success:
                self.position = {"price": price, "size": size, "order_id": result.order_id}
                self.trades_count += 1
    
    async def _exit_position(self, price: float):
        if not self.position:
            return
        
        pnl = (price - self.position["price"]) * self.position["size"]
        self.total_pnl += pnl
        
        if self.dry_run:
            logger.info(f"🛡️ DRY RUN: SELL @ {price:.4f} | P&L: ${pnl:+.2f}")
            self.position = None
            return
        
        if self.bot and self.bot.is_initialized():
            result = await self.bot.place_order(
                self.up_token, price, self.position["size"], "SELL"
            )
            if result.success:
                self.position = None
                logger.info(f"Exited position | P&L: ${pnl:+.2f}")
    
    async def run(self):
        await self.initialize()
        logger.info("Mean Reversion Strategy running...")
        try:
            await self.ws.run(auto_reconnect=True)
        except KeyboardInterrupt:
            logger.info("Stopped by user")
            stats = self.get_stats()
            print(f"\nFinal stats: {stats}")
        finally:
            await self.ws.disconnect()


if __name__ == "__main__":
    import argparse
    setup_logging("INFO")
    
    parser = argparse.ArgumentParser(description="Custom Strategy Example")
    parser.add_argument("--coin", default="BTC")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    
    strategy = ExampleMeanReversionStrategy(coin=args.coin, dry_run=args.dry_run)
    asyncio.run(strategy.run())
