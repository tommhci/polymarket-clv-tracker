"""
main.py — Entry point.

Usage:
  python main.py                  # single scan + dashboard
  python main.py --loop           # continuous scan (SCAN_INTERVAL_MINUTES)
  python main.py --digest         # send daily CLV digest to Telegram
  python main.py --close TRADE_ID PRICE   # manually close a paper trade
  python main.py --dashboard      # print CLV dashboard to terminal

The system runs in PAPER TRADING mode only.
No wallet, no pUSD, no real orders placed.
"""

from __future__ import annotations

import argparse
import logging
import time
from datetime import datetime, timezone

from config import SCAN_INTERVAL_MINUTES, DB_PATH
from scanner import run_scan
from tracker import (
    init_db, log_scan, open_paper_trade,
    auto_close_expired, close_paper_trade, print_dashboard,
)
from alerts import alert_edge_found, alert_daily_digest, alert_scan_summary

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-7s  %(name)s — %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("main")


# ── Core single-scan orchestration ────────────────────────────────────────────

def execute_scan(send_summary: bool = False) -> list:
    """
    Run one full scan, persist results, send edge alerts.
    Returns list of MarketSnapshot.
    """
    log.info("── Scan start ──────────────────────────────────")
    snapshots = run_scan()

    if not snapshots:
        log.warning("Scan returned 0 snapshots — check API keys and network")
        return []

    # Persist every snapshot to DB
    for snap in snapshots:
        log_scan(snap)

    # Auto-close trades that have reached resolution
    auto_close_expired(snapshots)

    # Open paper trades + alert for new signals
    new_signals = 0
    for snap in snapshots:
        if snap.alertable:
            trade_id = open_paper_trade(snap, direction="YES")
            snap.paper_trade_id = trade_id
            alert_edge_found(snap, trade_id)
            new_signals += 1

    if send_summary:
        alert_scan_summary(snapshots)

    log.info(
        "── Scan done: %d markets, %d new signals ─────────",
        len(snapshots), new_signals,
    )
    return snapshots


# ── CLI ────────────────────────────────────────────────────────────────────────

def parse_args():
    p = argparse.ArgumentParser(description="Polymarket edge scanner (paper trading)")
    p.add_argument("--loop",      action="store_true",
                   help="Run continuously every SCAN_INTERVAL_MINUTES minutes")
    p.add_argument("--interval",  type=int, default=SCAN_INTERVAL_MINUTES,
                   help="Override scan interval in minutes (default: %(default)s)")
    p.add_argument("--digest",    action="store_true",
                   help="Send daily CLV digest to Telegram and exit")
    p.add_argument("--dashboard", action="store_true",
                   help="Print CLV dashboard to terminal and exit")
    p.add_argument("--close",     nargs=2, metavar=("TRADE_ID", "PRICE"),
                   help="Manually close a paper trade: --close TRADE_ID 0.82")
    p.add_argument("--summary",   action="store_true",
                   help="Also send scan-summary Telegram ping each run")
    return p.parse_args()


def main():
    init_db(DB_PATH)
    args = parse_args()

    # ── Manual close ──────────────────────────────────────────────────────────
    if args.close:
        trade_id, price_str = args.close
        try:
            price = float(price_str)
        except ValueError:
            log.error("Invalid price: %s", price_str)
            return
        close_paper_trade(trade_id, price, DB_PATH)
        print_dashboard()
        return

    # ── Daily digest ──────────────────────────────────────────────────────────
    if args.digest:
        alert_daily_digest()
        return

    # ── Dashboard only ────────────────────────────────────────────────────────
    if args.dashboard:
        print_dashboard()
        return

    # ── Single scan ───────────────────────────────────────────────────────────
    if not args.loop:
        execute_scan(send_summary=args.summary)
        print_dashboard()
        return

    # ── Continuous loop ───────────────────────────────────────────────────────
    interval_sec = args.interval * 60
    log.info(
        "Continuous mode: scanning every %d minutes. Ctrl+C to stop.",
        args.interval,
    )

    scan_count = 0
    while True:
        try:
            execute_scan(send_summary=args.summary)
            scan_count += 1

            # Print dashboard every 4 scans (~2 hours at default interval)
            if scan_count % 4 == 0:
                print_dashboard()

            next_run = datetime.now(timezone.utc).strftime("%H:%M UTC")
            log.info("Sleeping %d min. Next run ~%s", args.interval, next_run)
            time.sleep(interval_sec)

        except KeyboardInterrupt:
            log.info("Stopped by user.")
            print_dashboard()
            break
        except Exception as e:
            log.error("Scan failed: %s — retrying in 5 min", e, exc_info=True)
            time.sleep(300)


if __name__ == "__main__":
    main()
