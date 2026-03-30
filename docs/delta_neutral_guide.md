# Delta-Neutral Scalping Strategy Guide

A complete guide for running the delta-neutral scalping strategy on Polymarket BTC 5-min and 15-min markets, optimized for $40 starting capital with compound interest reinvestment.

---

## Table of Contents

1. [Strategy Explanation](#strategy-explanation)
2. [Setup Instructions](#setup-instructions)
3. [Running Dry-Run Mode](#running-dry-run-mode)
4. [Running Live](#running-live)
5. [Parameter Tuning Guide](#parameter-tuning-guide)
6. [Interpreting Logs](#interpreting-logs)
7. [FAQ and Troubleshooting](#faq-and-troubleshooting)

---

## Strategy Explanation

### What is Delta-Neutral Scalping?

Delta-neutral scalping simultaneously buys **both sides** (UP and DOWN) of a binary market when the odds are near 50/50. Instead of betting on direction, the strategy profits from:

- **Odds drift**: Small movements away from 50/50 create asymmetric payoffs
- **Spread capture**: Buying at mid price and exiting when odds normalize
- **Compounding**: Reinvesting all profits into progressively larger positions

### The 8 Core Components

#### A. Delta-Neutral Straddle
- Buy both UP and DOWN on the same market window simultaneously
- Entry only when odds are near 50/50 (within 20% imbalance)
- Not directional betting — profit from odds drift and spread

#### B. Ladder / DCA Entry
- Split each order into 3 incremental ticks at successive price levels
- Example: UP @ 50¢, UP @ 51¢, UP @ 52¢ (simultaneously for both sides)
- Better average entry price, less slippage

#### C. Dynamic Delta Hedging
- Monitor positions in real-time via WebSocket
- Calculate delta: `delta = up_position_value - down_position_value`
- When `|delta| > 15%` of total position value:
  - Sell 60% of overweight side
  - Buy 150% on underweight side

#### D. Odds-Gated Entries
| Odds Range | Imbalance | Size per Side |
|------------|-----------|---------------|
| 48-52%     | ≤ 0.02    | $3-4          |
| 45-55%     | ≤ 0.05    | $2-3          |
| 40-60%     | ≤ 0.10    | $1-2          |
| 35-65%     | ≤ 0.15    | $0.50-1       |
| >65%/<35%  | > 0.20    | Skip          |

#### E. Kelly-Inspired Position Sizing
```python
def calculate_size(imbalance, bankroll):
    if imbalance > 0.20:
        return 0  # Skip — too risky
    max_size = bankroll * 0.10  # 10% of capital
    size = max_size / (1 + imbalance * 10)
    return max(2, min(size, 8))  # $2-8 range for $40 capital
```
As your bankroll grows, position sizes scale proportionally (compound interest).

#### F. Micro-Window Scalping
- Maximum 4 trades per single 5-minute window
- Scalp small odds movements at sub-second resolution via WebSocket
- Each trade is independent; exits are managed via delta hedging

#### G. Instant Capital Recycling
- All resolved positions are reinvested immediately
- Running bankroll: `bankroll = $40 + total_pnl`
- Position sizes grow automatically as profits accumulate

#### H. Low-Liquidity Hours Priority
- **2-4 AM ET**: Position sizes increased by 20%
- Wider spreads during these hours create better entry opportunities
- The strategy detects this automatically using Eastern Time

### Risk Management

| Parameter | Value | Description |
|-----------|-------|-------------|
| `MAX_BANKROLL_PER_WINDOW` | 15% | Maximum capital in any single window |
| `DAILY_DRAWDOWN_LIMIT` | 8% | Pause trading for 4 hours if hit |
| `MIN_WIN_RATE` | 52% | Pause trading for 2 hours if below (after 20 trades) |
| `ORDER_TIMEOUT` | 10s | Cancel unfilled orders |
| `ENTRY_IMBALANCE_MAX` | 0.20 | Skip entries beyond 20% from 50/50 |
| `HEDGE_THRESHOLD` | 0.15 | Trigger rebalancing at 15% delta |
| `MIN_LIQUIDITY` | $100 | Minimum orderbook depth required |

---

## Setup Instructions

### Prerequisites

- Python 3.9+
- A Polymarket account with a funded Safe wallet
- (Optional) Polymarket Builder Program credentials for gasless trading

### 1. Install Dependencies

```bash
git clone https://github.com/SergNillson/pm-bot-st.git
cd pm-bot-st
pip install -r requirements.txt
```

### 2. Configure Credentials

```bash
cp .env.example .env
```

Edit `.env` with your credentials:

```bash
# Required
POLY_PRIVATE_KEY=0xYourMetaMaskPrivateKey
POLY_SAFE_ADDRESS=0xYourPolymarketSafeAddress

# Optional: For gasless trading (Builder Program)
POLY_BUILDER_API_KEY=your_builder_key
POLY_BUILDER_API_SECRET=your_builder_secret
POLY_BUILDER_API_PASSPHRASE=your_builder_passphrase
```

**Where to find credentials:**
- **Private key**: MetaMask → Settings → Security → Export Private Key
- **Safe address**: [polymarket.com/settings](https://polymarket.com/settings) → General → Wallet Address
- **Builder credentials**: [polymarket.com/settings?tab=builder](https://polymarket.com/settings?tab=builder)

### 3. Verify Setup

```bash
source .env
python scripts/full_test.py --skip-trading
```

Expected output:
```
--- Test: GammaClient ---
  Testing get_market_info('BTC')... ✅ Found: Will BTC go up in next 15 minutes?
  Testing get_all_15m_markets()... ✅ Found 4 markets

--- Test: WebSocket ---
  Subscribing to BTC market... ✅ Received 2 book updates
     Mid price: 0.4987
```

---

## Running Dry-Run Mode

**Always start with dry-run mode for at least 48 hours before going live.**

Dry-run mode simulates all trades without executing real orders. It:
- Logs every trade that would have been placed
- Tracks hypothetical P&L and bankroll
- Respects all risk limits
- Sends Telegram notifications (if configured)

### Quick Start

```bash
source .env
./scripts/start_delta_neutral.sh
```

This runs in dry-run mode by default.

### Manual Command

```bash
python strategies/delta_neutral_scalping.py \
    --dry-run \
    --capital 40 \
    --coin BTC \
    --config config/delta_neutral_config.yaml
```

### With Telegram Notifications

```bash
python strategies/delta_neutral_scalping.py \
    --dry-run \
    --capital 40 \
    --coin BTC \
    --telegram-token YOUR_BOT_TOKEN \
    --telegram-chat-id YOUR_CHAT_ID
```

To get a Telegram bot token:
1. Message `@BotFather` on Telegram
2. Send `/newbot` and follow instructions
3. Copy the API token
4. Get your chat ID by messaging `@userinfobot`

### Dry-Run Output Example

```
2024-01-15 02:30:01 [INFO] Initializing Delta-Neutral Scalping Strategy
2024-01-15 02:30:01 [INFO]   Capital: $40.00
2024-01-15 02:30:01 [INFO]   Coin: BTC
2024-01-15 02:30:01 [INFO]   Dry Run: True
2024-01-15 02:30:01 [INFO] 🛡️ DRY RUN MODE - All trades simulated
2024-01-15 02:30:02 [INFO] Found 2 active BTC markets
2024-01-15 02:30:02 [INFO] 🎯 Entry signal: market=15min up=0.501 down=0.499 imbalance=0.001 (optimal) size=$3.99 [LOW-LIQ HOURS +20%]
2024-01-15 02:30:02 [INFO] 🛡️ DRY RUN: BUY 1.33 @ 0.5010 | token=a1b2c3d4e5...
2024-01-15 02:30:02 [INFO] 🛡️ DRY RUN: BUY 1.33 @ 0.5110 | token=a1b2c3d4e5...
2024-01-15 02:30:02 [INFO] 🛡️ DRY RUN: BUY 1.33 @ 0.5210 | token=a1b2c3d4e5...
```

---

## Running Live

**⚠️ Warning: Live trading uses real money. Start with the minimum $2 position size and monitor closely for the first week.**

### Before Going Live

1. ✅ Ran dry-run for at least 48 hours without errors
2. ✅ Confirmed Telegram notifications work
3. ✅ Understood all risk parameters
4. ✅ Funded your Polymarket Safe wallet with USDC
5. ✅ Applied for Builder Program (for gasless trading)

### Live Command

```bash
source .env
./scripts/start_delta_neutral.sh --live
```

The script will ask for confirmation before enabling live mode.

### Manual Live Command

```bash
python strategies/delta_neutral_scalping.py \
    --capital 40 \
    --coin BTC \
    --config config/delta_neutral_config.yaml
```

(No `--dry-run` flag = live mode)

### Recommended Rollout Schedule

| Week | Action |
|------|--------|
| Week 1-2 | Dry-run, analyze hypothetical P&L |
| Week 3 | Live with $10 capital, monitor every hour |
| Week 4 | Live with $20 if Week 3 profitable |
| Month 2+ | Live with $40, let compound interest work |

---

## Parameter Tuning Guide

### Configuration File: `config/delta_neutral_config.yaml`

```yaml
capital: 40.0                   # Starting capital
entry_imbalance_max: 0.20       # Widen to 0.25 on slow markets
min_liquidity: 100              # Lower to 50 if entry rate is too low
hedge_threshold: 0.15           # Lower to 0.10 for more aggressive hedging
daily_drawdown_limit: 0.08      # Tighten to 0.05 for more conservative risk
ladder_ticks: 3                 # Increase to 5 for smoother entry
low_liquidity_hours:
  size_multiplier: 1.2          # Increase to 1.5 if 2-4 AM is very active
```

### Key Tuning Scenarios

**Low entry rate (strategy not trading enough):**
- Increase `entry_imbalance_max` from 0.20 to 0.25
- Decrease `min_liquidity` from 100 to 50
- Check if BTC markets are active at your local time

**High hedge frequency (too much rebalancing):**
- Increase `hedge_threshold` from 0.15 to 0.20
- Check if `ladder_ticks` is causing entry imbalance

**Drawdown limit triggering too often:**
- Decrease `entry_imbalance_max` for stricter entry conditions
- Review `daily_drawdown_limit` — 8% may be too tight if the market is volatile

**Compound interest not growing fast enough:**
- Reduce `min_liquidity` requirement
- Increase `entry_imbalance_max` slightly
- Consider adding ETH or SOL markets

---

## Interpreting Logs

### Log Format
```
TIMESTAMP [LEVEL] MESSAGE
```

### Key Log Messages

| Emoji | Message | Meaning |
|-------|---------|---------|
| 🚀 | `Strategy running` | Strategy started successfully |
| 🎯 | `Entry signal` | Entry conditions met, placing straddle |
| 🛡️ | `DRY RUN: ...` | Dry-run mode, trade simulated |
| ⚖️ | `Delta imbalance detected` | Hedging triggered |
| ✅ | `Rebalanced successfully` | Hedging completed |
| ⏸️ | `Paused for X hours` | Risk limit triggered |
| ⚠️ | `Daily drawdown limit hit` | 8% daily loss reached |
| 📊 | `Stats:` | Periodic performance update |

### Performance Statistics (every 30 minutes)

```
📊 Stats: bankroll=$43.21 | P&L=+$3.21 | win_rate=58.3% | trades=24
```

- **bankroll**: Current capital including all profits
- **P&L**: Total profit/loss since strategy started
- **win_rate**: Percentage of winning trades
- **trades**: Total completed trades

### Example Healthy Log

```
[INFO] 📊 Stats: bankroll=$41.50 | P&L=+$1.50 | win_rate=60.0% | trades=10
[INFO] 🎯 Entry signal: market=15min up=0.502 imbalance=0.002 (optimal) size=$4.00
[INFO] Placing straddle: market=0xabc123 size=4.00 each side
[INFO] ⚖️ Delta imbalance detected: delta=0.85 (16.0% of total $5.30)
[INFO] ✅ Rebalanced successfully (hedge #3)
```

### Warning Signs

```
[WARNING] ⚠️ Daily drawdown limit hit: 8.1% >= 8.0%
[WARNING] ⚠️ Win rate too low: 48.0% < 52.0%
[WARNING] Bot not fully initialized - credentials may be missing
```

---

## FAQ and Troubleshooting

### Q: The strategy says "No active BTC markets found" — what do I do?

**A:** BTC 5-min and 15-min markets on Polymarket are only available during certain periods. Markets may not be available:
- Right after a market closes (wait 1-2 minutes for the next one)
- During technical issues with Polymarket

The strategy automatically retries every minute.

### Q: I'm getting "Bot not initialized" warnings

**A:** Your environment variables are not set correctly. Make sure to run:
```bash
source .env
echo $POLY_PRIVATE_KEY  # Should show your key
echo $POLY_SAFE_ADDRESS  # Should show 0x...
```

### Q: The WebSocket keeps disconnecting

**A:** This is normal. The strategy auto-reconnects. If it disconnects more than once every few minutes, check:
1. Your internet connection
2. Polymarket WebSocket status
3. Increase sleep time in the reconnection logic

### Q: Why is the win rate showing 0% with 0 trades?

**A:** The strategy needs enough liquidity and near-50/50 odds to enter. During trending markets, the imbalance may exceed `entry_imbalance_max`. Try:
- Lowering `entry_imbalance_max` to 0.25
- Running during 2-4 AM ET when odds are more neutral
- Checking if there are active BTC markets

### Q: My bankroll went below $40 — should I stop?

**A:** The strategy will automatically pause at 8% drawdown ($40 × 8% = $3.20 loss = $36.80 bankroll). If you've manually stopped and restarted, the drawdown counter resets. You can set a harder floor by modifying `DAILY_DRAWDOWN_LIMIT`.

### Q: How do I add Telegram notifications?

**A:**
1. Create a bot with `@BotFather` → get token
2. Get your chat ID from `@userinfobot`
3. Run with:
```bash
python strategies/delta_neutral_scalping.py \
    --dry-run \
    --telegram-token 123456:ABC-... \
    --telegram-chat-id 987654321
```

### Q: How long should I run dry-run before going live?

**A:** At least 48 hours, ideally 1 week. Look for:
- Consistent positive P&L trend
- Win rate above 52%
- No crashes or unexpected errors
- Understanding of when the strategy enters and exits

### Q: What are the expected returns for $40 capital?

**A:** This depends heavily on market conditions. The strategy is designed for:
- Small, consistent gains (0.5-2% per day)
- Compound growth over weeks/months
- Capital preservation as primary goal

**Do not expect to turn $40 into $400 quickly.** The compound interest effect becomes meaningful over months.

### Q: Can I run multiple instances for different coins?

**A:** Yes! Run separate instances:
```bash
# Terminal 1: BTC
python strategies/delta_neutral_scalping.py --dry-run --coin BTC --capital 20

# Terminal 2: ETH  
python strategies/delta_neutral_scalping.py --dry-run --coin ETH --capital 20
```

Split your capital proportionally. Note: Currently 5-min markets may only exist for BTC.

### Q: The strategy placed too many orders — how do I cancel them?

**A:**
```python
from src import create_bot_from_env
import asyncio

async def cancel_all():
    bot = create_bot_from_env()
    result = await bot.cancel_all_orders()
    print(f"Canceled: {result.success}")

asyncio.run(cancel_all())
```

Or interactively:
```bash
python scripts/run_bot.py --interactive
# Choose option 2: Cancel all orders
```

---

## Architecture Reference

```
DeltaNeutralScalpingStrategy
├── MarketScanner (market_scanner.py)
│   └── Discovers active BTC 5min/15min windows via GammaClient
│
├── OddsMonitor (odds_monitor.py)
│   └── Real-time odds & liquidity tracking via WebSocket
│
├── PositionManager (position_manager.py)
│   ├── Kelly-inspired sizing
│   ├── Ladder/DCA entry (3-5 ticks)
│   └── Compound bankroll tracking
│
├── DeltaHedger (delta_hedger.py)
│   └── Rebalances when |delta| > 15% of total value
│
└── TelegramNotifier
    └── Entry/exit/P&L/error notifications
```

---

## Important Disclaimers

- This strategy is for **educational purposes** with small capital ($40)
- **Start with dry-run mode** for at least 48 hours minimum
- Polymarket binary markets are **high-risk** instruments
- Past performance in dry-run does not guarantee live performance
- **Never trade with money you cannot afford to lose**
- Monitor the strategy closely, especially in the first week of live trading
