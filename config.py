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

# ── Odds API sport key for World Cup ──────────────────────────────────────────
# Free tier: 500 requests/month. One call returns ALL events for the sport.
ODDS_SPORT_KEY = os.environ.get("ODDS_SPORT_KEY", "soccer_fifa_world_cup")
ODDS_REGIONS   = "eu"          # eu books (Pinnacle, Bet365, Betfair)
ODDS_MARKETS   = "h2h"         # match winner; use "outrights" for qualification

# ── Fee model (Polymarket sports taker, post-2026 fee rollout) ─────────────────
# Formula: fee_per_contract = FEE_RATE * p * (1 - p)
# Max at p=0.5: 0.0075 * 0.25 = 0.001875/contract (~0.375% of notional)
SPORTS_TAKER_FEE_RATE = 0.0075

# ── Edge thresholds ────────────────────────────────────────────────────────────
MIN_NET_EDGE   = 0.04    # 4% minimum net edge to log a paper trade or alert
MAX_SPREAD_PCT = 0.03    # 3% max bid-ask spread; wider = skip (too illiquid)
MIN_VOLUME_USD = 20_000  # ignore markets with < $20K total volume

# ── Paper trade sizing (CLV tracking only — zero real money) ───────────────────
PAPER_TRADE_SIZE_USD = 200   # virtual position size for VWAP calculation
KELLY_FRACTION       = 0.25  # Quarter-Kelly when sizing real trades later

# ── Scan behaviour ────────────────────────────────────────────────────────────
SCAN_INTERVAL_MINUTES = 30   # cron cadence (override with --interval flag)
MAX_MARKETS_PER_SCAN  = 60   # raised to fit advancement markets + a few winners

# ── Risk-free rate for CLV time-value adjustment ───────────────────────────────
# US 3-month T-bill rate, June 2026 ≈ 5.3%
# clv_adjusted = clv_timing - (RISK_FREE_RATE * days_held / 365)
# This strips out the capital-lockup premium from the raw CLV signal.
RISK_FREE_RATE = 0.053

# ── Priority event slugs (the markets where retail edge could actually exist) ──
# Verified live (June 2026): advancement markets are $27K-250K volume, many
# near coin-flip (Czechia 0.55, Turkiye 0.515) = narrative-sensitive, the
# mid-liquidity tier institutions/bots under-cover. These are the TARGET.
# The "Win World Cup" outright markets ($50-70M) are efficient — negative edge.
PRIORITY_EVENT_SLUGS = [
    "world-cup-team-to-advance-to-knockout-stages",
]

# ── Database ──────────────────────────────────────────────────────────────────
DB_PATH = os.environ.get("DB_PATH", "polymarket_tracker.db")

# ── World Cup keyword filter (lower-case) ─────────────────────────────────────
WC_KEYWORDS = [
    "world cup", "qualify", "advance", "knockout", "group stage",
    "fifa", "2026 wc", "round of 32",
]

# ── Known team names for Odds API matching ────────────────────────────────────
TEAM_NAMES = [
    "Argentina", "Australia", "Belgium", "Brazil", "Cameroon", "Canada",
    "Colombia", "Croatia", "Denmark", "Ecuador", "England", "France",
    "Germany", "Ghana", "Iran", "Italy", "Japan", "Mexico", "Morocco",
    "Netherlands", "Nigeria", "Poland", "Portugal", "Saudi Arabia",
    "Scotland", "Senegal", "Serbia", "South Korea", "Spain", "Sweden",
    "Switzerland", "Tunisia", "Turkey", "Turkiye", "Ukraine", "Uruguay", "USA",
    "Wales", "Ivory Coast", "Curacao", "Haiti", "Paraguay", "Bosnia",
    "Bosnia and Herzegovina", "Qatar", "Czechia", "Czech Republic",
    "Norway", "New Zealand", "Egypt", "Uzbekistan", "Algeria", "Austria",
    "Congo DR", "Cape Verde", "Jordan", "Panama", "South Africa", "Iraq",
]
