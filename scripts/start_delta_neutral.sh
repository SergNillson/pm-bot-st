#!/bin/bash
# Quick start script for Delta-Neutral Scalping Strategy
# 
# Usage:
#   ./scripts/start_delta_neutral.sh              # Dry-run mode (safe)
#   ./scripts/start_delta_neutral.sh --live       # Live trading mode
#   ./scripts/start_delta_neutral.sh --help       # Show help

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

# Check if .env exists
if [ -f "$PROJECT_DIR/.env" ]; then
    echo "Loading environment from .env..."
    set -a
    source "$PROJECT_DIR/.env"
    set +a
fi

# Check required variables
if [ -z "$POLY_PRIVATE_KEY" ]; then
    echo "Warning: POLY_PRIVATE_KEY not set - will run in dry-run mode only"
fi

if [ -z "$POLY_SAFE_ADDRESS" ]; then
    echo "Warning: POLY_SAFE_ADDRESS not set - will run in dry-run mode only"
fi

# Parse arguments
DRY_RUN="--dry-run"
CAPITAL="40"
COIN="BTC"
CONFIG="$PROJECT_DIR/config/delta_neutral_config.yaml"

for arg in "$@"; do
    case $arg in
        --live)
            DRY_RUN=""
            echo "⚠️  LIVE MODE - Real money will be traded!"
            read -p "Are you sure? Type 'yes' to confirm: " confirm
            if [ "$confirm" != "yes" ]; then
                echo "Cancelled."
                exit 0
            fi
            ;;
        --capital=*)
            CAPITAL="${arg#*=}"
            ;;
        --coin=*)
            COIN="${arg#*=}"
            ;;
        --help)
            echo "Usage: $0 [--live] [--capital=40] [--coin=BTC]"
            echo ""
            echo "Options:"
            echo "  --live          Enable live trading (default: dry-run)"
            echo "  --capital=N     Starting capital in USDC (default: 40)"
            echo "  --coin=COIN     Asset to trade: BTC, ETH, SOL, XRP (default: BTC)"
            echo "  --help          Show this help"
            exit 0
            ;;
    esac
done

# Check dependencies
python3 -c "import pytz, yaml, websockets" 2>/dev/null || {
    echo "Installing required dependencies..."
    pip install -r "$PROJECT_DIR/requirements.txt" -q
}

echo "======================================"
echo "  Delta-Neutral Scalping Strategy"
echo "======================================"
echo "  Capital:  \$$CAPITAL"
echo "  Coin:     $COIN"
echo "  Mode:     ${DRY_RUN:+DRY RUN}${DRY_RUN:-LIVE}"
echo "  Config:   $CONFIG"
echo "======================================"
echo ""

# Run the strategy
cd "$PROJECT_DIR"
python3 strategies/delta_neutral_scalping.py \
    $DRY_RUN \
    --capital "$CAPITAL" \
    --coin "$COIN" \
    --config "$CONFIG"
