"""
tests/test_p4_quota.py — Offline self-test for FIXLOG.md Addendum 6:

  1. Odds API throttle: _fetch_odds returns [] without any HTTP call when the
     git-tracked state file shows a fetch inside ODDS_MIN_INTERVAL_H.
  2. State roundtrip: successful fetch stamps docs/odds_state.json.
  3. run_scan(use_baseline=False) (light/maintenance mode) skips the baseline
     entirely — no Odds API request is attempted.
  4. Sweep mode: execute_scan under POLYMARKET_SWEEP=1 degrades scheduler
     "skip" to a light scan instead of exiting.

All network is mocked. Run: python tests/test_p4_quota.py
"""

from __future__ import annotations

import json
import os
import sqlite3
import sys
import tempfile
import time
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import config         # noqa: E402
import scanner        # noqa: E402
import main           # noqa: E402
from scheduler import ScanDecision  # noqa: E402


class _Boom(Exception):
    pass


def _deny_network(*a, **kw):
    raise _Boom("network call attempted where none was allowed")


def run() -> None:
    tmp = tempfile.mkdtemp()
    docs = os.path.join(tmp, "docs")
    os.makedirs(docs, exist_ok=True)
    old_state = scanner.ODDS_STATE_PATH
    scanner.ODDS_STATE_PATH = os.path.join(docs, "odds_state.json")

    try:
        # ── 1. throttle: recent fetch ⇒ [] with zero HTTP ──────────────────
        now = time.time()
        with open(scanner.ODDS_STATE_PATH, "w") as f:
            json.dump({config.ODDS_SPORT_KEY: now - 60}, f)  # 1 min ago
        with mock.patch.object(scanner.requests, "get", _deny_network):
            events = scanner._fetch_odds(config.ODDS_SPORT_KEY, "h2h")
        assert events == [], events
        print("PASS 1 — throttled fetch returns [] with no HTTP call")

        # ── 2. roundtrip: successful fetch stamps the state file ───────────
        class FakeResp:
            headers = {"x-requests-remaining": "499"}
            def raise_for_status(self): pass
            def json(self): return []

        def fake_get(*a, **kw):
            return FakeResp()

        # age the state past the throttle window first, or the fetch is denied
        with open(scanner.ODDS_STATE_PATH, "w") as f:
            json.dump({config.ODDS_SPORT_KEY: now - 7 * 3600}, f)
        scanner._odds_cache.clear()
        with mock.patch.object(scanner.requests, "get", fake_get):
            scanner._fetch_odds(config.ODDS_SPORT_KEY, "h2h")
        stamped = json.load(open(scanner.ODDS_STATE_PATH))
        assert stamped[config.ODDS_SPORT_KEY] > now - 30, stamped
        print("PASS 2 — successful fetch stamps the state file")

        # ── 3. light mode never attempts the baseline ──────────────────────
        market = {
            "id": "m1", "question": "Will Liverpool FC win on 2026-08-30?",
            "endDateIso": "2026-08-30", "volume": 100_000.0,
            "clobTokenIds": json.dumps(["y", "n"]),
            "bestBid": 0.6, "bestAsk": 0.62,
            "gameStartTime": "2026-08-30 11:30:00+00",
            "_match_home": "Liverpool FC", "_match_away": "Everton FC",
        }
        with mock.patch.object(scanner, "get_scan_universe", return_value=[market]), \
             mock.patch.object(scanner, "get_clob_vwap", return_value=(0.61, 1.0)), \
             mock.patch.object(scanner.requests, "get", _deny_network):
            snaps = scanner.run_scan(use_baseline=False)
        assert len(snaps) == 1
        assert snaps[0].baseline_source == "baseline_skipped_light_mode", snaps[0].baseline_source
        assert snaps[0].market_type == "match"
        print("PASS 3 — use_baseline=False skips Odds API entirely")

        # ── 4. sweep mode: skip degrades to light scan ──────────────────────
        tmp_db = os.path.join(tmp, "test.db")
        os.environ["DB_PATH"] = tmp_db
        main.DB_PATH = tmp_db
        tracker_tmp = __import__("tracker")
        tracker_tmp.init_db(tmp_db)
        conn = sqlite3.connect(tmp_db)
        recent = __import__("datetime").datetime.utcnow().isoformat() + "+00:00"
        conn.execute("""INSERT INTO scans (timestamp, market_id, question,
            market_type, hours_to_end, time_bucket) VALUES (?,?,?,?,?,?)""",
            (recent, "m0", "Will X FC win on 2026-08-30?", "match", 1.0, "T-other"))
        conn.commit()
        conn.close()

        skip_decision = ScanDecision(mode="skip", windows_active=[],
                                     priority_teams=[], all_match_teams=[],
                                     next_window_h=None, reason="test")
        seen = {}
        def fake_run_scan(use_baseline=True):
            seen["use_baseline"] = use_baseline
            return []

        old_env = os.environ.get("POLYMARKET_SWEEP")
        os.environ["POLYMARKET_SWEEP"] = "1"
        try:
            with mock.patch.object(main, "compute_scan_decision",
                                   return_value=skip_decision), \
                 mock.patch.object(main, "run_scan", side_effect=fake_run_scan), \
                 mock.patch.object(main, "print_dashboard", lambda: None), \
                 mock.patch.object(main, "ensure_glm_cache", lambda *a, **k: None):
                result = main.execute_scan(send_summary=False, force=False)
        finally:
            if old_env is None:
                os.environ.pop("POLYMARKET_SWEEP", None)
            else:
                os.environ["POLYMARKET_SWEEP"] = old_env

        assert result == [] and seen.get("use_baseline") is False, (result, seen)
        print("PASS 4 — POLYMARKET_SWEEP degrades skip to a light scan "
              "(no baseline call)")
    finally:
        scanner.ODDS_STATE_PATH = old_state

    print("\nPASS — quota throttle, light-mode baseline skip, and sweep-mode "
          "degradation all behave as designed.")


if __name__ == "__main__":
    run()
