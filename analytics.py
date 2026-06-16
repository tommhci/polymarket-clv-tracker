"""
analytics.py — Calibration & statistical analysis for advancement markets.

WHY THIS MODULE (read before editing):
The advancement markets all resolve on the SAME date (group-stage end, 2026-06-28)
to a binary outcome (advanced=1 / not=0). This instrument does NOT support a
per-match CLV study (no per-match Polymarket markets exist). What it DOES support
is a cross-sectional CALIBRATION study:

    "Is Polymarket's implied probability of advancement well-calibrated against
     the actual binary outcomes — or systematically biased (favorite-longshot)?"

The correct metrics for this are Brier score, calibration curves, and bootstrap
confidence intervals — NOT CLV. This module pre-registers that analysis BEFORE
the outcomes are known (scientifically correct: avoids p-hacking).

HONEST LIMITATION (n≈46):
- Cannot prove a marginal 2-5% edge (needs n≈384-2401; see decision gate)
- CAN detect a large structural bias IF one exists
- Favorite-longshot bias is NOT reliably large in soccer (Winkelmann et al.,
  SAGE 2024: "not persistent or systematic"; Pinnacle study 2021: minimal)
- So bootstrap CI will likely show "not distinguishable from noise" — and that
  honest null result is itself the valuable output of Phase 1.

References:
- Brier (1950); Murphy (1973) decomposition
- Gneiting & Raftery (2007) proper scoring rules
- ECMWF Forecast User Guide (2025): Brier encourages honest probabilities
"""

from __future__ import annotations

import random
import sqlite3
from dataclasses import dataclass, field
from typing import Optional

from config import DB_PATH

# World Cup 2026: 32 of 48 teams advance → base rate for advancement
WC_BASE_RATE = 32 / 48   # = 0.6667


# ── Core scoring functions ──────────────────────────────────────────────────

def brier_score(probs: list[float], outcomes: list[int]) -> Optional[float]:
    """
    Brier score = mean squared error between predicted probability and outcome.
    Range [0, 1], lower = better. 0.25 = uninformative (always predict 0.5).
    """
    if not probs or len(probs) != len(outcomes):
        return None
    return sum((p - o) ** 2 for p, o in zip(probs, outcomes)) / len(probs)


def brier_skill_score(probs: list[float], outcomes: list[int],
                      base_rate: float = WC_BASE_RATE) -> Optional[float]:
    """
    BSS = 1 - BS_model / BS_reference

    Reference = always predicting the base rate (climatology).
    BSS > 0 → market beats the naive base-rate forecast (has real information)
    BSS ≤ 0 → market no better than guessing the base rate

    For advancement: reference = always predicting 0.667 (32/48 advance).
    """
    bs_model = brier_score(probs, outcomes)
    if bs_model is None:
        return None
    bs_ref = sum((base_rate - o) ** 2 for o in outcomes) / len(outcomes)
    if bs_ref == 0:
        return None
    return 1 - (bs_model / bs_ref)


def log_loss(probs: list[float], outcomes: list[int], eps: float = 1e-9) -> Optional[float]:
    """Logarithmic loss — penalises confident wrong predictions harder than Brier."""
    import math
    if not probs:
        return None
    total = 0.0
    for p, o in zip(probs, outcomes):
        p = min(max(p, eps), 1 - eps)
        total += -(o * math.log(p) + (1 - o) * math.log(1 - p))
    return total / len(probs)


def calibration_curve(probs: list[float], outcomes: list[int],
                      n_bins: int = 5) -> list[dict]:
    """
    Reliability diagram data: bucket predictions, compare predicted vs actual.

    A well-calibrated market: in the 60-80% bucket, ~70% of markets resolve YES.
    Points ABOVE diagonal → market underestimated (events happened more often).
    Points BELOW diagonal → market overestimated (overconfident).

    Returns list of {bin_lo, bin_hi, n, mean_pred, actual_rate}.
    """
    if not probs:
        return []
    bins = []
    width = 1.0 / n_bins
    for i in range(n_bins):
        lo, hi = i * width, (i + 1) * width
        idx = [j for j, p in enumerate(probs) if (lo <= p < hi or (i == n_bins - 1 and p == 1.0))]
        if not idx:
            bins.append({"bin_lo": round(lo, 2), "bin_hi": round(hi, 2),
                         "n": 0, "mean_pred": None, "actual_rate": None})
            continue
        mean_pred   = sum(probs[j] for j in idx) / len(idx)
        actual_rate = sum(outcomes[j] for j in idx) / len(idx)
        bins.append({
            "bin_lo": round(lo, 2), "bin_hi": round(hi, 2),
            "n": len(idx),
            "mean_pred": round(mean_pred, 4),
            "actual_rate": round(actual_rate, 4),
        })
    return bins


def expected_calibration_error(probs: list[float], outcomes: list[int],
                               n_bins: int = 5) -> Optional[float]:
    """
    ECE = weighted average gap between predicted prob and actual rate per bin.
    Lower = better calibrated. 0 = perfect calibration.
    """
    curve = calibration_curve(probs, outcomes, n_bins)
    if not curve:
        return None
    total_n = sum(b["n"] for b in curve)
    if total_n == 0:
        return None
    ece = 0.0
    for b in curve:
        if b["n"] > 0 and b["mean_pred"] is not None:
            ece += (b["n"] / total_n) * abs(b["mean_pred"] - b["actual_rate"])
    return round(ece, 4)


# ── Bootstrap inference (the honest small-sample tool) ──────────────────────

def bootstrap_brier_ci(probs: list[float], outcomes: list[int],
                       n_resamples: int = 10000, seed: int = 42) -> Optional[dict]:
    """
    Bootstrap 95% CI for the Brier Skill Score.

    This is the honest small-sample test Tom asked for: instead of assuming
    normality (invalid at n=46), resample with replacement 10,000 times and
    report the percentile CI.

    Interpretation:
      - If the 95% CI for BSS includes 0 → market skill NOT distinguishable
        from base-rate guessing at this sample size (the likely n=46 result)
      - If CI entirely > 0 → market has statistically detectable skill
      - If CI entirely < 0 → market is detectably WORSE than base rate
        (this would be the exploitable mispricing signal)
    """
    n = len(probs)
    if n < 10:
        return None
    rng = random.Random(seed)
    bss_samples = []
    indices = list(range(n))
    for _ in range(n_resamples):
        resample = [rng.choice(indices) for _ in range(n)]
        rp = [probs[i] for i in resample]
        ro = [outcomes[i] for i in resample]
        bss = brier_skill_score(rp, ro)
        if bss is not None:
            bss_samples.append(bss)
    if not bss_samples:
        return None
    bss_samples.sort()
    lo = bss_samples[int(0.025 * len(bss_samples))]
    hi = bss_samples[int(0.975 * len(bss_samples))]
    point = brier_skill_score(probs, outcomes)

    # Verdict
    if lo > 0:
        verdict = "SKILL DETECTED — market beats base rate (CI > 0)"
    elif hi < 0:
        verdict = "MISPRICING DETECTED — market worse than base rate (CI < 0) ★"
    else:
        verdict = "INCONCLUSIVE — CI includes 0 (cannot distinguish from noise)"

    return {
        "bss_point":   round(point, 4) if point is not None else None,
        "ci_low":      round(lo, 4),
        "ci_high":     round(hi, 4),
        "n":           n,
        "n_resamples": n_resamples,
        "verdict":     verdict,
    }


# ── Pull resolved data + run full analysis ──────────────────────────────────

@dataclass
class CalibrationReport:
    n_resolved:     int
    brier:          Optional[float] = None
    brier_skill:    Optional[float] = None
    log_loss:       Optional[float] = None
    ece:            Optional[float] = None
    base_rate:      float = WC_BASE_RATE
    actual_rate:    Optional[float] = None
    curve:          list = field(default_factory=list)
    bootstrap:      Optional[dict] = None
    by_bucket:      dict = field(default_factory=dict)
    note:           str = ""


def _get_resolved_entries(path: str, time_bucket: Optional[str] = None) -> tuple[list, list]:
    """
    Return (entry_probs, outcomes) for resolved paper trades.

    entry_prob = entry price (Polymarket implied prob at entry)
    outcome    = 1 if market resolved YES (advanced), else 0
                 derived from closing_price: ≥0.5 → 1, else 0
    """
    conn = sqlite3.connect(path)
    rows = conn.execute("""
        SELECT entry_price, closing_price
        FROM paper_trades
        WHERE outcome != 'PENDING' AND closing_price IS NOT NULL
    """).fetchall()
    conn.close()
    probs, outcomes = [], []
    for entry, closing in rows:
        if entry is None or closing is None:
            continue
        probs.append(float(entry))
        outcomes.append(1 if float(closing) >= 0.5 else 0)
    return probs, outcomes


def run_calibration_analysis(path: str = DB_PATH) -> CalibrationReport:
    """
    Full pre-registered calibration analysis on resolved advancement markets.
    Safe to call with zero resolved trades (returns empty report).
    """
    probs, outcomes = _get_resolved_entries(path)
    n = len(probs)

    if n == 0:
        return CalibrationReport(
            n_resolved=0,
            note="No resolved markets yet. Analysis activates when markets settle "
                 "at group-stage end (~2026-06-28).",
        )

    report = CalibrationReport(
        n_resolved=n,
        brier=round(brier_score(probs, outcomes), 4),
        brier_skill=round(brier_skill_score(probs, outcomes), 4) if brier_skill_score(probs, outcomes) is not None else None,
        log_loss=round(log_loss(probs, outcomes), 4) if log_loss(probs, outcomes) is not None else None,
        ece=expected_calibration_error(probs, outcomes),
        actual_rate=round(sum(outcomes) / n, 4),
        curve=calibration_curve(probs, outcomes),
        bootstrap=bootstrap_brier_ci(probs, outcomes) if n >= 10 else None,
    )

    if n < 30:
        report.note = (f"n={n}: below the n≥30 minimum for any verdict. "
                       f"Metrics shown for pipeline validation only.")
    else:
        report.note = (f"n={n}: sufficient for large-bias detection only "
                       f"(marginal 2-5% edge needs n≈384+).")

    return report
