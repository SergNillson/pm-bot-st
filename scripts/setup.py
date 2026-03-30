#!/usr/bin/env python3
"""
Interactive Setup Script for Polymarket Trading Bot

Guides you through:
1. Setting up your wallet credentials
2. (Optional) Encrypting your private key
3. Testing the connection

Usage:
    python scripts/setup.py
"""

import asyncio
import getpass
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.utils import validate_address, setup_logging
from src.crypto import KeyManager


def print_header(title: str):
    print(f"\n{'='*50}")
    print(f"  {title}")
    print(f"{'='*50}")


def setup_credentials():
    """Interactive credential setup."""
    print_header("Polymarket Trading Bot Setup")
    
    print("\nThis script will help you configure the trading bot.")
    print("Your credentials will NOT be stored in plain text.\n")
    
    # Get private key
    print("Step 1: Private Key")
    print("  Find your MetaMask private key in: Settings > Security > Export Private Key")
    private_key = getpass.getpass("  Enter private key (hidden): ").strip()
    
    if not private_key:
        print("  No private key provided")
        return
    
    if not private_key.startswith("0x"):
        private_key = "0x" + private_key
    
    # Get safe address
    print("\nStep 2: Safe Address")
    print("  Find at: polymarket.com/settings > General > Wallet Address")
    safe_address = input("  Enter Safe address: ").strip()
    
    if not validate_address(safe_address):
        print(f"  Warning: '{safe_address}' doesn't look like a valid Ethereum address")
    
    # Choose storage method
    print("\nStep 3: Choose how to store credentials")
    print("  1. Environment variables (recommended)")
    print("  2. Encrypted file (extra security)")
    
    choice = input("  Choice (1/2): ").strip()
    
    if choice == "1":
        print("\n✅ Add these to your .env file or shell profile:")
        print(f'  export POLY_PRIVATE_KEY="{private_key}"')
        print(f'  export POLY_SAFE_ADDRESS="{safe_address}"')
        
    elif choice == "2":
        password = getpass.getpass("\n  Create encryption password: ")
        confirm = getpass.getpass("  Confirm password: ")
        
        if password != confirm:
            print("  Passwords don't match!")
            return
        
        km = KeyManager(data_dir="credentials")
        os.makedirs("credentials", exist_ok=True)
        km.save_key(private_key, password)
        
        print("\n✅ Encrypted key saved to credentials/key.json")
        print("   Use KeyManager.load_key(password) to decrypt")
    
    print("\n🚀 Setup complete! Run: python scripts/run_bot.py")


if __name__ == "__main__":
    setup_logging("WARNING")
    setup_credentials()
