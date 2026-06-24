"""
tests/test_force_flag.py — Offline self-test for the post-deploy "--force"
fix (see FIXLOG.md "post-deploy: --force flag").

Confirms: when the scheduler says "skip" AND the scans table already has
rows (so the pre-existing bootstrap bypass does NOT apply), execute_scan()
still runs a real scan if force=True, and still correctly returns []
without scanning if force=False. This is exactly the situation that
happened after the P0-1/P0-2 deploy: the scheduler kept saying "skip"
because it was reconstructing windows from stale pre-fix data, and
force=False (the default, what cron uses) correctly did nothing — only
force=True (what workflow_dispatch now passes) unblocks it.

Run: python3 tests/test_force_flag.py
"""

from __future__ import annotations

import json
import os
import sqlite3
import sys
from pathlib import Path
from unittest import mock

TMP_DB = "/tmp/test_force_flag.db"
if os.path.exists(TMP_DB):
    os.remove(TMP_DB)
os.environ["DB_PATH"] = TMP_DB

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import main          # noqa: E402
import scanner        # noqa: E402
import tracker        # noqa: E402
from scheduler import ScanDecision  # noqa: E402


def _seed_nonempty_scans_table():
    """Insert one old row so the scans table is non-empty — this is what
    makes the pre-existing bootstrap bypass NOT apply (it only fires when
    the table has zero rows), which is exactly the real post-deploy
    situation (420 historical rows already present)."""
    conn = sqlite3.connect(TMP_DB)
    conn.execute("""INSERT INTO scans (timestamp, market_id, question, volume_usd,
        poly_mid, poly_ask_vwap, spread_pct, book_true_prob, baseline_source,
        net_edge, alertable, skip_reason, hours_to_end, time_bucket)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        ("2026-06-21T23:53:19", "old_mkt", "Will Spain advance...", 100000,
         0.55, 0.56, 0.02, 0.0, "no_advance_baseline", 0.0, 0, "", 168.09, "T-168h"))
    conn.commit()
    conn.close()


def main_test():
    main.init_db(TMP_DB)
    _seed_nonempty_scans_table()

    skip_decision = ScanDecision(
        mode="skip", windows_active=[], priority_teams=[], all_match_teams=[],
        next_window_h=None, reason="test: stale-data skip",
        use_news=False, use_glm=False, use_football_data=False,
    )

    markets = [{
        "id": "mkt_new", "question": "Will Norway advance to the knockout stages at the 2026 FIFA World Cup?",
        "endDateIso": "2026-06-28T00:00:00+00:00", "volume": 100_000.0,
        "clobTokenIds": json.dumps(["yes_tok", "no_tok"]),
        "bestBid": 0.49, "bestAsk": 0.51,
    }]

    with mock.patch.object(scanner, "get_world_cup_markets", return_value=markets), \
         mock.patch.object(scanner, "get_clob_vwap", return_value=(0.50, 1.0)), \
         mock.patch.object(scanner, "get_devigged_win_prob", return_value=(0.0, "no_advance_baseline")), \
         mock.patch.object(main, "compute_scan_decision", return_value=skip_decision):

        # ── force=False (what the regular 30-min cron uses) — must NOT scan ──
        result_no_force = main.execute_scan(send_summary=False, force=False)
        n_scans_after_no_force = sqlite3.connect(TMP_DB).execute(
            "SELECT COUNT(*) FROM scans").fetchone()[0]

        # ── force=True (what workflow_dispatch now passes) — MUST scan ──
        result_force = main.execute_scan(send_summary=False, force=True)
        n_scans_after_force = sqlite3.connect(TMP_DB).execute(
            "SELECT COUNT(*) FROM scans").fetchone()[0]

    print(f"force=False: execute_scan returned {len(result_no_force)} snapshots; "
          f"scans table rows: {n_scans_after_no_force}")
    print(f"force=True:  execute_scan returned {len(result_force)} snapshots; "
          f"scans table rows: {n_scans_after_force}")

    assert result_no_force == [], "force=False must NOT scan when scheduler says skip"
    assert n_scans_after_no_force == 1, "force=False must not write any new scan rows (still just the seeded row)"

    assert len(result_force) == 1, "force=True must run a real scan despite 'skip'"
    assert n_scans_after_force == 2, "force=True must write the new scan row (seeded row + 1 new)"

    print("\nPASS — force=False respects the scheduler's skip decision (matches "
          "regular cron behavior); force=True correctly bypasses it (matches "
          "the new workflow_dispatch behavior).")

    os.remove(TMP_DB)


if __name__ == "__main__":
    main_test()
