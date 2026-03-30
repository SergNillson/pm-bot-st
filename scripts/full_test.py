#!/usr/bin/env python3
"""
Full Integration Test - Tests all bot functionality against live Polymarket APIs.

This script tests:
- GammaClient: market discovery
- WebSocket: real-time data
- Bot: order management (requires credentials)

Usage:
    python scripts/full_test.py
    python scripts/full_test.py --skip-trading  # Skip order placement
"""

import asyncio
import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from src import create_bot_from_env
from src.gamma_client import GammaClient
from src.websocket_client import MarketWebSocket
from src.utils import setup_logging, validate_address

PASS = "✅"
FAIL = "❌"
SKIP = "⏭️"


async def test_gamma_client():
    """Test market discovery."""
    print("\n--- Test: GammaClient ---")
    
    gamma = GammaClient()
    
    # Test get_market_info
    print("  Testing get_market_info('BTC')...", end=" ")
    try:
        market = gamma.get_market_info("BTC")
        if market and "token_ids" in market:
            print(f"{PASS} Found: {market['question'][:40]}")
        else:
            print(f"  ℹ️ No active market right now")
    except Exception as e:
        print(f"{FAIL} Error: {e}")
    
    # Test get_all_15m_markets
    print("  Testing get_all_15m_markets()...", end=" ")
    try:
        markets = gamma.get_all_15m_markets()
        print(f"{PASS} Found {len(markets)} markets")
    except Exception as e:
        print(f"{FAIL} Error: {e}")


async def test_websocket():
    """Test WebSocket connection."""
    print("\n--- Test: WebSocket ---")
    
    gamma = GammaClient()
    market = gamma.get_market_info("BTC")
    
    if not market:
        print(f"  {SKIP} No active market - skipping WebSocket test")
        return
    
    ws = MarketWebSocket()
    received = []
    
    @ws.on_book
    async def on_book(snapshot):
        received.append(snapshot)
        if len(received) >= 2:
            await ws.disconnect()
    
    print("  Subscribing to BTC market...", end=" ", flush=True)
    token_ids = list(market["token_ids"].values())
    await ws.subscribe(token_ids)
    
    try:
        await asyncio.wait_for(ws.run(auto_reconnect=False), timeout=15)
    except asyncio.TimeoutError:
        pass
    except Exception as e:
        print(f"{FAIL} Error: {e}")
        return
    
    if received:
        print(f"{PASS} Received {len(received)} book updates")
        snapshot = received[0]
        print(f"     Mid price: {snapshot.mid_price:.4f}")
    else:
        print(f"  ℹ️ No data received (market may not be active)")


async def test_bot(skip_trading: bool = False):
    """Test bot functionality."""
    print("\n--- Test: TradingBot ---")
    
    bot = create_bot_from_env()
    
    if not bot.is_initialized():
        print(f"  {SKIP} Bot not initialized - skipping (set POLY_PRIVATE_KEY and POLY_SAFE_ADDRESS)")
        return
    
    print(f"  Bot initialized: {PASS}")
    
    # Get open orders
    print("  Getting open orders...", end=" ")
    try:
        orders = await bot.get_open_orders()
        print(f"{PASS} {len(orders)} open orders")
    except Exception as e:
        print(f"{FAIL} Error: {e}")
    
    if skip_trading:
        print(f"  {SKIP} Skipping order placement (--skip-trading)")
        return
    
    # Place and cancel a test order
    gamma = GammaClient()
    market = gamma.get_market_info("BTC")
    if not market:
        print(f"  {SKIP} No active market for trade test")
        return
    
    token_id = market["token_ids"]["up"]
    print("  Placing test order...", end=" ")
    result = await bot.place_order(token_id, 0.01, 1.0, "BUY")
    
    if result.success:
        print(f"{PASS} Order ID: {result.order_id[:20]}...")
        
        # Cancel it
        print("  Canceling test order...", end=" ")
        cancel_result = await bot.cancel_order(result.order_id)
        if cancel_result.success:
            print(f"{PASS}")
        else:
            print(f"{FAIL} {cancel_result.message}")
    else:
        print(f"{FAIL} {result.message}")


async def main():
    parser = argparse.ArgumentParser(description="Full Integration Test")
    parser.add_argument("--skip-trading", action="store_true",
                       help="Skip order placement tests")
    args = parser.parse_args()
    
    setup_logging("WARNING")
    
    print("=" * 50)
    print("  Polymarket Trading Bot - Full Integration Test")
    print("=" * 50)
    
    await test_gamma_client()
    await test_websocket()
    await test_bot(skip_trading=args.skip_trading)
    
    print("\n" + "=" * 50)
    print("  Tests complete!")
    print("=" * 50)


if __name__ == "__main__":
    asyncio.run(main())
