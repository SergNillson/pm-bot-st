#!/usr/bin/env python3
"""
Basic Trading Examples - Common operations with the Polymarket bot.

Demonstrates:
- Placing buy/sell orders
- Canceling orders
- Checking market prices
- Getting trade history

Setup:
    export POLY_PRIVATE_KEY=your_key
    export POLY_SAFE_ADDRESS=0xYourAddress
    python examples/basic_trading.py
"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from src import TradingBot, Config
from src import create_bot_from_env
from src.gamma_client import GammaClient


async def example_place_order():
    """Example: Place a buy order."""
    print("\n--- Example: Place Order ---")
    
    config = Config.from_env()
    bot = TradingBot(config=config, private_key="")  # Would need real key
    
    # Get a token ID to trade
    gamma = GammaClient()
    market = gamma.get_market_info("BTC")
    
    if not market:
        print("No market found")
        return
    
    token_id = market["token_ids"]["up"]
    
    print(f"Placing order: BUY 5 shares of UP @ $0.48")
    print(f"Token: {token_id[:20]}...")
    
    # This would place a real order if credentials are set
    result = await bot.place_order(
        token_id=token_id,
        price=0.48,
        size=5.0,
        side="BUY"
    )
    
    if result.success:
        print(f"✅ Order placed! ID: {result.order_id}")
    else:
        print(f"❌ Order failed: {result.message}")


async def example_cancel_orders():
    """Example: Cancel all open orders."""
    print("\n--- Example: Cancel All Orders ---")
    
    bot = create_bot_from_env()
    
    if not bot.is_initialized():
        print("Bot not initialized, skipping")
        return
    
    result = await bot.cancel_all_orders()
    if result.success:
        print("✅ All orders canceled")
    else:
        print(f"❌ Failed: {result.message}")


async def example_get_market_price():
    """Example: Get market price."""
    print("\n--- Example: Get Market Price ---")
    
    bot = create_bot_from_env()
    gamma = GammaClient()
    
    market = gamma.get_market_info("BTC")
    if not market:
        print("No market found")
        return
    
    up_token = market["token_ids"]["up"]
    price = await bot.get_market_price(up_token)
    
    if price is not None:
        print(f"BTC UP current price: {price:.4f} ({price*100:.1f}%)")
    else:
        print("Could not get price")


async def example_get_trades():
    """Example: Get trade history."""
    print("\n--- Example: Get Trade History ---")
    
    bot = create_bot_from_env()
    
    if not bot.is_initialized():
        print("Bot not initialized, skipping")
        return
    
    trades = await bot.get_trades(limit=5)
    print(f"Last {len(trades)} trades:")
    for trade in trades:
        print(f"  - {trade}")


async def main():
    print("=" * 50)
    print("  Polymarket Bot - Basic Trading Examples")
    print("=" * 50)
    
    await example_get_market_price()
    await example_get_trades()
    
    print("\n✅ Done!")


if __name__ == "__main__":
    asyncio.run(main())
