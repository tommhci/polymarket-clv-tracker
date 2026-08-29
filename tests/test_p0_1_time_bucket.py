"""
tests/test_p0_1_time_bucket.py — Offline self-test for FIXLOG.md "P0-1".

Originally written for the World Cup advancement markets, where each team's
kickoff had to be looked up from football-data.org. Since the EPL pivot
(2026-08) scanner anchors each match market's time_bucket to Polymarket's
own gameStartTime field (per-market kickoff, no external lookup), falling
back to endDateIso when it is missing. This test now protects THAT mechanism:
markets sharing one endDateIso must still get distinct hours_to_end when
gameStartTime differs, and the no-gameStartTime fallback must degrade
gracefully — without making any real network calls.

Run: python3 tests/test_p0_1_time_bucket.py
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import scanner
import news_fetcher


def _fake_market(question: str, end_date_shared: str,
                 game_start: str | None = None) -> dict:
    """Build a raw Gamma-API-shaped market dict (matches parse_market_meta)."""
    m = {
        "id": f"id_{abs(hash(question)) % 10**8}",
        "question": question,
        "endDateIso": end_date_shared,
        "volume": 100_000.0,
        "clobTokenIds": json.dumps(["yes_tok", "no_tok"]),
        "bestBid": 0.55,
        "bestAsk": 0.57,
    }
    if game_start is not None:
        m["gameStartTime"] = game_start
    return m


def main() -> None:
    now = datetime.now(timezone.utc)

    # Every market shares the SAME endDateIso — the original P0-1 bug shape.
    shared_end_date = (now + timedelta(hours=168.09)).isoformat()

    markets = [
        _fake_market("Will Spain advance to the knockout stages at the 2026 FIFA World Cup?", shared_end_date,
                     game_start=(now + timedelta(hours=1.0)).isoformat()),    # → T-1h
        _fake_market("Will USA advance to the knockout stages at the 2026 FIFA World Cup?", shared_end_date,
                     game_start=(now + timedelta(hours=25.0)).isoformat()),   # → T-24h
        _fake_market("Will Brazil advance to the knockout stages at the 2026 FIFA World Cup?", shared_end_date,
                     game_start=(now + timedelta(hours=400.0)).isoformat()),  # → T-other
        # Market with NO gameStartTime — must fall back gracefully to the
        # shared endDateIso, not raise.
        _fake_market("Will Wales advance to the knockout stages at the 2026 FIFA World Cup?", shared_end_date),
    ]

    with mock.patch.object(scanner, "get_scan_universe", return_value=markets), \
         mock.patch.object(scanner, "get_clob_vwap", return_value=(0.57, 1.0)), \
         mock.patch.object(scanner, "get_devigged_win_prob", return_value=(0.0, "no_baseline")):

        snapshots = scanner.run_scan()

    by_team = {}
    for s in snapshots:
        for t in ("Spain", "USA", "Brazil", "Wales"):
            if t.lower() in s.question.lower():
                by_team[t] = s

    print("team      hours_to_end   time_bucket")
    for t, s in by_team.items():
        print(f"{t:9s} {s.hours_to_end:>10.2f}   {s.time_bucket}")

    # ── Assertions ────────────────────────────────────────────────────────
    assert len(by_team) == 4, f"expected 4 teams, got {list(by_team)}"

    hours = {t: s.hours_to_end for t, s in by_team.items()}

    # Core regression check: these must NOT all be the same value anymore
    # (that was exactly the bug — all 46 teams sharing 168.09).
    assert len({round(h, 1) for h in hours.values()}) > 1, (
        f"BUG STILL PRESENT: all teams got the same hours_to_end: {hours}"
    )

    assert by_team["Spain"].time_bucket == "T-1h", by_team["Spain"].time_bucket
    assert by_team["USA"].time_bucket == "T-24h", by_team["USA"].time_bucket
    assert by_team["Brazil"].time_bucket == "T-other", by_team["Brazil"].time_bucket

    # Wales has no fixture match → falls back to the shared (old) end_date →
    # hours_to_end should be ~168.09, same as the original bug, for THIS team
    # only. This proves the fallback degrades gracefully instead of crashing.
    assert abs(by_team["Wales"].hours_to_end - 168.09) < 0.5, by_team["Wales"].hours_to_end

    print("\nPASS — each team now gets its own hours_to_end/time_bucket; "
          "fallback for no-fixture-match teams degrades gracefully.")


if __name__ == "__main__":
    main()
