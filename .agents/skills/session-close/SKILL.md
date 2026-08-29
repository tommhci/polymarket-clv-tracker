---
name: session-close
description: "End-of-session checklist: update HANDOVER SNAPSHOT, record any AI corrections as 不做 clauses, and confirm the repo is in a clean handover state."
last_verified: 2026-06-27
verified_against: AGENTS.md@2ee14b5
subordinate_to: host-repo/AGENTS.md
---

# Session Close

Run this skill at the end of every session, regardless of task type.

## 触发信号（由 LLM 识别，非代码检测）

这个 skill 没有自动触发机制。它依赖用户说出结束信号，AI 据此执行。

中文触发词示例：「今天到这」「我们结束」「session 结束」「下次继续」「我去休息了」「wrap up」

英文触发词示例：「let's wrap up」「closing for today」「end of session」「that's it for now」

**不触发的情况：** 「我要开一个新 session 来做 X」是计划声明，不是结束信号——AI 不应自动执行 session-close。

**CONTINUOUS 模式强制触发：** 如果当前 session 在 CONTINUOUS 模式下
修改了文件或运行了代码，AI 必须在输出"任务完成"之前主动执行本 skill，
不等待用户的结束信号。这与用户触发的路径并行，不互相替代。

**CONTINUOUS hard-stop 路径：** 若 CONTINUOUS session 因 hard-stop 中止（输出 🛑 而非"任务完成"），且该 session 已修改文件，则在 hard-stop 解决后用户的第一次回应时立即运行本 skill——优先于所有其他任务。不等待下一个 session-close 触发信号。

**auto-compact ≠ session 结束：** Claude Code 在上下文接近限制时会自动 compact（压缩早期对话为摘要，保留最近文件）。这是 session 内部事件，不触发 session-close。

## Input

- The work done in this session.
- Whether the AI was corrected at any point.

## Steps

**先判断 session 类型（这决定哪些步骤适用）：**

**Binary detection (mandatory — do not rely on AI judgment):** Run `git diff HEAD --name-only`.
- Output **non-empty** → **代码型 session** → 全部步骤
- Output **empty** → **分析型 session** → 步骤 2/4/5/6/7

Do not override this with "but we only changed docs" or "it was mainly analytical" — the git diff is the ground truth. Edge case: if the only changed file is HANDOVER.md itself (written during session-close), treat as 分析型.

---

### 代码型 session 步骤

1. Update `HANDOVER.md` SNAPSHOT block:
   - `Last updated:` → today's date + session label
   - `Tests:` → run the project verification command (check `.control-plane/verification.json` for `verificationCommand`; if absent, `npm test` for Node projects or leave blank) and record pass count
   - `Head commit:` → run `git log --oneline -1` and record hash + message
2. Ask: "Was the AI corrected at least once this session?"
   - **Yes** → write the correction as a `不做` clause in NODE_QUEUE.md or `the project archive file (see `HANDOVER.md` for the active archive path)` `## DEAD ENDS`. One sentence: what was wrong + what the right behavior is.
   - **No** → skip.
3. Confirm ACTIVE NODE status in NODE_QUEUE.md is accurate.
4. Confirm no untracked sensitive files (`git status --short`).
4b. **Dirty-worktree gate (hard stop, added 2026-08-23 / U2):** If
    `git status --short` (excluding the two files this skill itself writes —
    HANDOVER.md and `.agents/skills/EFFECTIVENESS_LOG.md` — and excluding
    files already staged for this session's final commit) is non-empty, this
    is a hard stop. A session that ends with uncommitted verified work
    re-creates the exact failure the 2026-08-11 audit-landing gap was about
    (13 days, 95 lines sitting uncommitted).
    - The ONLY escape is a DEFERRED record: write one line to HANDOVER.md
      `## DEFERRED` with a date, a one-sentence reason, and a deadline.
    - No DEFERRED record → do not release ownership, do not close.
    - This is the mandatory enforcement layer for the "uncommitted work has
      zero protection" principle; it is intentionally rigid because the
      failure it prevents recurs (see AGENTS.md "Uncommitted Work Has Zero
      Protection" section in host repos that carry it).
4c. **Unpushed-commits gate (hard stop, added 2026-08-23 / U2 extension):** If
    a tracking remote exists for the current branch and
    `git log <remote>/<branch>..HEAD --oneline` is non-empty (commits exist
    locally but not on the remote), this is a hard stop. Unpushed commits are
    the same class of failure as uncommitted work: they live only in one
    worktree and are invisible to every other session and tool — the
    2026-08-23 backlog-clearance re-verified this live when 5 commits
    (c16a827..c276e9e) sat `ahead 5` on `main` for an entire session while
    the remote stayed at c692ddd, and the owner had to push manually.
    - Same escape as 4b: a dated DEFERRED record in HANDOVER.md `## DEFERRED`
      with a deadline for the push.
    - No DEFERRED record → do not release ownership, do not close.
    - Push requires explicit owner authorization ("Never push without
      explicit owner authorization" per AGENTS.md); the gate fires only when
      the session ends with the owner un-informed of the unpushed state.
5. **localStorage capacity check** (browser-app specific — skip if not a browser UI project):
   ```js
   JSON.stringify(localStorage).length / 1024 / 1024
   ```
   - Result < 3 MB → OK, no action.
   - Result ≥ 3 MB → add one line to HANDOVER VOLATILE STATE: `⚠️ localStorage [X.X MB] — approaching limit. Review before next QuickCapture sprint.`
   - Result ≥ 4.5 MB → escalate: add to HANDOVER OPEN QUESTIONS as blocking risk.
5b. **Incident classification check:** Did any hard-stop fire this session?
    - Yes → label the EFFECTIVENESS_LOG entry header as `incident=yes`,
      record stop count, which `stop_condition` triggered, and evidence
      quality: `specification-only` / `behavioral-observed` /
      `behavioral-repeated`.
    - No → proceed to step 6.
    **stop_event coverage scan (mandatory — SQLite-first, JSONL fallback):**
    Primary path (SQLite — use if `.agents/state.db` exists):
    ```powershell
    $adapter = Get-Content .control-plane/adapter.json -Raw | ConvertFrom-Json
    $q = Join-Path $adapter.controlPlaneRepo "state/sqlite/query_control_plane_state.ps1"
    if (Test-Path .agents/state.db) {
      & $q -DatabasePath .agents/state.db | ConvertFrom-Json | Select-Object -ExpandProperty recent_stop_events -ErrorAction SilentlyContinue | Select-Object -Last 5
    } else {
      Select-String -Path .agents/session_log.jsonl -Pattern '"event_type":\s*"stop_event"' | Select-Object -Last 5
    }
    ```
    Fallback path (JSONL — use only if no `.agents/state.db`):
    ```powershell
    Select-String -Path .agents/session_log.jsonl -Pattern '"event_type":\s*"stop_event"' | Select-Object -Last 5
    ```
    Count entries added since this session started. If a hard-stop fired this session but no matching `stop_event` entry exists, append one now using this exact template:
    ```powershell
    $adapter = Get-Content .control-plane/adapter.json -Raw | ConvertFrom-Json
    $writer = Join-Path $adapter.controlPlaneRepo "state/write_session_event.ps1"
    powershell -ExecutionPolicy Bypass -File $writer -EventType stop_event -SessionId "<session-label>" -StopCondition "<exact rule text from AGENTS.md>" -Reason "<one sentence: what the AI was about to do>" -Resolution "<fired_awaiting_user|resumed_by_user|bypassed_by_user>"
    ```
    Do not close without this entry — an unlogged hard-stop is invisible to all future sessions and tools.
    Background: Compliance Gap (arXiv:2605.01771, 2026-05) found 0% compliance with in-flight file-write instructions under default conditions. Session-close is the mandatory catch point for stop_event entries missed during the hard-stop itself.
6. **Write a run-entry to `EFFECTIVENESS_LOG.md`** (observable facts only — no judgment, no self-assessment):
   ```
   ## [run=YYYY-MM-DD-NN | task=<node-id or "analytical"> | session_type=<product|governance|analytical>]
   Files modified: <output of `git diff --name-only HEAD`>
   Test outcome: <verification command exit 0 / exit 1 / not run>
   Rules cited: <AGENTS.md sections or rule IDs explicitly named in tool calls or AI reasoning this session — leave blank if none observed>
   Trend: first / repeat / regressed
   Human overhead: low / medium / high
   real_use_task: yes / no  (yes = task involved actual product use or user-facing validation; no = infra/meta/governance only)
   deferred_decision_id: <NODE_PROPOSALS entry ID or "none">  (any decision deferred to NODE_PROPOSALS this session)
   meta_work_streak: <N>  (count consecutive sessions with real_use_task=no, including this one; reset to 0 on real_use_task=yes)
   ```
   **Meta-work streak rule:** if `meta_work_streak` reaches 3, the NEXT session must begin with a meta-vs-real-work classification (see host-repo governance for the specific guard this feeds). Do not auto-block — only flag. Record the streak count so the guard has an observable trigger.

   **Streak counter procedure:**
   ```powershell
   # Count consecutive real_use_task=no entries at the end of EFFECTIVENESS_LOG
   $entries = Select-String -Path .agents/skills/EFFECTIVENESS_LOG.md -Pattern 'real_use_task: no'
   # Manual count: look at the last N run-entries and count trailing 'real_use_task: no'
   # The streak resets at the first 'real_use_task: yes' run-entry encountered going backwards.
   ```
   - `Files modified`: mechanical — from `git diff`, no interpretation.
   - `Rules cited`: mechanical — scan own tool calls and reasoning for explicit references to rule names or file sections. **Do not infer.** If none observed, write `none observed`.
   - `Trend`: `first` = first time this task type ran; `repeat` = same task type ran before; `regressed` = same task type ran before and something got worse.
   - `Human overhead`: `low` = AI executed without intervention; `medium` = 1-2 corrections or redirections; `high` = 3+ corrections, major mid-task pivot, or scope change.
   - `session_type` classification (binary, use these exact labels):
     - `product` → `git diff HEAD --name-only` contains any source file AND the verification command was run
     - `governance` → changed files are only in `AGENTS.md`, `AI_BOOTSTRAP.md`, `.agents/`, `governance/`, `new-project-template/` — no `src/` files
     - `analytical` → `git diff HEAD --name-only` is empty or HANDOVER.md only
   - **Purpose of this entry**: feeds periodic protocol review — raw observable facts that will be analyzed to identify silent rules and write patterns back to AGENTS.md/CLAUDE.md.
   - **Cadence counter:** the host repo's protocol-review skill reads `session_type=product` count to enforce its own review cadence. Omitting this field breaks the counter — do not skip it.
6b. **State-drift check (mandatory for analytical and governance sessions):** Before closing, scan the HANDOVER SNAPSHOT and any session output for the following substitutions. Each is a protocol violation, not a style preference:

   | Forbidden substitution | Why it matters |
   |------------------------|----------------|
   | [Inference] written as [Fact] without a new source | Upgrades an unverified claim to ground truth |
   | [Assumption] written as [Fact] | Same — assumption becomes load-bearing without evidence |
   | `CANDIDATE` node written as `ACTIVE` | Creates a false authorization signal in NODE_QUEUE |
   | `pending` written as `verified` | Claims validation occurred when it did not |
   | The operator's decision replaced by AI inference | Cognitive authority violation — see host-repo governance for the specific rule |
   | `insufficient evidence` replaced by confident assertion | Eliminates the explicit gap marker |

   **Check procedure (lightweight):**
   1. Read the current HANDOVER SNAPSHOT section you are about to commit.
   2. For each row in the table above, scan for the substitution pattern.
   3. If found → mark the substitution as `[STATE-DRIFT: type]` in the HANDOVER draft, do NOT commit until corrected.
   4. If none found → proceed to step 7.

   This check is **skill-side** (semantic), not scanner-side (pattern). The scanner can detect token presence; only you can detect meaning substitution.

7. Check: did any AI collaboration behavior in this session reveal something about the protocol itself (a constraint that failed, a skill that misfired, a gap that was discovered)? If yes → add to HANDOVER `## PROTOCOL LEARNINGS` block (one bullet per observation, with trigger condition).
   **Friction sub-check (three questions, answer each yes/no):**
   - **Intervention:** Did you interrupt or redirect the AI mid-task? If yes → one line: what triggered it + what Stop Condition was missing.
   - **Context Miss:** Did the AI produce wrong output because it hadn't read a file? If yes → one line: which file was missing + which bootstrap or node-intake step should have caught it.
   - **Tool Friction:** Did you end up doing work in the wrong tool? If yes → one line: what task + what tool would have been faster.
   Any "yes" → add to `## PROTOCOL LEARNINGS` with tag `[Intervention]` / `[ContextMiss]` / `[ToolFriction]`.
   **Promotion scan (mandatory, run after friction sub-check):** Run:
   ```powershell
   $lines = Select-String -Path .agents/skills/EFFECTIVENESS_LOG.md -Pattern 'outcome=(wrong-trigger|unsafe)' | ForEach-Object { ($_.Line -split 'skill=')[1] -split '\s' | Select-Object -First 1 }
   $lines | Group-Object | Where-Object { $_.Count -ge 2 } | Select-Object Name, Count
   ```
   If any skill appears ≥2 times with `wrong-trigger` or `unsafe` outcome, add to PROTOCOL LEARNINGS:
   `[PromotionCandidate] skill=<name> — appeared <N> times with outcome=wrong-trigger/unsafe. Review for Experience Promotion Rule eligibility.`
   Do not auto-promote — flag only. Flagging is mandatory even if no other PROTOCOL LEARNINGS entry is written.
8. Check: did any skill clearly help, fail to trigger, trigger incorrectly, or introduce unsafe / drifting behavior? If yes → add one line to `.agents/skills/EFFECTIVENESS_LOG.md` using the **skill-outcome format** (distinct from the run-entry above).
9. Release any active entry in `.agents/ACTIVE_EDIT_OWNERSHIP.md`. If plan-freeze wrote a lock entry at the start of this session, write the release line now. If no entry was written (missed step), note it explicitly in the EFFECTIVENESS_LOG run-entry as `ownership_write=missed`.
10. Commit HANDOVER update if any changes were made to it.
10b. **Status-co-push rule (added 2026-08-23 / U3; simplified 2026-08-28):** If
     `PROJECT_STATUS.md` exists in this repo and this session's work is
     recorded there (a node, finding, or verdict), the PROJECT_STATUS.md
     update MUST land in the SAME PUSH as the work it describes — same
     commit preferred, but the rule is satisfied by any combination that
     reaches the remote together (e.g. work commit + a separate status
     commit pushed in one `git push`). What the rule forbids is landing the
     work and leaving its status update unpushed or unwritten at session
     close — that gap is exactly the 13-day 95-line failure the U2 gates
     exist to prevent. If PROJECT_STATUS.md is not touched this session,
     verify no previously-recorded status line has gone stale and correct
     it now (same push).
10c. **Report-plan mapping rule (added 2026-08-23 / U1 report-layer mirror):**
    If this session had a defined plan (a plan-freeze, an authorized multi-step
    task list, or a node with explicit phases), the session-end report MUST
    map every plan item to exactly one outcome line: a commit SHA, a
    DEFERRED record with date+reason+deadline, or a REJECTED/WON'T-DO note
    with reason. A report with missing items is INVALID — the work may be
    done and committed, but the report's silence re-creates the exact
    "executed but reported missing" failure the 2026-08-23 closeout exposed
    (a verification pass concluded phases 3/4 were absent because the report
    did not 1:1 map them). Analytical sessions without a defined plan are
    exempt (map to "analytical — no plan items").

### 分析型 session 步骤

1. Update `the project archive file (see `HANDOVER.md` for the active archive path)` `## ANALYTICAL STATE (T-04 format)`:
   - Goal / Verified facts / Working assumptions / Open questions / Next action
   - Do not regrow the root `HANDOVER.md`; keep long-form analytical state in the archive file.
2. Record **Contribution Mode** in the archived ANALYTICAL STATE:
   - `Amplification`：the operator generated the frame / first pass / challenge; AI executed or critiqued
   - `Delegation`：AI generated the frame; the operator accepted without independent assessment
   - `Mixed`：both patterns present
   One sentence of evidence for the choice.
3. **Write a run-entry to `EFFECTIVENESS_LOG.md`** (observable facts only):
   ```
   ## [run=YYYY-MM-DD-NN | task=analytical | topic=<one-word label> | session_type=analytical]
   Files modified: <git diff --name-only HEAD, or "none">
   Frameworks or external sources cited: <arXiv IDs or named frameworks explicitly referenced this session>
   Rules cited: <AGENTS.md sections or rule IDs explicitly named in reasoning — leave blank if none observed>
   Trend: first / repeat / regressed
   Human overhead: low / medium / high
   ```
   For analytical sessions, `Files modified` will usually be `none` or only docs files; that is expected and informative.
   `Human overhead`: `low` = session ran to plan without redirects; `medium` = 1-2 corrections or pivots; `high` = 3+ redirections or major scope change mid-session.
4. Ask: "Was any AI collaboration failure mode observed this session?" If yes → add to `## PROTOCOL LEARNINGS`.
   **Friction sub-check (three questions, answer each yes/no):**
   - **Intervention:** Did you interrupt or redirect the AI mid-task? If yes → one line: what triggered it + what Stop Condition was missing.
   - **Context Miss:** Did the AI produce wrong output because it hadn't read a file? If yes → one line: which file was missing + which bootstrap or node-intake step should have caught it.
   - **Tool Friction:** Did you end up doing work in the wrong tool (cost more time than if you'd switched)? If yes → one line: what task + what tool would have been faster.
   Any "yes" → add the one-liner to `## PROTOCOL LEARNINGS` with tag `[Intervention]` / `[ContextMiss]` / `[ToolFriction]`.
5. Check: did any skill clearly help, fail to trigger, trigger incorrectly, or introduce unsafe / drifting behavior? If yes → add one line to `.agents/skills/EFFECTIVENESS_LOG.md` using the **skill-outcome format**.
6. Release any active entry in `.agents/ACTIVE_EDIT_OWNERSHIP.md`, or explain why it remains active.
7. **Untracked skill file check (mandatory):** Run `git status --short | grep "?? .agents/skills/"`. If any result appears:
   - These are SKILL.md files that exist in the worktree but have never been committed.
   - For each one, the user must choose before session-close completes:
     - **Commit** → stage and include in the session's final commit.
     - **Abandon** → delete the file and remove its entry from `skills-lock.json`.
   - No third option. An untracked skill file that survives session-close will be invisible to git and will be lost when the worktree is cleaned.
   ```
   ⚠ Untracked skill file(s) found: [list paths] | Choose for each: commit or abandon?
   ```
8. Confirm no other untracked sensitive files (`git status --short`).
9. Commit HANDOVER update (requires explicit user confirmation before committing).

## MACHINE STATE block (machine-readable recovery)

When a session changes files or runs code, the handover must carry a `MACHINE STATE`
block above the human narrative, so the next session can route without re-reading the
transcript. The block uses the recovery tuple (see control-plane
`protocols/failure-recovery-flow.md` and `session_state.schema.json` `task_control`):

```text
## MACHINE STATE
task_state: <READY|IN_PROGRESS|NEEDS_REVIEW|REVIEW_FAILED|VALIDATION_FAILED|PARTIAL_SUCCESS|SKIPPED|DONE|NEEDS_HUMAN|HARD_STOP>
failure_class: <NONE|OWNERSHIP_CONFLICT|PRECHECK_FAILED|VALIDATION_FAILED|MISSING_INFO|UNKNOWN_OOD|SCOPE_DRIFT|ENVIRONMENT_ERROR|USER_DECISION_REQUIRED>
reviewer_trigger: <NONE|GOVERNANCE_FILE_CHANGE|SKILL_OR_PROTOCOL_CHANGE|...>
next_allowed_action: <one concrete action>
disallowed_actions: [<action>, ...]
touched_files: [<path>, ...]
commands_run: [<cmd>, ...]
validation_result: <PASS|FAIL|NOT RUN>
evidence_pointers: [<commit hash | file:line>, ...]

## HUMAN CONTEXT
<freeform explanation — the existing SNAPSHOT / narrative goes here>
```

- `MACHINE STATE` is for routing; `HUMAN CONTEXT` is for explanation. Freeform handover
  is still allowed below `HUMAN CONTEXT`.
- This is additive: the existing SNAPSHOT block satisfies `HUMAN CONTEXT`.

### DONE hardening rule

`task_state: DONE` may be recorded **only** when all of the following hold. If any
fails, use `PARTIAL_SUCCESS`, `SKIPPED`, or `NEEDS_REVIEW` instead — never DONE:

- acceptance criteria met (`acceptance_criteria_met: true`)
- `validation_result: PASS`
- `touched_files` listed if any files changed
- `ownership_conflict: none`
- `open_blockers: []`
- `reviewer_required_but_skipped: false`

`PARTIAL_SUCCESS` and `SKIPPED` are distinct from `DONE` and must not be relabeled as
DONE at session-close.

### Task Contract Telemetry

When the session used a compact or gated Task Contract, record only observed
contract outcomes in the effectiveness or handover surface already used by the
client repository:

- `contract_drift`: scope, non-scope, permissions, invariants, or acceptance
  evidence changed after approval;
- `false_escalation`: a task was gated but direct evidence showed compact or
  pass-through handling was sufficient;
- `missed_escalation`: execution began without a required forced escalation;
- `wrong_adapter`: the selected adapter did not match the actual task domain;
- `fact_hypothesis_contamination`: a hypothesis was treated as an observed fact
  or user-approved invariant.

Use `not observed` when none occurred. Do not infer successful classification
from silence, and do not claim behavioral effectiveness from replay fixtures.
If drift changed authorization or scope, the session must identify the new
`contract_version` or report that execution stopped before the drifted work.

## Output

- Updated HANDOVER SNAPSHOT (commit hash, date, test count).
- One-line note on what 不做 clause was added (or "no corrections this session").

## Stop conditions

- Do not start new implementation work inside this skill.
- Do not commit HANDOVER or log updates without explicit user confirmation.
- Do not skip the SNAPSHOT update even if "nothing changed."
- Do not skip step 2 — recording corrections is the only mechanism that feeds skill improvement over time.

## 已知失败路径

- **「这次 session 没有重要的东西要记录」** → 这是错误判断；SNAPSHOT 必须更新，哪怕只是日期。SNAPSHOT 是新 agent 判断 HANDOVER 新鲜度的唯一客观信号。
- **有改动但没有 commit HANDOVER** → 下一个 agent 读到的是旧状态，产生文档漂移。
- **步骤 2 被跳过因为「纠正太小了不值得记录」** → 小的纠正累积成模式；记录它，即使只有一句话。
