"""
scheduler.py — Event-driven scan priority engine.

Problem with flat 30-min cron:
  - Wastes GitHub Actions minutes during idle nights (no matches)
  - Misses the exact high-signal windows (T-1h, halftime, T+15min)
  - Squanders Tavily/GLM quota on low-value moments
  - Can't distinguish "Scotland plays in 23h" from "nothing until next week"

Solution — Four-tier scan priority based on match proximity:

  ┌──────────────────────────────────────────────────────┐
  │  FULL_LIVE  → match is live RIGHT NOW (within ±100min) │
  │  FULL_PRE   → critical pre-match windows              │
  │  LIGHT      → match today, no critical window         │
  │  SKIP       → no match in next 48h                    │
  └──────────────────────────────────────────────────────┘

Evidence base for window design:
  - arXiv 2505.21275 (2025): biggest betting market movements cluster around
    the first goal and halftime break — these are the mispriceable moments
  - arXiv 2211.06052: momentum bias inflates prices ~40% on "hot" teams
    → over-reaction is highest in first 15min and after halftime restart
  - SSRN 1540313 (Hartzmark & Solomon): prices too low when team is ahead,
    too high when behind → disposition effect peaks mid-match
  - Page & Clemen SSRN 2013: T-168h and T-24h show largest miscalibration →
    these are the structural CLV measurement points

Time windows (all relative to estimated kickoff = endDateIso − 2h):

  T-168h  ±6h   → 7-day pre-match, structural bias zone (CLV measurement)
  T-24h   ±3h   → Squad confirmation + news peak (news fetch + GLM)
  T-6h    ±2h   → Live betting opens, sharp money arrives (GLM re-analysis)
  T-1h    ±1h   → Final lineups, highest narrative bias (CLV entry + news)
  LIVE    0−90min after kickoff  → Active play, momentum/disposition spikes
  HALFTIME ~40−65min after kickoff → Score known, market recalibrates
  POST    90−180min → Match ending, auto-close verification

All times are derived from the advancement markets' endDateIso field
(already in our DB) — no extra API calls required for scheduling.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from typing import Optional

from config import DB_PATH


# ── Window definitions ─────────────────────────────────────────────────────────
# (low_h, high_h) relative to estimated KICKOFF (endDateIso - RESOLUTION_LAG_H)

RESOLUTION_LAG_H = 2.0      # endDateIso is typically ~2h after kickoff

WINDOWS = {
    # Critical measurement points for CLV
    "T-168h":   (162.0,  174.0),   # 7 days ± 6h
    "T-24h":    ( 21.0,   27.0),   # 24h ± 3h
    "T-6h":     (  4.0,    8.0),   # 6h ± 2h
    "T-1h":     (  0.5,    2.5),   # 1h ± 1h

    # Live-play windows (evidence-based — arXiv 2505.21275, SSRN 1540313)
    "T-kickoff": ( -0.5,   0.5),   # exact kickoff ±30min
    "T-half":   ( -1.5,  -0.5),    # ~halftime (40–65min after kickoff)
    "T-ft":     ( -3.0,  -1.5),    # ~full time (75–90+min)
    "T-post":   ( -5.0,  -3.0),    # settling / auto-close verification
}

# Scan mode assignment per window
#  full_news  → run Polymarket + football-data + Tavily + GLM
#  full_live  → run Polymarket + football-data only (too volatile for GLM queue)
#  full_pre   → run Polymarket + football-data + GLM (no Tavily)
#  light      → Polymarket prices only
#  skip       → exit immediately

WINDOW_MODE = {
    "T-168h":    "full_pre",
    "T-24h":     "full_news",    # news + GLM
    "T-6h":      "full_pre",
    "T-1h":      "full_news",    # news + GLM + CLV entry
    "T-kickoff": "full_live",    # live data, fast
    "T-half":    "full_live",    # halftime recalibration
    "T-ft":      "full_live",
    "T-post":    "light",        # just check resolution prices
}


@dataclass
class ScanDecision:
    mode:              str            # "full_news" | "full_live" | "full_pre" | "light" | "skip"
    windows_active:    list[str]      # which time windows triggered
    priority_teams:    list[str]      # teams with matches in active windows
    all_match_teams:   list[str]      # all teams playing today
    next_window_h:     Optional[float]  # hours until next active window
    reason:            str            # human-readable explanation
    use_news:          bool = False   # whether to call Tavily + GLM
    use_glm:           bool = False   # whether to call GLM at all
    use_football_data: bool = False   # whether to call football-data.org


def compute_scan_decision(path: str = DB_PATH) -> ScanDecision:
    """
    Determine what to do on this scan run by reading upcoming match windows
    from the advancement markets already stored in the DB.

    No external API calls — uses only endDateIso from the scans table.
    Returns a ScanDecision the main loop uses to decide what code paths to run.
    """
    now    = datetime.now(timezone.utc)
    today  = now.date()

    # ── Pull upcoming markets from DB using hours_to_end + timestamp ─────────
    # The scans table stores hours_to_end at scan time, not end_date directly.
    # We reconstruct estimated end_dt = scan_timestamp + hours_to_end.
    # Use the most recent snapshot per market.
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    markets = conn.execute("""
        SELECT s.market_id, s.question, s.hours_to_end, s.timestamp, s.time_bucket
        FROM scans s
        INNER JOIN (
            SELECT market_id, MAX(timestamp) AS latest
            FROM scans GROUP BY market_id
        ) L ON s.market_id = L.market_id AND s.timestamp = L.latest
        WHERE (lower(s.question) LIKE '%advance%'
            OR lower(s.question) LIKE '%qualify%'
            OR lower(s.question) LIKE '%knockout%')
          AND s.hours_to_end IS NOT NULL
          AND s.hours_to_end > -48
    """).fetchall()
    conn.close()

    if not markets:
        return ScanDecision(
            mode="skip", windows_active=[], priority_teams=[],
            all_match_teams=[], next_window_h=None,
            reason="No advancement markets in DB yet — run initial scan first.",
        )

    # ── For each market, compute hours from estimated kickoff ─────────────────
    active_windows:    dict[str, list[str]] = {k: [] for k in WINDOWS}
    today_teams:       list[str] = []
    next_kicks:        list[float] = []      # positive = hours until kickoff

    from scanner import extract_team

    for m in markets:
        h2e    = m["hours_to_end"]
        ts_str = m["timestamp"]
        if h2e is None:
            continue
        try:
            scan_ts = datetime.fromisoformat(str(ts_str).replace("Z", "+00:00"))
            if scan_ts.tzinfo is None:
                scan_ts = scan_ts.replace(tzinfo=timezone.utc)
        except (ValueError, TypeError):
            continue

        # Reconstruct estimated end_dt and kickoff from scan data
        estimated_end_dt = scan_ts + timedelta(hours=float(h2e))
        kickoff_est      = estimated_end_dt - timedelta(hours=RESOLUTION_LAG_H)
        hours_to_kick    = (kickoff_est - now).total_seconds() / 3600

        # Track kickoff times for "next window" calculation
        next_kicks.append(hours_to_kick)

        # Is kickoff today (within 0..24h) or recently past (within -4..0h)?
        if -4 <= hours_to_kick <= 24:
            team = extract_team(m["question"]) or m["question"][:20]
            if team not in today_teams:
                today_teams.append(team)

        # Check which priority windows are active right now
        for win_name, (lo, hi) in WINDOWS.items():
            if lo <= hours_to_kick <= hi:
                team = extract_team(m["question"]) or m["question"][:20]
                active_windows[win_name].append(team)

    # ── Determine highest-priority mode ──────────────────────────────────────
    # Process windows in priority order (most time-sensitive first)
    priority_order = ["T-kickoff", "T-half", "T-1h", "T-ft", "T-6h",
                      "T-24h", "T-168h", "T-post"]

    triggered_windows:  list[str]  = []
    priority_teams:     list[str]  = []
    chosen_mode:        str        = "skip"

    for win in priority_order:
        teams = active_windows.get(win, [])
        if teams:
            triggered_windows.append(win)
            for t in teams:
                if t not in priority_teams:
                    priority_teams.append(t)
            mode_candidate = WINDOW_MODE[win]
            # Upgrade mode if new window is more important
            if chosen_mode == "skip":
                chosen_mode = mode_candidate
            elif mode_candidate == "full_news" and chosen_mode not in ("full_news", "full_live"):
                chosen_mode = "full_news"
            elif mode_candidate == "full_live" and chosen_mode == "full_pre":
                chosen_mode = "full_live"

    # Fallback: match today but no active window
    if chosen_mode == "skip" and today_teams:
        chosen_mode = "light"
        reason = (f"Match today for {', '.join(today_teams[:3])} "
                  f"but no priority window active — light price check.")
    elif chosen_mode == "skip":
        # Compute time until next kickoff
        future_kicks = [h for h in next_kicks if h > 0]
        if future_kicks:
            next_h = min(future_kicks)
            # Find the nearest priority window for next kickoff
            next_win_h = None
            for win_name, (lo, _) in WINDOWS.items():
                candidate = next_h - lo
                if candidate > 0 and (next_win_h is None or candidate < next_win_h):
                    next_win_h = candidate
            reason = (f"No matches in active windows. "
                      f"Next kickoff in ~{next_h:.1f}h, "
                      f"next scan trigger in ~{next_win_h:.1f}h.")
        else:
            next_win_h = None
            reason = "No upcoming matches found — all markets may have resolved."
        return ScanDecision(
            mode="skip", windows_active=[], priority_teams=[],
            all_match_teams=today_teams, next_window_h=next_win_h,
            reason=reason,
        )
    else:
        wins_str  = ", ".join(triggered_windows)
        teams_str = ", ".join(priority_teams[:4])
        reason = f"Active windows [{wins_str}] for {teams_str} → mode={chosen_mode}"

    # ── Derive API flags from mode ─────────────────────────────────────────────
    use_news  = chosen_mode in ("full_news",)
    use_glm   = chosen_mode in ("full_news", "full_pre")
    use_fd    = chosen_mode in ("full_news", "full_pre", "full_live")

    return ScanDecision(
        mode=chosen_mode,
        windows_active=triggered_windows,
        priority_teams=priority_teams,
        all_match_teams=today_teams,
        next_window_h=None,
        reason=reason,
        use_news=use_news,
        use_glm=use_glm,
        use_football_data=use_fd,
    )


def schedule_summary(decision: ScanDecision) -> str:
    """Return a one-line log-friendly summary of the scheduling decision."""
    return (
        f"[SCHEDULER] mode={decision.mode} "
        f"windows={decision.windows_active} "
        f"teams={decision.priority_teams[:3]} "
        f"— {decision.reason}"
    )
