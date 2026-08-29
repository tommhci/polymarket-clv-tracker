"""
alerts.py — Telegram alert system.

Two alert types:
  1. EDGE SIGNAL   — new alertable snapshot (edge > 4%, spread < 3%)
  2. DAILY DIGEST  — CLV summary + open positions (run once a day)

If TELEGRAM_BOT_TOKEN / CHAT_ID not set, alerts fall back to stdout.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional

import requests

from config import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID
from scanner import MarketSnapshot
from tracker import get_clv_summary, get_open_trades, DB_PATH

log = logging.getLogger(__name__)

TELEGRAM_API = "https://api.telegram.org/bot{token}/sendMessage"


# ── Core send ──────────────────────────────────────────────────────────────────

def _send(text: str, parse_mode: str = "HTML") -> bool:
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print(f"\n[ALERT]\n{text}\n")
        return True

    url = TELEGRAM_API.format(token=TELEGRAM_BOT_TOKEN)
    payload = {
        "chat_id":    TELEGRAM_CHAT_ID,
        "text":       text,
        "parse_mode": parse_mode,
    }
    try:
        r = requests.post(url, json=payload, timeout=8)
        r.raise_for_status()
        return True
    except requests.RequestException as e:
        log.error("Telegram send failed: %s", e)
        return False


# ── Alert type 1: Edge signal ──────────────────────────────────────────────────

def alert_edge_found(snap: MarketSnapshot, trade_id: Optional[str] = None) -> bool:
    """
    Send a Telegram message when a positive-edge opportunity is detected.
    Includes: market, Poly price vs P_true, net edge, spread, paper trade ID.
    """
    direction = "YES" if snap.book_true_prob > snap.poly_mid else "NO"

    # Maker alternative note (always better than taker for thin markets)
    maker_price = snap.poly_bid if direction == "YES" else (1 - snap.poly_ask_vwap)
    maker_note  = f"Maker bid: <b>{maker_price:.3f}</b> (0% fee + rebate)" \
                  if direction == "YES" else ""

    trade_note = f"\n📋 Paper trade logged: <code>#{trade_id}</code>" if trade_id else ""

    msg = (
        f"🔔 <b>EDGE SIGNAL — {direction}</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"📌 <b>{snap.question}</b>\n\n"
        f"Poly ask (VWAP $200): <b>{snap.poly_ask_vwap:.3f}</b>\n"
        f"Spread:               <b>{snap.spread_pct:.1%}</b>\n"
        f"P_true (de-vigged):   <b>{snap.book_true_prob:.3f}</b>\n"
        f"Source: <i>{snap.baseline_source}</i>\n\n"
        f"Taker fee:  {snap.taker_fee:.3%}\n"
        f"<b>Net edge:  {snap.net_edge:+.1%}</b>\n"
        f"{maker_note}"
        f"\nVolume: ${snap.volume_usd:,.0f}  |  "
        f"End: {snap.end_date[:10] if snap.end_date else 'unknown'}"
        f"{trade_note}\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"⚠️ Paper trade only. Verify before real execution."
    )
    return _send(msg)


# ── Alert type 2: Daily digest ─────────────────────────────────────────────────

def alert_daily_digest(path: str = DB_PATH) -> bool:
    """
    Send a morning summary: CLV verdict + open positions.
    Recommend running at 08:00 local time via cron.
    """
    summary     = get_clv_summary(path)
    open_trades = get_open_trades(path)
    ts          = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    # CLV block
    if summary.get("total_resolved", 0) == 0:
        clv_block = "No resolved trades yet."
    else:
        clv_block = (
            f"Resolved : {summary['total_resolved']}  |  "
            f"Beat line: {summary['beat_line']} ({summary['win_rate']})\n"
            f"Avg CLV  : {summary['avg_clv']:+.3f}  "
            f"[{summary['worst_clv']:+.3f} / {summary['best_clv']:+.3f}]\n"
            f"<b>{summary['verdict']}</b>"
        )

    # Open positions block
    if not open_trades:
        pos_block = "No open positions."
    else:
        lines = []
        for t in open_trades[:8]:
            lines.append(
                f"  [{t['trade_id']}] {t['question'][:38]:38s} "
                f"entry={t['entry_price']:.3f}"
            )
        if len(open_trades) > 8:
            lines.append(f"  … +{len(open_trades)-8} more")
        pos_block = "\n".join(lines)

    msg = (
        f"📊 <b>Daily CLV Digest</b> — {ts}\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"{clv_block}\n\n"
        f"<b>Open positions ({len(open_trades)}):</b>\n"
        f"<code>{pos_block}</code>"
    )
    return _send(msg)


# ── Alert type 3: Scan summary (optional, quieter) ────────────────────────────

def alert_scan_summary(snapshots: list[MarketSnapshot]) -> bool:
    """
    Send a brief scan-completion ping showing market count and signal count.
    Useful for confirming the bot is alive without spamming.
    """
    total     = len(snapshots)
    alertable = sum(1 for s in snapshots if s.alertable)
    ts        = datetime.now(timezone.utc).strftime("%H:%M UTC")

    if alertable == 0:
        msg = f"🔍 Scan {ts} — {total} markets checked, <b>0 signals</b>."
    else:
        lines = [
            f"  • {s.question[:45]} | edge={s.net_edge:+.1%}"
            for s in snapshots if s.alertable
        ]
        body  = "\n".join(lines)
        msg   = (
            f"🔍 Scan {ts} — {total} markets, "
            f"<b>{alertable} signal{'s' if alertable>1 else ''}</b>:\n"
            f"<code>{body}</code>"
        )
    return _send(msg)


import os
import re
import sys


# ── Dead-man's switch (FIXLOG Addendum 5) ──────────────────────────────────────
# This pipeline has already died silently once: the World Cup ended in early
# July 2026 and the cron kept "running" for two months while finding zero
# markets — no new rows, no errors, nobody noticed. Secondary risk on top:
# GitHub auto-disables scheduled workflows after 60 days of repo inactivity
# (workflow runs don't count as activity; the commits it pushes do). So once
# the scanner starts failing silently (no new rows → no commits → no activity),
# the schedule itself dies on day 60. This check exists to make that failure
# LOUD: red banner in STATUS.md + auto-opened GitHub issue, auto-closed on
# recovery. It runs as the last workflow step with `if: always()` so it fires
# even when the scan step failed.

STALE_ISSUE_TITLE_PREFIX = "[ALERT] Polymarket pipeline stale"


def check_pipeline_staleness(csv_path: str = "docs/scans.csv",
                             threshold_h: float = 48.0) -> dict:
    """
    Read the newest scan row from the committed truth source (docs/scans.csv —
    the DB doesn't exist on a fresh runner until main.py rebuilds it, and if
    the scan failed this CSV is exactly the last good state) and compare
    against the threshold.
    """
    import csv as _csv
    import os as _os

    if not _os.path.exists(csv_path):
        return {"stale": True, "age_h": None, "last_row": None,
                "threshold_h": threshold_h,
                "reason": f"{csv_path} missing — pipeline never exported data"}

    last_ts = None
    with open(csv_path, newline="", encoding="utf-8") as f:
        for row in _csv.DictReader(f):
            ts = row.get("timestamp")
            if ts:
                last_ts = ts   # rows are ordered by id; keep the last one

    now = datetime.now(timezone.utc)
    if not last_ts:
        return {"stale": True, "age_h": None, "last_row": None,
                "threshold_h": threshold_h, "reason": "no rows in scans.csv"}

    try:
        last_dt = datetime.fromisoformat(str(last_ts).replace("Z", "+00:00"))
        if last_dt.tzinfo is None:
            last_dt = last_dt.replace(tzinfo=timezone.utc)
    except (ValueError, TypeError):
        return {"stale": True, "age_h": None, "last_row": last_ts,
                "threshold_h": threshold_h, "reason": f"unparseable timestamp"}

    age_h = (now - last_dt).total_seconds() / 3600
    return {"stale": age_h >= threshold_h, "age_h": round(age_h, 1),
            "last_row": last_ts, "threshold_h": threshold_h, "reason": ""}


def _stale_banner(stats: dict) -> str:
    age = stats["age_h"]
    age_str = f"{age:.0f}h" if age is not None else "unknown"
    return (
        f"> 🚨 **PIPELINE STALE — no new scan rows for {age_str} "
        f"(threshold: {stats['threshold_h']:.0f}h).** "
        f"Last row: `{stats['last_row']}`. This pipeline died silently once "
        f"before (Jul–Aug 2026). Check the latest Actions runs: "
        f"see the Actions tab of this repository"
    )


def write_stale_banner(docs_dir: str = ".", stats: dict | None = None):
    """Prepend the red banner to STATUS.md (idempotent). Returns True if written."""
    stats = stats or check_pipeline_staleness()
    status_path = os.path.join(docs_dir, "STATUS.md")
    if not os.path.exists(status_path):
        return False
    banner = _stale_banner(stats)
    with open(status_path, encoding="utf-8") as f:
        content = f.read()
    if banner.splitlines()[0] in content:
        return False   # already flagged
    with open(status_path, "w", encoding="utf-8") as f:
        f.write(banner + "\n\n" + content)
    return True


def _gh(*args: str) -> tuple[int, str]:
    import subprocess
    r = subprocess.run(["gh", *args], capture_output=True, text=True,
                       timeout=30)
    return r.returncode, (r.stdout + r.stderr).strip()


def _open_stale_issue() -> Optional[str]:
    """Return the URL of an existing open stale-alert issue, else None."""
    code, out = _gh("issue", "list", "--state", "open", "--limit", "10",
                    "--search", f'"{STALE_ISSUE_TITLE_PREFIX}" in:title')
    for line in out.splitlines():
        m = re.search(r"https://github\.com/\S+/issues/\d+", line)
        if m:
            return m.group(0)
    return None


def create_stale_issue(stats: dict) -> Optional[str]:
    """Open a GitHub issue for the stale pipeline (deduped). Returns URL or None."""
    if _open_stale_issue():
        return None   # already alerted — don't spam
    age = stats["age_h"]
    body = (
        f"Automated dead-man's switch (alerts.py --stale).\n\n"
        f"- No new scan rows for: **{age if age is not None else 'unknown'}h** "
        f"(threshold {stats['threshold_h']:.0f}h)\n"
        f"- Last row: `{stats['last_row']}`\n"
        f"- Note: GitHub disables scheduled workflows after 60 days of repo "
        f"inactivity — if this keeps failing silently, the cron itself dies "
        f"next. Fix the scan, then close this issue (or it auto-closes on "
        f"recovery via the same check).\n"
    )
    code, out = _gh("issue", "create",
                    "--title", f"{STALE_ISSUE_TITLE_PREFIX} — no scans for "
                               f"{age if age is not None else '?'}h",
                    "--body", body)
    m = re.search(r"https://github\.com/\S+/issues/\d+", out)
    return m.group(0) if m else None


def close_stale_issue_if_any() -> Optional[str]:
    """Auto-close the alert issue once the pipeline is healthy again."""
    url = _open_stale_issue()
    if not url:
        return None
    _gh("issue", "close", url,
        "--comment", "Recovered — fresh scan rows detected. Auto-closed by "
                     "the dead-man's switch.")
    return url


def run_stale_check(threshold_h: float = 48.0,
                    docs_dir: str = "docs") -> int:
    """
    CLI entry (python alerts.py --stale). Order of operations:
      fresh  → close any leftover alert issue, exit 0
      stale  → write STATUS banner (committed by caller step = repo activity,
               which itself defers GitHub's 60-day schedule disable), open a
               deduped issue, exit 0 (advisory — never fails the workflow)
    """
    stats = check_pipeline_staleness(threshold_h=threshold_h)
    log.info("Staleness check: %s", stats)

    if not stats["stale"]:
        closed = close_stale_issue_if_any()
        if closed:
            log.info("Pipeline recovered — closed alert issue %s", closed)
        print(f"OK: last scan row {stats['last_row']} "
              f"({stats['age_h']}h old, < {threshold_h:.0f}h threshold)")
        return 0

    written = write_stale_banner(docs_dir, stats)
    url = create_stale_issue(stats)
    print(f"STALE: no rows for {stats['age_h']}h "
          f"(threshold {threshold_h:.0f}h) — "
          f"banner {'written' if written else 'already present'}, "
          f"issue {url or 'already open'}")
    return 0


if __name__ == "__main__":
    import argparse
    import os
    import re

    p = argparse.ArgumentParser()
    p.add_argument("--stale", action="store_true",
                   help="Run the dead-man's-switch staleness check")
    p.add_argument("--threshold-h", type=float, default=48.0)
    args = p.parse_args()

    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s  %(levelname)-8s %(message)s")
    if args.stale:
        sys.exit(run_stale_check(threshold_h=args.threshold_h))
    print("nothing to do — pass --stale")
