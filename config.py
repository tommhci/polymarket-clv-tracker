"""
config.py — All configuration constants.
Loaded from environment variables; falls back to defaults for read-only ops.
"""

import os
from dotenv import load_dotenv

load_dotenv()

# ── External APIs ──────────────────────────────────────────────────────────────
ODDS_API_KEY        = os.environ.get("ODDS_API_KEY", "")
TELEGRAM_BOT_TOKEN  = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID    = os.environ.get("TELEGRAM_CHAT_ID", "")

# ── GLM (智谱AI) ───────────────────────────────────────────────────────────────
GLM_API_KEY  = os.environ.get("GLM_API_KEY", "")
GLM_MODEL    = os.environ.get("GLM_MODEL", "glm-4-flash")
GLM_BASE_URL = os.environ.get("GLM_BASE_URL", "https://open.bigmodel.cn/api/paas/v4")

# ── Real-time grounding ────────────────────────────────────────────────────────
# football-data.org — free, structured WC standings/results
# Docs: https://docs.football-data.org/general/v4/ (May 2022)
FOOTBALL_DATA_API_KEY = os.environ.get("FOOTBALL_DATA_API_KEY", "")

# Tavily — LLM-optimised news search, free 1000 calls/month
# Verified: designed for RAG/LLM grounding (Tavily docs, 2025)
TAVILY_API_KEY = os.environ.get("TAVILY_API_KEY", "")

# ── Polymarket endpoints (read-only, no auth required) ─────────────────────────
GAMMA_API_BASE = "https://gamma-api.polymarket.com"
CLOB_BASE      = "https://clob.polymarket.com"

# ── Odds API sport keys (EPL, since 2026-08 pivot) ─────────────────────────────
# CONSTRAINT (FIXLOG Addendum 4): the Odds API is an OPTIONAL reference layer —
# CLV is computed purely from Polymarket's own entry vs final prices. Budget:
# free tier 500 credits/month, 1 credit per call per region per market type;
# single region + h2h only + ≤2 calls/day ≈ 60 credits/month. Stay inside that
# envelope; /sports list calls are free. Missing key ⇒ no_baseline (logged,
# prices still recorded) — degradation is expected behavior, not an error.
ODDS_SPORT_KEY         = os.environ.get("ODDS_SPORT_KEY", "soccer_epl")
ODDS_SPORT_OUTRIGHT_KEY = os.environ.get("ODDS_SPORT_OUTRIGHT_KEY", "soccer_epl_winner")
ODDS_REGIONS   = "uk"          # single region (uk books) — one credit per call
ODDS_MARKETS   = "h2h"         # match winner; use "outrights" for futures

# ── Fee model (Polymarket sports taker, post-2026 fee rollout) ─────────────────
# Formula: fee_per_contract = FEE_RATE * p * (1 - p)
# Max at p=0.5: 0.0075 * 0.25 = 0.001875/contract (~0.375% of notional)
SPORTS_TAKER_FEE_RATE = 0.0075

# ── Edge thresholds ────────────────────────────────────────────────────────────
MIN_NET_EDGE   = 0.04    # 4% minimum net edge to log a paper trade or alert
MAX_SPREAD_PCT = 0.03    # 3% max bid-ask spread; wider = skip (too illiquid)
MIN_VOLUME_USD = 20_000  # ignore markets with < $20K total volume

# ── Strategy pre-registration (FIXLOG.md "P0-2") ────────────────────────────────
# Locked BEFORE paper_trades had any real rows (0 rows at the time this was
# written) — the whole point of pre-registration is committing to the entry
# rule before seeing outcomes, so results can't be cherry-picked after the
# fact. Do not add a 4th strategy or change these thresholds once real data
# has started accumulating; see tracker.classify_strategies().
STRATEGY_B_DISCOUNT_MAX     = 0.62   # B_discount: poly_mid <  this
STRATEGY_C_UNCERTAIN_LO     = 0.38   # C_uncertain: this <  poly_mid
STRATEGY_C_UNCERTAIN_HI     = 0.65   #              poly_mid <  this

# ── Paper trade sizing (CLV tracking only — zero real money) ───────────────────
PAPER_TRADE_SIZE_USD = 200   # virtual position size for VWAP calculation
KELLY_FRACTION       = 0.25  # Quarter-Kelly when sizing real trades later

# ── Scan behaviour ────────────────────────────────────────────────────────────
SCAN_INTERVAL_MINUTES = 30   # cron cadence (override with --interval flag)
MAX_MARKETS_PER_SCAN  = 60   # raised to fit advancement markets + a few winners
# EPL pivot: when no match window is active, run one light price-only scan
# per this many hours so the CLV time series keeps accumulating between
# matches (main.execute_scan "maintenance sample").
MAINTENANCE_INTERVAL_H = 6

# ── Risk-free rate for CLV time-value adjustment ───────────────────────────────
# US 3-month T-bill rate, June 2026 ≈ 5.3%
# clv_adjusted = clv_timing - (RISK_FREE_RATE * days_held / 365)
# This strips out the capital-lockup premium from the raw CLV signal.
RISK_FREE_RATE = 0.053

# ── Priority event slugs (season futures; per-match events are discovered
#    dynamically by scanner.get_epl_match_events via the Gamma tag endpoint) ──
# Verified live (2026-08-29): slug is suffixed with a creation timestamp —
# the bare "epl-2027-champion" resolves to nothing via the events endpoint.
# "EPL: 2027 Champion" is $11M volume across 24 sub-markets — the season-long
# outright series where CLV drift is measurable over months, complementing
# the weekly match-level dataset.
PRIORITY_EVENT_SLUGS = [
    "epl-2027-champion-20260701200428749",
]

# ── Database ──────────────────────────────────────────────────────────────────
DB_PATH = os.environ.get("DB_PATH", "polymarket_tracker.db")

# ── EPL keyword filter (lower-case) ───────────────────────────────────────────
# Secondary flat-feed filler only; the primary universe comes from
# scanner.get_epl_match_events() (Gamma /events?tag_slug=epl), because
# per-match questions ("Will Liverpool FC win on 2026-08-29?") contain
# neither "premier league" nor "epl".
EPL_KEYWORDS = [
    "premier league", "epl",
]

# ── Known team names for Odds API matching ────────────────────────────────────
# 2026-27 EPL clubs, enumerated from live Gamma API events on 2026-08-29
# (includes promoted Coventry City FC, Hull City AFC — do not "correct"
# against last season's table).
TEAM_NAMES = [
    "AFC Bournemouth", "Arsenal FC", "Aston Villa FC", "Brentford FC",
    "Brighton & Hove Albion FC", "Chelsea FC", "Coventry City FC",
    "Crystal Palace FC", "Everton FC", "Fulham FC", "Hull City AFC",
    "Ipswich Town FC", "Leeds United FC", "Liverpool FC",
    "Manchester City FC", "Manchester United FC", "Newcastle United FC",
    "Nottingham Forest FC", "Sunderland AFC", "Tottenham Hotspur FC",
]
