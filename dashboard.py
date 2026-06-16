"""
dashboard.py — Export structured data for the web dashboard + portable analysis.

Produces three artifacts, each with a distinct purpose:
  docs/data.json  → consumed by the static web dashboard (docs/index.html)
  docs/data.csv   → portable export for pandas / Excel / future computation
  (SQLite)        → remains the canonical source of truth, fully queryable

Design principle: NO throwaway data. Every scan row is preserved in SQLite,
mirrored to CSV for portability, and summarised in JSON for visualisation.
This makes the dataset future-proof — you can migrate to Postgres/DuckDB/
Parquet later by reading the CSV or the SQLite file directly.
"""

from __future__ import annotations

import csv
import json
import sqlite3
import statistics
import os
from datetime import datetime, timezone

from config import DB_PATH, RISK_FREE_RATE, MIN_NET_EDGE

DOCS_DIR = "docs"


def _rows_to_dicts(cursor) -> list[dict]:
    cols = [d[0] for d in cursor.description]
    return [dict(zip(cols, row)) for row in cursor.fetchall()]


def export_all(path: str = DB_PATH, docs_dir: str = DOCS_DIR):
    """Generate data.json + data.csv in docs/ for the web dashboard."""
    os.makedirs(docs_dir, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row

    now = datetime.now(timezone.utc)

    # ── 1. Headline metrics ──────────────────────────────────────────────────
    total_scans = conn.execute("SELECT COUNT(*) FROM scans").fetchone()[0]
    last_scan   = conn.execute("SELECT MAX(timestamp) FROM scans").fetchone()[0]

    # ── 2. Time-bucket inventory ─────────────────────────────────────────────
    bucket_rows = conn.execute("""
        SELECT time_bucket AS bucket,
               COUNT(DISTINCT market_id) AS markets,
               COUNT(*) AS rows
        FROM scans
        WHERE time_bucket IS NOT NULL
        GROUP BY time_bucket
    """)
    buckets = _rows_to_dicts(bucket_rows)

    # ── 3. CLV summary (resolved trades) ─────────────────────────────────────
    clv = conn.execute("""
        SELECT COUNT(*) AS n,
               SUM(CASE WHEN outcome='BEAT_LINE' THEN 1 ELSE 0 END) AS beat,
               AVG(COALESCE(clv_adjusted, clv)) AS avg_adj,
               AVG(clv) AS avg_raw,
               AVG(COALESCE(time_value_baseline, 0)) AS avg_lockup,
               MIN(COALESCE(clv_adjusted, clv)) AS worst,
               MAX(COALESCE(clv_adjusted, clv)) AS best
        FROM paper_trades WHERE outcome != 'PENDING'
    """).fetchone()

    clv_adj_values = [
        r[0] for r in conn.execute(
            """SELECT COALESCE(clv_adjusted, clv) FROM paper_trades
               WHERE outcome!='PENDING' AND COALESCE(clv_adjusted, clv) IS NOT NULL"""
        ).fetchall()
    ]

    n_resolved = clv["n"] or 0
    avg_adj    = clv["avg_adj"]
    stdev      = statistics.pstdev(clv_adj_values) if len(clv_adj_values) > 1 else 0.0
    std_err    = (stdev / (n_resolved ** 0.5)) if n_resolved > 0 and stdev > 0 else 0.0
    t_stat     = (avg_adj / std_err) if std_err > 0 and avg_adj else 0.0

    # Decision gate
    if n_resolved < 30:
        gate, gate_class = f"INSUFFICIENT SAMPLE (n={n_resolved}/30)", "neutral"
    elif avg_adj is not None and avg_adj <= 0:
        gate, gate_class = f"PROJECT STOP SIGNAL (CLV_adj={avg_adj:+.3f})", "stop"
    elif t_stat < 2.0:
        gate, gate_class = f"NOT SIGNIFICANT (t={t_stat:.2f})", "warn"
    elif n_resolved < 100:
        gate, gate_class = f"PROMISING (t={t_stat:.2f}, n={n_resolved}/100)", "promising"
    else:
        gate, gate_class = f"EDGE SUPPORTED (t={t_stat:.2f})", "good"

    # ── 4. CLV histogram bins (for distribution chart) ───────────────────────
    hist_bins = {}
    if clv_adj_values:
        for v in clv_adj_values:
            b = round(v, 1)  # 0.1-wide bins
            hist_bins[b] = hist_bins.get(b, 0) + 1
    histogram = sorted([{"bin": k, "count": v} for k, v in hist_bins.items()],
                       key=lambda x: x["bin"])

    # ── 5. Latest snapshot per advancement market ────────────────────────────
    market_rows = conn.execute("""
        SELECT s.question, s.poly_mid, s.poly_ask_vwap,
               s.volume_usd, s.spread_pct, s.time_bucket, s.timestamp
        FROM scans s
        INNER JOIN (
            SELECT market_id, MAX(timestamp) AS latest
            FROM scans GROUP BY market_id
        ) L ON s.market_id = L.market_id AND s.timestamp = L.latest
        WHERE lower(s.question) LIKE '%advance%'
           OR lower(s.question) LIKE '%qualify%'
           OR lower(s.question) LIKE '%knockout%'
        ORDER BY ABS(s.poly_mid - 0.5) ASC
    """)
    markets = []
    for r in _rows_to_dicts(market_rows):
        team = (r["question"]
                .replace("Will ", "")
                .replace(" advance to the knockout stages at the 2026 FIFA World Cup?", "")
                .replace(" advance to the knockout stages at the 2026 FIFA World Cup", ""))
        markets.append({
            "team":       team,
            "mid":        round(r["poly_mid"], 4),
            "ask":        round(r["poly_ask_vwap"], 4),
            "volume":     round(r["volume_usd"], 0),
            "spread_pct": round(r["spread_pct"], 4),
            "bucket":     r["time_bucket"],
            "distance":   round(abs(r["poly_mid"] - 0.5), 4),
        })

    # ── 6. Open positions ────────────────────────────────────────────────────
    open_rows = conn.execute("""
        SELECT question, entry_price, entry_timestamp
        FROM paper_trades WHERE outcome='PENDING' ORDER BY entry_timestamp DESC
    """)
    open_positions = _rows_to_dicts(open_rows)

    # ── 7. Resolved trades (for CLV scatter / table) ─────────────────────────
    resolved_rows = conn.execute("""
        SELECT question, entry_price, closing_price, clv, clv_adjusted,
               days_held, outcome, close_timestamp
        FROM paper_trades WHERE outcome != 'PENDING'
        ORDER BY close_timestamp DESC
    """)
    resolved = _rows_to_dicts(resolved_rows)

    # ── 8. Price history (time series per market — for the trend chart) ──────
    # The CLV thesis IS about price drift over time. We expose the implied-prob
    # trajectory of the most interesting markets (nearest 0.5 = most narrative-
    # sensitive). Line series, NOT candlestick: we sample one point per scan,
    # not OHLC, so candlesticks would be fabricated precision.
    #
    # To keep data.json small, limit to top N markets by interest and cap points.
    HISTORY_MARKETS = 8
    HISTORY_POINTS  = 200

    # Pick the markets nearest 0.5 from the latest snapshot set
    focus_ids = [
        r[0] for r in conn.execute("""
            SELECT s.market_id
            FROM scans s
            INNER JOIN (
                SELECT market_id, MAX(timestamp) AS latest
                FROM scans GROUP BY market_id
            ) L ON s.market_id = L.market_id AND s.timestamp = L.latest
            WHERE lower(s.question) LIKE '%advance%'
               OR lower(s.question) LIKE '%qualify%'
               OR lower(s.question) LIKE '%knockout%'
            ORDER BY ABS(s.poly_mid - 0.5) ASC
            LIMIT ?
        """, (HISTORY_MARKETS,)).fetchall()
    ]

    price_history = []
    for mid_id in focus_ids:
        rows = conn.execute("""
            SELECT timestamp, poly_mid, time_bucket
            FROM scans WHERE market_id = ?
            ORDER BY timestamp
        """, (mid_id,)).fetchall()
        if not rows:
            continue
        # Downsample if too many points (keep newest HISTORY_POINTS)
        rows = rows[-HISTORY_POINTS:]
        # Get team label
        q = conn.execute(
            "SELECT question FROM scans WHERE market_id=? LIMIT 1", (mid_id,)
        ).fetchone()[0]
        team = (q.replace("Will ", "")
                 .replace(" advance to the knockout stages at the 2026 FIFA World Cup?", "")
                 .replace(" advance to the knockout stages at the 2026 FIFA World Cup", ""))
        price_history.append({
            "team":   team,
            "series": [{"t": r[0][:16], "p": round(r[1], 4), "bucket": r[2]} for r in rows],
        })

    conn.close()

    # ── 9. GLM pre-match signals ─────────────────────────────────────────────
    from glm_helper import get_latest_prematch_signals, ensure_glm_cache
    ensure_glm_cache(path)
    glm_signals = get_latest_prematch_signals(path, limit=12)

    # ── Assemble JSON ────────────────────────────────────────────────────────
    payload = {
        "generated_at":   now.isoformat(),
        "last_scan":      last_scan,
        "total_scans":    total_scans,
        "config": {
            "risk_free_rate": RISK_FREE_RATE,
            "min_net_edge":   MIN_NET_EDGE,
        },
        "summary": {
            "n_resolved":    n_resolved,
            "beat_line":     clv["beat"] or 0,
            "win_rate":      round((clv["beat"] or 0) / n_resolved, 3) if n_resolved else None,
            "avg_clv_raw":   round(clv["avg_raw"], 4) if clv["avg_raw"] is not None else None,
            "avg_clv_adj":   round(avg_adj, 4) if avg_adj is not None else None,
            "avg_lockup":    round(clv["avg_lockup"], 6) if clv["avg_lockup"] is not None else 0,
            "std_err":       round(std_err, 4),
            "t_stat":        round(t_stat, 2),
            "worst":         round(clv["worst"], 4) if clv["worst"] is not None else None,
            "best":          round(clv["best"], 4) if clv["best"] is not None else None,
            "gate":          gate,
            "gate_class":    gate_class,
        },
        "buckets":        buckets,
        "histogram":      histogram,
        "markets":        markets,
        "open_positions": open_positions,
        "resolved":       resolved,
        "price_history":  price_history,
        "glm_signals":    glm_signals,
    }

    json_path = os.path.join(docs_dir, "data.json")
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)

    # ── CSV export (portable, full scans table) ──────────────────────────────
    _export_csv(path, docs_dir)

    return payload


def _export_csv(path: str = DB_PATH, docs_dir: str = DOCS_DIR):
    """
    Mirror the full scans table to docs/scans.csv for portability.
    
    Migration path (DuckDB, one command each):
      scans.csv → Parquet:    duckdb -c "COPY scans TO 'scans.parquet' (FORMAT PARQUET)"
      scans.csv → Postgres:   duckdb -c "COPY (SELECT * FROM 'scans.csv') TO 'scans.sql' (FORMAT CSV)"
      
    Source: DuckDB docs (Dec 2024) — CSV as universal exchange format;
            DuckDB queries CSVs directly with no conversion needed.
    """
    conn = sqlite3.connect(path)
    for table in ("scans", "paper_trades"):
        try:
            cur  = conn.execute(f"SELECT * FROM {table} ORDER BY rowid")
            cols = [d[0] for d in cur.description]
            rows = cur.fetchall()
            out  = os.path.join(docs_dir, f"{table}.csv")
            with open(out, "w", newline="", encoding="utf-8") as f:
                w = csv.writer(f)
                w.writerow(cols)
                w.writerows(rows)
        except Exception as e:
            log.warning("CSV export failed for %s: %s", table, e)
    conn.close()
    # Legacy single-file export for backwards compat
    _export_single_csv(path, docs_dir)


def _export_single_csv(path: str = DB_PATH, docs_dir: str = DOCS_DIR):
    """Keep docs/data.csv (scans only) for backwards compatibility."""
    conn = sqlite3.connect(path)
    try:
        cur = conn.execute("SELECT * FROM scans ORDER BY timestamp")
        cols = [d[0] for d in cur.description]
        rows = cur.fetchall()
        csv_path = os.path.join(docs_dir, "data.csv")
        with open(csv_path, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(cols)
            w.writerows(rows)
    except Exception:
        pass
    conn.close()


if __name__ == "__main__":
    p = export_all()
    print(f"Exported docs/data.json + docs/data.csv")
    print(f"  Total scans:   {p['total_scans']}")
    print(f"  Markets:       {len(p['markets'])}")
    print(f"  Resolved:      {p['summary']['n_resolved']}")
    print(f"  Gate:          {p['summary']['gate']}")
