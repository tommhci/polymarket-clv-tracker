---
name: publish-safe
description: "Prepare a safe commit, push, or PR by checking scope, verification, and branch cleanliness first."
last_verified: 2026-06-27
verified_against: AGENTS.md@2ee14b5
subordinate_to: host-repo/AGENTS.md
---

# Publish Safe

Use this skill before commit, push, or pull request actions.

## Input

- The current branch.
- The files staged or about to be staged.

## Steps

1. Confirm the branch name and target.
2. Inspect `git status --short`.
3. Inspect the changed file list.
4. **Verification gate (binary — do not rely on AI recall):**
   - Read `.control-plane/verification.json`'s `verificationCommand` first.
     Run it and capture the last 10 lines of output.
     - Exit 0 → continue.
     - Exit 1 / command not found → stop immediately:
       ```
       🛑 Verification gate failed | Test output: [paste last 10 lines] | Needs your decision: fix the test failure or confirm this change is exempt.
       ```
   - **If `verification.json` is absent or has no `verificationCommand`,** and
     the client repo has a `package.json`: fall back to `npm test` when
     `git diff HEAD --name-only` contains any `src/` file, otherwise
     `npm run build`. State explicitly that this is an inferred fallback, not
     a declared command.
   - **If neither is available:** stop — do not publish without a verifiable
     command. `🛑 No verification command declared or inferable | Needs your
     decision: define .control-plane/verification.json or confirm this
     publish is exempt.`
   - Do not accept "verification passed earlier", "verify-task passed", or AI recall as a substitute. This step requires a live command output visible in the current response.
5. Pause and confirm intent before touching any file if scope is unclear.
6. Block the publish step if unrelated files or missing checks appear.

## Validation

- Only publish when the scope is clean and the task is verified.
- If scope is unclear, stop and ask for confirmation.

## Output

- Safe-to-publish or not-safe-to-publish.
- The exact reason.

## Stop conditions

- Do not stage, commit, push, or create a PR without explicit user confirmation.
- Do not auto-push.
- Do not widen scope.
- Do not publish if verification is missing or ambiguous.
- **Binary extension block:** if any file about to be staged matches `.env*`, `*.pdf`, `*.html`, `*.jpeg`, `*.jpg`, `*.png`, `*.docx`, `build_*.py` — stop before staging. Only proceed if the active node's declared outputs explicitly name that file type. This is a hard check, not a scope-clarity judgment.

## 已知失败路径

- **部分文件应发布，其他不应该**（`.env`、`*.docx`、`build_*.py` 意外进入 staging）→ 停止，逐文件确认，`.gitignore` 应已覆盖这些扩展名；如未覆盖先修 `.gitignore`。
- **目标分支不明确**（用户说「push」但没说 push 到哪）→ 明确确认目标分支，不默认 main；特别是有多个 remote 时。
- **有未 commit 的相关改动在 worktree 里**（改动了但没 stage）→ 先完成 commit，再 push；不能在 worktree dirty 的情况下认为 publish 完成。
- **force push 被请求** → 无论理由，向用户明确说明风险并要求二次确认；绝不在 main 分支 force push。
