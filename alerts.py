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
