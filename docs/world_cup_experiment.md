# Did Closing-Line Value Beat Us? — A Pre-Registered CLV Experiment on World Cup Prediction Markets

**One-page experiment report · data window 2026-06-16 → 2026-06-29 · status: CLOSED, verdict recorded**

*This document is self-contained: it can be read without the repo's commit
history or FIXLOG. Raw data: `docs/scans.csv` (3,480 price snapshots),
`docs/paper_trades.csv` (73 settled virtual positions), both in this repo.*

---

## 1. Research question

In Polymarket's 2026 FIFA World Cup markets, if you buy at the price you can
get shortly before a match's decision moment, do you systematically beat the
closing line — i.e. does the final pre-resolution price (the most informed
price, set after all information is priced in) systematically move in your
favour? Beating the closing line consistently is the standard evidence that a
selection edge exists, independent of short-term luck.

## 2. Design and pre-registration

Three entry strategies were locked in `config.py` **before any trade row
existed** (visible in commit history; thresholds were written while
`paper_trades.csv` had 0 rows, per FIXLOG "P0-2"):

| Strategy | Entry rule | Lock |
|---|---|---|
| `A_all` | all markets at the T-1h price point | baseline |
| `B_discount` | only markets priced below 0.62 at entry | long-bias probe |
| `C_uncertain` | only markets priced 0.38–0.65 | "coin-flip zone" probe |

- **Entry price**: Polymarket CLOB VWAP for a fixed $200 order, captured by an
  automated scanner at the T-1h time bucket (0–2h before the team's own match,
  anchored to the market's decision deadline).
- **Closing price**: the market's own final pre-resolution price (prices
  converge to 0/1 near resolution; positions auto-close at ≥0.95 / ≤0.05).
- **Primary metric**: `CLV_adjusted = (closing − entry) − time-value
  correction` (US 3-month T-bill, 5.3% annualised, × days held). The correction
  was negligible here (avg +0.00005).
- **Decision gate (pre-registered)**: continue only if `CLV_adjusted > 0`,
  t > 2, n ≥ 30. A zero-or-negative mean at n ≥ 30 stops the experiment.
- **No real money**: all positions are virtual ($200 paper size).

## 3. Sample

- 48 "Win the World Cup" outright markets ($50–70M volume each — deep,
  professional order books) plus 46 team-advancement markets ($27–250K —
  thin, retail-heavy).
- 3,480 price snapshots over 13 days; 73 virtual positions settled.
- 12.3% of entries were flagged "approximate" (entered via catch-up backfill
  rather than a clean T-1h capture) — disclosed, not excluded.

## 4. Result

| Metric | Value |
|---|---|
| n (settled trades) | 73 |
| Beat the closing line | 21 (28.8%) |
| Mean CLV (raw) | **−0.0178** |
| Mean CLV (adjusted) | **−0.0178** |
| Std error / t-stat | 0.0404 / −0.44 |
| Range | −0.940 … +0.851 |
| **Pre-registered gate** | **PROJECT STOP SIGNAL** |

Strategy-level decomposition (exploratory, not pre-registered):

| Strategy | n | Beat rate | Mean CLV_adj |
|---|---|---|---|
| `A_all` | 48 | 31% | +0.0089 |
| `B_discount` | 20 | 20% | −0.0315 |
| `C_uncertain` | 5 | 40% | −0.2198 |

## 5. Interpretation — and what this result does NOT claim

**What it shows**: under the pre-registered rule, the experiment stops. On
this sample the entry filter produced no evidence of an edge over the closing
line in World Cup markets. The most liquid tier (outright winners) is where
CLV was measured; it is exactly where professional pricing should be most
efficient.

**What it does not show**:

- The study is **underpowered**: with n=73 and σ≈0.35, the 95% CI on the mean
  is roughly ±0.08 — wide enough to contain both "small edge" and "moderate
  anti-edge". t = −0.44 means we cannot even reject zero, let alone claim a
  reliable negative. The honest summary is *"no sign of edge"* — the gate was
  designed to stop on absence of evidence, and it did.
- The strategy split is directionally interesting (the naive A_all was flat-to-
  positive; the discount-seeking B_discount was worst — consistent with
  long-shot bias *buying* being the crowd's mistake, not selling it) but
  neither cell approaches significance. This is a hypothesis for a future,
  larger dataset — not a finding.
- Results are specific to a two-week single-elimination tournament; they do
  not transfer to league-season markets (different liquidity, different
  resolution cadence). The successor experiment on EPL moneylines uses the
  same pre-registration discipline with the gate re-armed on fresh data.

## 6. Known defects and how they were handled

1. **Shared deadline bug (caught and fixed mid-experiment)**: Polymarket stamped
   all advancement markets with one shared end date, which collapsed every
   team into the same time bucket. Detected by noticing 46 markets showed an
   identical `hours_to_end` at the same timestamp; fixed by anchoring each
   market to its own decision moment; affected rows are identifiable and the
   fix is regression-tested.
2. **No sportsbook baseline for advancement markets**: the free odds feed only
   carries outright-winner lines, so "value vs bookmaker" could not be computed
   for those markets. By design the experiment degraded to a pure CLV design
   (Polymarket entry vs Polymarket close) — which is the primary metric anyway.
3. **Capture gaps**: cron-based collection is best-effort (GitHub Actions
   schedule events can be delayed or dropped). Missed closings were backfilled
   from recorded exchange prices; the successor pipeline quantifies capture
   rate explicitly instead of assuming it.

## 7. What survives the negative result

- A working, fully automated collection pipeline (Gamma API + order-book VWAP
  + CSV-as-truth persistence), now pivoted to the 2026-27 Premier League.
- The methodology itself — pre-registered thresholds, a mechanical stop gate,
  time-bucketed entries, disclosed approximation flags — is reusable
  regardless of what any single experiment concludes. A pre-registered null is
  a *result about market efficiency*, and it cost zero dollars to learn.
