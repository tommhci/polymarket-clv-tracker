# Project Guidance

## Output Language Boundary (always active)

The user understands **Chinese and English only**.

All user-facing and next-agent-facing output MUST be written in Chinese or English. This includes: main replies, status updates, stop_event messages, classifier explanations, hook outputs, subagent summaries, handoff packets, validation logs, and commit/checkpoint summaries.

Korean, Japanese, or any other language is **forbidden** unless:
1. The user explicitly requests that language, or
2. The text is a verbatim quoted source that must remain unchanged.

If any upstream tool, script, agent, hook, or template emits non-Chinese/non-English text, **translate it before presenting to the user**.

This rule applies to all execution modes (STEP, CONTINUOUS, AUDIT) and all agent types (main, subagent, classifier, hook).

---

## Executable Instruction Boundary (always active)

Whenever an AI tool concludes that a step must be performed by the human user rather than the AI itself (a governance-approval script, a GUI action in VS Code/OS settings, anything requiring the user's own terminal or mouse), the response MUST include the complete, copy-pasteable command(s) or exact step sequence for the user's real environment — working directory, exact flags, and what success/failure output looks like. Do not describe the action in the abstract ("you need to run the approval script," "you need to clear Recent Workspaces") and stop there; assume the user does not already know the tool, flag, path, or UI location.

When the step is a decision rather than a mechanical action (choosing between approaches), the same principle applies to judgment: give a complete enough comparison that the user can decide without first doing their own research — don't assume they'll fill the gap themselves.

Never state that something has been recorded, remembered, saved, or completed unless the corresponding write/action actually happened in that same turn. State it after doing it, not as a promise of doing it.

当 AI 工具判断某一步必须由用户本人执行（治理审批脚本、VS Code/系统设置里的 GUI 操作、任何需要用户自己终端或鼠标的动作）时，回复中**必须**包含针对用户真实环境的完整、可直接复制执行的命令或精确步骤序列——包括工作目录、确切参数、以及成功/失败时分别会看到什么输出。不能只抽象描述这个动作（"你需要跑批准脚本""你需要清理 Recent Workspaces"）就停在那里；默认用户不知道具体工具、参数、路径或界面位置。

当这一步是决策而非机械操作时（在几个方案之间选择），同样的原则适用于判断本身：给出足够完整的对比，让用户不需要自己先做调研就能决定——不能假设用户会自己补全这个空白。

除非对应的写入/动作**在同一轮回复中真的已经执行**，否则不要说"已经记下来了""已保存""已完成"。要先做完，再陈述完成，而不是把陈述当承诺。

---

## Session Quality Layer (AIS — always active)

These four constraints apply to every response in this project, regardless of task type:

① **Judgment before evidence** — lead with the core finding; evidence follows.
② **Distinguish [Fact] / [Inference] / [Assumption]** — never conflate the three.
③ **Flag gaps directly** — never substitute vague language for an honest gap marker.
④ **Frame core claims as open questions, not closed assertions** — especially under uncertainty.

When evaluating workflow design, governance decisions, or skill architecture: map against known AI collaboration failure modes before recommending. Do not fill evidentiary gaps with plausible-sounding inference.

**Citation Integrity (always active):**
- Every external claim must include arXiv ID or DOI + date. No ID = cannot be independently verified = treat as [Insufficient evidence].
- Citations from another AI tool or session must be traced back to the original source before use. Second-hand summaries are [Inference — unverified], not [Fact].
- Non-peer-reviewed sources (industry blogs, vendor docs, company engineering posts) are valid evidence but must be explicitly labeled and downgraded one level: [Inference — vendor self-report] or [Inference — industry blog, not peer-reviewed].
- Disclose structural conflict of interest: if the AI running the check is itself a product of the vendor being cited, flag it as [COI — vendor source].

**D7/D9 guard (always active, lightweight):**
- 连续的 meta/基础设施 session（无真实使用验证）不再触发停机判定；它们在 session close 时记录一次 D7 转化结果：`Pattern Converted`、`Artifact Fragment Converted` 或 `No Conversion`。
- 关闭时只问：这次 reflective / analytical / meta session 转化成了什么？若没有可复用对象，记录 `NO_CONVERSION` 并结束。`No Conversion` 是中性证据，不是失败标签。
- D7 不得询问用户是否在逃避、拖延或循环，不得默认阻断分析工作，也不得扩展成新的 scoring / taxonomy / hook。D9（Challenge 输入先复述确认再执行）的判定过程仍留在 `strategic-alignment` skill 与 `AIS_charter.md`。

---

## Experience Promotion Rule

Platform memory is the fast-landing layer — session learnings go there first. Repo files are the stable layer — cross-tool and cross-session.

**Promote a memory entry into a repo file when all three are true:**
1. The same pattern appeared in 2+ sessions (not a one-off). Exception: behavioral evidence from `collab-system-redteam` or `infrastructure-audit` that is clearly cross-tool applicable qualifies at 1 session — implicit exemptions are more dangerous than explicit rules.
2. The rule applies to any AI tool, not just the one that learned it.
3. Forgetting it would cost more than 10 minutes to re-derive.

**Where to promote:**

| What was learned | Promote into |
|-----------------|--------------|
| AI behavior / output format / mode rules | `AGENTS.md` |
| What to read and when | `AI_BOOTSTRAP.md` |
| Rejected approach + why + reopening condition | TODO: your archived-handover file's `## DEAD ENDS` section, or `HANDOVER.md` directly if you don't keep a separate archive |
| Architectural constraint that must survive tool switches | `governance/agent-constitution.md` |
| Reusable pattern for future projects | TODO: your own bootstrap-template repo, if you maintain one |

**Do not promote:** one-session fixes, project-specific state, anything that rots as the codebase evolves.

## Context Compression Resilience

Auto-compaction, forked threads, tool-private memory, and handoff prose are
lossy transport layers, not durable execution state. For any task that is
still in flight, the repo needs one small, explicit checkpoint surface that a
new session or a different AI tool can re-read without trusting a compressed
summary.

Use `ACTIVE_CONTEXT.md` whenever any of these are true:

- the task has already consumed more than 10 tool calls and is still unresolved
- more than about 10 minutes have been spent on one unresolved branch
- the work involves browser automation, multi-step runtime debugging, or repeated process/cache/selector probing
- the session is about to switch tools, switch models, switch worktrees, or hand unfinished work back to the human
- a compaction event already happened, or is likely to happen before the next clean milestone

Minimum contents of `ACTIVE_CONTEXT.md`:

- current objective
- scope freeze (which files are in-bounds)
- last verified facts
- open branch or decision point
- next action
- durable promotions pending

Resume rule:

- if `ACTIVE_CONTEXT.md` says `Status: active` or `Status: parked`, read it before trusting chat summaries, tool memory, or handoff prose

Release rule:

- when the task is done, reset `ACTIVE_CONTEXT.md` to a neutral state
- when the task is unfinished, leave one final parked checkpoint instead of a stale active claim
- never end a session with `ACTIVE_CONTEXT.md` still implying active execution unless the same session is truly continuing

## Protocol Review Loop

- Read `HANDOVER.md` `## PROTOCOL LEARNINGS` during Darwin checks and strategic-alignment reviews.
- If a learning appears in 2+ sessions or repeats across tool contexts, mark it as a promotion candidate.
- Promote the item into the stable file listed above, then leave a short note in `HANDOVER.md` that it was promoted.
- **Cadence trigger:** After every 3 real product sessions (not meta/infra sessions), run one Protocol Review: count D7 proximity (consecutive meta sessions), check EFFECTIVENESS_LOG for repeated patterns, apply the 4-step template (`Claim → Variables → Evidence → Conclusion → Reopen condition`) to one pending governance question. Do not run this review more than once per cadence cycle; extra attempts should be recorded as `No Conversion`, not escalated into a stop rule.
- **Cross-tool memory audit (mandatory at each Protocol Review):** Check whether any important learnings in tool-private memory (Claude memory, Codex workspace, Cursor rules, etc.) have not yet been promoted into repo files per the Promotion Rule above. If found, promote immediately or create a NODE_PROPOSALS entry. Tool-private memory that is not promoted is invisible to all other AI tools and will be lost on tool switch.

## Thin Watchlist

- Use this when a rule both records outcomes and changes behavior.
- Ask four checks before adding enforcement: does it only record, does it infer motive by default, can benefit be observed separately from enforcement, and does it have a clear sunset condition?
- If any check is unclear, keep the recording path and defer enforcement until behavioral evidence exists.
- If the same watch item repeats in 2+ sessions, promote it for review as a NODE_PROPOSALS candidate or skill only after the registry shows the pattern is reusable.

## Skill Layer

- Use `.agents/skills/README.md` as the route map for operational skills.
- **Invoke project skills by reading, not by tool:** `.agents/skills/` files must be read via `Read` and executed inline. The `Skill` tool routes to the platform-level plugin registry only — it does not load `.agents/skills/` files. Using the `Skill` tool for project skills silently fails or invokes the wrong handler.
- Prefer the narrowest matching skill, and treat skills as bounded procedures rather than parallel owners.
- **Default skill routing tie-breaker:** do not activate `feynman-perspective` and `learn-system` at the same time for one request. Choose one by intent: validation/critique → `feynman-perspective`; learning/encoding → `learn-system`. If a request has distinct phases, run them serially and keep `learning-patterns.md` as `learn-system` reference material.
- Do not load the whole skill directory unless the task is about workflow mechanics or the user explicitly asks about skills.
- Record material skill successes or failures in `.agents/skills/EFFECTIVENESS_LOG.md`; review patterns before changing skill behavior.
- **Skill creation requires an authorizing node:** A new `.agents/skills/*/SKILL.md` file may only be created when a CANDIDATE or ACTIVE node in `NODE_QUEUE.md` explicitly authorizes it. Informal creation without an authorizing node is not permitted — untracked skill files cannot be tracked by git and will be permanently lost if the session ends abnormally.
- All skills are subordinate to this file. If any skill instruction conflicts with `AGENTS.md`, `AGENTS.md` takes precedence.

## Execution Truth Before Causal Reasoning

**Trigger**: when reasoning-from-reading-the-code (or from any layer's stated/
inferred state) and observed-runtime-behavior disagree — code looks correct
but the app is blank/wrong; code looks buggy but tests pass; a subagent
reports success but the described behavior doesn't reproduce. Not UI-specific
— the same disagreement pattern applies across frontend runtime, backend
runtime, subagent execution, cache/proxy layers, dev servers, worktrees, and
tool/browser observations. Does not apply when there is already a specific
static error signal (a lint/build error naming an exact line) — go fix that
directly.

When triggered, verify in this order before allowing any causal attribution to
application code, UI design, backend logic, or architecture:

1. **Execution ground truth** — is the observed behavior actually coming from
   the current code, on the current branch/worktree, from the current process?
   Staleness can stack across layers simultaneously (browser HTTP cache,
   dev-server/build-tool module cache, and a stale background process can all
   be present at once — clearing one is not proof the others are clear).
   Check for more than one process bound to the same port before trusting a
   "fresh restart" (on Windows, IPv4 `0.0.0.0` and IPv6 `[::1]` can each bind
   a different process without a port-conflict error). This risk is highest
   right after a subagent has run shell commands in a shared/worktree
   directory — nothing guarantees its background processes are cleaned up
   when its turn ends. If this repo has a runtime/port-shadow check script,
   run it before the code-reading pass.
2. **Signal validity** — test/build passing is not proof the app runs
   correctly; open it. A subagent's own "completed / fixed / verified" report
   is not evidence either, especially with a capability-limited or
   classifier-unavailable warning attached — independently reproduce before
   trusting it. See the Subagent Verification Contract below.
3. Only after (1) and (2) are checked may the failure be attributed to
   application design, backend logic, or architecture.

Cheap checks (process/port inspection, diffing served content against source)
come before expensive ones (custom error boundaries, console/error-handler
patching) — inverting this order is itself the same failure pattern, just
about the debugger's own tool choice rather than the underlying bug.

### Failure Pattern Library

Reusable detection aids — not new approval gates.

- **Execution Shadowing** — a "fresh restart" doesn't change observed
  behavior. First action: check for multiple listeners/processes on the same
  port/resource before assuming the fix is wrong.
- **Signal-Reality Mismatch** — automated signals (tests/build/lint) are
  green but the described real-world behavior doesn't match. First action:
  reproduce the actual behavior directly before trusting either side.
- **False Completion Signal** — a subagent or prior session states
  "completed/fixed/verified" with no reproduction evidence attached. First
  action: apply the Subagent Verification Contract below before accepting it.
- **Spec Enforcement Drift** — a rule exists in a governance/protocol file
  but no behavioral evidence shows it was actually applied this session.
  First action: look for enforcement evidence (hook log, stop event), not
  just the rule's existence in a file.
- **Debug Order Inversion** — multiple rounds of re-reading/re-editing
  application code with no behavior change, before any environment/process
  check has been run. First action: stop and run the cheapest
  environment/runtime check available first.
- **Session Instruction Binding Drift** — a session's injected project
  instructions (CLAUDE.md/AGENTS.md content) are fixed to whichever
  directory the session started in and do not refresh mid-session. If work
  shifts to a sibling repo/worktree partway through, those originally-loaded
  instructions silently stay stale relative to where edits are actually
  happening. First action: when work moves to a different repo root than the
  one instructions were loaded from, explicitly re-read that repo's own
  AGENTS.md/governance files as the operative source for actions taken
  there — do not assume the session-start copy still applies.
- **Mid-Audit Model Switching** — switching the acting AI tool/model partway
  through a complex, multi-phase audit or investigation loses working
  context and continuity that a single continuous session would have kept.
  First action: for multi-stage diagnostic work, keep the same tool/model
  from start to finish, or do an explicit handoff carrying the full
  transcript/evidence ledger rather than assuming a fresh session can
  resume equivalently.
- **Mid-Branch Compaction Loss** — context compaction or a tool switch lands
  in the middle of a still-unresolved branch, and the next session assumes
  it remembers the eliminated paths, frozen scope, and exact next action.
  First action: update `ACTIVE_CONTEXT.md` before continuing the branch, so
  the checkpoint survives even if the chat transcript is compressed.
- **Unverified Confident Claim** — asserting how a framework/library
  behaves, what industry teams currently do, or what a tool's known
  limitations are, purely from training-data recall, when a live search
  could confirm or correct it before the user has to demand one. Repeated
  real instance (2026-07-05): correct technical pushback was given from
  reasoning alone multiple times in one session before the user forced a
  search each time — and the first correction attempt itself repeated the
  same error one level up, converging on the first search hit instead of
  comparing multiple independent sources (arXiv:2605.06717's "proactivity
  vs. autonomy" framing) before proposing a fix.
  First action: search when all three hold — (a) the claim is externally
  checkable, (b) confidence in it is not already high, (c) the answer
  would change a subsequent recommendation or action — and weigh at least
  two independent sources before proposing anything, not the first hit.
  Does not apply to claims fully verifiable from the local repo/codebase
  itself (reading a file, running a test), or to settled, stable facts
  where searching would itself be the over-retrieval failure mode this
  entry is trying to prevent.
  **Do not invent a parallel claim-tracking scheme here.** If you already
  maintain an external claim-tracking system (claim IDs, source-grade
  labeling, reopen conditions, a living status table), route claims there
  instead of building a project-local mini version of the same mechanism.
  TODO: name your claim-tracking system and its location here, or delete
  this note if you don't have one.
- Does not apply to any of the above when a specific static error (exact
  line, exact stack frame) already points at the fault — fix the named line.

### Subagent Verification Contract

Before accepting a subagent's (or a prior session's) "done" report as
sufficient to proceed, it should state — or you should independently
establish — the worktree path, branch name, exact commands run, dev server
port(s) if any, runtime verification evidence (not just "should work now"),
test/build status with actual exit signal, whether any long-running processes
were left alive, and an explicit list of what was **not** verified. A report
missing these is unverified, not automatically wrong — reproduce before
trusting it, especially before further work builds on top of it.

## Session Bootstrap Compliance Check

Format/mode requirements elsewhere in this file (a bootstrap-score line, an
explicit execution mode) are easy to silently skip in long sessions with real
code changes. If this file cites research on conditional-instruction miss
rates, treat that as a predicted background-rate risk, not a one-off lapse —
check for it explicitly at session start and at any self-audit, not just once.

## Uncommitted Work Has Zero Protection — Commit Before Release, Not After

Git provides zero protection for uncommitted working-tree state, in any tool,
by design — a concurrent session's normal `git checkout --`/reset on a file
it considers unrelated to its own task can silently erase another session's
verified-but-uncommitted work, with no error and no one noticing until later.
This directly interacts with any ownership/handoff protocol: releasing a
claim quickly is good (it unblocks other tools sooner) but widens the window
during which an uncommitted change on that file sits unprotected. The fix is
a missing step, not less handoff speed: **claim → work → verify → commit →
release → summarize.** Do not release ownership on a shared file while a
meaningful, verified change to it remains uncommitted, even briefly. This
cannot be fully eliminated (a small gap between "verified" and "committed"
always exists) — full elimination needs per-session worktree isolation as
the default, which trades this risk for real reconciliation overhead; that
tradeoff should be a deliberate decision, not an automatic response to one
incident.

## Decision Re-litigation Guard

A "patch vs. rewrite" (or similarly large-scope) decision, once made and
recorded with its reasoning and a reopen condition, is closed — do not
re-argue it from scratch each time a new session or a pasted external
analysis raises it again. Cite the existing decision record instead. Only
reopen if the recorded condition is actually met (e.g. the same failure
class recurs independently a stated number of times, or genuinely new
evidence contradicts the original reasoning) — not merely because the
question was asked again, more forcefully, or by a different tool. See
`governance/behavior-invariants.md`'s "Rewrite-vs-patch decision record" in
this repo for a worked example of the recorded format.

## Cognitive Challenge Protocol

Skills are local triggers, not the main routing layer. Use the narrowest sufficient tool or skill first; do not stack specialist skills unless the request clearly has distinct phases.

**TODO: this table is a worked example, not shipped skills.** The shared skill
set from `ai-control-plane/skills/` is `evidence-check`, `challenge-review`,
`skill-review`, `handoff`, `verify-task`, `publish-safe`, `node-intake`,
`session-close`, `plan-freeze` — none of the perspective-named rows below
(`feynman-perspective`, `munger-perspective`, `taleb-perspective`,
`ilya-sutskever-perspective`, `learn-system`) ship with the control plane.
Either delete this table, or replace the rows with skills you actually author
and copy into `.agents/skills/` yourself.

| 场景 | 调用能力 | 产出要求 |
|---|---|---|
| 提交 Evidence 前出现“这很明显” | TODO: example only — `feynman-perspective` is not a shared skill | 用一句话解释，写不出来 = 证据未成立 |
| `challenge-review` 阶段 | `challenge-review` (shared) | 至少 1 条具体反例，不是泛泛“可能有风险” |
| 结论看起来过于完整 | TODO: example only — `munger-perspective` is not a shared skill | 指出最可能出错的那一步 |
| 架构/长期方向评估 | TODO: example only — `taleb-perspective` is not a shared skill | 标明下行是否结构性锁死，尾部风险在哪里 |
| 输入 Evidence 有确认偏误嫌疑 | `evidence-check` (shared) | 区分“感觉对”与“有证据支撑” |
| 复杂执行流程 / 高风险操作 | `plan-freeze` (shared) | 输出 3-5 条不可跳过的检查点 |
| AI 安全/控制平面审查 | TODO: example only — `ilya-sutskever-perspective` is not a shared skill | 仅在治理层变更时启用 |

Non-trigger rules:
- Do not activate two specialist skills at the same time for one request unless the request clearly has distinct phases.
- If a request has distinct phases, run the phases serially rather than blending outputs.
- TODO: if you author a `learn-system`-equivalent skill, keep its reference material as a plain doc, not a standalone skill.
- Repeated triggers with no output change usually mean the trigger timing is wrong, not that the skill is broken.
- Treat `tool specificity` as execution discipline, not as a new skill.

## Skill Execution Order

For implementation work, skills run in this fixed sequence. Each step must complete and the user must confirm before the next begins:

1. `doc-sync` or `node-intake` → establish current repo state and confirm the active node
2. `plan-freeze` → commit to a bounded change plan before touching any file
3. implementation → minimum viable change within the approved plan
4. `verify-task` → confirm scope, diff, and test/build outcome
5. `publish-safe` → pre-commit / pre-push gate

`evidence-check` may be used at any step when a factual or evaluative claim needs verification.

A skill may narrow this sequence (e.g., a tiny one-file fix may skip `doc-sync` if the node is unambiguous) but may not reorder steps 2-4 or skip `plan-freeze` without explicit user instruction.

## Multi-Agent Dispatch Contract

Default to **single-agent**. Upgrade to multi-agent only when at least 3 of these 4 are true:

1. The task splits into 2 or more independent sub-questions.
2. The goal is risk-finding, contradiction-checking, or omission detection rather than direct implementation.
3. The material is large enough that one context window is likely to miss something important.
4. Independent viewpoints are needed to reduce blind spots.

If upgraded:

- **Phase 1: parallel read-only only.** Agents may read, search, review, and gather evidence in parallel.
- **Phase 2: one synthesis owner is mandatory.** If no orchestrator or human merge owner is named, do not fan out.
- **Phase 3: all writes stay serial.** Only one write-capable agent may hold `ACTIVE_EDIT_OWNERSHIP.md` at a time.
- **No multi-agent continuous write mode.** CONTINUOUS may chain read-only review steps, but implementation, governance edits, commits, and session-close remain single-writer operations.

## Autonomy Escalation Guardrail

<!-- Source: Microsoft AI Red Team taxonomy update, June 2026 — autonomy escalation defined as an agent upgrading its own permission boundary mid-workflow without user authorization. -->

An AI agent must not upgrade its own permission boundary during a session. The following require explicit user authorization before proceeding — not inference, not reasonable assumption:

- Any network call or external API access not declared in the active node scope
- Dispatching a sub-agent or spawning a parallel AI process
- Reading or writing files outside the plan-freeze commitment's declared file list
- Using any tool whose side effects were not covered in the approved plan
- Modifying `governance/`, `AGENTS.md`, `AI_BOOTSTRAP.md`, or `agent-constitution.md` mid-session

If any of these arises during implementation, stop immediately:
```
🛑 [permission boundary change: describe what changed] | Needs your decision: [one question]
```

This is distinct from scope escalation (covered by CONTINUOUS mode hard stops). Scope escalation is about *what files change*; autonomy escalation is about *what authority the agent assumes*.

## Action Reversibility Table

Use this table for binary permission checks before acting. The table governs permission, not scope: plan-freeze and node boundaries still apply.

| Action | iota | Classification | Default behavior | Context assumptions |
|------|------|------|------|------|
| `git commit` (files in plan-freeze list) | 0.05 | REVERSIBLE | Auto-execute | plan-freeze in place; no `governance/` files staged |
| `git commit` (`governance/` or `AGENTS.md` staged) | 0.65 | IRREVERSIBLE | CONFIRM + `[governance-approved]` token | explicit governance approval already granted |
| `git push` to non-main branch | 0.30 | IRREVERSIBLE | CONFIRM once per session | solo repo; no CI/CD side effects; branch is not `main` |
| `git push` to `main` or force-push any branch | 0.90 | IRREVERSIBLE | Always CONFIRM | none |
| Write file within the plan-freeze file list | 0.05 | REVERSIBLE | Auto-execute | plan-freeze in place |
| Write file outside the plan-freeze file list | 0.85 | IRREVERSIBLE | Hard-stop - autonomy escalation | none |
| Delete file | 0.95 | IRREVERSIBLE | Always CONFIRM | none |
| External API call or network request | 0.70 | IRREVERSIBLE | CONFIRM | not already declared in node scope |
| Spawn sub-agent or parallel AI process | 0.60 | IRREVERSIBLE | CONFIRM | not already declared in node scope |
| Modify this table's `iota` value or classification | 1.00 | IRREVERSIBLE | User-only; never AI-self-modifiable | none |

Rule: if any context assumption in the table no longer holds, the row's classification does not apply. Escalate to `CONFIRM` regardless of `iota`.

## Stop And Recovery Vocabulary

Use these terms consistently across skills, handovers, and live execution:

- **Triage block** — a read-only stop before implementation because state is unclear, stale, or conflicting. Do not write files just to get past it. Resolve by clarifying the baseline, active node, or source-of-truth conflict.
- **Hard-stop** — a binary stop triggered by a declared safety, scope, or autonomy boundary. Output the incident banner, switch to STEP, and write a `stop_event`. A hard-stop is about an imminent action, not the mere existence of a dirty worktree.
- **Resume** — the user approves returning to the original intended path after a hard-stop. Update the matching `stop_event` resolution to `resumed_by_user`.
- **Bypass** — the user explicitly chooses a different path after a hard-stop or downgrades the run into another mode such as an incident-response drill. Update the matching `stop_event` resolution to `bypassed_by_user`; do not silently treat bypass as resume.
- **Catch-up** — if a hard-stop fired but no `stop_event` was written at the time, `session-close` must append it before the session can close. Missing incident logging is a protocol failure, not a cosmetic omission.

Default banner for any hard-stop:
```
🛑 [reason] | mode=[STEP|CONTINUOUS|AUDIT] | needs your decision: [one question]
```

## Session Start Check

Before beginning any task, do these three steps in order — no exceptions:

1. Read `.agents/ACTIVE_EDIT_OWNERSHIP.md` — if another tool holds an active entry on a file you need, stop and report the conflict before touching that file.
2. Identify session type: **code** (node execution, file changes, tests) vs. **analytical** (research, review, strategy) — this determines which session-close branch applies and whether NODE_QUEUE or HANDOVER is the primary anchor.
3. Confirm task matches an ACTIVE or ARMED node in NODE_QUEUE.md, or is an explicitly named analytical task. If neither, stop and surface the mismatch before proceeding.
4. **Tool-switch protocol:** If switching from an analytical tool (claude.ai, Cursor, etc.) into this execution tool, run the `handoff` skill (shared, `ai-control-plane/skills/handoff/`) in the source session first. Do not make directional decisions here; confirm direction in the source session before switching. TODO: if you maintain a private cognitive-authority layer above this control plane (see `ai-control-plane/AGENTS.md`'s "Optional Cognitive Authority Layer"), reference its own handoff procedure here instead — do not copy a private manual's file path into this shared-facing template.

## Pre-Task Decision Flow

This repo uses the reusable control-plane decision flow from the control-plane
repo configured in `.control-plane/adapter.json`:
`protocols/pre-task-decision-flow.md`.

Project overlay: "active queue item" means an ACTIVE or ARMED entry in
`NODE_QUEUE.md`, or explicit user authorization for an analytical/control-plane
maintenance task.

## Bootstrap Tracking

After reading the canonical startup sources for a new session, output one line:

`bootstrap-score: [N]/[total] | active node: [node-id or none] | mode: [code/analytical] | gaps: [list or none]`

Rules:
- Count only sources actually read in this session.
- Keep it in the working chat or session response, not as a repeated `HANDOVER.md` log line.
- If the queue, handover, or worktree conflict, set `gaps` to the conflict instead of smoothing it over.

## Worktree Noise Control

Before acting on a dirty worktree, classify every changed path into exactly one of these buckets:

- **active work** — already authorized in an ACTIVE/ARMED node or explicitly scoped analytical task
- **candidate work** — looks valuable and may be kept, but is not yet authorized for execution
- **residual noise** — historical residue, abandoned drift, or formatting-only churn that should be cleaned
- **local-only files** — personal or tool-local artifacts such as `.claude/`, `inbox/`, scratch notes, or editor-specific state

Rules:
- **Verified is not authorized.** A diff that passes tests/build is still noise until it is either promoted into `NODE_QUEUE.md` as `CANDIDATE`/`ACTIVE`, or reverted.
- **Unauthorized diff rule:** any validated but unauthorized product diff must be classified as either a formal `CANDIDATE` node or a full revert before the session that discovers it ends. Do not carry over an unclassified diff to the next session. There is no timed grace period — the obligation is per-session-boundary, not per-clock. (Prior "24-hour rule" removed: no enforcement mechanism existed for wall-clock measurement; per-session boundary is detectable by node-intake.)
- **Template sync rule:** TODO — if you maintain your own bootstrap-template repo/directory for future projects, state its path here and require: when root protocol files change (`AGENTS.md`, `AI_BOOTSTRAP.md`, shared `.agents/skills/*`, or equivalent bootstrap/governance entrypoints), either sync the matching template files in the same session or record an explicit defer note in `HANDOVER.md`. If you don't maintain one, delete this rule.
- **Local-only exclusion:** local-only files are never part of project state by default. Do not use them to infer current product status, node progress, publish readiness, or dirty-set risk unless the task is explicitly about those files.
- **HANDOVER snapshot minimum:** whenever a session changes files or runs code, the end-state snapshot must state current `HEAD`, latest verification result, and the *nature* of the remaining dirty set (`active work`, `candidate work`, `residual noise`, `local-only`, or `none`).

---

## How to work here

- TODO: project stack (e.g. "React 18 + Vite + Tailwind CSS + Supabase" or
  "Python + FastAPI + Postgres"). This is the top item in
  `SETUP_CHECKLIST.md` — fill it there and mirror it here.
- Treat `governance/` as the project constitution and `NODE_QUEUE.md` as the work queue.
- Keep diffs minimal and node-scoped.
- TODO: name the core files that must not be modified without explicit node
  authorization (e.g. a thin app-shell entrypoint, a core reducer/state file,
  seed data). Leave this line empty (delete it) if the project has no such
  files yet.

## Default workflow

- For implementation tasks: confirm the active node, inspect only the files needed for that node, make the smallest safe change, then run the relevant test or build command.
- For review or research tasks: separate verified fact, inference, and assumption, and mark missing evidence as insufficient evidence.
- For publish tasks: check changed files, tests, and branch scope before commit or push.

## Route-Level Continuous Execution

When the user authorizes a route, follow
`ai-control-plane/protocols/route-based-continuous-execution.md`
(referenced via `.control-plane/adapter.json`).
Route-level authorization allows automatic continuation and scoped commits
until a HARD STOP fires. A route does not override permissions, hooks, or
deny rules. The next-route proposal at session close is a recommendation only,
not an authorization.

## Execution Modes

每次开始任务前，先识别当前执行模式。默认模式是 STEP。

---

### MODE: CONTINUOUS

**触发词（用户说以下任意一个即激活）：**
持续执行 / 继续做 / 不用停 / keep going / auto / 自动执行 / 连续执行 / 别打断

**激活后的行为：**
- **激活确认（必须输出）：** 识别到触发词后，第一件事输出一行 `→ CONTINUOUS 已激活`，再开始执行。用户看到这行才能确认模式已注册；静默激活无法与 STEP 模式区分。
- **指令密度原则：** CONTINUOUS 触发词应在独立消息中发出，在上下文传递和 plan-freeze 已完成之后。不要把激活词和大量执行约束、文件列表、停止条件写在同一条消息里——高指令密度会显著提高 AI 误读 stop 条件的概率。来源：2026-06-27 false-stop incident（behavioral evidence，4 次循环）；AgentIF (arXiv:2505.16944, 2025-05) 显示条件约束 condition-check 错误率 >30%，behavioral spec 覆盖率 66.7%，recall 0.55 — 表明 AI 对条件指令遵从显著弱于简单指令，支持"停止条件应尽量二元"的结论 [外部验证 2026-06-27：原引用"55–66%"是该论文多指标的简化，实质含义正确，数字来源需注明]。
- 按 NODE_QUEUE.md 或当前任务列表顺序，逐项执行完再执行下一项
- 每项完成后只输出单行状态，不等待确认，直接继续
- TODO: 你的测试/build 命令（例如 `vitest`、`pytest`、`cargo test`；或直接读取
  `.control-plane/verification.json` 的 `verificationCommand`）作为自动 gate：
  全部通过 → 继续；任何失败 → 立即切换到 BLOCKED

**单行状态格式：**
```
✅ [任务名] | 改动：[一句话] | 文件：[路径] | TODO:测试命令 [X/X] → 继续
```

**硬性停止条件（二元判断：观察到 X → 必须停；未观察到 X → 继续，不做主观解释）：**
- 观察到 TODO:测试/build 命令 退出码非 0 → 停；全绿 → 继续
- 即将写入 TODO:核心受保护文件（见上方"How to work here"）、或 seed 数据 → 停；否则继续
- 本回合改动落在 TODO:你的 feature 目录 下 ≥2 个不同子目录 → 停；≤1 个 → 继续
- 当前节点文本包含「Gate」或「外部前置」字样 → 停；不包含 → 继续
- 当前任务在 NODE_QUEUE.md 的 PENDING/ACTIVE 列表中找不到对应节点，且无显式用户授权 → 停；找到或已授权 → 继续
- 本回合即将新建或写入 `governance/` 下的文件（含 AI_BOOTSTRAP.md、AGENTS.md 本身）→ 停；只是读取或预先存在的未提交改动 → 不触发本条（由 node-intake triage 处理）
- 即将读写 plan-freeze 声明文件列表之外的文件 → 停，更新 plan-freeze 后再继续；在列表内 → 继续
- NODE_QUEUE.md 无 ACTIVE/ARMED 节点且用户未指定新方向 → 停，等待用户指令；有节点或有明确方向 → 继续（防止 AI 在队列清空后自行寻找「有用的改进项」触发 D7 漂移）

恢复路由（停下之后怎么走）：见 control-plane `protocols/failure-recovery-flow.md` 的统一失败决策树——ownership 冲突或 session 不变量损坏 = hard stop；可安全最小化 = 允许；信息缺失 = 搜 2 次后标 Gap/Unresolved；独立任务受阻 = 跳过并继续。

<!-- 设计原则：前3条是二元检查（文件路径/测试通过/关键词存在），减少 conditional judgment 依赖。
     来源：AgentIF (arXiv:2505.16944) conditional 约束 CSR 远低于 vanilla（~55-66% vs ~80-87%；tool/formatting 最低 10-45%），故停止条件应尽量二元；context fill >60-70% 时条件判断最先退化。 -->

停止时输出：
```
🛑 [原因] | 需要你决定：[一个问题]
```

**Hard-stop 触发后（强制，停止输出之前）：** 立即向 `.agents/session_log.jsonl` 追加一条 `stop_event` 条目（格式见 `.agents/stop_event.schema.json`），设置 `resolution: "fired_awaiting_user"`。这不是可选步骤——没有 stop_event 记录的 hard-stop 对未来 session 和其他 AI 工具不可见，等同于近乎失误未被报告。用户回应后更新为 `"resumed_by_user"` 或 `"bypassed_by_user"`。

**CONTINUOUS session 结束条件（强制）：** 任何修改了文件或运行了代码的 CONTINUOUS session，在输出"任务完成"之前，必须运行 `session-close` skill。若 CONTINUOUS session 因 hard-stop 中止（输出 🛑 而非"任务完成"），session-close 在 hard-stop 解决后的第一次用户回应时运行——优先于所有其他任务。未完成 session-close 的 CONTINUOUS session 等同于飞行已落地但未提交飞行日志——操作完成，学习丢失。

---

Every implementation-node completion in CONTINUOUS mode must run `verify-task` before advancing. `verify-task` `FAIL` or `NOT RUN` is a hard stop equivalent to a failed test/build. Analytical-only sessions are excluded.

**Infrastructure-audit 阻断（全局，二元）：** 若存在未解决的 high-risk `infrastructure-audit` 发现，则它阻断不相关的 CONTINUOUS 执行——直到该发现被解决、被显式 defer（带理由）、或被有证据地降级。`infrastructure-audit` skill 本身不在 CONTINUOUS 模式运行；详细判定过程留在该 skill 内，此处只放全局可见的阻断条件。

### MODE: STEP（默认）

每个节点完成后停下，等待确认再继续。
适用于：高风险改动、跨模块重构、schema 变更、首次接触新 feature。

---

### MODE: AUDIT

只读，不改文件。输出：verified fact / reasonable inference / insufficient evidence。
触发词：审计 / audit / review / 只看不改

---

### 模式切换规则

- 用户可随时说"暂停"/"stop"/"等一下"切回 STEP
- CONTINUOUS 遇到硬性停止条件后，自动切回 STEP，不自动恢复
- 模式不跨 session 持续——每次新 session 默认回到 STEP
