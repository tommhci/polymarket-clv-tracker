---
name: node-intake
description: "Read the project docs, current worktree state, and NODE_QUEUE.md to decide the safest next node before any implementation work."
last_verified: 2026-06-27
verified_against: AGENTS.md@2ee14b5
subordinate_to: host-repo/AGENTS.md
---

# Node Intake

Use this skill at the start of a session when a repository uses node-based task tracking.

> **Scope:** This skill is subordinate to `AGENTS.md`. If any step here conflicts with `AGENTS.md` or `governance/agent-constitution.md`, those files take precedence.

## Input

- The current repository.
- The current working tree state.
- The user's immediate goal.
- The current Task Contract when the pre-task flow produced one.

## Steps

0. **ACTIVE_EDIT_OWNERSHIP lock check (binary, mandatory first):** Read `.agents/ACTIVE_EDIT_OWNERSHIP.md`. Check the `## Current Ownership` section only (not History).
   - If the section contains anything other than `None` (case-insensitive, trim whitespace): stop immediately.
     ```
     🛑 ACTIVE_EDIT_OWNERSHIP.md shows an unreleased lock: [paste Current Ownership content] | Needs your decision: wait for that session to release, or confirm the entry is stale and clear it manually.
     ```
   - If `None`: proceed.
   - **Format compliance note:** if the History section contains an `[active]` entry with no matching `[released]` line, but Current Ownership says `None` — report it as a format gap (`⚠ History has unclosed active entry for [owner] — format violation, not a hard stop; verify manually`) and continue. The authoritative field is `## Current Ownership`.

1. Read `README.md`.
2. Read `NODE_QUEUE.md`.
3. Read `governance/agent-constitution.md` (if the project uses a `governance/` directory).
4. Read `governance/project-status.md` (if present).
5. Read relevant `governance/decisions/*.md` files if the queue references them.
6. Inspect `git status --short` and identify any untracked, deleted, or unrelated files.
   Classify every changed path into one of the five AGENTS.md Worktree Noise
   Control buckets: `active work` / `candidate work` / `residual noise` /
   `local-only` / `none`. Use these exact labels in the triage report —
   not ad-hoc descriptions.
   - **Skills-lock missing-skill check (mandatory if lock exists):** if `.agents/skills-lock.json` exists, scan for any entry with `"source": "missing"`. If found:
     ```
     🛑 skills-lock.json has source=missing entries: [list skill names] | Needs your decision: Restore the skill file(s) or remove their skills-lock entries before continuing.
     ```
     Do not proceed until resolved. A missing skill that is referenced in AGENTS.md is a governance integrity failure, not a routine worktree gap.
   - **Optional skills-lock hash check:** if `.agents/skills/` contains files modified since the last commit (`git diff HEAD -- .agents/skills/`), run `powershell -ExecutionPolicy Bypass -File .\.agents\scripts\validate_skills_lock.ps1`. A hash mismatch is a stop signal unless this session is explicitly reviewing or publishing a skill change.
   - **Template drift check:** Run `git log -1 --format=%H -- AGENTS.md` and `git log -1 --format=%H -- new-project-template/AGENTS.md (skip if project has no new-project-template/)`. If the two hashes differ, add to the triage report:
     ```
     ⚠ Template drift: AGENTS.md last changed at [hash1], template file last changed at [hash2]. Sync before closing or add a defer note to HANDOVER.md.
     ```
     Visibility flag only — not a hard stop. Skip if this session is about to modify AGENTS.md itself (sync check moves to session-close).
7. Compare the worktree to the queue. Handle the following cases explicitly — each has a defined stop format, not a judgment call:
   - **No ACTIVE node in NODE_QUEUE.md:** Stop immediately. Do not auto-promote ARMED to ACTIVE. Do not infer the "most logical" next node.
     ```
     🛑 No ACTIVE node in NODE_QUEUE.md | Needs your decision: Which node should be activated, or should we promote one from ARMED?
     ```
   - **Two or more ACTIVE nodes:** This is a queue integrity error.
     ```
     🛑 Multiple ACTIVE nodes found: [list them] | Needs your decision: Which one is the real active node?
     ```
   - **HANDOVER head commit diverges from git:** Compare the `Head commit:` field in `HANDOVER.md` against `git log --oneline -1`. If they differ:
     - **Session-close lag (self-healing):** If HEAD is exactly 1 commit ahead of HANDOVER's value AND that commit's message begins with `chore(session-close):` — this is a known design artifact (session-close cannot record its own hash). Silently advance HANDOVER's `Head commit:` to the current HEAD and continue. No stop required.
     - **All other divergences:** Report the mismatch before selecting any node.
     ```
     🛑 HANDOVER head commit [X] does not match git log [Y] | Needs your decision: Is HANDOVER stale, or is the local repo ahead/behind?
     ```
   - **HANDOVER inline COMPLETE claims:** For any line in `HANDOVER.md` matching `COMPLETE (<hash>)`, run `git cat-file -e <hash>` (read-only). If the hash does not exist in local git history:
     ```
     🛑 HANDOVER claims COMPLETE (<hash>) for [node] but hash not found in git | Needs your decision: Is this a stale claim or a missing commit?
     ```
     Do not proceed until the user resolves the discrepancy.
   - **Worktree clean and exactly one ACTIVE node:** Confirm the node to the user, then stop. This skill ends at selection — execution begins only after explicit user confirmation.
   - **Unexplained worktree changes:** Stop and triage before selecting a node.
8. If the queue and worktree disagree in any way not covered above, do not guess. Surface the mismatch first.

### Task Contract Consumption

`node-intake` remains responsible for repository, queue, ownership, and worktree
truth. It does not own semantic task compilation.

When a compact or gated Task Contract exists:

- compare dirty and proposed paths with contract `scope` and `non_scope`;
- confirm each `permissions_required` item needed for intake is satisfied;
- stop if the contract requires gated execution but no approved plan-freeze exists;
- stop and request a new contract version if repo evidence changes scope,
  permissions, invariants, or acceptance evidence;
- never let an adapter or intake finding silently add files to contract scope.

## Validation

- The chosen node must not conflict with any unexplained worktree change.
- If the worktree and queue disagree materially, report `insufficient evidence`.

## Output

- Current repo state.
- Whether `NODE_QUEUE.md` is safe to follow now.
- The safest next action.
- **Bootstrap-score line (mandatory):** Output exactly one line in this format after reading canonical sources:
  `bootstrap-score: [N]/[total] | active node: [node-id or none] | mode: [code/analytical] | gaps: [list or none]`
  This line must appear in the response — it is the observable artifact that proves bootstrap completed. Without it, the next session cannot tell if startup was partial.
- **ACTIVE_EDIT_OWNERSHIP.md write (mandatory if any shared protocol file will change):** Shared protocol files: `AGENTS.md`, `AI_BOOTSTRAP.md`, `HANDOVER.md`, `NODE_QUEUE.md`, `.agents/skills/*`, `.agents/protocols/*`. Write the lock entry **before** any file is opened for editing — including before plan-freeze output. For CONTINUOUS sessions this step is especially critical because plan-freeze may be omitted entirely. Append to `.agents/ACTIVE_EDIT_OWNERSHIP.md` under `## Current Ownership`:
  ```
  [YYYY-MM-DD HH:MM UTC] owner=ClaudeCode/<session-label> files="<file list>" purpose="<active node id> — <one-line description>" release="At session-close or upon explicit user instruction."
  ```
  Omission is worse than duplication — if plan-freeze also writes an entry, session-close will clean it up.

**When a hard stop fires:** append a `stop_event` entry to `.agents/session_log.jsonl` **before waiting for user response**. Use this exact PowerShell template:
```powershell
$adapter = Get-Content .control-plane/adapter.json -Raw | ConvertFrom-Json
$writer = Join-Path $adapter.controlPlaneRepo "state/write_session_event.ps1"
powershell -ExecutionPolicy Bypass -File $writer -EventType stop_event -SessionId "<session-label>" -StopCondition "<exact rule text from AGENTS.md>" -Reason "<one sentence: what the AI was about to do>" -Resolution fired_awaiting_user
```
Set `resolution: "resumed_by_user"` or `"bypassed_by_user"` once the user responds. Without this entry the hard-stop is invisible to all future sessions and tools.

## Stop conditions

- **Untracked skill file — binary block:** If `git status --short` contains any line matching `?? .agents/skills/` — regardless of skills-lock state — stop immediately. This is not a worktree triage judgment call.
  ```
  🛑 Untracked skill file(s) found: [paths] | Needs your decision: commit or delete each before proceeding.
  ```
  A `??` SKILL.md is permanently lost if the session ends without committing it. Do not proceed until the user resolves each file.
- Do not advance to implementation if `git status --short` contains untracked or modified files with non-code extensions (`.pdf`, `.docx`, `.html`, `.jpeg`, `.jpg`, `.png`, `build_*.py`) that cannot be explained by the active node or a prior HANDOVER session entry. Presence of any such unexplained file is a binary block, not a judgment call about whether the worktree is "understood."
- Do not guess which changes belong to which agent.
- Do not treat NODE_QUEUE.md as higher priority than unresolved worktree evidence.
- Do not begin executing the selected node without explicit user confirmation — this skill ends at selection, not execution.

## 已知失败路径

- **HANDOVER 与代码不一致**（HANDOVER 写「已完成」但无对应 commit hash）→ 以代码为准，更新 HANDOVER，不执行 NODE_QUEUE 里的节点直到两者一致。
- **NODE_QUEUE 有 ACTIVE 节点但 worktree 有无法解释的改动** → 不选下一节点，先上报 worktree 状态，等待用户判断。
- **多个文档声称「当前状态」但互相冲突**（README vs HANDOVER vs project-status）→ 优先级：代码 > HANDOVER SNAPSHOT > NODE_QUEUE > README；上报冲突，不猜测。
- **读完所有文档后仍不确定 active 节点** → 报告 `insufficient evidence`，不推断，不继续执行。
- **AI 未经授权节点创建了 skill 文件** → 该文件是 untracked 状态，git 不追踪，session 异常结束即永久丢失。发现时立即归入 `residual noise`，提示用户 commit-or-delete，不继续执行其他工作。

## Session Close

本 session 结束前，运行 `session-close` skill。
