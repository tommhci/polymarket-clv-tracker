"""
news_fetcher.py — Real-time data grounding for GLM pre-match analysis.

Architecture (RAG pattern — Retrieval-Augmented Generation):
  1. RETRIEVE: fetch structured data + news from external sources
  2. AUGMENT:  inject retrieved context into the GLM prompt
  3. GENERATE: GLM reasons over live data, not just training memory

Two data sources, chosen for reliability + free tier availability:

  football-data.org   → structured match results + standings (v4 API)
                        Free forever for covered competitions.
                        Rate limit: 10 req/min on free tier.
                        Docs: docs.football-data.org/general/v4/

  Tavily              → LLM-optimised web search → structured news snippets
                        Designed specifically for RAG grounding.
                        Free tier: 1000 API calls/month.

Why this beats asking GLM to "browse" on its own:
  - You control exactly what data is retrieved
  - You can verify/log what GLM is reasoning from
  - No dependence on whether GLM's built-in search is available
  - Lower latency (one fetch, not multiple rounds of tool calls)
"""

from __future__ import annotations

import json
import logging
import re
import time
import unicodedata
from datetime import datetime, timezone
from typing import Optional

import requests

from config import FOOTBALL_DATA_API_KEY, TAVILY_API_KEY

log = logging.getLogger(__name__)

# football-data.org WC 2026 competition code
# The WC 2026 competition ID — verify at https://api.football-data.org/v4/competitions/
_WC_COMPETITION_CODE = "WC"
_FD_BASE = "https://api.football-data.org/v4"

# Team name normalisation (football-data.org uses full FIFA names)
_TEAM_ALIASES = {
    "usa":          "USA",
    "south korea":  "Korea Republic",
    "ivory coast":  "Côte d'Ivoire",
    "cote d'ivoire": "Côte d'Ivoire",
    "czechia":      "Czech Republic",
    "turkiye":      "Türkiye",
    "turkey":       "Türkiye",
    "congo dr":     "DR Congo",
    # FIXLOG P0-1: fixed typo ("boss" → "bosnia") — this alias was silently
    # dead code before (key never matched "Bosnia and Herzegovina" lookups).
    "bosnia and herzegovina": "Bosnia and Herzegovina",
}


def _fd_headers() -> dict:
    return {"X-Auth-Token": FOOTBALL_DATA_API_KEY} if FOOTBALL_DATA_API_KEY else {}


def _fd_get(path: str) -> Optional[dict]:
    """Single GET to football-data.org v4 API. Returns None on any error."""
    if not FOOTBALL_DATA_API_KEY:
        return None
    try:
        resp = requests.get(
            f"{_FD_BASE}{path}",
            headers=_fd_headers(),
            timeout=8,
        )
        resp.raise_for_status()
        return resp.json()
    except requests.RequestException as e:
        log.warning("football-data.org error [%s]: %s", path, e)
        return None


def check_football_data_health() -> tuple[bool, str]:
    """
    P1 health check — confirms FOOTBALL_DATA_API_KEY is present AND actually
    works (not just "the env var exists"). Makes one lightweight call
    (competition metadata, not the full match list) and checks for a real
    200 response.

    Returns (ok, message). Designed to be called from a dedicated CI step
    (see .github/workflows/scan.yml) so failures are visible in the Actions
    log without silently degrading data quality.
    """
    if not FOOTBALL_DATA_API_KEY:
        return False, "FOOTBALL_DATA_API_KEY is not set (missing secret)."
    try:
        resp = requests.get(
            f"{_FD_BASE}/competitions/{_WC_COMPETITION_CODE}",
            headers=_fd_headers(),
            timeout=8,
        )
    except requests.RequestException as e:
        return False, f"football-data.org request failed: {e}"

    if resp.status_code == 200:
        return True, "football-data.org OK (200) — key is valid and working."
    if resp.status_code in (401, 403):
        return False, (
            f"football-data.org rejected the key (HTTP {resp.status_code}) — "
            f"FOOTBALL_DATA_API_KEY is set but invalid/expired."
        )
    if resp.status_code == 429:
        return False, "football-data.org rate-limited us (HTTP 429) — key is valid, just throttled."
    return False, f"football-data.org returned unexpected HTTP {resp.status_code}: {resp.text[:200]}"


# ── Team name normalisation helpers ──────────────────────────────────────────

def _normalize_team_key(name: str) -> str:
    """
    Lowercase, strip diacritics/punctuation, collapse whitespace.
    Used to match our internal team names (config.TEAM_NAMES / extract_team())
    against whatever spelling football-data.org happens to use
    (e.g. "Côte d'Ivoire", "Türkiye", "Korea Republic").
    """
    if not name:
        return ""
    n = unicodedata.normalize("NFKD", name)
    n = "".join(c for c in n if not unicodedata.combining(c))
    n = n.lower().strip()
    n = re.sub(r"[^a-z0-9 ]", " ", n)
    n = re.sub(r"\s+", " ", n).strip()
    return n


# ── Group-stage fixture list (single call, in-process cache) ────────────────
#
# Fetched ONCE per process (each cron invocation is a fresh process anyway,
# so there is no point persisting this to disk — see FIXLOG.md "P0-1").
# Critically: this is ONE API call for the whole competition, reused for
# every team, instead of one call per team (free tier is 10 req/min and
# there are 46+ advancement markets per scan — see FIXLOG.md).

_GROUP_STAGE_MATCHES_CACHE: Optional[list[dict]] = None
_TEAM_LAST_KICKOFF_CACHE: Optional[dict[str, datetime]] = None


def get_wc_group_fixtures(force_refresh: bool = False) -> Optional[list[dict]]:
    """
    Fetch the full WC 2026 group-stage fixture list (scheduled + finished)
    in a single API call. Cached in-process for the lifetime of this run.
    """
    global _GROUP_STAGE_MATCHES_CACHE
    if _GROUP_STAGE_MATCHES_CACHE is not None and not force_refresh:
        return _GROUP_STAGE_MATCHES_CACHE

    data = _fd_get(f"/competitions/{_WC_COMPETITION_CODE}/matches?stage=GROUP_STAGE")
    if not data:
        return None

    matches = data.get("matches", [])
    _GROUP_STAGE_MATCHES_CACHE = matches
    log.info("Fetched %d WC2026 group-stage fixtures from football-data.org", len(matches))
    return matches


def get_team_last_group_kickoff_map(force_refresh: bool = False) -> dict[str, datetime]:
    """
    Build {normalized_team_key: last_group_stage_match_kickoff_utc}.

    "Last" = the team's latest-dated group-stage fixture — i.e. their 3rd
    (final) group match, whose result is what actually determines whether
    they advance. This is the per-team replacement for Polymarket's shared
    endDateIso (see FIXLOG.md "P0-1" for why that was the bug).
    """
    global _TEAM_LAST_KICKOFF_CACHE
    if _TEAM_LAST_KICKOFF_CACHE is not None and not force_refresh:
        return _TEAM_LAST_KICKOFF_CACHE

    matches = get_wc_group_fixtures(force_refresh=force_refresh)
    if not matches:
        _TEAM_LAST_KICKOFF_CACHE = {}
        return _TEAM_LAST_KICKOFF_CACHE

    last_kickoff: dict[str, datetime] = {}
    for m in matches:
        utc_date = m.get("utcDate")
        if not utc_date:
            continue
        try:
            dt = datetime.fromisoformat(utc_date.replace("Z", "+00:00"))
        except (ValueError, TypeError):
            continue
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)

        for side in ("homeTeam", "awayTeam"):
            team_obj = m.get(side) or {}
            for name_field in ("name", "shortName"):
                raw_name = team_obj.get(name_field)
                if not raw_name:
                    continue
                key = _normalize_team_key(raw_name)
                if not key:
                    continue
                if key not in last_kickoff or dt > last_kickoff[key]:
                    last_kickoff[key] = dt

    _TEAM_LAST_KICKOFF_CACHE = last_kickoff
    return last_kickoff


def get_team_last_group_kickoff(team: str) -> Optional[datetime]:
    """
    Look up `team`'s (our internal naming, e.g. config.TEAM_NAMES spelling)
    last group-stage match kickoff time (UTC), or None if no fixture data
    is available / no match found (caller should fall back gracefully).
    """
    kickoff_map = get_team_last_group_kickoff_map()
    if not kickoff_map:
        return None

    candidates = [team]
    alias = _TEAM_ALIASES.get(team.lower())
    if alias:
        candidates.append(alias)

    for cand in candidates:
        key = _normalize_team_key(cand)
        if key in kickoff_map:
            return kickoff_map[key]

    # Fallback: fuzzy containment match for naming variants not covered by
    # the alias table (football-data.org's exact spelling can't be verified
    # without live network access — see FIXLOG.md known limitations).
    team_key = _normalize_team_key(team)
    if team_key:
        for map_key, dt in kickoff_map.items():
            if team_key in map_key or map_key in team_key:
                return dt

    return None


# ── Live match context ─────────────────────────────────────────────────────────

def get_wc_standings() -> Optional[list[dict]]:
    """
    Fetch current WC 2026 group standings.
    Returns list of group dicts or None if unavailable.
    """
    data = _fd_get(f"/competitions/{_WC_COMPETITION_CODE}/standings")
    if not data:
        return None
    return data.get("standings", [])


def get_team_standing(team: str) -> Optional[dict]:
    """
    Find a team's current standing in the WC 2026 group stage.
    Returns dict with keys: position, playedGames, won, draw, lost, points, goalDifference
    or None if not found.
    """
    standings = get_wc_standings()
    if not standings:
        return None

    team_lower = team.lower()
    normalised = _TEAM_ALIASES.get(team_lower, team)

    for group in standings:
        for entry in group.get("table", []):
            t = entry.get("team", {})
            t_name = t.get("name", "")
            t_short = t.get("shortName", "")
            if (team_lower in t_name.lower() or
                    team_lower in t_short.lower() or
                    normalised.lower() in t_name.lower()):
                return {
                    "group":         group.get("group", ""),
                    "position":      entry.get("position"),
                    "played":        entry.get("playedGames"),
                    "won":           entry.get("won"),
                    "draw":          entry.get("draw"),
                    "lost":          entry.get("lost"),
                    "points":        entry.get("points"),
                    "goal_diff":     entry.get("goalDifference"),
                    "goals_for":     entry.get("goalsFor"),
                    "goals_against": entry.get("goalsAgainst"),
                }
    return None


def get_recent_wc_matches(team: str, n: int = 3) -> list[dict]:
    """
    Fetch the team's most recent WC 2026 match results.
    Returns up to n dicts: {date, home, away, score_home, score_away, status}
    """
    data = _fd_get(f"/competitions/{_WC_COMPETITION_CODE}/matches?status=FINISHED")
    if not data:
        return []

    team_lower = team.lower()
    matches = []
    for m in data.get("matches", []):
        home = m.get("homeTeam", {}).get("name", "")
        away = m.get("awayTeam", {}).get("name", "")
        if team_lower in home.lower() or team_lower in away.lower():
            score = m.get("score", {}).get("fullTime", {})
            matches.append({
                "date":        m.get("utcDate", "")[:10],
                "home":        home,
                "away":        away,
                "score_home":  score.get("home"),
                "score_away":  score.get("away"),
            })

    # Sort by date desc, return most recent n
    matches.sort(key=lambda x: x["date"], reverse=True)
    return matches[:n]


# ── News search ───────────────────────────────────────────────────────────────

def search_news(team: str, max_results: int = 5) -> dict:
    """
    Search for the latest news about this team using Tavily.

    Tavily is designed for LLM grounding: it returns clean structured results
    with an AI-generated answer (not just raw links).
    Source: Tavily docs (2025); free tier 1000 calls/month.

    Returns dict with keys:
      - answer:   AI-generated 1-paragraph summary of latest news
      - articles: list of {title, url, snippet, date}
      - error:    present if unavailable
    """
    if not TAVILY_API_KEY:
        return {"error": "TAVILY_API_KEY not configured", "articles": [], "answer": ""}

    try:
        from tavily import TavilyClient
        client = TavilyClient(api_key=TAVILY_API_KEY)

        result = client.search(
            query=f"{team} 2026 World Cup latest news injury lineup squad",
            search_depth="basic",
            max_results=max_results,
            include_answer=True,
            days=7,                   # only last 7 days
        )
        articles = [
            {
                "title":   r.get("title", ""),
                "url":     r.get("url", ""),
                "snippet": r.get("content", "")[:300],
                "score":   round(r.get("score", 0), 3),
            }
            for r in result.get("results", [])
        ]
        return {
            "answer":   result.get("answer", ""),
            "articles": articles,
        }
    except Exception as e:
        log.warning("Tavily search error for %s: %s", team, e)
        return {"error": str(e), "articles": [], "answer": ""}


# ── Combined context bundle ────────────────────────────────────────────────────

def fetch_live_context(team: str) -> dict:
    """
    Fetch all available live context for a team and return a structured bundle
    ready to be injected into a GLM prompt.

    Tries all sources gracefully — partial data is better than no data.
    """
    now = datetime.now(timezone.utc).isoformat()

    standing = get_team_standing(team)
    matches  = get_recent_wc_matches(team)
    news     = search_news(team)

    # ── Build human-readable standing summary ──────────────────────────────
    if standing:
        st = standing
        standing_text = (
            f"{team} is currently {_ordinal(st['position'])} in "
            f"{st['group']} with {st['points']} points "
            f"(W{st['won']} D{st['draw']} L{st['lost']}, "
            f"GD {st['goal_diff']:+d}) from {st['played']} match(es)."
        )
    else:
        standing_text = f"Current standings for {team} unavailable (API key or data issue)."

    # ── Build match history summary ────────────────────────────────────────
    if matches:
        match_lines = []
        for m in matches:
            line = f"  {m['date']}: {m['home']} {m['score_home']}–{m['score_away']} {m['away']}"
            match_lines.append(line)
        match_text = "Recent results:\n" + "\n".join(match_lines)
    else:
        match_text = "No completed WC 2026 matches found for this team yet."

    # ── Assemble final context dict ────────────────────────────────────────
    return {
        "fetched_at":    now,
        "standing":      standing,
        "standing_text": standing_text,
        "matches":       matches,
        "match_text":    match_text,
        "news_answer":   news.get("answer", ""),
        "news_articles": news.get("articles", []),
        "sources_used":  {
            "football_data": standing is not None,
            "tavily":        bool(news.get("answer")),
        },
    }


def _ordinal(n: Optional[int]) -> str:
    if n is None:
        return "unknown position"
    s = {1: "1st", 2: "2nd", 3: "3rd"}
    return s.get(n, f"{n}th")


# ── Quick CLI test ─────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys
    team = sys.argv[1] if len(sys.argv) > 1 else "Scotland"
    print(f"Fetching live context for: {team}")
    ctx = fetch_live_context(team)
    print(f"\nStanding: {ctx['standing_text']}")
    print(f"Matches:  {ctx['match_text']}")
    print(f"News:     {ctx['news_answer'][:300] if ctx['news_answer'] else 'unavailable'}")
    print(f"Articles: {len(ctx['news_articles'])} found")
    print(f"Sources:  football_data={ctx['sources_used']['football_data']} tavily={ctx['sources_used']['tavily']}")
