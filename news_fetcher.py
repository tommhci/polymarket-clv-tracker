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
import time
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
    "boss and herzegovina": "Bosnia and Herzegovina",
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
