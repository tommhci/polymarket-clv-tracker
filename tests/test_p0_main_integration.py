"""
tests/test_p0_main_integration.py — Offline integration self-test for
FIXLOG.md "P0-1" (catch-up backfill + dedup guard) and "P0-2" (strategy
labels actually landing on real paper_trades rows).

No network calls: mocks scanner's Polymarket/CLOB calls, news_fetcher's
football-data.org lookup, and replaces scheduler.compute_scan_decision with
a fixed decision so this test exercises exactly the trade-opening logic in
main.py, not the scheduler's own window math (covered separately and noted
as a known limitation in FIXLOG.md).

Run: DB_PATH=/tmp/test_p0_main.db python3 tests/test_p0_main_integration.py
(this script sets DB_PATH itself before importing anything — see below)
"""

from __future__ import annotations

import json
import os
import sqlite3
import sys
from pathlib import Path
from unittest import mock

TMP_DB = "/tmp/test_p0_main_integration.db"
if os.path.exists(TMP_DB):
    os.remove(TMP_DB)
os.environ["DB_PATH"] = TMP_DB  # must happen BEFORE config.py is imported

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import main          # noqa: E402  (import after DB_PATH env var is set)
import scanner        # noqa: E402
import news_fetcher   # noqa: E402
import tracker        # noqa: E402
from scheduler import ScanDecision  # noqa: E402


def _fake_market(question: str, mid: float, alertable: bool = False) -> dict:
    bid, ask = mid - 0.01, mid + 0.01
    return {
        "id": f"id_{abs(hash(question)) % 10**8}",
        "question": question,
        "endDateIso": "2026-06-28T00:00:00+00:00",  # the shared (buggy) deadline
        "volume": 100_000.0,
        "clobTokenIds": json.dumps(["yes_tok", "no_tok"]),
        "bestBid": bid,
        "bestAsk": ask,
        "_alertable_test_flag": alertable,  # read by the fake edge fn below
    }


def _row_count(path: str) -> int:
    conn = sqlite3.connect(path)
    n = conn.execute("SELECT COUNT(*) FROM paper_trades").fetchone()[0]
    conn.close()
    return n


def run_one_scan(real_kickoffs: dict, historical_prices: dict[str, float]):
    """
    Run main.execute_scan() once, fully offline:
      - scanner.get_world_cup_markets() -> our fixed market list
      - scanner.get_clob_vwap()         -> trivial passthrough
      - scanner.get_devigged_win_prob() -> no baseline (matches real advance-market behavior)
      - news_fetcher.get_team_last_group_kickoff -> our synthetic per-team kickoffs
      - scheduler.compute_scan_decision -> fixed, no DB-dependent reconstruction
      - calculate_edge() is the REAL function -- alertable is decided for us
        by net_edge/spread the same way production does, so we don't fake it.
    """
    markets = [
        _fake_market("Will Spain advance to the knockout stages at the 2026 FIFA World Cup?", 0.50),
        _fake_market("Will Norway advance to the knockout stages at the 2026 FIFA World Cup?", 0.50),
        _fake_market("Will Panama advance to the knockout stages at the 2026 FIFA World Cup?", 0.50),
    ]

    fixed_decision = ScanDecision(
        mode="full_pre", windows_active=[], priority_teams=[], all_match_teams=[],
        next_window_h=None, reason="test: scheduler bypassed",
        use_news=False, use_glm=False, use_football_data=True,
    )

    def fake_kickoff(team: str):
        return real_kickoffs.get(team)

    def fake_hist_price(market_id: str, before_ts=None, path=tracker.DB_PATH):
        # Look up by question keyword rather than market_id (market_id is a
        # hash, not stable across test setup) -- good enough for this test.
        for team, price in historical_prices.items():
            if team.lower() in market_id_to_question.get(market_id, "").lower():
                return (price, "2026-06-21T23:53:19+00:00")
        return None

    market_id_to_question = {m["id"]: m["question"] for m in markets}

    with mock.patch.object(scanner, "get_world_cup_markets", return_value=markets), \
         mock.patch.object(scanner, "get_clob_vwap", return_value=(0.50, 1.0)), \
         mock.patch.object(scanner, "get_devigged_win_prob", return_value=(0.0, "no_advance_baseline")), \
         mock.patch.object(news_fetcher, "get_team_last_group_kickoff", side_effect=fake_kickoff), \
         mock.patch.object(main, "compute_scan_decision", return_value=fixed_decision), \
         mock.patch.object(main, "get_latest_historical_price", side_effect=fake_hist_price):
        return main.execute_scan(send_summary=False)


def main_test():
    from datetime import datetime, timedelta, timezone
    now = datetime.now(timezone.utc)

    # Spain: genuinely 1h before kickoff -> clean T-1h entry.
    # Norway: kickoff already passed, but we DO have an old scan on file for
    #         them (simulated via fake_hist_price) -> catch-up using that
    #         historical price.
    # Panama: kickoff already passed AND no historical scan on file ->
    #         catch-up falls back to live (already-resolved-looking) price.
    real_kickoffs = {
        "Spain":  now + timedelta(hours=1.0),
        "Norway": now - timedelta(hours=10.0),
        "Panama": now - timedelta(hours=10.0),
    }
    historical_prices = {"Norway": 0.61}   # Panama deliberately has none

    main.init_db(tracker.DB_PATH)

    snaps1 = run_one_scan(real_kickoffs, historical_prices)
    n_after_run1 = _row_count(tracker.DB_PATH)
    print(f"Run 1: {len(snaps1)} snapshots, {n_after_run1} paper_trades rows")

    conn = sqlite3.connect(tracker.DB_PATH)
    conn.row_factory = sqlite3.Row
    rows1 = [dict(r) for r in conn.execute("SELECT * FROM paper_trades").fetchall()]
    conn.close()

    by_team_label = {}
    for r in rows1:
        for team in ("Spain", "Norway", "Panama"):
            if team.lower() in r["question"].lower():
                by_team_label[(team, r["strategy_label"])] = r

    # ── Spain: clean T-1h entry, mid=0.50 -> qualifies for all 3 labels ──
    for label in ("A_all", "B_discount", "C_uncertain"):
        r = by_team_label.get(("Spain", label))
        assert r is not None, f"Spain/{label} missing"
        assert r["entry_is_approx"] == 0, f"Spain/{label} should NOT be approx: {r}"
        assert abs(r["entry_price"] - 0.50) < 1e-6, r["entry_price"]

    # ── Norway: catch-up, historical price (0.61) should be used, flagged approx ──
    for label in ("A_all", "B_discount", "C_uncertain"):
        r = by_team_label.get(("Norway", label))
        assert r is not None, f"Norway/{label} missing"
        assert r["entry_is_approx"] == 1, f"Norway/{label} should be approx: {r}"
        assert abs(r["entry_price"] - 0.61) < 1e-6, (
            f"Norway/{label} should use the HISTORICAL price 0.61, not live: {r['entry_price']}"
        )
        assert "backfilled from scan" in (r["entry_note"] or ""), r["entry_note"]

    # ── Panama: catch-up, NO historical price -> falls back to live (0.50), flagged approx ──
    for label in ("A_all", "B_discount", "C_uncertain"):
        r = by_team_label.get(("Panama", label))
        assert r is not None, f"Panama/{label} missing"
        assert r["entry_is_approx"] == 1, f"Panama/{label} should be approx: {r}"
        assert abs(r["entry_price"] - 0.50) < 1e-6, r["entry_price"]
        assert "no pre-resolution scan on file" in (r["entry_note"] or ""), r["entry_note"]

    expected_rows_run1 = 3 * 3  # 3 teams x 3 strategy labels each
    assert n_after_run1 == expected_rows_run1, (
        f"expected {expected_rows_run1} rows after run 1, got {n_after_run1}"
    )

    # ── Run 2: SAME markets/teams again -> dedup guard must prevent ANY new rows ──
    snaps2 = run_one_scan(real_kickoffs, historical_prices)
    n_after_run2 = _row_count(tracker.DB_PATH)
    print(f"Run 2: {len(snaps2)} snapshots, {n_after_run2} paper_trades rows (dedup check)")
    assert n_after_run2 == n_after_run1, (
        f"DUPLICATE ENTRIES: row count grew from {n_after_run1} to {n_after_run2} "
        f"on a repeat scan of the same markets — dedup guard is not working."
    )

    print("\nPASS — T-1h clean entries, catch-up backfill (with and without "
          "historical price), strategy labelling, and the dedup guard across "
          "repeated scan ticks all behave as designed.")

    os.remove(TMP_DB)


if __name__ == "__main__":
    main_test()
