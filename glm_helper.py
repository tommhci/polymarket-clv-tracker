"""
glm_helper.py — GLM (智谱AI) powered market analysis.

API: OpenAI-compatible endpoint at https://open.bigmodel.cn/api/paas/v4
SDK: openai Python package with custom base_url (no separate zhipuai install needed)
Source: apidog.com/blog/how-to-use-glm-5-1-api (May 2026)

Two jobs:
  1. extract_market_info()  — parse complex question text the regex can't handle
  2. check_resolution_risk() — flag markets likely to trigger UMA disputes

Both results are cached in SQLite to avoid re-calling GLM for the same market.
Entire module degrades gracefully to None if GLM_API_KEY is not set.
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
