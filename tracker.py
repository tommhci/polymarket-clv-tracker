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
import json
import logging
from datetime import datetime, timezone
from dataclasses import dataclass
from typing import Optional

from config import (
    DB_PATH, RISK_FREE_RATE,
    STRATEGY_B_DISCOUNT_MAX, STRATEGY_C_UNCERTAIN_LO, STRATEGY_C_UNCERTAIN_HI,
)
from scanner import MarketSnapshot

log = logging.getLogger(__name__)


# ── Strategy pre-registration (FIXLOG.md "P0-2") ─────────────────────────────
#
# Locked before paper_trades had any real rows. Three independent entry
# rules, each evaluated against the SAME snapshot — a single market can
# qualify for more than one, in which case it gets one separate paper_trade
# row PER qualifying label (same entry price/timestamp, different trade_id
# and strategy_label), so each hypothesis's sample never overlaps/leaks into
# another's and can be analysed completely independently:
#
#   A_all       — every advancement market, YES, no filter.
#                 Tests: is Polymarket's advancement pricing well
#                 calibrated overall?
#   B_discount  — only poly_mid < STRATEGY_B_DISCOUNT_MAX (0.62).
#                 Tests: are mid-tier teams under-priced in the 48-team
#                 format?
#   C_uncertain — only STRATEGY_C_UNCERTAIN_LO < poly_mid < STRATEGY_C_UNCERTAIN_HI
#                 (0.38–0.65).
#                 Tests: is narrative bias strongest in genuinely uncertain
#                 markets?
#
# Do not add a 4th strategy or edit these thresholds (see config.py) — that
# would defeat the purpose of pre-registration once real data exists.

def classify_strategies(poly_mid: float) -> list[str]:
    """Return every pre-registered strategy label this poly_mid qualifies for."""
    labels = ["A_all"]
    if poly_mid < STRATEGY_B_DISCOUNT_MAX:
        labels.append("B_discount")
    if STRATEGY_C_UNCERTAIN_LO < poly_mid < STRATEGY_C_UNCERTAIN_HI:
        labels.append("C_uncertain")
    return labels


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


# ── Market typing (EPL pivot, FIXLOG Addendum 4) ───────────────────────────────
# CLV semantics differ by market class: match moneylines settle weekly and are
# the CLV sample; season futures (champion etc.) settle in May 2027 and have no
# "closing line" until then. Mixing them into one gate would stall the gate on
# futures for nine months. The stop gate therefore runs on market_type='match'
# only. Derived from the question so historical CSV rows backfill cleanly.

def derive_market_type(question: str) -> str:
    q = (question or "").lower()
    if "win on " in q or "end in a draw" in q:
        return "match"          # EPL match moneyline ("Will X win on DATE?")
    if ("world cup" in q or "fifa" in q or "advance" in q
            or "knockout" in q or "group stage" in q):
        return "wc_legacy"      # closed WC experiment — verdict recorded
    return "futures"            # season outrights (champion, etc.)


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
            skip_reason      TEXT,
            hours_to_end     REAL,
            time_bucket      TEXT
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS paper_trades (
            trade_id               TEXT PRIMARY KEY,
            market_id              TEXT NOT NULL,
            question               TEXT,
            direction              TEXT NOT NULL,
            entry_price            REAL NOT NULL,
            true_prob_entry        REAL,
            net_edge_entry         REAL,
            entry_timestamp        TEXT NOT NULL,
            end_date               TEXT,
            closing_price          REAL,
            clv                    REAL,
            outcome                TEXT DEFAULT 'PENDING',
            close_timestamp        TEXT,
            days_held              REAL,
            time_value_baseline    REAL,
            clv_adjusted           REAL
        )
    """)

    # ── Schema migrations: add columns to existing tables if absent ──────────
    # SQLite has no "ADD COLUMN IF NOT EXISTS"; use try/except per column.
    new_scan_cols    = ["hours_to_end REAL", "time_bucket TEXT",
                        "market_type TEXT"]
    new_trade_cols   = [
        "days_held REAL", "time_value_baseline REAL", "clv_adjusted REAL",
        # FIXLOG P0-2: pre-registered strategy label (A_all/B_discount/
        # C_uncertain/EDGE_ALERT) + catch-up-backfill approximation flags.
        "strategy_label TEXT",
        "entry_is_approx INTEGER DEFAULT 0",
        "entry_note TEXT",
        "market_type TEXT",
    ]
    for col in new_scan_cols:
        try:
            conn.execute(f"ALTER TABLE scans ADD COLUMN {col}")
        except sqlite3.OperationalError:
            pass   # already exists
    for col in new_trade_cols:
        try:
            conn.execute(f"ALTER TABLE paper_trades ADD COLUMN {col}")
        except sqlite3.OperationalError:
            pass

    # Backfill market_type in-place (SQL mirror of derive_market_type) —
    # rebuild_from_csv only fires on an empty DB, so a pre-existing local/CI
    # DB would otherwise keep NULLs and silently fall out of the gate filter.
    # rebuild_from_csv handles the fresh-DB CSV path with the same logic.
    _backfill_sql = """
        UPDATE {table} SET market_type = CASE
            WHEN lower(question) LIKE '%win on %'
              OR lower(question) LIKE '%end in a draw%'      THEN 'match'
            WHEN lower(question) LIKE '%world cup%'
              OR lower(question) LIKE '%fifa%'
              OR lower(question) LIKE '%advance%'
              OR lower(question) LIKE '%knockout%'
              OR lower(question) LIKE '%group stage%'        THEN 'wc_legacy'
            ELSE 'futures' END
        WHERE market_type IS NULL
    """
    conn.execute(_backfill_sql.format(table="scans"))
    conn.execute(_backfill_sql.format(table="paper_trades"))

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
         spread_pct, book_true_prob, baseline_source, net_edge, alertable,
         skip_reason, hours_to_end, time_bucket, market_type)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
    """, (
        snap.timestamp, snap.market_id, snap.question, snap.volume_usd,
        snap.poly_mid, snap.poly_ask_vwap, snap.spread_pct,
        snap.book_true_prob, snap.baseline_source, snap.net_edge,
        int(snap.alertable), snap.skip_reason,
        snap.hours_to_end, snap.time_bucket, snap.market_type,
    ))
    conn.commit()
    conn.close()


# ── Paper trade lifecycle ──────────────────────────────────────────────────────

def open_paper_trade(
    snap: MarketSnapshot,
    direction: str = "YES",
    strategy_label: Optional[str] = None,
    entry_price_override: Optional[float] = None,
    is_approx: bool = False,
    approx_note: Optional[str] = None,
    path: str = DB_PATH,
) -> str:
    """
    Open a virtual position. Returns trade_id.
    direction: "YES" uses poly_ask_vwap; "NO" uses 1 - poly_bid.

    strategy_label: which pre-registered strategy this row belongs to (see
      classify_strategies() — "A_all" / "B_discount" / "C_uncertain" for
      advancement-market CLV/calibration entries, "EDGE_ALERT" for the
      separate genuine-edge-vs-sportsbook trigger). Callers SHOULD always
      pass this explicitly for new code (FIXLOG.md "P0-2"); left optional
      only so this signature stays backward compatible.

    entry_price_override / is_approx / approx_note: used by the catch-up
      backfill path (FIXLOG.md "P0-1" item 4) — when a team's last group
      match already happened before we could record a clean T-1h price,
      the caller supplies the best available historical price instead of
      `snap`'s live (already-resolved) price, and marks the row so it's
      never silently mistaken for a precise T-1h entry downstream.
    """
    entry_price = (
        entry_price_override if entry_price_override is not None
        else (snap.poly_ask_vwap if direction == "YES" else (1.0 - snap.poly_bid))
    )
    trade_id    = uuid.uuid4().hex[:10]
    ts          = datetime.now(timezone.utc).isoformat()

    conn = sqlite3.connect(path)
    conn.execute("""
        INSERT OR IGNORE INTO paper_trades
        (trade_id, market_id, question, direction, entry_price,
         true_prob_entry, net_edge_entry, entry_timestamp, end_date,
         strategy_label, entry_is_approx, entry_note, market_type)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
    """, (
        trade_id, snap.market_id, snap.question, direction,
        entry_price, snap.book_true_prob, snap.net_edge, ts, snap.end_date,
        strategy_label, int(is_approx), approx_note, snap.market_type,
    ))
    conn.commit()
    conn.close()

    log.info("Opened paper trade %s | %s | entry=%.3f | strategy=%s%s",
             trade_id, snap.question[:45], entry_price, strategy_label,
             "  [APPROX]" if is_approx else "")
    return trade_id


def has_paper_trade(market_id: str, strategy_label: Optional[str] = None, path: str = DB_PATH) -> bool:
    """
    Whether a paper trade already exists for this market (optionally scoped
    to one strategy_label). Guards against duplicate entries when the same
    market is seen across multiple scan ticks within its entry window — at
    the default 30-min cron cadence, a market can sit inside the 0-2h T-1h
    bucket for several consecutive ticks; without this check each tick would
    open a brand new (duplicate) trade, corrupting the "one entry price per
    market per strategy" assumption the whole CLV/calibration analysis
    depends on. Also used by the catch-up backfill path to avoid re-opening
    a position every single run for a match that finished long ago.
    """
    conn = sqlite3.connect(path)
    if strategy_label is None:
        row = conn.execute(
            "SELECT 1 FROM paper_trades WHERE market_id=? LIMIT 1", (market_id,)
        ).fetchone()
    else:
        row = conn.execute(
            "SELECT 1 FROM paper_trades WHERE market_id=? AND strategy_label=? LIMIT 1",
            (market_id, strategy_label),
        ).fetchone()
    conn.close()
    return row is not None


def get_latest_historical_price(
    market_id: str, before_ts: Optional[str] = None, path: str = DB_PATH,
) -> Optional[tuple[float, str]]:
    """
    Return (poly_ask_vwap, timestamp) of the most recent `scans` row for this
    market, optionally restricted to strictly before `before_ts`.

    Used by the catch-up backfill (FIXLOG.md "P0-1" item 4): when a team's
    last group match already happened before this fix was deployed/ran,
    today's freshly-scanned live price has likely already converged to the
    known outcome — using it as the "entry price" would make the
    calibration input trivially correct (entry≈outcome) and useless. The
    most recent price we already had on file from BEFORE today is a better
    (though still explicitly-flagged-as-approximate) stand-in for what a
    clean T-1h price would have looked like.
    """
    conn = sqlite3.connect(path)
    if before_ts:
        row = conn.execute(
            """SELECT poly_ask_vwap, timestamp FROM scans
               WHERE market_id=? AND timestamp < ?
               ORDER BY timestamp DESC LIMIT 1""",
            (market_id, before_ts),
        ).fetchone()
    else:
        row = conn.execute(
            """SELECT poly_ask_vwap, timestamp FROM scans
               WHERE market_id=?
               ORDER BY timestamp DESC LIMIT 1""",
            (market_id,),
        ).fetchone()
    conn.close()
    return (row[0], row[1]) if row else None


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
    Close a paper trade.  Computes:
      clv                 = closing_price - entry_price   (raw timing CLV)
      days_held           = calendar days the position was open
      time_value_baseline = RISK_FREE_RATE * days_held / 365  (lockup discount)
      clv_adjusted        = clv - time_value_baseline   (strips capital cost)

    Decision gate uses clv_adjusted, not clv.
    Basis: Page & Clemen SSRN 2013 — far-from-resolution price drift partly
    reflects rational lockup discount, not necessarily exploitable edge.
    """
    conn = sqlite3.connect(path)
    c = conn.cursor()
    c.execute("SELECT entry_price, entry_timestamp FROM paper_trades WHERE trade_id = ?",
              (trade_id,))
    row = c.fetchone()
    if not row:
        log.warning("close_paper_trade: trade %s not found", trade_id)
        conn.close()
        return

    entry, entry_ts = row[0], row[1]
    clv     = round(closing_price - entry, 4)
    outcome = "BEAT_LINE" if clv > 0 else "MISSED_LINE"
    ts      = datetime.now(timezone.utc).isoformat()

    # Time-value adjustment
    try:
        entry_dt = datetime.fromisoformat(str(entry_ts).replace("Z", "+00:00"))
        if entry_dt.tzinfo is None:
            entry_dt = entry_dt.replace(tzinfo=timezone.utc)
        close_dt   = datetime.now(timezone.utc)
        days_held  = max(0.0, (close_dt - entry_dt).total_seconds() / 86400)
    except (ValueError, TypeError):
        days_held = 0.0

    time_value_baseline = round(RISK_FREE_RATE * days_held / 365, 6)
    clv_adjusted        = round(clv - time_value_baseline, 4)

    conn.execute("""
        UPDATE paper_trades
        SET closing_price=?, clv=?, outcome=?, close_timestamp=?,
            days_held=?, time_value_baseline=?, clv_adjusted=?
        WHERE trade_id=?
    """, (closing_price, clv, outcome, ts,
          round(days_held, 3), time_value_baseline, clv_adjusted,
          trade_id))
    conn.commit()
    conn.close()

    log.info("Closed %s | CLV=%.3f | adj=%.3f (−%.4f lockup) | %s",
             trade_id, clv, clv_adjusted, time_value_baseline, outcome)


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

    PRIMARY metric: clv_adjusted = clv_timing - time_value_baseline
    FALLBACK:       clv (used when clv_adjusted is NULL, e.g. old rows)

    Decision gate (hard, not advisory):
      n < 30             → INSUFFICIENT SAMPLE
      clv_adjusted ≤ 0   → PROJECT STOP SIGNAL
      t-stat < 2.0       → NOT SIGNIFICANT
    """
    conn = sqlite3.connect(path)
    c = conn.cursor()
    c.execute("""
        SELECT
            COUNT(*)                                                        AS total,
            SUM(CASE WHEN outcome='BEAT_LINE' THEN 1 ELSE 0 END)           AS beat,
            ROUND(AVG(COALESCE(clv_adjusted, clv)), 4)                     AS avg_adj,
            ROUND(AVG(clv), 4)                                             AS avg_raw,
            ROUND(MIN(COALESCE(clv_adjusted, clv)), 4)                     AS worst,
            ROUND(MAX(COALESCE(clv_adjusted, clv)), 4)                     AS best,
            ROUND(AVG(COALESCE(time_value_baseline, 0)), 6)                AS avg_lockup
        FROM paper_trades
        WHERE outcome != 'PENDING'
    """)
    row = c.fetchone()
    conn.close()

    if not row or row[0] == 0:
        return {"total": 0, "verdict": "⏳ INSUFFICIENT SAMPLE — 0 resolved trades"}

    total, beat, avg_adj, avg_raw, worst, best, avg_lockup = row
    win_rate   = beat / total if total > 0 else 0
    avg_clv    = avg_adj if avg_adj is not None else avg_raw

    if avg_clv is None:
        return {"total": total, "verdict": "INSUFFICIENT_DATA"}

    # ── t-statistic ──────────────────────────────────────────────────────────
    import statistics
    clv_values = _get_all_clv_adjusted(path)
    stdev      = statistics.pstdev(clv_values) if len(clv_values) > 1 else 0.0
    std_err    = (stdev / (total ** 0.5)) if total > 0 and stdev > 0 else 0.0
    t_stat     = (avg_clv / std_err) if std_err > 0 else 0.0

    # ── Hard decision gate ────────────────────────────────────────────────────
    # Gate 1: sample too small for any read
    if total < 30:
        verdict = (f"⏳ INSUFFICIENT SAMPLE — n={total}/30. "
                   f"World Cup alone cannot reach this threshold.")
    # Gate 2: PROJECT STOP SIGNAL (the hard termination criterion)
    elif avg_clv <= 0:
        verdict = (f"🛑 PROJECT STOP SIGNAL — "
                   f"clv_adjusted={avg_clv:+.3f} ≤ 0 at n={total}. "
                   f"Strategy has no positive signal after time-value adjustment.")
    elif t_stat < 2.0:
        verdict = (f"⚠️  NOT SIGNIFICANT — clv_adj={avg_clv:+.3f} but "
                   f"t={t_stat:.2f} (<2.0). Noise. Do NOT scale.")
    elif total < 100:
        verdict = (f"🟡 PROMISING — clv_adj={avg_clv:+.3f}, t={t_stat:.2f}, "
                   f"n={total}. Keep collecting (target n=100).")
    else:
        verdict = (f"✅ EDGE SUPPORTED — clv_adj={avg_clv:+.3f}, t={t_stat:.2f}, "
                   f"n={total}. Scale with 0.25 Kelly.")

    return {
        "total_resolved":      total,
        "beat_line":           beat,
        "win_rate":            f"{win_rate:.0%}",
        "avg_clv_adjusted":    avg_adj,
        "avg_clv_raw":         avg_raw,
        "avg_lockup_discount": avg_lockup,
        "std_err":             round(std_err, 4),
        "t_stat":              round(t_stat, 2),
        "worst_clv":           worst,
        "best_clv":            best,
        "verdict":             verdict,
    }


def _get_all_clv_adjusted(path: str = DB_PATH) -> list[float]:
    """Return clv_adjusted values (falling back to clv) for t-stat computation."""
    conn = sqlite3.connect(path)
    rows = conn.execute(
        """SELECT COALESCE(clv_adjusted, clv) FROM paper_trades
           WHERE outcome != 'PENDING'
           AND COALESCE(clv_adjusted, clv) IS NOT NULL"""
    ).fetchall()
    conn.close()
    return [r[0] for r in rows]


def _get_all_clv(path: str = DB_PATH) -> list[float]:
    """Legacy helper — raw CLV values."""
    conn = sqlite3.connect(path)
    rows = conn.execute(
        "SELECT clv FROM paper_trades WHERE outcome != 'PENDING' AND clv IS NOT NULL"
    ).fetchall()
    conn.close()
    return [r[0] for r in rows]


def print_dashboard(path: str = DB_PATH):
    """Print a human-readable dashboard to stdout."""
    summary     = get_clv_summary(path)
    open_trades = get_open_trades(path)

    print("\n" + "═" * 60)
    print("  POLYMARKET PAPER TRADING DASHBOARD")
    print("═" * 60)
    print(f"  Open positions : {len(open_trades)}")
    if open_trades:
        for t in open_trades[:5]:
            print(f"    [{t['trade_id']}] {t['question'][:40]:40s} "
                  f"entry={t['entry_price']:.3f}")
        if len(open_trades) > 5:
            print(f"    … and {len(open_trades)-5} more")

    # ── Multi-timepoint snapshot inventory ──────────────────────────────────
    conn = sqlite3.connect(path)
    bucket_rows = conn.execute("""
        SELECT time_bucket, COUNT(DISTINCT market_id), COUNT(*)
        FROM scans
        WHERE time_bucket != 'T-other' AND time_bucket IS NOT NULL
        GROUP BY time_bucket
        ORDER BY time_bucket
    """).fetchall()
    total_scans = conn.execute("SELECT COUNT(*) FROM scans").fetchone()[0]
    conn.close()

    print(f"\n  Price snapshots  (total: {total_scans:,})")
    if bucket_rows:
        for bucket, n_markets, n_rows in bucket_rows:
            print(f"    {bucket:10s}  {n_rows:4d} rows  ({n_markets} unique markets)")
        print("    T-other      (continuous monitoring — all other scans)")
    else:
        print("    No T-168h/T-24h/T-1h snapshots yet (need matching run times)")

    # ── CLV summary with hard decision gate ──────────────────────────────────
    print(f"\n  CLV Summary — PRIMARY: clv_adjusted  (raw − lockup discount)")
    if summary.get("total_resolved", 0) == 0:
        print(f"    {summary['verdict']}")
    else:
        adj = summary.get("avg_clv_adjusted")
        raw = summary.get("avg_clv_raw")
        lkp = summary.get("avg_lockup_discount", 0)
        print(f"    Resolved       : {summary['total_resolved']}")
        print(f"    Beat line      : {summary['beat_line']} ({summary['win_rate']})")
        print(f"    Avg CLV raw    : {raw:+.4f}")
        print(f"    Avg lockup disc: {lkp:+.6f}  (RFR={RISK_FREE_RATE:.1%} × days/365)")
        print(f"    Avg CLV adj    : {adj:+.4f}  ← decision gate uses this")
        print(f"    Std err / t    : {summary.get('std_err', 0):.4f} / "
              f"{summary.get('t_stat', 0):.2f}")
        print(f"    Range          : {summary['worst_clv']:+.3f} to "
              f"{summary['best_clv']:+.3f}")
        print()
        print(f"  ▶  VERDICT: {summary['verdict']}")
    print("═" * 60 + "\n")


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


def close_orphaned_trades(current_market_ids: set, path: str = DB_PATH,
                          max_lookups: int = 20):
    """
    Close PENDING trades whose market has vanished from the active scan
    universe — i.e. it resolved (and closed) between two scans, which is
    exactly when the cron grid is most likely to have missed it (Actions
    schedule events are officially best-effort and can be delayed/dropped).

    Without this, a missed window orphans the trade forever: auto_close_expired
    only sees markets still in the universe, and closed markets stop appearing
    in Gamma's active feeds. Each orphan costs one Gamma /markets/{id} lookup;
    capped per run. Closing price = Polymarket's final Yes outcomePrice —
    the market's own closing line, no sportsbook involved.
    """
    import requests as _requests

    open_trades = get_open_trades(path)
    orphans = [t for t in open_trades if t["market_id"] not in current_market_ids]
    if not orphans:
        return
    log.info("Orphan check: %d open trade(s) not in current universe", len(orphans))

    closed_any = False
    for trade in orphans[:max_lookups]:
        try:
            resp = _requests.get(
                f"https://gamma-api.polymarket.com/markets/{trade['market_id']}",
                timeout=8,
            )
            resp.raise_for_status()
            data = resp.json()
        except _requests.RequestException as e:
            log.warning("Gamma lookup failed for market %s: %s",
                        trade["market_id"], e)
            continue

        if not data.get("closed"):
            continue   # still alive, just not in today's filtered universe

        try:
            prices = json.loads(data.get("outcomePrices", "[]"))
            final_yes = float(prices[0])
        except (json.JSONDecodeError, IndexError, TypeError, ValueError):
            continue
        if not (0.0 <= final_yes <= 1.0):
            continue

        log_clv_checkpoint(trade["trade_id"], final_yes, path)
        close_paper_trade(trade["trade_id"], final_yes, path)
        closed_any = True
        log.info("Closed orphaned trade %s at final price %.3f (market resolved "
                 "between scans — capture was missed live)", 
                 trade["trade_id"], final_yes)
    if closed_any:
        log.info("Orphan reconciliation done — capture gaps backfilled from "
                 "Gamma final prices")


def capture_rate_stats(path: str = DB_PATH) -> dict:
    """
    Quantify closing-line capture (FIXLOG Addendum 4, clause 3).

    For every match-type market whose kickoff has passed, reconstruct the
    kickoff instant (scan_ts + hours_to_end is constant per market because
    match rows are anchored to Polymarket's gameStartTime) and check whether
    at least one price point exists in the final hour before kickoff — the
    entry window CLV is defined on. Rate = captured / past.

    This makes missed captures a visible metric instead of silent selection
    bias (misses correlate with kickoff time, since late-night UK slots hit
    GitHub's high-load cron windows more often).
    """
    conn = sqlite3.connect(path)
    rows = conn.execute("""
        SELECT market_id, timestamp, hours_to_end
        FROM scans
        WHERE market_type = 'match'
          AND hours_to_end IS NOT NULL
          AND time_bucket != 'T-expired'
    """).fetchall()
    conn.close()

    kickoffs: dict[str, float] = {}   # market_id → reconstructed kickoff (epoch s)
    for market_id, ts, h2e in rows:
        try:
            scan_dt = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
            if scan_dt.tzinfo is None:
                scan_dt = scan_dt.replace(tzinfo=timezone.utc)
        except (ValueError, TypeError):
            continue
        kick = scan_dt.timestamp() + float(h2e) * 3600
        # rows within ±1h of each other reconstruct the same kickoff; keep max
        kickoffs[market_id] = max(kickoffs.get(market_id, 0.0), kick)

    conn = sqlite3.connect(path)
    all_ts: dict[str, list[float]] = {}
    for market_id, ts in conn.execute(
            "SELECT market_id, timestamp FROM scans WHERE market_type='match'"):
        try:
            dt = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            all_ts.setdefault(market_id, []).append(dt.timestamp())
        except (ValueError, TypeError):
            continue
    conn.close()

    now = datetime.now(timezone.utc).timestamp()
    past = captured = 0
    for market_id, kick in kickoffs.items():
        if kick >= now:
            continue
        past += 1
        stamps = all_ts.get(market_id, [])
        if any(kick - 3600 <= t <= kick for t in stamps):
            captured += 1

    rate = (captured / past) if past else None
    return {
        "match_markets_past": past,
        "captured_final_hour": captured,
        "capture_rate": round(rate, 3) if rate is not None else None,
        "definition": "share of past match markets with ≥1 price point in "
                      "the last hour before kickoff (the CLV entry window)",
    }



# ── CSV truth-source rebuild ────────────────────────────────────────────────

def rebuild_from_csv(docs_dir: str = "docs", path: str = DB_PATH):
    """
    Rebuild SQLite from docs/scans.csv + docs/paper_trades.csv if the DB is
    missing or empty.  Called at startup when running in GitHub Actions after a
    fresh checkout (DB not tracked in git; CSVs are the truth source).

    Migration note: the same CSVs can be loaded into any other system:
      - DuckDB:   duckdb -c "CREATE TABLE scans AS SELECT * FROM 'docs/scans.csv'"
      - Pandas:   pd.read_csv('docs/scans.csv')
      - Postgres: COPY scans FROM '/path/docs/scans.csv' CSV HEADER;
    Source: DuckDB blog (Dec 2024) — CSV as universal exchange format.
    """
    import csv as _csv
    import os as _os

    # Only rebuild if DB is empty
    conn = sqlite3.connect(path)
    n = conn.execute("SELECT COUNT(*) FROM scans").fetchone()[0]
    conn.close()
    if n > 0:
        return  # DB already has data, nothing to rebuild

    log.info("DB empty — rebuilding from CSV files in %s/", docs_dir)

    for table in ("scans", "paper_trades"):
        csv_path = _os.path.join(docs_dir, f"{table}.csv")
        if not _os.path.exists(csv_path):
            log.info("  %s.csv not found — skipping", table)
            continue
        with open(csv_path, newline="", encoding="utf-8") as f:
            reader = _csv.DictReader(f)
            rows = list(reader)
        if not rows:
            continue
        cols = list(rows[0].keys())
        # Pre-pivot CSVs have no market_type column — backfill it from the
        # question text so the match/futures gate works on historical data.
        if "market_type" not in cols:
            cols.append("market_type")
        conn = sqlite3.connect(path)
        for row in rows:
            vals = [row.get(c) for c in cols if c != "market_type"]
            vals.append(row.get("market_type")
                        or derive_market_type(row.get("question", "")))
            placeholders = ",".join(["?"] * len(cols))
            col_str = ",".join(cols)
            conn.execute(
                f"INSERT OR IGNORE INTO {table} ({col_str}) VALUES ({placeholders})",
                vals,
            )
        conn.commit()
        conn.close()
        log.info("  Rebuilt %s from %s (%d rows)", table, csv_path, len(rows))
