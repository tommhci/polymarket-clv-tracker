"""
tracker.py — SQLite paper trade logger + CLV calculator.

Tables:
  scans        — every MarketSnapshot logged
  paper_trades — virtual positions (opened on edge signal, closed at resolution)
  clv_log      — final CLV record per trade

CLV definition (prediction market variant):
  CLV = closing_price - entry_price   (for Yes positions)
  Positive → you entered cheaper than where the market closed (beat the line)
  Negative → you overpaid; closing line moved against you
"""

from __future__ import annotations

import sqlite3
import uuid
import logging
from datetime import datetime, timezone
from dataclasses import dataclass
from typing import Optional

from config import DB_PATH
from scanner import MarketSnapshot

log = logging.getLogger(__name__)


# ── Data structure ─────────────────────────────────────────────────────────────

@dataclass
class PaperTrade:
    trade_id:           str
    market_id:          str
    question:           str
    direction:          str          # "YES" | "NO"
    entry_price:        float        # poly_ask_vwap at entry
    true_prob_entry:    float        # book_true_prob at entry
    net_edge_entry:     float
    entry_timestamp:    str
    end_date:           Optional[str]
    # Filled at close
    closing_price:      Optional[float] = None
    clv:                Optional[float] = None
    outcome:            str = "PENDING"  # PENDING | BEAT_LINE | MISSED_LINE
    close_timestamp:    Optional[str]  = None


# ── DB init ────────────────────────────────────────────────────────────────────

def init_db(path: str = DB_PATH):
    conn = sqlite3.connect(path)
    c = conn.cursor()

    c.execute("""
        CREATE TABLE IF NOT EXISTS scans (
            id               INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp        TEXT NOT NULL,
            market_id        TEXT NOT NULL,
            question         TEXT,
            volume_usd       REAL,
            poly_mid         REAL,
            poly_ask_vwap    REAL,
            spread_pct       REAL,
            book_true_prob   REAL,
            baseline_source  TEXT,
            net_edge         REAL,
            alertable        INTEGER,
            skip_reason      TEXT
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS paper_trades (
            trade_id          TEXT PRIMARY KEY,
            market_id         TEXT NOT NULL,
            question          TEXT,
            direction         TEXT NOT NULL,
            entry_price       REAL NOT NULL,
            true_prob_entry   REAL,
            net_edge_entry    REAL,
            entry_timestamp   TEXT NOT NULL,
            end_date          TEXT,
            closing_price     REAL,
            clv               REAL,
            outcome           TEXT DEFAULT 'PENDING',
            close_timestamp   TEXT
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS clv_log (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            trade_id        TEXT NOT NULL,
            check_timestamp TEXT NOT NULL,
            current_price   REAL,
            unrealised_clv  REAL
        )
    """)

    conn.commit()
    conn.close()
    log.info("DB initialised at %s", path)


# ── Scan logging ───────────────────────────────────────────────────────────────

def log_scan(snap: MarketSnapshot, path: str = DB_PATH):
    conn = sqlite3.connect(path)
    conn.execute("""
        INSERT INTO scans
        (timestamp, market_id, question, volume_usd, poly_mid, poly_ask_vwap,
         spread_pct, book_true_prob, baseline_source, net_edge, alertable, skip_reason)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
    """, (
        snap.timestamp, snap.market_id, snap.question, snap.volume_usd,
        snap.poly_mid, snap.poly_ask_vwap, snap.spread_pct,
        snap.book_true_prob, snap.baseline_source, snap.net_edge,
        int(snap.alertable), snap.skip_reason,
    ))
    conn.commit()
    conn.close()


# ── Paper trade lifecycle ──────────────────────────────────────────────────────

def open_paper_trade(snap: MarketSnapshot, direction: str = "YES", path: str = DB_PATH) -> str:
    """
    Open a virtual position. Returns trade_id.
    direction: "YES" uses poly_ask_vwap; "NO" uses 1 - poly_bid.
    """
    entry_price = snap.poly_ask_vwap if direction == "YES" else (1.0 - snap.poly_bid)
    trade_id    = uuid.uuid4().hex[:10]
    ts          = datetime.now(timezone.utc).isoformat()

    conn = sqlite3.connect(path)
    conn.execute("""
        INSERT OR IGNORE INTO paper_trades
        (trade_id, market_id, question, direction, entry_price,
         true_prob_entry, net_edge_entry, entry_timestamp, end_date)
        VALUES (?,?,?,?,?,?,?,?,?)
    """, (
        trade_id, snap.market_id, snap.question, direction,
        entry_price, snap.book_true_prob, snap.net_edge, ts, snap.end_date,
    ))
    conn.commit()
    conn.close()

    log.info("Opened paper trade %s | %s | entry=%.3f | edge=%.1f%%",
             trade_id, snap.question[:45], entry_price, snap.net_edge * 100)
    return trade_id


def log_clv_checkpoint(trade_id: str, current_price: float, path: str = DB_PATH):
    """Record an intra-trade mark-to-market CLV snapshot."""
    conn = sqlite3.connect(path)
    c = conn.cursor()
    c.execute("SELECT entry_price FROM paper_trades WHERE trade_id = ?", (trade_id,))
    row = c.fetchone()
    if row:
        unrealised = current_price - row[0]
        conn.execute("""
            INSERT INTO clv_log (trade_id, check_timestamp, current_price, unrealised_clv)
            VALUES (?,?,?,?)
        """, (trade_id, datetime.now(timezone.utc).isoformat(), current_price, unrealised))
        conn.commit()
    conn.close()


def close_paper_trade(trade_id: str, closing_price: float, path: str = DB_PATH):
    """
    Close a paper trade at `closing_price` (price at resolution / match kickoff).
    CLV = closing_price - entry_price
    """
    conn = sqlite3.connect(path)
    c = conn.cursor()
    c.execute("SELECT entry_price FROM paper_trades WHERE trade_id = ?", (trade_id,))
    row = c.fetchone()
    if not row:
        log.warning("close_paper_trade: trade %s not found", trade_id)
        conn.close()
        return

    entry   = row[0]
    clv     = round(closing_price - entry, 4)
    outcome = "BEAT_LINE" if clv > 0 else "MISSED_LINE"
    ts      = datetime.now(timezone.utc).isoformat()

    conn.execute("""
        UPDATE paper_trades
        SET closing_price=?, clv=?, outcome=?, close_timestamp=?
        WHERE trade_id=?
    """, (closing_price, clv, outcome, ts, trade_id))
    conn.commit()
    conn.close()

    log.info("Closed trade %s | CLV=%.3f | %s", trade_id, clv, outcome)


# ── Query helpers ──────────────────────────────────────────────────────────────

def get_open_trades(path: str = DB_PATH) -> list[dict]:
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT * FROM paper_trades WHERE outcome='PENDING' ORDER BY entry_timestamp"
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_clv_summary(path: str = DB_PATH) -> dict:
    """
    Aggregate CLV across all resolved trades.
    avg_clv > 0.01  → EDGE CONFIRMED  (beat closing line consistently)
    avg_clv 0–0.01  → MARGINAL        (investigate further)
    avg_clv < 0     → NO EDGE         (stop / reassess)
    """
    conn = sqlite3.connect(path)
    c = conn.cursor()
    c.execute("""
        SELECT
            COUNT(*)                                          AS total,
            SUM(CASE WHEN outcome='BEAT_LINE' THEN 1 ELSE 0 END) AS beat,
            ROUND(AVG(clv), 4)                               AS avg_clv,
            ROUND(MIN(clv), 4)                               AS worst,
            ROUND(MAX(clv), 4)                               AS best
        FROM paper_trades
        WHERE outcome != 'PENDING'
    """)
    row = c.fetchone()
    conn.close()

    if not row or row[0] == 0:
        return {"total": 0, "verdict": "INSUFFICIENT_DATA (need ≥10 resolved trades)"}

    total, beat, avg_clv, worst, best = row
    win_rate = beat / total

    if avg_clv is None:
        return {"total": total, "verdict": "INSUFFICIENT_DATA"}

    if avg_clv >= 0.02:
        verdict = "✅ EDGE CONFIRMED — scale up carefully"
    elif avg_clv >= 0.005:
        verdict = "⚠️  MARGINAL — monitor 10 more trades before scaling"
    elif avg_clv >= 0:
        verdict = "⚠️  WEAK — noise or small sample; do not scale"
    else:
        verdict = "❌ NO EDGE — strategy invalid at current params; reassess"

    return {
        "total_resolved": total,
        "beat_line":       beat,
        "win_rate":        f"{win_rate:.0%}",
        "avg_clv":         avg_clv,
        "worst_clv":       worst,
        "best_clv":        best,
        "verdict":         verdict,
    }


def print_dashboard(path: str = DB_PATH):
    """Print a human-readable dashboard to stdout."""
    summary = get_clv_summary(path)
    open_trades = get_open_trades(path)

    print("\n" + "═" * 55)
    print("  POLYMARKET PAPER TRADING DASHBOARD")
    print("═" * 55)
    print(f"  Open positions : {len(open_trades)}")
    if open_trades:
        for t in open_trades[:5]:
            print(f"    [{t['trade_id']}] {t['question'][:40]:40s} "
                  f"entry={t['entry_price']:.3f}  edge={t['net_edge_entry']:.1%}")
        if len(open_trades) > 5:
            print(f"    … and {len(open_trades)-5} more")

    print("\n  CLV Summary (resolved trades):")
    if summary.get("total_resolved", 0) == 0:
        print(f"    {summary['verdict']}")
    else:
        print(f"    Resolved  : {summary['total_resolved']}")
        print(f"    Beat line : {summary['beat_line']} ({summary['win_rate']})")
        print(f"    Avg CLV   : {summary['avg_clv']:+.3f}  "
              f"[worst {summary['worst_clv']:+.3f} / best {summary['best_clv']:+.3f}]")
        print(f"    Verdict   : {summary['verdict']}")
    print("═" * 55 + "\n")


# ── Auto-close trades near resolution ─────────────────────────────────────────

def auto_close_expired(scanner_snapshots: list[MarketSnapshot], path: str = DB_PATH):
    """
    For any open paper trade whose market now prices at ≥ 0.95 or ≤ 0.05,
    treat it as effectively resolved and close with the current mid-price.
    (Markets approaching resolution converge to 0 or 1.)
    """
    open_trades = get_open_trades(path)
    if not open_trades:
        return

    # Build market_id → current mid lookup from latest scan
    mid_lookup = {s.market_id: s.poly_mid for s in scanner_snapshots}

    for trade in open_trades:
        mid = mid_lookup.get(trade["market_id"])
        if mid is None:
            continue
        if mid >= 0.95 or mid <= 0.05:
            # Market has effectively resolved
            log_clv_checkpoint(trade["trade_id"], mid, path)
            close_paper_trade(trade["trade_id"], mid, path)
            log.info("Auto-closed %s at %.3f (near resolution)", trade["trade_id"], mid)
