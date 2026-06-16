# Polymarket Edge Scanner — Paper Trading System

Automated scanner: Polymarket World Cup prices vs de-vigged sportsbook baseline.
**Paper trading only. No wallet. No real money. Zero credentials needed to run.**

---

## What it does

Every 30 minutes (configurable):

```
Gamma API → find active WC markets
    ↓
CLOB REST → fetch order-book depth, compute $200 VWAP
    ↓
Odds API  → fetch 3-book de-vigged true probability
    ↓
Edge calc → net_edge = P_true − VWAP_ask − taker_fee
    ↓
If net_edge > 4% AND spread < 3%:
    → log paper trade in SQLite
    → send Telegram alert
```

CLV is recorded when markets approach resolution, letting you measure
whether your entries consistently beat the closing line — the only
reliable proof of a real edge.

---

## Setup (5 minutes)

### 1. Install Python dependencies
```bash
pip install -r requirements.txt
```

### 2. Configure environment variables
```bash
cp .env.example .env
# Edit .env with your keys (Odds API required; Telegram optional)
```

**Odds API** (free, 500 calls/month — sufficient):
→ Sign up at https://the-odds-api.com
→ Paste the key into `ODDS_API_KEY`

**Telegram bot** (optional — alerts fall back to stdout if not set):
1. Message `@BotFather` → `/newbot` → copy token
2. Start your bot, visit `https://api.telegram.org/bot<TOKEN>/getUpdates`
3. Copy the `chat.id` value

### 3. Run a test scan
```bash
python main.py
```

Expected output:
```
09:15:32  INFO     main — Scan start
09:15:33  INFO     scanner — Discovered 18 WC markets above $20000 volume
09:15:41  INFO     scanner — Scan complete — 14 markets | 0 alertable
09:15:41  INFO     main — Scan done: 14 markets, 0 new signals

═══════════════════════════════════════════════════
  POLYMARKET PAPER TRADING DASHBOARD
═══════════════════════════════════════════════════
  Open positions : 0
  CLV Summary: INSUFFICIENT_DATA (need ≥10 resolved trades)
═══════════════════════════════════════════════════
```

---

## Usage

| Command | What it does |
|---|---|
| `python main.py` | Single scan + print dashboard |
| `python main.py --loop` | Scan every 30 min continuously |
| `python main.py --loop --interval 60` | Scan every 60 min |
| `python main.py --digest` | Send daily CLV summary to Telegram |
| `python main.py --dashboard` | Print dashboard to terminal |
| `python main.py --close TRADE_ID 0.82` | Manually close a paper trade |

---

## Automate with cron (Linux/macOS)

```bash
crontab -e
```

Add these lines:
```
# Scan every 30 min on matchdays
*/30 * * * * cd /path/to/polymarket-scanner && python main.py >> logs/scan.log 2>&1

# Daily CLV digest at 08:00
0 8 * * * cd /path/to/polymarket-scanner && python main.py --digest >> logs/digest.log 2>&1
```

Create the log directory first:
```bash
mkdir -p /path/to/polymarket-scanner/logs
```

**Windows**: Use Task Scheduler. Set action to:
`python C:\path\to\polymarket-scanner\main.py`

---

## Interpreting the CLV dashboard

After ≥10 resolved trades:

| Avg CLV | Verdict | Action |
|---|---|---|
| ≥ +0.020 | ✅ EDGE CONFIRMED | Scale up carefully with small real positions |
| +0.005 to +0.020 | ⚠️ MARGINAL | Track 10 more trades before deciding |
| 0 to +0.005 | ⚠️ WEAK | Noise; do not scale |
| < 0 | ❌ NO EDGE | Strategy invalid at current parameters |

**CLV definition**: `closing_price − entry_price` (for YES positions).
Positive = you entered cheaper than where the market closed.
Negative = closing line moved against your entry.

---

## Architecture

```
config.py     — constants, thresholds, API keys from .env
scanner.py    — market discovery, CLOB depth, de-vig, edge calc
tracker.py    — SQLite schema, paper trade CRUD, CLV aggregation
alerts.py     — Telegram edge signals + daily digest
main.py       — orchestration, CLI, cron entry point
```

Database (`polymarket_tracker.db`):
- `scans`        — every market snapshot (full history)
- `paper_trades` — virtual positions + CLV outcomes
- `clv_log`      — intra-trade mark-to-market checkpoints

---

## Tuning the edge threshold

Default `MIN_NET_EDGE = 0.04` (4%). Rationale:
- Polymarket sports taker fee ≈ 0.375% max
- Safety margin for API latency, spread slippage: ~1%
- Minimum signal-to-noise filter: ~2.5%
- Total friction buffer: ~4%

If you get zero signals after 2 weeks, try lowering to 0.03 (3%).
If you get 10+ signals per day, raise to 0.05 (5%) — signals are too noisy.

---

## Known limitations

1. **Team name extraction is keyword-based** — complex questions ("Will Morocco
   finish top 2 in Group C?") may not match the Odds API. Unmatched markets
   are logged with `baseline_source = "no_team_match"` and skipped.

2. **Odds API covers match-level h2h** — "will team qualify" markets have
   no direct match-level equivalent. The scanner compares match-winner odds
   as the closest available proxy; true qualification odds would be more
   accurate (requires a bookmaker with explicit qualification lines).

3. **Paper trading ≠ real execution** — VWAP at $200 paper size may differ
   from real fill at your actual size. Measure slippage explicitly before
   scaling real positions.

4. **Platform changes** — Polymarket V2 launched April 28, 2026. If the
   CLOB endpoint or Gamma API changes again, update `config.py` constants.
   Check `https://docs.polymarket.com/changelog` after any reported outage.

---

## Next steps (only after CLV confirms positive edge)

1. Add the `py-clob-client-v2` SDK for real order placement
2. Implement maker-only limit orders (0% fee + 25% rebate)
3. Apply 0.25 Kelly sizing based on confirmed avg_clv
4. Add multi-team qualification probability model (Monte Carlo, group stage)
