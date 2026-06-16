"""
glm_helper.py — GLM (智谱AI) powered market analysis.

Two functions, both hitting the same API:
  1. analyze_market()     — parse complex question text the regex can't handle
  2. analyze_pre_match()  — pre-match trading intelligence report

For #2: GLM is used for what LLMs are actually good at in financial contexts —
extracting structured signals from known context (team history, tournament format,
narrative factors) — NOT for real-time price prediction.

KNOWN LIMITATION (documented): GLM-4's training cutoff is ~late 2024, so it does
not know June 2026 match results. Pre-match analysis draws on historical context
(team tournament record, playing style, squad strength) + structural reasoning
about the 2026 format. Current standings must be injected as context from our DB.

API endpoint: https://open.bigmodel.cn/api/paas/v4  (OpenAI-compatible)
Source: apidog.com/blog/how-to-use-glm-5-1-api (May 2026)
"""

from __future__ import annotations

import json
import logging
import sqlite3
from dataclasses import dataclass
from typing import Optional

from config import GLM_API_KEY, GLM_MODEL, GLM_BASE_URL, DB_PATH

log = logging.getLogger(__name__)

# Lazy-init client — only created when a key is present
_client = None


def _get_client():
    global _client
    if _client is not None:
        return _client
    if not GLM_API_KEY:
        return None
    try:
        from openai import OpenAI
        _client = OpenAI(api_key=GLM_API_KEY, base_url=GLM_BASE_URL)
        log.info("GLM client initialised (model: %s)", GLM_MODEL)
        return _client
    except Exception as e:
        log.warning("GLM client init failed: %s", e)
        return None


# ── Cache schema (added to existing DB) ───────────────────────────────────────

def ensure_glm_cache(path: str = DB_PATH):
    conn = sqlite3.connect(path)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS glm_cache (
            market_id        TEXT PRIMARY KEY,
            team_name        TEXT,
            market_type      TEXT,
            resolution_risk  INTEGER,   -- 0 = clean, 1 = possible dispute
            risk_reason      TEXT,
            raw_response     TEXT,
            created_at       TEXT
        )
    """)
    # ── Pre-match intelligence table ─────────────────────────────────────────
    conn.execute("""
        CREATE TABLE IF NOT EXISTS glm_prematch (
            id               INTEGER PRIMARY KEY AUTOINCREMENT,
            market_id        TEXT NOT NULL,
            team             TEXT,
            poly_price       REAL,
            hours_to_end     REAL,
            price_assessment TEXT,
            group_status     TEXT,
            narrative_risk   TEXT,
            watch_flags      TEXT,
            context_text     TEXT,
            confidence       TEXT,
            raw_response     TEXT,
            created_at       TEXT,
            UNIQUE(market_id, created_at)
        )
    """)
    conn.commit()
    conn.close()


def _get_cached(market_id: str, path: str = DB_PATH) -> Optional[dict]:
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    row = conn.execute(
        "SELECT * FROM glm_cache WHERE market_id = ?", (market_id,)
    ).fetchone()
    conn.close()
    return dict(row) if row else None


def _save_cache(market_id: str, result: dict, path: str = DB_PATH):
    from datetime import datetime, timezone
    conn = sqlite3.connect(path)
    conn.execute("""
        INSERT OR REPLACE INTO glm_cache
        (market_id, team_name, market_type, resolution_risk, risk_reason, raw_response, created_at)
        VALUES (?,?,?,?,?,?,?)
    """, (
        market_id,
        result.get("team_name"),
        result.get("market_type"),
        int(result.get("resolution_risk", 0)),
        result.get("risk_reason", ""),
        json.dumps(result),
        datetime.now(timezone.utc).isoformat(),
    ))
    conn.commit()
    conn.close()


# ── Core GLM call ──────────────────────────────────────────────────────────────

@dataclass
class MarketInfo:
    team_name:       Optional[str]    # e.g. "Japan"
    market_type:     str              # "outright_winner" | "qualify" | "match" | "prop"
    resolution_risk: bool             # True → possible UMA dispute
    risk_reason:     str              # human-readable explanation
    source:          str              # "glm" | "cache" | "regex_fallback"


_SYSTEM_PROMPT = """\
You are a prediction market analyst. When given a Polymarket question and its
description, return ONLY a JSON object with exactly these keys:

{
  "team_name": "<FIFA member team name, or null>",
  "market_type": "<one of: outright_winner | qualify | match_winner | group_winner | prop | other>",
  "resolution_risk": <true if resolution criteria are ambiguous, involve tiebreakers,
                      multi-condition logic, or third-place wildcards; else false>,
  "risk_reason": "<one sentence explanation, or empty string>"
}

Rules:
- team_name must be the exact FIFA team name (e.g. "Ivory Coast" not "CIV")
- Do NOT add extra keys. Do NOT wrap in markdown. Return raw JSON only.
"""


def analyze_market(
    market_id:   str,
    question:    str,
    description: str = "",
    path:        str = DB_PATH,
) -> MarketInfo:
    """
    Returns MarketInfo for a market question, using:
      1. SQLite cache  (free, instant)
      2. GLM API call  (costs tokens, ~1 call per new unique market)
      3. Regex fallback (if GLM unavailable)

    For the paper-trading phase, call this only when extract_team() returns None.
    """
    ensure_glm_cache(path)

    # ── Cache hit ──
    cached = _get_cached(market_id, path)
    if cached:
        return MarketInfo(
            team_name=cached["team_name"],
            market_type=cached.get("market_type", "other"),
            resolution_risk=bool(cached["resolution_risk"]),
            risk_reason=cached.get("risk_reason", ""),
            source="cache",
        )

    client = _get_client()

    # ── Regex fallback (no GLM key) ──
    if client is None:
        from scanner import extract_team
        team = extract_team(question)
        result = MarketInfo(
            team_name=team,
            market_type="unknown",
            resolution_risk=False,
            risk_reason="",
            source="regex_fallback",
        )
        return result

    # ── GLM API call ──
    user_msg = f"Question: {question}\n\nDescription: {description[:600]}"
    try:
        response = client.chat.completions.create(
            model=GLM_MODEL,
            messages=[
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user",   "content": user_msg},
            ],
            temperature=0,
            max_tokens=200,
        )
        raw = response.choices[0].message.content.strip()
        data = json.loads(raw)

        result_dict = {
            "team_name":       data.get("team_name"),
            "market_type":     data.get("market_type", "other"),
            "resolution_risk": bool(data.get("resolution_risk", False)),
            "risk_reason":     data.get("risk_reason", ""),
        }
        _save_cache(market_id, result_dict, path)
        log.info("GLM parsed: %s → team=%s risk=%s",
                 question[:50], result_dict["team_name"], result_dict["resolution_risk"])

        return MarketInfo(
            team_name=result_dict["team_name"],
            market_type=result_dict["market_type"],
            resolution_risk=result_dict["resolution_risk"],
            risk_reason=result_dict["risk_reason"],
            source="glm",
        )

    except json.JSONDecodeError as e:
        log.warning("GLM returned non-JSON for %s: %s", question[:40], e)
    except Exception as e:
        log.warning("GLM API error for %s: %s", question[:40], e)

    # Final fallback
    from scanner import extract_team
    return MarketInfo(
        team_name=extract_team(question),
        market_type="unknown",
        resolution_risk=False,
        risk_reason="glm_error",
        source="regex_fallback",
    )


# ── Batch analysis for a full scan ────────────────────────────────────────────

def enrich_snapshots(snapshots: list, path: str = DB_PATH) -> dict[str, MarketInfo]:
    """
    For all snapshots where team is missing or market type is unclear,
    call GLM to fill in the gaps. Returns {market_id: MarketInfo} mapping.

    Call this AFTER run_scan(), before deciding which paper trades to open.
    """
    results: dict[str, MarketInfo] = {}

    for snap in snapshots:
        # Only call GLM when keyword matching already failed
        if snap.baseline_source in ("no_team_match", "NO_MATCH", ""):
            info = analyze_market(snap.market_id, snap.question, path=path)
            results[snap.market_id] = info

    if results:
        log.info("GLM enriched %d markets", len(results))

    return results



# ── Pre-match intelligence ──────────────────────────────────────────────────

_PREMATCH_SYSTEM = """\
You are a quantitative prediction market analyst specialising in football (soccer)
World Cup advancement markets. Your job is NOT sports broadcasting — it is identifying
whether the current Polymarket implied probability is consistent with fundamentals,
and flagging specific reasons the price might be systematically wrong.

IMPORTANT LIMITATION: Your training data may not include real-time match results
from the current tournament. If you don't know the current standings, say so in
context_text and reason from historical base rates and format rules instead.

Return ONLY valid JSON with exactly these keys — no markdown, no extra text:
{
  "context_text":     "<2-3 sentences of relevant factual context>",
  "group_status":     "<one of: leading|mid-table|must-win|already-qualified|eliminated|unknown>",
  "price_assessment": "<one of: appears_overpriced|appears_underpriced|appears_fair|uncertain>",
  "narrative_risk":   "<1 sentence — the single most plausible reason the market might be wrong>",
  "watch_flags":      ["<specific thing to watch>", "<max 3 items>"],
  "confidence":       "<one of: low|medium|high>",
  "reasoning":        "<1-2 sentences explaining price_assessment>"
}
"""


@dataclass
class PreMatchSignal:
    market_id:        str
    team:             str
    poly_price:       float
    price_assessment: str    # appears_overpriced | underpriced | fair | uncertain
    group_status:     str
    narrative_risk:   str
    watch_flags:      list
    context_text:     str
    reasoning:        str
    confidence:       str
    source:           str    # "glm" | "glm_cache" | "unavailable"
    created_at:       str    = ""


def analyze_pre_match(
    market_id:    str,
    team:         str,
    poly_price:   float,
    hours_to_end: float,
    path:         str = DB_PATH,
    max_age_h:    float = 6.0,      # re-analyse at most every 6 hours
) -> PreMatchSignal:
    """
    Generate a pre-match trading intelligence signal using GLM.

    Called when time_bucket is T-24h or T-1h. Results are cached in the
    glm_prematch table (one fresh analysis per market per ~6h window).

    GLM is used here for what LLMs are genuinely good at: extracting structured
    signals from historical/contextual knowledge. It is NOT asked to predict
    outcomes — it is asked whether the CURRENT PRICE seems consistent with what
    it knows about this team.

    Source: NVIDIA blog on LLM financial signal discovery (June 2026);
            Squawka AI methodology — structured signals from weighted inputs.
    """
    ensure_glm_cache(path)
    now = datetime.now(timezone.utc)
    ts  = now.isoformat()

    # ── Check for recent cached analysis ─────────────────────────────────────
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    row = conn.execute("""
        SELECT * FROM glm_prematch
        WHERE market_id = ?
        ORDER BY created_at DESC LIMIT 1
    """, (market_id,)).fetchone()
    conn.close()

    if row:
        age_h = (now - datetime.fromisoformat(
            str(row["created_at"]).replace("Z", "+00:00")
        )).total_seconds() / 3600
        if age_h < max_age_h:
            flags = json.loads(row["watch_flags"] or "[]")
            return PreMatchSignal(
                market_id=market_id, team=team, poly_price=poly_price,
                price_assessment=row["price_assessment"] or "uncertain",
                group_status=row["group_status"] or "unknown",
                narrative_risk=row["narrative_risk"] or "",
                watch_flags=flags,
                context_text=row["context_text"] or "",
                reasoning="",
                confidence=row["confidence"] or "low",
                source="glm_cache",
                created_at=row["created_at"],
            )

    client = _get_client()
    if client is None:
        return PreMatchSignal(
            market_id=market_id, team=team, poly_price=poly_price,
            price_assessment="uncertain", group_status="unknown",
            narrative_risk="", watch_flags=[],
            context_text="GLM_API_KEY not configured — no AI analysis available.",
            reasoning="", confidence="low",
            source="unavailable", created_at=ts,
        )

    # ── Build user prompt ─────────────────────────────────────────────────────
    pct = f"{poly_price * 100:.1f}%"
    direction = (
        "significantly above 50%" if poly_price > 0.65 else
        "slightly above 50%"      if poly_price > 0.52 else
        "near coin-flip (50/50)"  if abs(poly_price - 0.5) < 0.05 else
        "slightly below 50%"      if poly_price > 0.35 else
        "significantly below 50%"
    )
    user_msg = (
        f"Market: Will {team} advance to the knockout stages at the 2026 FIFA World Cup?\n"
        f"Current Polymarket implied probability: {pct} ({direction})\n"
        f"Hours until market resolution: {hours_to_end:.1f}h\n\n"
        f"Analyse whether this price appears well-calibrated given:\n"
        f"1. {team}'s historical World Cup record and typical performance level\n"
        f"2. Their group composition and likely opponents\n"
        f"3. The 2026 format: top 2 per group qualify + 8 best 3rd-place teams\n"
        f"4. Any known factors (squad strength, playing style, historical patterns)\n\n"
        f"If you lack current tournament data, reason from base rates and structure.\n"
        f"Focus on: is {pct} a reasonable price, or does it seem inconsistent?"
    )

    try:
        resp = client.chat.completions.create(
            model=GLM_MODEL,
            messages=[
                {"role": "system", "content": _PREMATCH_SYSTEM},
                {"role": "user",   "content": user_msg},
            ],
            temperature=0.2,
            max_tokens=400,
        )
        raw  = resp.choices[0].message.content.strip()
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        log.warning("GLM prematch non-JSON for %s: %s", team, e)
        data = {}
    except Exception as e:
        log.error("GLM prematch API error for %s: %s", team, e)
        data = {}

    flags = data.get("watch_flags", [])
    if not isinstance(flags, list):
        flags = []

    # ── Persist to DB ─────────────────────────────────────────────────────────
    conn = sqlite3.connect(path)
    conn.execute("""
        INSERT INTO glm_prematch
        (market_id, team, poly_price, hours_to_end, price_assessment,
         group_status, narrative_risk, watch_flags, context_text,
         confidence, raw_response, created_at)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
    """, (
        market_id, team, poly_price, hours_to_end,
        data.get("price_assessment", "uncertain"),
        data.get("group_status", "unknown"),
        data.get("narrative_risk", ""),
        json.dumps(flags),
        data.get("context_text", ""),
        data.get("confidence", "low"),
        raw if 'raw' in dir() else "{}",
        ts,
    ))
    conn.commit()
    conn.close()

    log.info("GLM prematch [%s] @ %.3f → %s (confidence=%s)",
             team, poly_price,
             data.get("price_assessment", "uncertain"),
             data.get("confidence", "low"))

    return PreMatchSignal(
        market_id=market_id, team=team, poly_price=poly_price,
        price_assessment=data.get("price_assessment", "uncertain"),
        group_status=data.get("group_status", "unknown"),
        narrative_risk=data.get("narrative_risk", ""),
        watch_flags=flags,
        context_text=data.get("context_text", ""),
        reasoning=data.get("reasoning", ""),
        confidence=data.get("confidence", "low"),
        source="glm",
        created_at=ts,
    )


def get_latest_prematch_signals(
    path: str = DB_PATH,
    limit: int = 10,
) -> list[dict]:
    """
    Fetch the most recent pre-match signals for the dashboard.
    Returns list of dicts sorted by created_at desc.
    """
    ensure_glm_cache(path)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    rows = conn.execute("""
        SELECT g.team, g.poly_price, g.price_assessment, g.group_status,
               g.narrative_risk, g.watch_flags, g.context_text,
               g.confidence, g.created_at, g.hours_to_end
        FROM glm_prematch g
        INNER JOIN (
            SELECT market_id, MAX(created_at) AS latest
            FROM glm_prematch GROUP BY market_id
        ) L ON g.market_id = L.market_id AND g.created_at = L.latest
        ORDER BY g.created_at DESC
        LIMIT ?
    """, (limit,)).fetchall()
    conn.close()
    out = []
    for r in rows:
        flags = json.loads(r["watch_flags"] or "[]")
        out.append({
            "team":            r["team"],
            "price":           r["poly_price"],
            "assessment":      r["price_assessment"],
            "group_status":    r["group_status"],
            "narrative_risk":  r["narrative_risk"],
            "watch_flags":     flags,
            "context":         r["context_text"],
            "confidence":      r["confidence"],
            "created_at":      r["created_at"],
            "hours_to_end":    r["hours_to_end"],
        })
    return out
