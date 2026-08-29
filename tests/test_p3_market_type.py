"""
tests/test_p3_market_type.py — Offline self-test for FIXLOG.md Addendum 4:

  1. derive_market_type() routing (match / futures / wc_legacy)
  2. init_db() in-place backfill of market_type on a pre-existing DB
     (rebuild_from_csv covers fresh DBs; this covers existing ones)
  3. capture_rate_stats() — closing-line capture quantification
  4. close_orphaned_trades() — orphaned PENDING trades get closed from
     Gamma final prices when their market resolved between scans
     (Gamma mocked — no network)

Run: python tests/test_p3_market_type.py
"""

from __future__ import annotations

import json
import os
import sqlite3
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

TMP_DB = "/tmp/test_p3_market_type.db"
if os.path.exists(TMP_DB):
    os.remove(TMP_DB)
os.environ["DB_PATH"] = TMP_DB  # must happen BEFORE config.py is imported

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import scanner        # noqa: E402
import tracker        # noqa: E402


def main() -> None:
    now = datetime.now(timezone.utc)

    # ── 1. derive_market_type routing ──────────────────────────────────────
    assert tracker.derive_market_type(
        "Will Liverpool FC win on 2026-08-29?") == "match"
    assert tracker.derive_market_type(
        "Will Liverpool FC vs. Nottingham Forest FC end in a draw?") == "match"
    assert tracker.derive_market_type(
        "Will Hull City win the 2026-27 English Premier League (EPL) "
        "Championship?") == "futures"
    assert tracker.derive_market_type(
        "Will Spain advance to the knockout stages at the 2026 FIFA World "
        "Cup?") == "wc_legacy"
    print("PASS 1 — derive_market_type routing")

    # ── 2. in-place backfill on a pre-existing DB ──────────────────────────
    conn = sqlite3.connect(TMP_DB)
    # Simulate the REAL pre-pivot state: a `scans` table with the old
    # 15-column schema (no market_type) already holding rows — exactly what
    # a CI checkout rebuilt from last season's CSVs looks like.
    conn.execute("""
        CREATE TABLE scans (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT, market_id TEXT, question TEXT,
            volume_usd REAL, poly_mid REAL, poly_ask_vwap REAL,
            spread_pct REAL, book_true_prob REAL, baseline_source TEXT,
            net_edge REAL, alertable INTEGER, skip_reason TEXT,
            hours_to_end REAL, time_bucket TEXT
        )
    """)
    conn.execute("""INSERT INTO scans (timestamp, market_id, question,
        volume_usd, poly_mid, poly_ask_vwap, spread_pct, book_true_prob,
        baseline_source, net_edge, alertable, skip_reason, hours_to_end,
        time_bucket) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (now.isoformat(), "m1", "Will Arsenal FC win on 2026-08-30?",
         100000.0, 0.6, 0.61, 0.02, 0.0, "no_baseline", 0.0, 0, "", 20.0,
         "T-24h"))
    conn.commit()
    conn.close()

    tracker.init_db(TMP_DB)   # must add market_type + backfill scans

    conn = sqlite3.connect(TMP_DB)
    types = dict(conn.execute(
        "SELECT market_type, COUNT(*) FROM scans GROUP BY 1").fetchall())
    conn.close()
    assert types.get("match") == 1, f"backfill failed: {types}"
    print("PASS 2 — init_db backfills market_type on existing rows")

    # ── 3. capture_rate_stats on synthetic match rows ───────────────────────
    conn = sqlite3.connect(TMP_DB)
    # Kickoff is 5h ago. Match market "m_past_miss" was scanned twice:
    #   6.5h ago (MISS: 90min before kickoff) and 5h10m ago (HIT: inside the
    #   final 60min). hours_to_end is relative to the scan instant, so each
    #   row reconstructs the same kickoff = ts + hours_to_end.
    # Market "m_future": kickoff in 3h — must be excluded from the rate.
    kickoff_epoch = (now - timedelta(hours=5)).timestamp()
    miss_ts = (now - timedelta(hours=6.5)).isoformat()   # h2e = 1.5h
    hit_ts = (now - timedelta(hours=5, minutes=10)).isoformat()  # h2e = 10min
    fut_ts = now.isoformat()
    for mid, ts, h2e in (("m_past_miss", miss_ts, 1.5),
                         ("m_past_miss", hit_ts, 10 / 60),
                         ("m_future", fut_ts, 3.0)):
        conn.execute("""INSERT INTO scans (timestamp, market_id, question,
            market_type, hours_to_end, time_bucket)
            VALUES (?,?,?,?,?,?)""", (ts, mid, "Will X FC win on 2026-08-30?",
                                      "match", h2e, "T-other"))
    conn.commit()
    conn.close()

    stats = tracker.capture_rate_stats(TMP_DB)
    assert stats["match_markets_past"] == 1, stats
    assert stats["captured_final_hour"] == 1, stats
    assert stats["capture_rate"] == 1.0, stats
    print("PASS 3 — capture_rate_stats: hit inside final hour counted, miss "
          "before window not counted, future match excluded")

    # ── 4. close_orphaned_trades with mocked Gamma ──────────────────────────
    conn = sqlite3.connect(TMP_DB)
    conn.execute("""INSERT INTO paper_trades (trade_id, market_id, question,
        direction, entry_price, entry_timestamp, outcome, market_type)
        VALUES ('t_orphan', 'm_resolved', 'Will Y FC win on 2026-08-29?',
                'YES', 0.4, ?, 'PENDING', 'match')""",
        ((now - timedelta(hours=10)).isoformat(),))
    conn.commit()
    conn.close()

    class FakeResp:
        def raise_for_status(self): pass
        def json(self):
            return {"closed": True, "outcomePrices": json.dumps([1.0, 0.0])}

    with mock.patch.object(tracker, "get_open_trades",
                           return_value=[{"trade_id": "t_orphan",
                                          "market_id": "m_resolved"}]), \
         mock.patch("requests.get", return_value=FakeResp()):
        tracker.close_orphaned_trades(current_market_ids={"m_other"},
                                      path=TMP_DB)

    conn = sqlite3.connect(TMP_DB)
    outcome, closing = conn.execute(
        "SELECT outcome, closing_price FROM paper_trades "
        "WHERE trade_id='t_orphan'").fetchone()
    conn.close()
    assert outcome == "BEAT_LINE" and abs(closing - 1.0) < 1e-9, (outcome, closing)
    print("PASS 4 — orphaned trade closed from Gamma final price (capture gap "
          "backfilled)")

    print("\nPASS — market typing, in-place backfill, capture-rate metric, "
          "and orphan reconciliation all behave as designed.")
    os.remove(TMP_DB)


if __name__ == "__main__":
    main()
