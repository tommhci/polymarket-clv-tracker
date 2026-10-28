# Polymarket CLV Tracker — Paper-Trading Research

Research scanner for public soccer prediction-market prices, order-book execution proxies, and closing-line value (CLV). Current configuration focuses on EPL match markets; World Cup analysis is historical work.

**Paper trading only:** no wallet or real orders. Public-market scanning does not require exchange-trading credentials. The optional sportsbook comparison uses an `ODDS_API_KEY`; without one, that reference baseline is unavailable. No trading advantage is claimed.

---

## What it does

On each scheduled or manual scan (cadence depends on the scheduler and workflows):

```
Gamma API → discover configured soccer markets
    ↓
CLOB REST → fetch order-book depth, compute $200 VWAP
    ↓
Odds API (optional) → estimate a de-vigged sportsbook reference
    ↓
Edge calc → net_edge = P_true − VWAP_ask − taker_fee
    ↓
If net_edge > 4% AND spread < 3%:
    → log paper trade in SQLite
    → send Telegram alert
```

CLV records how paper entry prices compare with later market prices; the tracker also calculates a time-value-adjusted CLV where data permit. Positive CLV is **not** proof of a repeatable, executable or net-profitable trading edge.

---

## Setup

### 1. Install Python dependencies
```bash
pip install -r requirements.txt
```

### 2. Configure environment variables
```bash
cp .env.example .env
# Optional: add an Odds API key for sportsbook baselines; Telegram alerts are optional
```

**Odds API** (optional external sportsbook reference; check the provider for current limits):
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

Output depends on available markets, optional data providers and existing paper-trade history. An empty/insufficient-data result is valid; the command does not imply an edge was found.

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

The current `tracker.py` uses an **exploratory internal gate**, not an investment-validating statistical test:

| Resolved paper observations | Current tracker output | Interpretation |
|---|---|---|
| Fewer than 30 | Insufficient sample | Do not interpret the estimate as an established pattern |
| 30+ with adjusted CLV ≤ 0 | Negative observed signal | This sample does not support a positive signal |
| 30+ with positive adjusted CLV but `t < 2` | Not significant | The observed average is uncertain under this simple test |
| 30–99 with positive adjusted CLV and `t ≥ 2` | Promising (exploratory) | Collect independent samples; do not extrapolate to profit |
| 100+ with positive adjusted CLV and `t ≥ 2` | Positive CLV pattern | Still not proof of causation, independent performance, or executable profitability |

**Definitions:** Raw CLV compares closing and entry prices for paper positions. Adjusted CLV subtracts a modeled time-value baseline, when available. These gates do not by themselves establish statistical independence, out-of-sample validity, slippage, or net return.

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

The current configuration includes `MIN_NET_EDGE = 0.04` and `MAX_SPREAD_PCT = 0.03`. These are **research filters**, not empirically validated profitability thresholds. Adjusting them after observing outcomes can introduce selection bias; record any change before further evaluation.

---

## Known limitations

1. **Team name extraction is keyword-based** — complex questions ("Will Morocco
   finish top 2 in Group C?") may not match the Odds API. Unmatched markets
   are logged with `baseline_source = "no_team_match"` and skipped.

2. **Odds API covers match-level h2h** — "will team qualify" markets have
   no direct match-level equivalent. The scanner compares match-winner odds
   as the closest available proxy; true qualification odds would be more
   accurate (requires a bookmaker with explicit qualification lines).

3. **Paper trading ≠ real execution** — an assumed VWAP at paper size does not establish actual fills, slippage, funding/lockup costs, or net profitability.

4. **Platform changes** — Polymarket V2 launched April 28, 2026. If the
   CLOB endpoint or Gamma API changes again, update `config.py` constants.
   Check `https://docs.polymarket.com/changelog` after any reported outage.

---

## Research next steps

1. Document a pre-registered evaluation window, independent observations and missing-data rules.
2. Compare CLV and realized outcomes out of sample, with uncertainty intervals and sensitivity to selection effects.
3. Quantify theoretical execution assumptions separately from measured paper prices. This repository does not place real orders.
