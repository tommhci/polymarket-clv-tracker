---
name: plan-freeze
description: "Commit to a bounded execution plan before writing any code. Use after node-intake confirms the active node, before implementation begins. Output a plan and stop — do not touch files."
last_verified: 2026-06-27
verified_against: AGENTS.md@2ee14b5
subordinate_to: host-repo/AGENTS.md
---

# Plan Freeze

Use this skill between node selection and implementation. Its only job is to produce a
binding written commitment and then stop. Implementation does not begin until the user
explicitly approves the plan.

This skill is subordinate to `AGENTS.md`. If any instruction here conflicts with
`AGENTS.md`, `AGENTS.md` takes precedence.

## When to use

- After `node-intake` has confirmed the active node and the user has approved proceeding.
- Before any file is opened for editing.
- Any time a task boundary feels unclear before starting.

## When NOT to use

- Do not use for read-only tasks (research, `doc-sync`, `evidence-check`).
- Do not use for session-close or publish steps.
- Do not use when the user explicitly says "skip plan-freeze, just do it."

## Preconditions

All four must be satisfied before producing the plan. If any is missing, stop and report:

1. `AGENTS.md` has been read this session.
2. `NODE_QUEUE.md` has been read and the ACTIVE node is confirmed.
3. Worktree is clean or all dirty files are explained by the active node or prior HANDOVER entry.
4. `node-intake` (or equivalent state-check) has completed and the user has confirmed the node.

If the pre-task flow produced a compact or gated Task Contract, it must be the
current contract version. Plan-freeze consumes that contract; it does not
recompile the user's request.

## Steps

1. State the ACTIVE node ID and its one-line description from NODE_QUEUE.md.
2. State the exact user-approved objective for this session in one sentence.
3. If a Task Contract exists, state its `contract_id` and `contract_version`.
4. Bind the plan to the contract's `scope`, `non_scope`, `invariants`,
   `permissions_required`, and `stop_conditions`.
5. List every file expected to be touched. For each file, state WHY it must change.
6. State the minimum verifiable change - the smallest diff that satisfies the node.
7. State the validation commands that will confirm success after implementation.
8. Output the plan in the format below and stop. Do not proceed.

## Required output format

```
### Plan Freeze

**ACTIVE node:** [node-id] — [one-line description]

**Objective:** [one sentence, user-approved]

**Task Contract:** [contract_id + contract_version, or `none`]

**Invariants and permissions:**
- [invariants that constrain implementation]
- [permissions_required and whether each is satisfied]

**Files to touch:**
- `path/to/file.js`: [reason — what change, why needed]
- `path/to/other.js`: [reason]

**Minimum verifiable change:**
[Describe the smallest diff that satisfies the node — no opportunistic cleanup]

**Explicit non-scope:**
- [files or concerns that will NOT be touched]
- [No refactors outside node boundary]
- [No changes to governance/, AGENTS.md, or seed data unless node requires it]

**Validation:**
- `[command]` — confirms [what]
- `[command]` — confirms [what]

**Stop conditions:**
- [Specific condition that would require pausing and asking the user]
- [e.g., if X file has unexpected state]
- [Any Task Contract stop_conditions]

🛑 Plan committed. Awaiting approval before implementation.
```

**After user approves this plan** — before touching any file — write a lock entry to `.agents/ACTIVE_EDIT_OWNERSHIP.md`:
```
[YYYY-MM-DD HH:MM TZ] owner=ClaudeCode/<session-label> files="<files-to-touch list>" purpose="<active node id> — <one-line node description>" release="At session-close or upon explicit user instruction."
```
This is mandatory for any session that will modify shared protocol files (`AGENTS.md`, `AI_BOOTSTRAP.md`, `HANDOVER.md`, `NODE_QUEUE.md`, `.agents/skills/*`, `.agents/protocols/*`). Without this entry, concurrent AI sessions have no visibility into this session's file scope and will silently race.

## Stop conditions

- Do not create, edit, delete, move, rename, commit, or push any file.
- Do not proceed to implementation without explicit user approval of the plan **in the current conversation turn** — a prior-turn affirmative ("ok", "好", "继续") does not satisfy this gate. The approval must respond directly to this plan-freeze output.
- If the ACTIVE node is missing or ambiguous:
  `🛑 No confirmed ACTIVE node | Needs your decision: Which node should we implement?`
- If worktree has unexplained changes that conflict with the plan:
  `🛑 Worktree conflict with plan | Needs your decision: [describe the conflict]`
- Read `.control-plane/protected-paths.json`'s `protectedPaths` list. If the
  plan would touch any path matching an entry in that list, and the node does
  not explicitly name it:
  `🛑 Plan touches protected file outside node scope | Needs your decision: Is this intended?`
- If `protected-paths.json` is absent or unreadable, fall back to treating
  `governance/` as protected (documented fallback, not a silent default) and
  say so explicitly in the plan's Stop conditions section.
- If scope exceeds one node boundary (changes span 2+ independent feature areas):
  `🛑 Scope exceeds node boundary | Needs your decision: Split into two nodes or confirm combined scope?`

## 已知失败路径

- **把 plan-freeze 当成 node-intake 的重复** → 不同：node-intake 选节点，plan-freeze 承诺具体改什么文件、怎么改。两者不互相替代。
- **「计划看起来合理就直接开始实现」** → 不对。必须等到用户显式说「好」「approved」「开始」之后才能动文件。
- **Files to touch 列表写得太宽（「相关文件」「可能需要」）** → 必须精确到文件名和理由；模糊计划等于没有计划。
- **跳过 Explicit non-scope** → 这是最重要的一行：明确说不改什么，防止 AI 「顺手」扩大范围。
- **Validation 写了 `npm test` 但 package.json 里没有 test 命令** → 先确认命令存在，不能写无法运行的验证步骤。
