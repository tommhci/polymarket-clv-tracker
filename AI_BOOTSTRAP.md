# AI BOOTSTRAP

Canonical cross-tool handover protocol for this repository.

## Purpose

- Give any AI agent enough context to continue work without re-explaining the project.
- Keep project truth in one place and let tool-specific files act as adapters.
- Prevent rule drift when switching between Claude Code, Cursor, Kiro, or future tools.

## Canonical Sources

Read these first and treat them as the source of truth:

1. `README.md`
2. `NODE_QUEUE.md`
3. `AGENTS.md`
4. `governance/README.md`
5. `governance/agent-constitution.md`
6. `HANDOVER.md`

**Machine-readable state companions (present in Standard+ tier):**

- `.agents/session_log.jsonl` — append-only client-local session state event log. Machine-authoritative for `branch`, `head_commit`, `dirty_files` in the current checkout. Capture with `.agents/scripts/capture_session_state.ps1`; do not handwrite these fields. If it conflicts with `HANDOVER.md`, prefer the JSONL for branch/head/dirty-file facts in the current checkout.
- `.agents/effectiveness_log.jsonl` — append-only client-local structured skill telemetry. Companion to `.agents/skills/EFFECTIVENESS_LOG.md`.
- `.agents/skills-lock.json` — pins expected `SKILL.md` SHA-256 hashes. Validate with `.agents/scripts/validate_skills_lock.ps1` before trusting skill behavior. A mismatch is a stop signal unless the session is explicitly reviewing or publishing a skill change.
- `NODE_PROPOSALS.md` — AI-writable proposal inbox only. Not the execution queue. Only the user may promote a proposal into `NODE_QUEUE.md`; promotion requires an explicit instruction.
- Local-only paths such as `.claude/`, `inbox/`, scratch notes, or editor state are excluded from repo-state judgment unless the task explicitly targets them.

## Persistence Authority

- Chat summaries, auto-compaction summaries, tool-private memory, and adapter context are non-authoritative context only. They may help an AI continue work, but they do not define repo state.
- If information must survive session switches, tool switches, context compression, or fresh clones, write it into repo artifacts such as `HANDOVER.md`, archived handover detail, `NODE_QUEUE.md`, `NODE_PROPOSALS.md`, or `governance/*`. The machine-readable logs above are authoritative for the current checkout, but they are client-local rather than durable repo history.
- `ACTIVE_CONTEXT.md` is the active-task continuity surface. It is not machine-state authority, but it is the preferred durable checkpoint for current objective, frozen scope, last verified step, open branch, and next action after compaction, interruption, or tool switching.

**On-demand only (do NOT load every session):**

- `governance/product-vision.md` — read when running strategic-alignment, making an architectural decision, or onboarding a new AI tool for the first time.
- `.agents/skills/README.md` — read when selecting an operational skill, onboarding a new AI tool, or checking how skills route to one another. Do not load for routine node execution.
- `.agents/skills/EFFECTIVENESS_LOG.md` — read during strategic-alignment, Darwin checks, or when changing a skill. Do not load for routine execution.
- `.agents/protocols/AIS_charter.md` — read when running a Darwin check, or when strategic-alignment output suggests protocol drift.
- `.agents/protocols/multi_agent_workflow.md` — read when dispatching work to more than one AI agent, or designing cross-tool / cross-session division of labor. Do NOT load for single-agent node execution.
- `.agents/protocols/MULTI_AGENT_TRIGGER.md` — read when deciding whether to upgrade from single-agent to multi-agent. Only present in Standard+ tier; delete if not using multi-agent review.
- `.agents/MULTI_AGENT_ROI_LOG.md` — read when evaluating past multi-agent runs or running a new comparison. Only present in High-Governance tier; delete if not using multi-agent.
- `.cursor/rules/project.mdc` — read when using Cursor; keep it as a thin adapter back to this file.
- `.kiro/steering/bootstrap.md` — read when using Kiro; keep it as a thin adapter back to this file.

If a tool adapter conflicts with one of these files, assume the adapter is stale.

## Stable Rules

- Keep diffs minimal and node-scoped.
- Do not modify `AGENTS.md`, `AI_BOOTSTRAP.md`, `HANDOVER.md`, `NODE_QUEUE.md`, `governance/agent-constitution.md`, `governance/README.md`, or `.agents/protocols/AIS_charter.md` without explicit user authorization.
- Treat `governance/` as the constitution and `NODE_QUEUE.md` as the execution queue.
- Verify changes before reporting completion.

## Session Contract

Every new session should:

- read the canonical sources above
- inspect the current worktree
- **verify the workspace pointer** (if this repo uses one): read the pointer
  file `<workspace-pointer>` (path defined in your SETUP_CHECKLIST); confirm
  it resolves to the CURRENT repo root. `git rev-parse --show-toplevel` must
  match the pointer's value. If the pointer is absent, empty, or points to a
  different root (e.g. an archived worktree), STOP before reading or editing
  any file — the guard that prevents wrong-root sessions is disabled. See
  Failure Modes below.
- classify remaining changes as `active work`, `candidate work`, `residual noise`, `local-only`, or `none`
- identify the active node or gate
- update `HANDOVER.md` before switching context
- if `ACTIVE_CONTEXT.md` is not neutral (`Status: none`), read it before trusting chat summaries, tool memory, or prior handoff prose

## Tool Adapters

- **Claude Code**: `CLAUDE.md` imports `AGENTS.md` and this file via `@` directives. No extra config needed — repo files are the authority.
- **Codex**: repo-level `AGENTS.md` is auto-loaded. No separate adapter file needed. If a global `~/.codex/AGENTS.md` exists, it provides universal habits only (not project rules). Codex adapter entry point: this file + `AGENTS.md`.
- **Cursor**: `.cursor/rules/project.mdc` should import this file and point back to canonical sources.
- **Kiro**: `.kiro/steering/bootstrap.md` should import this file and point back to canonical sources.
- **Other tools**: read `AGENTS.md` + this file as the minimum start set. Tool-specific files are thin adapters only — they must not become alternate sources of truth.

## Failure Modes

- If the workspace pointer (if used) is absent, empty, or points to a root other
  than `git rev-parse --show-toplevel`, stop immediately — the active-workspace
  guard is disabled and the session may be running in the wrong worktree.
  Confirm the correct workspace with the owner before proceeding. (Root cause
  class: 2026-08-17 wrong-root incident; cross-repo findings register, finding 1 / P2.)
- If the worktree and queue disagree, stop and triage.
- If validated product code is dirty but no node authorizes it, do not infer an ACTIVE task from the diff; classify it as `CANDIDATE` or revert it.
- If a gate exists, do not advance past it without the gate condition being met.
- If the snapshot is stale, refresh `HANDOVER.md` before continuing.
- If a long-running task resumes after compaction or a tool switch without first checking `ACTIVE_CONTEXT.md`, treat the resumed plan as unsafe until the checkpoint is re-read or rebuilt from file evidence.
- If root protocol files changed but the corresponding template files were not synced (or explicitly deferred), treat that mismatch as residual noise rather than “future work someday”.
- If a handover prompt or cross-tool message states a specific HEAD commit hash: do not trust it. Run `git log -1 --format=%H` at startup and use that as ground truth. Prompt-stated HEAD was written in a prior session and is always potentially stale.

## Generation Contract

When creating tool-specific files, keep them as thin adapters. They should not become an alternate source of truth.
