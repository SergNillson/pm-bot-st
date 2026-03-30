#!/usr/bin/env python3
"""
Real-time Orderbook Terminal UI for Polymarket

Displays live orderbook data for BTC/ETH/SOL/XRP 15-minute markets
with in-place terminal updates.

Usage:
    python strategies/orderbook_tui.py --coin BTC
    python strategies/orderbook_tui.py --coin ETH --levels 10
"""

import argparse
import asyncio
import logging
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.gamma_client import GammaClient
from src.websocket_client import MarketWebSocket, OrderbookSnapshot
from src.utils import setup_logging

logger = logging.getLogger(__name__)

# ANSI color codes
GREEN = "\033[92m"
RED = "\033[91m"
YELLOW = "\033[93m"
CYAN = "\033[96m"
RESET = "\033[0m"
CLEAR_LINE = "\033[2K\r"
MOVE_UP = "\033[{}A"


class OrderbookTUI:
    """Real-time terminal UI for Polymarket orderbook data."""
    
    def __init__(self, coin: str = "BTC", levels: int = 5):
        self.coin = coin.upper()
        self.levels = levels
        self.gamma = GammaClient()
        self.ws = MarketWebSocket()
        self.market_info = None
        self.up_token = None
        self.down_token = None
        self.last_up_price = 0.0
        self.last_down_price = 0.0
        self.update_count = 0
        self.start_time = time.time()
    
    async def initialize(self):
        """Find market and subscribe."""
        logger.info(f"Looking up {self.coin} 15-minute market...")
        self.market_info = self.gamma.get_market_info(self.coin)
        
        if not self.market_info:
            raise RuntimeError(f"No active 15-minute market found for {self.coin}")
        
        self.up_token = self.market_info["token_ids"]["up"]
        self.down_token = self.market_info["token_ids"]["down"]
        
        await self.ws.subscribe([self.up_token, self.down_token])
        
        @self.ws.on_book
        async def on_book(snapshot: OrderbookSnapshot):
            await self._render(snapshot)
    
    async def _render(self, snapshot: OrderbookSnapshot):
        """Render the orderbook to the terminal."""
        self.update_count += 1
        
        if snapshot.asset_id == self.up_token:
            self.last_up_price = snapshot.mid_price
        else:
            self.last_down_price = snapshot.mid_price
        
        # Build display
        lines = []
        lines.append(f"{CYAN}{'='*50}{RESET}")
        lines.append(f"{CYAN}  {self.coin} 15-Min Market Orderbook{RESET}")
        lines.append(f"  {self.market_info['question'][:45]}")
        lines.append(f"{CYAN}{'='*50}{RESET}")
        
        # UP side
        lines.append(f"\n{GREEN}  ↑ UP Token{RESET}")
        if snapshot.asset_id == self.up_token:
            ob = snapshot
        else:
            ob = self.ws.get_orderbook(self.up_token)
        
        if ob:
            lines.append(f"  Mid Price: {GREEN}{ob.mid_price:.4f}{RESET}")
            lines.append(f"  Spread:    {ob.spread:.4f}")
            lines.append(f"\n  {'Price':>8}  {'Size':>10}  Side")
            for ask in list(reversed(ob.asks[:self.levels])):
                lines.append(f"  {RED}{float(ask['price']):>8.4f}  {float(ask.get('size', 0)):>10.2f}  ASK{RESET}")
            lines.append(f"  {'---':>8}  {'---':>10}  ---")
            for bid in ob.bids[:self.levels]:
                lines.append(f"  {GREEN}{float(bid['price']):>8.4f}  {float(bid.get('size', 0)):>10.2f}  BID{RESET}")
        
        # Stats
        runtime = time.time() - self.start_time
        lines.append(f"\n{CYAN}{'='*50}{RESET}")
        lines.append(f"  Updates: {self.update_count} | Runtime: {runtime:.0f}s")
        lines.append(f"  Up: {GREEN}{self.last_up_price:.4f}{RESET} | Down: {RED}{self.last_down_price:.4f}{RESET}")
        
        # Clear and redraw
        if self.update_count > 1:
            print(MOVE_UP.format(len(lines) + 1), end="")
        
        for line in lines:
            print(f"{CLEAR_LINE}{line}")
        
        sys.stdout.flush()
    
    async def run(self):
        """Run the TUI."""
        await self.initialize()
        print(f"Connecting to {self.coin} market... (Ctrl+C to stop)\n")
        try:
            await self.ws.run(auto_reconnect=True)
        except KeyboardInterrupt:
            print("\nStopped.")


def parse_args():
    parser = argparse.ArgumentParser(description="Real-time Orderbook TUI")
    parser.add_argument("--coin", default="BTC", choices=["BTC", "ETH", "SOL", "XRP"])
    parser.add_argument("--levels", type=int, default=5, help="Number of price levels to show")
    return parser.parse_args()


if __name__ == "__main__":
    setup_logging("WARNING")  # Suppress info logs to keep TUI clean
    args = parse_args()
    tui = OrderbookTUI(coin=args.coin, levels=args.levels)
    asyncio.run(tui.run())
