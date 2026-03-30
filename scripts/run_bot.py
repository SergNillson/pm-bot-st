#!/usr/bin/env python3
"""
Run the Polymarket Trading Bot

Supports multiple modes:
- Quick demo: python scripts/run_bot.py
- Interactive: python scripts/run_bot.py --interactive
- Flash crash strategy: python scripts/run_bot.py --strategy flash_crash --coin BTC

Usage:
    python scripts/run_bot.py
    python scripts/run_bot.py --interactive
    python scripts/run_bot.py --strategy flash_crash --coin BTC --dry-run
"""

import argparse
import asyncio
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from src import create_bot_from_env
from src.gamma_client import GammaClient
from src.utils import setup_logging

logger = logging.getLogger(__name__)


async def demo_mode():
    """Quick demo showing bot capabilities."""
    print("\n🤖 Polymarket Trading Bot - Demo Mode")
    print("=" * 45)
    
    bot = create_bot_from_env()
    gamma = GammaClient()
    
    print("\n📊 Finding active markets...")
    market = gamma.get_market_info("BTC")
    if market:
        print(f"  ✅ BTC market: {market['question'][:50]}")
        print(f"     Ends: {market['end_date']}")
        print(f"     Accepting: {market['accepting_orders']}")
    else:
        print("  ℹ️  No active BTC market right now")
    
    print(f"\n🔑 Bot status: {'✅ Initialized' if bot.is_initialized() else '⚠️  Not initialized (credentials missing)'}")
    
    if bot.is_initialized():
        print("\n📋 Checking open orders...")
        orders = await bot.get_open_orders()
        print(f"  Open orders: {len(orders)}")
    
    print("\n✅ Demo complete!")
    print("   Use --interactive for manual trading")
    print("   Use --strategy flash_crash for automated trading")


async def interactive_mode():
    """Interactive trading mode."""
    print("\n🤖 Polymarket Trading Bot - Interactive Mode")
    print("=" * 45)
    
    bot = create_bot_from_env()
    gamma = GammaClient()
    
    if not bot.is_initialized():
        print("⚠️  Bot not initialized. Set POLY_PRIVATE_KEY and POLY_SAFE_ADDRESS")
        return
    
    while True:
        print("\nCommands:")
        print("  1. List open orders")
        print("  2. Cancel all orders")
        print("  3. Get BTC market info")
        print("  4. Exit")
        
        choice = input("\nEnter choice: ").strip()
        
        if choice == "1":
            orders = await bot.get_open_orders()
            print(f"\nOpen orders ({len(orders)}):")
            for order in orders:
                print(f"  - {order}")
        
        elif choice == "2":
            confirm = input("Cancel ALL orders? (y/n): ")
            if confirm.lower() == "y":
                result = await bot.cancel_all_orders()
                print("✅ Done" if result.success else f"❌ Failed: {result.message}")
        
        elif choice == "3":
            market = gamma.get_market_info("BTC")
            if market:
                print(f"\nMarket: {market['question']}")
                print(f"Up token: {market['token_ids']['up']}")
                print(f"Down token: {market['token_ids']['down']}")
            else:
                print("No active market")
        
        elif choice == "4":
            print("Goodbye!")
            break
        
        else:
            print("Invalid choice")


def parse_args():
    parser = argparse.ArgumentParser(description="Run the Polymarket Trading Bot")
    parser.add_argument("--interactive", action="store_true", help="Interactive mode")
    parser.add_argument("--strategy", choices=["flash_crash", "delta_neutral"],
                       help="Run a specific strategy")
    parser.add_argument("--coin", default="BTC", choices=["BTC", "ETH", "SOL", "XRP"])
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


async def main():
    args = parse_args()
    setup_logging("INFO")
    
    if args.strategy == "flash_crash":
        from strategies.flash_crash_strategy import FlashCrashStrategy
        strategy = FlashCrashStrategy(coin=args.coin, dry_run=args.dry_run)
        await strategy.run()
    elif args.strategy == "delta_neutral":
        from strategies.delta_neutral_scalping import main as delta_main
        await delta_main()
    elif args.interactive:
        await interactive_mode()
    else:
        await demo_mode()


if __name__ == "__main__":
    asyncio.run(main())
