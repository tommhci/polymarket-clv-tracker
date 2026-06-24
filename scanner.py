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
    WC_KEYWORDS, TEAM_NAMES, PRIORITY_EVENT_SLUGS,
    RISK_FREE_RATE,
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
    # ── Multi-timepoint tracking (new) ──────────────────────────────────────
    # hours_to_end: time until market end_date at this scan moment.
    # time_bucket:  classifies which time-window this snapshot falls in.
    #   T-168h = 7 days before kickoff (far-from-resolution, bias zone)
    #   T-24h  = 24h before kickoff    (narrative is near-peak)
    #   T-1h   = 1h before kickoff     (market most informed, CLV baseline)
    #   T-other = any other scan
    # Rationale: Page & Clemen (SSRN 2013), arXiv 2602.19520 (2026) both show
    # prediction markets are miscalibrated far from resolution; CLV at T-168h
    # vs T-1h measures whether that drift is exploitable or just lockup discount.
    hours_to_end:    float = -1.0
    time_bucket:     str   = "T-other"


# ── Module 1: Market Discovery (Gamma API) ─────────────────────────────────────

def get_world_cup_markets() -> list[dict]:
    """
    Fetch active WC markets from Gamma API.
    Primary universe: "Will X win the 2026 FIFA World Cup?" outright markets.
    Returns raw dicts with corrected field names.
    """
def get_event_markets(slug: str) -> list[dict]:
    """
    Fetch all sub-markets under a Polymarket EVENT by slug.

    This is the FIX for the scan-direction defect: advancement markets
    ("Will X advance to knockout stages?") live as sub-markets under an event,
    NOT as standalone entries in the flat /markets feed. The flat feed, sorted
    by volume, is dominated by the 48 × $50-70M "Win World Cup" outright markets
    (highly efficient → negative edge), which crowd out the $27-250K advancement
    markets (mid-liquidity, narrative-sensitive → where retail edge can exist).
    """
    try:
        resp = requests.get(
            f"{GAMMA_API_BASE}/events",
            params={"slug": slug},
            timeout=12,
        )
        resp.raise_for_status()
        events = resp.json()
    except requests.RequestException as e:
        log.error("Gamma events error for slug %s: %s", slug, e)
        return []

    if not events:
        return []

    markets = events[0].get("markets", [])
    # Keep only markets that are active, have tokens, and clear volume floor
    out = []
    for m in markets:
        vol = float(m.get("volume", 0) or 0)
        tok = m.get("clobTokenIds", "[]")
        if vol >= MIN_VOLUME_USD and tok and tok != "[]":
            out.append(m)
    log.info("Event '%s': %d sub-markets above $%s", slug, len(out), f"{MIN_VOLUME_USD:,}")
    return out


def get_world_cup_markets() -> list[dict]:
    """
    Build the scan universe, PRIORITISING advancement markets over outright winners.

    Order:
      1. Priority event sub-markets (advancement to knockout) — the real target
      2. Flat /markets WC entries (fills remaining slots; mostly outright winners)

    Deduplicated by market id. Capped at MAX_MARKETS_PER_SCAN.
    """
    found: list[dict] = []
    seen_ids: set = set()

    # ── 1. Priority: advancement markets via event endpoint ──
    for slug in PRIORITY_EVENT_SLUGS:
        for m in get_event_markets(slug):
            mid = str(m.get("id", ""))
            if mid and mid not in seen_ids:
                seen_ids.add(mid)
                found.append(m)

    n_priority = len(found)

    # ── 2. Fill remaining slots from flat /markets feed ──
    url    = f"{GAMMA_API_BASE}/markets"
    offset = 0
    flat: list[dict] = []

    while len(found) + len(flat) < MAX_MARKETS_PER_SCAN:
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
            mid = str(m.get("id", ""))

            if (mid not in seen_ids
                    and vol >= MIN_VOLUME_USD
                    and any(kw in q for kw in WC_KEYWORDS)
                    and tok and tok != "[]"):
                seen_ids.add(mid)
                flat.append(m)

        if len(batch) < 100:
            break
        offset += 100
        time.sleep(0.1)

    # Sort flat fillers by volume desc, append after priority markets
    flat.sort(key=lambda m: float(m.get("volume", 0) or 0), reverse=True)
    found.extend(flat)
    result = found[:MAX_MARKETS_PER_SCAN]

    log.info(
        "Universe: %d markets (%d priority advancement + %d flat fillers)",
        len(result), n_priority, len(result) - n_priority,
    )
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


def _classify_time_bucket(end_date: Optional[str]) -> tuple[float, str]:
    """
    Compute hours until end_date and classify into time bucket.

    Buckets (±tolerance to catch GitHub Actions schedule drift):
      T-168h : 162–174h  (7 days ± 6h)
      T-24h  : 21–27h    (24h ± 3h)
      T-1h   : 0–2h      (final approach)
      T-other: everything else with hours_to_end > 0
      T-expired: end_date already passed
    """
    if not end_date:
        return -1.0, "T-other"

    now_utc = datetime.now(timezone.utc)
    try:
        ed = str(end_date)
        if "T" in ed:
            end_dt = datetime.fromisoformat(ed.replace("Z", "+00:00"))
        else:
            # Date-only string like "2026-06-20" → treat as end of day UTC
            end_dt = datetime.fromisoformat(f"{ed}T23:59:00+00:00")

        if end_dt.tzinfo is None:
            end_dt = end_dt.replace(tzinfo=timezone.utc)

        hours = (end_dt - now_utc).total_seconds() / 3600

    except (ValueError, TypeError):
        return -1.0, "T-other"

    if hours < 0:
        return round(hours, 2), "T-expired"
    elif hours <= 2:
        return round(hours, 2), "T-1h"
    elif 21 <= hours <= 27:
        return round(hours, 2), "T-24h"
    elif 162 <= hours <= 174:
        return round(hours, 2), "T-168h"
    else:
        return round(hours, 2), "T-other"


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
        # IMPORTANT: advancement markets ("Will X advance to knockout?") need
        # "to qualify" odds. The free Odds API only provides tournament-WINNER
        # outrights + match h2h — NOT advancement odds. Comparing an advance
        # market (e.g. 0.49) to winner odds (e.g. 0.005) is meaningless, so we
        # do NOT fabricate an edge signal for these. They are still logged every
        # scan, which is all CLV needs (CLV = entry price vs closing price, both
        # from Polymarket — no sportsbook baseline required).
        q_lower = question.lower()
        is_advance = any(k in q_lower for k in
                         ("advance", "qualify", "knockout", "reach the", "group stage"))

        team = extract_team(question)

        if is_advance:
            p_true, source = 0.0, "no_advance_baseline (qualification odds unavailable)"
        else:
            if team:
                p_true, source = get_devigged_win_prob(team)
            else:
                p_true, source = 0.0, "no_team_match"

        # ── Fee (always computed, regardless of baseline) ──
        fee_always = taker_fee_fraction(vwap_ask)

        # ── Edge (requires baseline) ──
        net_edge, _fee, alertable, skip_reason = calculate_edge(p_true, vwap_ask, spread_pct)

        # ── Multi-timepoint: classify this scan into a time bucket ──
        #
        # FIXLOG P0-1: Polymarket sets ONE shared endDateIso for every
        # advancement market (the group-stage-wide deadline, ~6/28), not
        # each team's own last group match. Feeding that shared date into
        # _classify_time_bucket() collapses every team into the same bucket
        # regardless of when they actually play — verified directly against
        # docs/scans.csv (all 46 advancement markets showed identical
        # hours_to_end=168.09 at the same scan timestamp). That breaks the
        # T-1h CLV/calibration entry trigger below: by the time the shared
        # deadline's T-1h window arrives, every match has long since been
        # played and prices have already converged to the known outcome.
        #
        # Fix: for advancement markets, look up this specific team's own
        # last group-stage match kickoff (football-data.org — one fetch for
        # the whole tournament, see news_fetcher.get_team_last_group_kickoff)
        # and classify against an end_date derived from THAT instead. The
        # bucket thresholds in _classify_time_bucket() itself are unchanged —
        # only the input end_date changes for advancement markets.
        effective_end_date = end_date
        if is_advance and team:
            try:
                from news_fetcher import get_team_last_group_kickoff
                real_kickoff = get_team_last_group_kickoff(team)
            except Exception as e:
                real_kickoff = None
                log.warning("football-data.org lookup failed for %s: %s", team, e)
            if real_kickoff is not None:
                # Feed the team's own kickoff time directly — NOT kickoff
                # plus a resolution lag. _classify_time_bucket()'s "T-1h"
                # bucket (hours_to_end ∈ [0,2]) is meant to mean "0-2h
                # BEFORE the moment that matters" (final lineups, highest
                # narrative bias, entry before the outcome is known — see
                # the bucket_desc comments in main.py). For advancement
                # markets that moment IS kickoff: once the match starts,
                # the live price already reflects in-game events, so the
                # clean pre-match entry window is [kickoff-2h, kickoff],
                # not [kickoff, kickoff+2h]. An earlier draft of this fix
                # added scheduler.py's RESOLUTION_LAG_H here, which shifted
                # "T-1h" to fire AFTER kickoff instead of before it — caught
                # by tests/test_p0_1_time_bucket.py, reverted.
                effective_end_date = real_kickoff.isoformat()
            else:
                log.warning(
                    "No football-data.org fixture match for advancement-market "
                    "team=%r (%s) — falling back to Polymarket's shared "
                    "endDateIso for this team only. time_bucket will be "
                    "inaccurate until football-data.org coverage improves "
                    "(see FIXLOG.md known limitations).",
                    team, question[:60],
                )

        hours_to_end, time_bucket = _classify_time_bucket(effective_end_date)

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
            hours_to_end=hours_to_end,
            time_bucket=time_bucket,
        )
        snapshots.append(snap)
        time.sleep(0.12)   # gentle rate-limit pause

    n_alert = sum(1 for s in snapshots if s.alertable)
    log.info("Scan complete — %d markets scanned | %d signals", len(snapshots), n_alert)
    return snapshots
