"""
tests/p2_dry_run.py — FIXLOG.md "P2": full pipeline dry-run with simulated
resolved outcomes, run entirely against an isolated temp sqlite db and a
temp docs/ directory. Never touches the real tracked docs/ files or the
real paper_trades data (which stays at 0 real rows).

Purpose: catch a SQL or dashboard-rendering bug now, with fake data, rather
than for the first time on ~6/28 when real resolutions start arriving.

Run: python3 tests/p2_dry_run.py
"""

from __future__ import annotations

import json
import os
import random
import shutil
import sys
from pathlib import Path

TMP_DB = "/tmp/p2_dry_run.db"
TMP_DOCS = "/tmp/p2_dry_run_docs"

if os.path.exists(TMP_DB):
    os.remove(TMP_DB)
if os.path.exists(TMP_DOCS):
    shutil.rmtree(TMP_DOCS)
os.makedirs(TMP_DOCS, exist_ok=True)
os.environ["DB_PATH"] = TMP_DB

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import tracker     # noqa: E402
import analytics   # noqa: E402
import dashboard   # noqa: E402
from scanner import MarketSnapshot  # noqa: E402


def make_snapshot(i: int, market_id: str, question: str, poly_mid: float) -> MarketSnapshot:
    return MarketSnapshot(
        timestamp="2026-06-27T01:00:00+00:00",
        market_id=market_id,
        question=question,
        end_date="2026-06-27T02:00:00+00:00",
        volume_usd=80_000.0,
        yes_token_id="tok",
        poly_mid=poly_mid,
        poly_ask_vwap=poly_mid + 0.01,
        poly_bid=poly_mid - 0.01,
        spread_pct=0.02,
        book_true_prob=0.0,
        baseline_source="no_advance_baseline",
        taker_fee=0.001,
        net_edge=0.0,
        alertable=False,
        hours_to_end=1.0,
        time_bucket="T-1h",
    )


def main() -> None:
    random.seed(7)
    tracker.init_db(TMP_DB)

    # ── Simulate 40 advancement markets with KNOWN entry probs + outcomes ──
    # Slightly miscalibrated on purpose (entries skew a bit low relative to
    # the true advance rate) so the calibration metrics have something
    # non-trivial to report, instead of a degenerate perfectly-calibrated
    # toy case that wouldn't exercise the bootstrap CI / curve code paths
    # realistically.
    n = 40
    trade_ids = []
    for i in range(n):
        poly_mid = round(random.uniform(0.15, 0.85), 3)
        team = f"Team{i:02d}"
        snap = make_snapshot(i, f"mkt_{i}", f"Will {team} advance to the knockout stages at the 2026 FIFA World Cup?", poly_mid)
        for label in tracker.classify_strategies(poly_mid):
            tid = tracker.open_paper_trade(snap, direction="YES", strategy_label=label, path=TMP_DB)
            trade_ids.append((tid, poly_mid))

    # Resolve each trade: outcome ~ Bernoulli(poly_mid + small negative bias)
    # so brier_skill / bootstrap CI have realistic (not degenerate) values.
    for tid, poly_mid in trade_ids:
        true_p = max(0.02, min(0.98, poly_mid - 0.05))
        outcome = 1 if random.random() < true_p else 0
        closing_price = 0.97 if outcome else 0.03
        tracker.close_paper_trade(tid, closing_price, path=TMP_DB)

    n_rows = len(trade_ids)
    print(f"Simulated {n_rows} resolved paper_trades rows across {n} markets.")

    # ── Run the REAL (untouched) analytics module ───────────────────────────
    report = analytics.run_calibration_analysis(path=TMP_DB)
    print("\n--- analytics.run_calibration_analysis() ---")
    print(f"n_resolved   = {report.n_resolved}")
    print(f"brier        = {report.brier}")
    print(f"brier_skill  = {report.brier_skill}")
    print(f"log_loss     = {report.log_loss}")
    print(f"ece          = {report.ece}")
    print(f"actual_rate  = {report.actual_rate}")
    print(f"note         = {report.note}")
    print(f"bootstrap    = {report.bootstrap}")
    print(f"curve bins   = {len(report.curve)}")
    for b in report.curve:
        print(f"   {b}")

    assert report.n_resolved == n_rows
    assert report.brier is not None and 0.0 <= report.brier <= 1.0, report.brier
    assert report.bootstrap is not None, "expected a bootstrap CI at n>=10"
    assert "ci_low" in report.bootstrap and "ci_high" in report.bootstrap
    assert len(report.curve) == 5

    # ── Run the REAL (untouched) dashboard export, into a TEMP docs dir ─────
    payload = dashboard.export_all(path=TMP_DB, docs_dir=TMP_DOCS)
    print("\n--- dashboard.export_all() ---")
    print("Top-level keys:", sorted(payload.keys()))
    cal = payload["calibration"]
    print("calibration payload:", json.dumps(cal, indent=2)[:800], "...")

    assert cal["n_resolved"] == n_rows
    assert cal["brier"] is not None
    assert cal["bootstrap"] is not None
    assert cal["bootstrap"]["verdict"]
    assert isinstance(cal["curve"], list) and len(cal["curve"]) == 5

    data_json_path = os.path.join(TMP_DOCS, "data.json")
    assert os.path.exists(data_json_path), "data.json was not written"
    with open(data_json_path) as f:
        reloaded = json.load(f)
    assert reloaded["calibration"]["n_resolved"] == n_rows

    scans_csv = os.path.join(TMP_DOCS, "scans.csv")
    trades_csv = os.path.join(TMP_DOCS, "paper_trades.csv")
    assert os.path.exists(scans_csv), "scans.csv was not exported"
    assert os.path.exists(trades_csv), "paper_trades.csv was not exported"
    with open(trades_csv) as f:
        exported_rows = sum(1 for _ in f) - 1  # minus header
    assert exported_rows == n_rows, (exported_rows, n_rows)

    print(f"\nPASS — full pipeline ran with {n_rows} simulated resolved trades, "
          f"no exceptions, all expected fields populated. "
          f"(Real docs/ and DB untouched — this ran entirely against {TMP_DB} / {TMP_DOCS}.)")

    os.remove(TMP_DB)
    shutil.rmtree(TMP_DOCS)


if __name__ == "__main__":
    main()
