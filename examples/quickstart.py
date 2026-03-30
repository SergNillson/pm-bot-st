#!/usr/bin/env python3
"""
Quickstart Example - Polymarket Trading Bot

The simplest possible example to get started with the bot.
Demonstrates:
- Creating a bot from environment variables
- Getting open orders
- Viewing market prices

Setup:
    export POLY_PRIVATE_KEY=your_key
    export POLY_SAFE_ADDRESS=0xYourAddress
    python examples/quickstart.py
"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from src import create_bot_from_env
from src.gamma_client import GammaClient


async def main():
    print("=" * 50)
    print("  Polymarket Trading Bot - Quickstart")
    print("=" * 50)
    
    # Step 1: Create bot from environment variables
    print("\n1. Creating bot from environment...")
    bot = create_bot_from_env()
    
    if bot.is_initialized():
        print("   ✅ Bot initialized successfully!")
    else:
        print("   ⚠️  Bot not fully initialized (credentials missing)")
        print("      Set POLY_PRIVATE_KEY and POLY_SAFE_ADDRESS to trade")
    
    # Step 2: Find a current market
    print("\n2. Finding BTC 15-minute market...")
    gamma = GammaClient()
    market = gamma.get_market_info("BTC")
    
    if market:
        print(f"   ✅ Found: {market['question']}")
        print(f"      Up token:   {market['token_ids']['up'][:20]}...")
        print(f"      Down token: {market['token_ids']['down'][:20]}...")
        print(f"      Ends: {market['end_date']}")
        print(f"      Accepting orders: {market['accepting_orders']}")
    else:
        print("   ℹ️  No active BTC market found right now")
    
    # Step 3: Get open orders (if credentials available)
    if bot.is_initialized():
        print("\n3. Getting open orders...")
        orders = await bot.get_open_orders()
        print(f"   You have {len(orders)} open orders")
    
    print("\n" + "=" * 50)
    print("  Done! Check examples/basic_trading.py for more.")
    print("=" * 50)


if __name__ == "__main__":
    asyncio.run(main())
