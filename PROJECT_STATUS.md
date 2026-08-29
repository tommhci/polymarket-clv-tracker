# Project Status

Project: polymarket-clv-tracker
Project ID: polymarket-clv-tracker
AI Control Plane: C:\Users\1\ai-control-plane
Attach tier: minimal
Attached: 2026-08-28

## Current State

- Goal: automated paper-trading scanner — Polymarket World Cup advancement
  prices vs de-vigged sportsbook baseline; CLV calibration study across three
  pre-registered entry strategies (A_all / B_discount / C_uncertain).
  Paper only: no wallet, no real money, no credentials to run.
- Working: 30-min cron scan (GitHub Actions, `scan.yml`: schedule 7,37 * * * *
  + workflow_dispatch force path); ~451 data-scan commits landed since 2026-07;
  scans persisted to SQLite (untracked by design, `*.db` gitignored);
  portable truth source = `docs/scans.csv` + `docs/paper_trades.csv`.
- Do not change without owner approval: everything in
  `.control-plane/protected-paths.json` (AGENTS.md, AI_BOOTSTRAP.md,
  PROJECT_STATUS.md, .control-plane/*, config.py, docs/paper_trades.csv,
  .env.example) plus `.github/workflows/scan.yml` cron semantics and the
  three pre-registered strategy definitions in main.py.

## Verification

- Declared command (see `.control-plane/verification.json`):
  `python tests/test_force_flag.py && python tests/test_p0_1_time_bucket.py && python tests/test_p0_main_integration.py && python tests/p2_dry_run.py`
  — all four are `__main__`-style scripts, NOT pytest-collectable (pytest
  reports "collected 0 items"; do not use `python -m pytest` here).
- Last verified: 2026-08-29 — all 4 scripts exit 0 on Windows after the
  sqlite connection-leak fix (140c232).
- Known limitation: tests write scratch DBs under `/tmp` (Git Bash/MSYS
  path mapping); no Windows-native temp handling yet.

## AI Working Constraints

- Read AGENTS.md and AI_BOOTSTRAP.md at session start.
- Load shared ai-control-plane protocols only when the current task needs them.
- Keep project-specific state in this repo, not in the shared control plane.
- Never commit: `.env*`, `*.db`, `__pycache__/`, runtime session logs
  (`.agents/session_log.jsonl`, `.agents/effectiveness_log.jsonl`).
