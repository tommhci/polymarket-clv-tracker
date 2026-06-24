# FIXLOG.md — P0/P1/P2 fix session (2026-06-23)

**Read this first: these commits are not deployed yet.** They exist in a
local clone made by an AI assistant session that had no push credentials
and no network access to GitHub or football-data.org. See "⚠️ Deployment"
at the bottom — you (Tom) need to actually push this before any of it runs
for real. Everything below describes what was changed and how it was
tested *offline*, not what has happened in production.

---

## P0-1 — T-1h CLV entry timing bug

**Diagnosis confirmed** by reading `docs/scans.csv` directly before changing
anything: at timestamp `2026-06-21T23:53:19`, all 46 advancement markets
(Spain, Saudi Arabia, France, Argentina, Portugal, Croatia, ... every team)
show `hours_to_end = 168.09` — the *exact same number*. Polymarket sets one
shared `endDateIso` for the whole "team to advance to knockout stages"
event, not one per team. This matches the document's diagnosis exactly.

**What changed:**

- **`news_fetcher.py`** — added `get_wc_group_fixtures()` (one call to
  `/competitions/WC/matches?stage=GROUP_STAGE` for the *entire* tournament,
  not per-team — avoids the free-tier 10 req/min limit), and
  `get_team_last_group_kickoff(team)` which builds a `{team: last group
  match kickoff}` map from that fixture list, with diacritic/punctuation-
  insensitive matching plus a fuzzy-containment fallback for naming
  variants. Also added `check_football_data_health()` (used in P1).
  Incidental 1-line fix: `_TEAM_ALIASES` had `"boss and herzegovina"` —
  a typo for `"bosnia"` that made the alias permanently dead code; fixed
  while touching this dict.

- **`scanner.py`** — in `run_scan()`, for advancement markets where a team
  can be identified, the team's own last-group-match kickoff (from
  `news_fetcher`) is now used as the input to `_classify_time_bucket()`
  instead of Polymarket's shared `endDateIso`. **No change** to
  `_classify_time_bucket()`'s own bucket thresholds — only the input
  changes, exactly as the spec asked. Teams aren't split into "safely
  through" vs "fighting for best-third" — every team uses the same rule
  (last own group match), per the spec's explicit instruction that
  `close_paper_trade()`'s existing lockup-discount mechanism already
  absorbs the extra waiting time for best-third-place scenarios.
  If football-data.org has no fixture match for a team, that team alone
  falls back to the old (wrong) shared date, with a logged warning — never
  crashes the scan.

  **Self-caught bug, fixed before commit:** my first draft added a +2h
  "resolution lag" offset (mirroring `scheduler.py`'s `RESOLUTION_LAG_H`)
  before feeding the kickoff time in. That shifted the "T-1h" bucket to
  fire *after* kickoff instead of before it — backwards from the entire
  point of the fix. Caught by `tests/test_p0_1_time_bucket.py` during
  development, reverted. Left in the test and the commit message as a
  record since it's exactly the class of error this fix exists to prevent.

- **`main.py`** — the T-1h entry trigger now opens one `paper_trades` row
  per qualifying pre-registered strategy (see P0-2), and is guarded by
  `has_paper_trade(market_id, label)` so the same market+strategy can't be
  entered twice across repeated 30-min cron ticks within the same window
  (this dedup risk existed latently in the *old* code too, just invisible
  because every team coincidentally shared one bucket).

  **New catch-up/backfill path:** when a team's `time_bucket` is
  `T-expired` (their real last-match kickoff already passed) and no entry
  exists yet for that market+strategy, a position is opened immediately
  using `tracker.get_latest_historical_price()` — the most recent price
  already on file (e.g. from the 6/16 or 6/21 scan clusters) — instead of
  today's live price, which has likely already converged to the known
  result. If no historical price exists at all for that market, it falls
  back to the live price. **Both cases are flagged `entry_is_approx=1`**
  with an explanatory `entry_note`, never silently passed off as a clean
  T-1h price.

**Verification (offline, no network):**
- `tests/test_p0_1_time_bucket.py` — reproduces the original bug, mocks
  per-team kickoffs, confirms different teams now land in different
  buckets, confirms graceful fallback for a team with no fixture match.
- `tests/test_p0_main_integration.py` — runs the real `main.execute_scan()`
  against a temp sqlite db: confirms a clean T-1h market opens 3
  correctly-priced non-approx rows; confirms a T-expired market *with* a
  historical price uses that price (not live) and is flagged approx;
  confirms a T-expired market *without* one falls back to live, still
  flagged approx; confirms running the identical scan twice adds **zero**
  duplicate rows (9 rows after run 1, 9 after run 2).

**NOT verified (could not be, in this sandbox):** the live HTTP call to
football-data.org itself. No `FOOTBALL_DATA_API_KEY` and no network egress
to `api.football-data.org` were available in this session. The fixture-
fetch and team-matching *logic* was tested against a realistic synthetic
payload shape, but the real API's exact team-name spelling, `stage=` filter
behavior, and rate-limit behavior are unverified. **Action needed from
you:** trigger a `workflow_dispatch` run (or wait for the next cron tick)
and check the Actions log for the P1 health-check line and for any
`"No football-data.org fixture match for..."` warnings from `scanner.py` —
those would name any team whose football-data.org spelling didn't match.

---

## P0-2 — strategy pre-registration

Locked in **before** P0-1 produced any real data (`paper_trades` was 0 rows
at the time `config.py`/`tracker.py` were edited — confirmed by `git log`
ordering: the P0-2 commits land before the `main.py` wiring that could
actually open a row).

- `config.py`: `STRATEGY_B_DISCOUNT_MAX = 0.62`,
  `STRATEGY_C_UNCERTAIN_LO/HI = 0.38/0.65` — named constants, with a
  comment saying not to add a 4th strategy or edit these once real data
  exists.
- `tracker.py`: `classify_strategies(poly_mid)` returns every label a
  market qualifies for (`A_all` always; `B_discount`/`C_uncertain`
  conditionally). A market can qualify for more than one — each
  qualifying label gets its **own** `paper_trades` row (same entry price/
  timestamp, different `trade_id`), so the three hypotheses' samples never
  overlap or leak into each other.
- Schema: `paper_trades` gained `strategy_label`, `entry_is_approx`,
  `entry_note` columns (migration, not a rebuild — existing rows, if any
  existed, would be preserved; in practice there were none to preserve).
- The older edge-vs-sportsbook alert mechanism (`alertable=True`,
  effectively only ever fires on the WIN-outright markets, not advancement
  markets) is labelled `"EDGE_ALERT"` so the column is never `NULL`, kept
  clearly separate from the three pre-registered strategies, and
  deliberately **not** given the dedup guard — that matches its
  pre-existing (unchanged) behavior.

**Verification:** boundary-value checks on `classify_strategies()`
(0.38/0.62/0.65 edges, mid=0.5 → all three, mid=0.9/0.7 → `A_all` only);
confirmed via `tests/test_p0_main_integration.py` that real rows opened by
`main.py` carry the correct label.

---

## P1 — football-data.org health check

Added `news_fetcher.check_football_data_health()` (one lightweight call to
`/v4/competitions/WC`, checks for a real HTTP 200 — not just "is the env
var non-empty") and wired it into `.github/workflows/scan.yml` as its own
step, `continue-on-error: true` (a transient outage shouldn't kill the
whole cron run; `scanner.py` already degrades gracefully per-team).

**Verified:** YAML parses correctly (6 steps in the right order); the
embedded Python snippet runs correctly standalone (prints the expected
"key not set" warning in this sandbox, which has no key).
**NOT verified:** the real HTTP 200 path. **Action needed from you:** check
the Actions log after the next run for a line starting `✅` or `⚠️`.

---

## P2 — full pipeline dry-run

`tests/p2_dry_run.py` — ran entirely against an isolated `/tmp` sqlite db
and `/tmp` docs directory. **Did not touch the real `docs/` files or the
real `paper_trades` data, which remain at 0 real rows** (this was a hard
constraint from the task spec — no fake rows were ever written to the
tracked CSV).

Simulated 40 fake advancement markets → 90 `paper_trades` rows (1-3
strategy labels each) → resolved each via the real `close_paper_trade()`
with outcomes drawn from a deliberately-miscalibrated distribution. Ran
the real, untouched `analytics.run_calibration_analysis()` and
`dashboard.export_all()`:

```
n_resolved   = 90
brier        = 0.193          (0-1 range, OK)
brier_skill  = +0.387
bootstrap CI = [0.240, 0.504]  →  "SKILL DETECTED" (CI entirely > 0)
ECE          = 0.108
curve bins   = 5/5 populated
```

No exceptions anywhere in the Python pipeline. JSON round-trips correctly;
CSV export row counts match (90/90).

**Additionally** (ad-hoc, not a committed file): extracted the actual
calibration-panel JavaScript from `docs/index.html` (lines 350-387) and
ran it under Node with a minimal `document` stub, feeding it the real JSON
this dry-run produced. It rendered the full card/bootstrap-verdict/curve-
table HTML with no exceptions. Separately re-ran it against today's real
`n_resolved=0` payload shape and confirmed the "no data yet" message still
renders correctly too — so both the empty and populated states are
confirmed working at the frontend level, not just "the Python side didn't
crash."

---

## Current data state (as of this commit)

- `docs/paper_trades.csv`: **0 real rows** (header updated to the new
  schema, no data rows added or removed — confirmed before and after with
  `wc -l`).
- `docs/scans.csv`: unchanged, still the same 420 historical rows from the
  6/16 and 6/21 clusters.
- No `strategy_label` distribution to report yet, because nothing has run
  for real. The first real numbers will appear after the next actual
  GitHub Actions run (or `workflow_dispatch`) against the live Polymarket +
  football-data.org APIs.

---

## Known limitations / explicitly NOT done (out of scope by design)

1. **Not deployed.** See "⚠️ Deployment" below — this is the most important
   item on this list.
2. **`scheduler.py`'s window detection has a related but distinct ~2h
   skew for advancement markets, not fixed here.** `scheduler.py`
   reconstructs an estimated kickoff as `stored_end_date - RESOLUTION_LAG_H
   (2h)`, a convention that assumed Polymarket's `endDateIso` was always
   2h *after* kickoff. After this fix, advancement-market `end_date` (as
   stored in `scans`) *is* the team's kickoff directly (no +2h), so
   `scheduler.py`'s reconstruction is now off by ~2h for those markets
   specifically. I traced through the window math by hand: this does
   **not** cause the scheduler to skip scanning during the real T-1h
   window (the shifted value still falls inside an adjacent window in
   every case I checked), so the core entry mechanism in `main.py` is
   unaffected — but it can pick a different/suboptimal scan *mode* (e.g.
   missing the GLM/news pre-match enrichment at the exact intended
   moment) for advancement markets. Left unfixed because it's outside the
   spec's explicit scope (the spec named `main.py`'s entry trigger only)
   and isn't a "the data is wrong" bug, just a "the optional enrichment
   might fire at a slightly different time" one. If you want this exact,
   the fix is to remove/zero `RESOLUTION_LAG_H` specifically for
   advancement-market reconstruction in `scheduler.py`.
3. Per the spec: did not touch `analytics.py`, `dashboard.py`'s existing
   Brier/Bootstrap/CLV logic, did not add a 4th strategy, did not add any
   new external data source (no Betfair, nothing beyond football-data.org
   which was already integrated), did not restyle the dashboard UI (P2
   found no rendering bug, so nothing there needed changing), did not
   refactor `main.py`'s overall structure beyond the entry-trigger block.
4. Noticed but left alone (truly out of scope, harmless): `scanner.py` has
   two `get_world_cup_markets()` definitions — an empty stub at the top of
   the file (pre-existing, not introduced by this session) immediately
   shadowed by the real implementation lower down. Dead code, no
   functional impact, not touched.
5. `analytics.py`'s own docstring says this instrument does "NOT support a
   per-match CLV study" and frames everything as a calibration (Brier)
   study instead — while `tracker.py`/`main.py`/`STATUS.md` still use "CLV"
   terminology throughout. These aren't actually in conflict (the "CLV"-
   named entry price is exactly the calibration study's input probability;
   "CLV" is legacy naming from an earlier framing of the project), but the
   naming inconsistency predates this session and wasn't cleaned up, since
   the spec explicitly said not to rewrite `analytics.py`.
6. Team-name matching between football-data.org and our internal
   `config.TEAM_NAMES` spellings is fuzzy/best-effort (diacritic-stripping
   + substring fallback) because the real API's exact spellings couldn't
   be verified live in this session. Watch the Actions log for
   `"No football-data.org fixture match for..."` warnings after the next
   run — any team named there has a matching gap that needs a manual
   alias added to `news_fetcher._TEAM_ALIASES`.

---

## ⚠️ Deployment — this has NOT been pushed to GitHub

This session ran in a sandboxed clone with **no push credentials** and
**no network access to football-data.org** (only Polymarket-adjacent and
package-registry domains were reachable; football-data.org wasn't in the
sandbox's allowed domain list, and no `FOOTBALL_DATA_API_KEY` was present).
That means:

- All 9 commits above exist only in a local clone in this session's
  sandbox — `git push` was attempted and failed with "could not read
  Username for 'https://github.com'", as expected with no stored
  credentials.
- The live football-data.org integration (the actual HTTP call, the real
  team-name spellings, the real `stage=GROUP_STAGE` filter behavior) is
  untested beyond the offline logic tests described above.

**To actually deploy this, you need to either:**
1. Pull the bundle/patch delivered alongside this file into your real
   local clone of `tommhci/polymarket-clv-tracker` and push it yourself
   (preserves the exact commit history and messages above), or
2. Re-run this same fix with a tool that has push access to your repo
   (e.g. Claude Code running locally with your own git credentials, or by
   giving this assistant a way to authenticate) so it can push directly
   and then watch the next real Actions run to confirm the P1 health
   check and the per-team time buckets actually work against the live
   API.

Either way: **after deploying, check the Actions log of the next run**
for (a) the P1 football-data.org health-check line, and (b) any
`scanner.py` warnings about unmatched team names — both are called out
above as the two things this session could not verify live.

---

## Addendum (post-deploy) — `--force` flag

Tom deployed the bundle above (merge + push confirmed in the live repo's
history: `d7181d3 Merge branch 'fix-from-claude'`), and the P1 health check
ran for real and passed: `✅ football-data.org OK (200) — key is valid and
working.` Good — that confirms the secret and the API call both work.

**However**, re-cloning the live repo directly afterward (not just reading
the pasted log) showed `docs/scans.csv` still frozen at `2026-06-21T23:53:19`
(421 lines, unchanged) and `docs/paper_trades.csv` still at 1 line (header
only) — i.e. `run_scan()` never actually executed on that run, despite the
health check passing and a manual `workflow_dispatch` trigger. Initial
read of the situation ("the catch-up mechanism must have fired") was
**incorrect** — it had not been exercised at all yet.

**Root cause:** `scheduler.compute_scan_decision()` reconstructs its
window estimate from the *existing* rows in the `scans` table — and every
existing row was written under the old bug (every team's `hours_to_end`
computed from the shared, frozen, ~168h-out `endDateIso`). So the
scheduler kept returning `"skip"` based on that stale wrong timeline. The
pre-existing bootstrap bypass only fires when the table is fully empty
(`n==0`), which wasn't the case (420 historical rows). Separately,
`scan.yml` already *claimed* in a comment that `workflow_dispatch` "always
runs full scan regardless of scheduler" — but the code never implemented
that; the manual trigger behaved identically to a regular cron tick.

**Fix (new commit, `4c62b79`):** added a `--force` flag to `main.py` that
bypasses the skip decision the same way the bootstrap guard does, and
wired `.github/workflows/scan.yml` to pass `--force` automatically when
`github.event_name == 'workflow_dispatch'` — making the workflow's own
pre-existing comment actually true. Regular 30-min cron ticks are
unaffected (`force=False`, identical to before). Verified offline with a
new `tests/test_force_flag.py` (seeds a non-empty `scans` table + a
scheduler mock forced to `"skip"`; confirms `force=False` correctly does
nothing and `force=True` correctly runs a real scan and writes the new
row) — full existing test suite re-run, no regressions.

This is a **one-time bootstrap problem**: once a single forced run
completes, `scanner.py` writes fresh correct per-team `hours_to_end`
values, and the scheduler reads from that same (now-correct) table going
forward — so regular cron ticks should self-correct after that, no
repeated forcing needed.

**Still not deployed** (same constraint as before — no push access from
this sandbox). Tom needs to merge this on top of the already-deployed
branch and push again, then run `workflow_dispatch` one more time, then
check `docs/scans.csv`'s latest timestamp and `docs/paper_trades.csv`'s
row count directly (not just the health-check log) to confirm a real scan
actually ran this time.

