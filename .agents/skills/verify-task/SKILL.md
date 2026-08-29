---
name: verify-task
description: "Verify a completed repo task against the current node, changed files, and test/build checks."
last_verified: 2026-06-27
verified_against: AGENTS.md@2ee14b5
subordinate_to: host-repo/AGENTS.md
---

# Verify Task

Use this skill after making code changes for a single node.

## Input

- The current node or task name.
- The modified files.
- The current Task Contract, when the pre-task flow produced one.

## Steps

1. Read the active node in `NODE_QUEUE.md`.
2. Inspect the changed files.
3. Check whether the diff stays within the node boundary.
4. If a Task Contract exists, verify the current `contract_id` and
   `contract_version`, then compare the result against its `scope`, `non_scope`,
   `invariants`, and `acceptance_evidence`.
5. Run every applicable contract `verification_method`, plus the client's
   declared verification command:
   - Read `.control-plane/verification.json`'s `verificationCommand` first and
     run that.
   - If `verification.json` is absent or has no `verificationCommand`, and the
     client repo has a `package.json`, fall back to `npm run build` (UI/app
     wiring changed) or `npm test` (core logic changed) — and say explicitly
     that this is a fallback, not a declared command.
   - If neither is available, targeted checks scoped to the node, and report
     `verification: NOT RUN — no verification command declared or inferable`
     per the binary reporting rule below.
6. Compare results against the node checklist.
7. If scope, permissions, invariants, or acceptance evidence changed during
   execution, report contract drift and fail verification until a new contract
   version is approved.

## Validation

- Confirm the task is complete only if the node scope, diff, and checks all line up.
- If any required check failed or was not run, report `FAIL`.
- If a test or build fails, stop and report the failure before making new changes.
- **Binary reporting rule:** if verification cannot be run (command missing, not applicable, environment issue), output exactly `verification: NOT RUN — [reason]`. Never output `PASS` for an unchecked item. Never omit a check silently. A fabricated PASS is worse than an explicit NOT RUN — the former propagates false confidence to session-close and the next node-intake.

## Output

- Pass/fail for each checklist item.
- Pass/fail for each `acceptance_evidence` and `verification_method` item when a
  Task Contract exists.
- A concise note on residual risk.

## Stop conditions

- Do not propose extra refactors.
- Do not advance to the next node.
- Do not retry verification blindly after a failure.

## 已知失败路径

- **测试通过但 diff 范围超出节点边界**（顺手改了不相关文件）→ 不算 PASS，标记 scope creep，要求 revert 无关改动后重新验证。
- **「改动很小」所以跳过了声明的验证命令** → 必须运行，不能凭判断跳过；小改动导致的隐式回归是常见错误来源。
- **忽略 `.control-plane/verification.json`，直接假设 npm test** → 客户端仓库可能不是 Node 项目；`verification.json` 是 control plane 与客户端之间的契约，必须先读它。
- **验证通过但 HANDOVER SNAPSHOT 没有更新** → 任务未完成，SNAPSHOT（日期+测试数+commit hash）是验证的一部分。
- **lint 有警告但 build 通过** → 如果节点描述要求 lint-clean，则 FAIL；不能用「只是警告」绕过。
