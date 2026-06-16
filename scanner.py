"""
scanner.py — Core scanning pipeline (corrected for Polymarket V2 / live API).

Verified field names from live Gamma API (June 2026):
  - Market token IDs : clobTokenIds  (JSON string → list; index 0 = Yes, 1 = No)
  - Live prices      : bestBid, bestAsk, lastTradePrice, outcomePrices (JSON str)
  - Volume           : volume  (float string)
  - End date         : endDateIso
  - Order book       : CLOB REST at clob.polymarket.com/book?token_id=TOKEN_ID

Main available WC markets: "Will X WIN the 2026 FIFA World Cup?" outright winner
markets ($50–70M volume each).  Compared against Odds API outright winner lines.
"""

from __future__ import annotations

import json
import re
import time
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

import requests

from config import (
    GAMMA_API_BASE, CLOB_BASE,
    ODDS_API_KEY, ODDS_SPORT_KEY, ODDS_REGIONS,
    SPORTS_TAKER_FEE_RATE,
    MIN_NET_EDGE, MAX_SPREAD_PCT, MIN_VOLUME_USD,
    PAPER_TRADE_SIZE_USD, MAX_MARKETS_PER_SCAN,
    WC_KEYWORDS, TEAM_NAMES,
)

log = logging.getLogger(__name__)


# ── Data structures ────────────────────────────────────────────────────────────

@dataclass
class MarketSnapshot:
    timestamp:        str
    market_id:        str
    question:         str
    end_date:         Optional[str]
    volume_usd:       float
    yes_token_id:     str
    # Prices (from Gamma API bestBid/bestAsk + CLOB VWAP for depth)
    poly_mid:         float        # (bestBid + bestAsk) / 2 — Gamma API
    poly_ask_vwap:    float        # true cost walking $200 through ask side
    poly_bid:         float        # bestBid from Gamma API
    spread_pct:       float
    # External baseline
    book_true_prob:   float        # de-vigged P_true from sportsbooks
    baseline_source:  str
    # Decision
    taker_fee:        float
    net_edge:         float        # book_true_prob − poly_ask_vwap − fee
    alertable:        bool
    skip_reason:      str = ""
    paper_trade_id:   Optional[str] = None


# ── Module 1: Market Discovery (Gamma API) ─────────────────────────────────────

def get_world_cup_markets() -> list[dict]:
    """
    Fetch active WC markets from Gamma API.
    Primary universe: "Will X win the 2026 FIFA World Cup?" outright markets.
    Returns raw dicts with corrected field names.
    """
    url    = f"{GAMMA_API_BASE}/markets"
    found  = []
    offset = 0

    while len(found) < MAX_MARKETS_PER_SCAN:
        try:
            resp = requests.get(url, params={
                "active": "true", "closed": "false",
                "limit": 100, "offset": offset,
            }, timeout=12)
            resp.raise_for_status()
            batch = resp.json()
        except requests.RequestException as e:
            log.error("Gamma API error at offset %d: %s", offset, e)
            break

        if not batch:
            break

        for m in batch:
            q   = m.get("question", "").lower()
            vol = float(m.get("volume", 0) or 0)
            tok = m.get("clobTokenIds", "[]")

            # Volume floor + keyword filter + has token IDs
            if (vol >= MIN_VOLUME_USD
                    and any(kw in q for kw in WC_KEYWORDS)
                    and tok and tok != "[]"):
                found.append(m)

        if len(batch) < 100:
            break
        offset += 100
        time.sleep(0.1)

    # Sort by volume desc, take top MAX_MARKETS_PER_SCAN
    found.sort(key=lambda m: float(m.get("volume", 0) or 0), reverse=True)
    result = found[:MAX_MARKETS_PER_SCAN]
    log.info("Discovered %d WC markets (vol > $%s)", len(result), f"{MIN_VOLUME_USD:,}")
    return result


def parse_market_meta(m: dict) -> tuple[str, str, float, str, float, float]:
    """
    Extract (yes_token_id, end_date, volume, question, best_bid, best_ask)
    from a raw Gamma API market dict.
    """
    # clobTokenIds is a JSON string: '["tokenA", "tokenB"]'
    # outcomes[0] = "Yes", so clobTokenIds[0] = Yes token
    try:
        token_ids = json.loads(m.get("clobTokenIds", "[]"))
        yes_token = token_ids[0] if token_ids else ""
    except (json.JSONDecodeError, IndexError):
        yes_token = ""

    end_date = m.get("endDateIso") or m.get("endDate", "")
    volume   = float(m.get("volume", 0) or 0)
    question = m.get("question", "")
    best_bid = float(m.get("bestBid", 0) or 0)
    best_ask = float(m.get("bestAsk", 1) or 1)

    return yes_token, end_date, volume, question, best_bid, best_ask


# ── Module 2: CLOB Order-Book Depth ───────────────────────────────────────────

def get_clob_vwap(token_id: str, size_usd: float = PAPER_TRADE_SIZE_USD) -> tuple[float, float]:
    """
    Fetch CLOB order book, walk the ask side for `size_usd`, return
    (vwap_ask, depth_fraction).

    VWAP = total_usd_spent / total_contracts_bought
         = weighted average price per contract for this order size.

    For neg_risk markets the raw CLOB includes backstop orders at 0.001/0.999.
    We filter to the range [0.001, 0.995] to exclude those.
    Public endpoint, no authentication required.
    """
    if not token_id:
        return 0.0, 0.0

    try:
        resp = requests.get(
            f"{CLOB_BASE}/book",
            params={"token_id": token_id},
            timeout=6,
        )
        resp.raise_for_status()
        data = resp.json()
    except requests.RequestException as e:
        log.debug("CLOB unavailable for token %s: %s", token_id[:16], e)
        return 0.0, 0.0

    # Sort ascending by price (cheapest ask first), exclude backstop levels
    asks = sorted(
        [a for a in data.get("asks", []) if float(a.get("price", 1)) < 0.995],
        key=lambda x: float(x.get("price", 1)),
    )
    if not asks:
        return 0.0, 0.0

    remaining    = size_usd   # USD left to deploy
    total_usd    = 0.0        # USD spent
    total_qty    = 0.0        # contracts purchased

    for level in asks:
        price     = float(level.get("price", 1))
        qty_avail = float(level.get("size", 0))    # contracts at this level
        usd_avail = qty_avail * price              # max USD to spend here

        if usd_avail <= 0 or price <= 0:
            continue

        usd_fill  = min(remaining, usd_avail)
        qty_fill  = usd_fill / price

        total_usd += usd_fill
        total_qty += qty_fill
        remaining -= usd_fill

        if remaining <= 0:
            break

    if total_qty <= 0:
        return 0.0, 0.0

    vwap_ask       = total_usd / total_qty         # correct: USD / contracts
    depth_fraction = total_usd / size_usd          # fraction of order filled

    return round(vwap_ask, 5), round(depth_fraction, 3)


# ── Module 3: Sportsbook Baseline (De-vigged) ─────────────────────────────────

_odds_cache: dict = {}   # { sport_key: [event, ...] }


def clear_odds_cache():
    global _odds_cache
    _odds_cache = {}


def _fetch_odds(sport: str, markets: str) -> list[dict]:
    """
    Generic Odds API fetch. Cached per (sport, markets) tuple per scan run.
    The Odds API uses DIFFERENT sport keys for match odds vs outright winner:
      - soccer_fifa_world_cup         → supports h2h (match winner)
      - soccer_fifa_world_cup_winner  → supports outrights (tournament winner)
    """
    cache_key = f"{sport}:{markets}"
    if cache_key in _odds_cache:
        return _odds_cache[cache_key]

    if not ODDS_API_KEY:
        log.warning("ODDS_API_KEY not set — sportsbook baseline unavailable")
        return []

    url    = f"https://api.the-odds-api.com/v4/sports/{sport}/odds/"
    params = {
        "apiKey":     ODDS_API_KEY,
        "regions":    ODDS_REGIONS,
        "markets":    markets,
        "oddsFormat": "decimal",
    }
    try:
        resp = requests.get(url, params=params, timeout=12)
        resp.raise_for_status()
        events = resp.json()
        _odds_cache[cache_key] = events
        remaining = resp.headers.get("x-requests-remaining", "?")
        log.info("Odds API [%s/%s]: %d events (quota: %s)", sport, markets, len(events), remaining)
        return events
    except requests.RequestException as e:
        log.error("Odds API error [%s/%s]: %s", sport, markets, e)
        return []


def _fetch_odds_outright() -> list[dict]:
    """Fetch tournament winner outrights (uses soccer_fifa_world_cup_winner key)."""
    return _fetch_odds("soccer_fifa_world_cup_winner", "outrights")


def _fetch_odds_h2h() -> list[dict]:
    """Fetch match-level h2h odds (uses soccer_fifa_world_cup key)."""
    return _fetch_odds(ODDS_SPORT_KEY, "h2h")


def _devig_multiplicative(raw_probs: list[float]) -> list[float]:
    total = sum(raw_probs)
    if total == 0:
        return raw_probs
    return [p / total for p in raw_probs]


def get_devigged_win_prob(team_name: str) -> tuple[float, str]:
    """
    Find team in Odds API outright events, return (P_true, source_label).
    Averages across up to 3 bookmakers.
    Returns (0.0, "NO_MATCH") if not found.
    """
    events = _fetch_odds_outright()
    team_lower = team_name.lower()

    for event in events:
        bookmakers = event.get("bookmakers", [])
        book_probs: list[float] = []

        for bk in bookmakers[:3]:
            for mkt in bk.get("markets", []):
                # Both h2h and outrights use "outcomes" list
                outcomes = mkt.get("outcomes", [])
                names    = [o["name"].lower() for o in outcomes]

                # Find our team in this market's outcomes
                try:
                    idx = next(i for i, n in enumerate(names)
                               if team_lower in n or n in team_lower)
                except StopIteration:
                    continue

                raw   = [1.0 / o["price"] for o in outcomes]
                devig = _devig_multiplicative(raw)
                if idx < len(devig):
                    book_probs.append(devig[idx])

        if book_probs:
            avg = sum(book_probs) / len(book_probs)
            source = f"{team_name} outrights ({len(book_probs)} books)"
            return round(avg, 5), source

    return 0.0, "NO_MATCH"


# ── Module 4: Fee & Edge ───────────────────────────────────────────────────────

def taker_fee_fraction(price: float, rate: float = SPORTS_TAKER_FEE_RATE) -> float:
    """Sports taker fee as fraction of notional. Max ≈ 0.375% at p=0.5."""
    if price <= 0 or price >= 1:
        return 0.0
    return (rate * price * (1 - price)) / price


def calculate_edge(
    p_true: float,
    vwap_ask: float,
    spread_pct: float,
) -> tuple[float, float, bool, str]:
    """Return (net_edge, fee, alertable, skip_reason)."""
    if p_true <= 0:
        return 0.0, 0.0, False, "no_baseline"
    if spread_pct >= MAX_SPREAD_PCT:
        return 0.0, 0.0, False, f"spread_wide({spread_pct:.1%})"

    fee      = taker_fee_fraction(vwap_ask)
    net_edge = p_true - vwap_ask - fee

    if net_edge <= MIN_NET_EDGE:
        return net_edge, fee, False, f"edge_low({net_edge:.1%})"

    return net_edge, fee, True, ""


# ── Module 5: Team Name Extraction ────────────────────────────────────────────

def extract_team(question: str) -> Optional[str]:
    """Whole-word case-insensitive match against TEAM_NAMES list."""
    q = question.lower()
    for name in TEAM_NAMES:
        if re.search(r"\b" + re.escape(name.lower()) + r"\b", q):
            return name
    return None


# ── Module 6: Full Scan Pipeline ──────────────────────────────────────────────

def run_scan() -> list[MarketSnapshot]:
    """
    One full scan. Returns all MarketSnapshot objects (alertable and skipped).
    Callers (main.py) write to DB and send alerts.
    """
    clear_odds_cache()
    ts = datetime.now(timezone.utc).isoformat()

    markets   = get_world_cup_markets()
    snapshots = []

    for mkt in markets:
        yes_token, end_date, volume, question, best_bid, best_ask = parse_market_meta(mkt)

        if not yes_token:
            log.debug("No yes_token for: %s", question[:50])
            continue

        # ── Price from Gamma (fast, no extra call) ──
        poly_mid   = (best_bid + best_ask) / 2
        spread_pct = (best_ask - best_bid) / best_ask if best_ask > 0 else 1.0

        # ── CLOB depth for realistic VWAP ──
        vwap_ask, depth_frac = get_clob_vwap(yes_token)
        if vwap_ask <= 0 or depth_frac < 0.5:
            # Fall back to best_ask when CLOB depth is insufficient
            vwap_ask = best_ask

        # ── External baseline ──
        team = extract_team(question)
        if team:
            p_true, source = get_devigged_win_prob(team)
        else:
            p_true, source = 0.0, "no_team_match"

        # ── Fee (always computed, regardless of baseline) ──
        fee_always = taker_fee_fraction(vwap_ask)

        # ── Edge (requires baseline) ──
        net_edge, _fee, alertable, skip_reason = calculate_edge(p_true, vwap_ask, spread_pct)

        snap = MarketSnapshot(
            timestamp=ts,
            market_id=str(mkt.get("id", "")),
            question=question,
            end_date=end_date,
            volume_usd=volume,
            yes_token_id=yes_token,
            poly_mid=round(poly_mid, 4),
            poly_ask_vwap=round(vwap_ask, 4),
            poly_bid=round(best_bid, 4),
            spread_pct=round(spread_pct, 4),
            book_true_prob=p_true,
            baseline_source=source,
            taker_fee=round(fee_always, 5),
            net_edge=round(net_edge, 4),
            alertable=alertable,
            skip_reason=skip_reason,
        )
        snapshots.append(snap)
        time.sleep(0.12)   # gentle rate-limit pause

    n_alert = sum(1 for s in snapshots if s.alertable)
    log.info("Scan complete — %d markets scanned | %d signals", len(snapshots), n_alert)
    return snapshots
