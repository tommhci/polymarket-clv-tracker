---
name: evidence-check
description: "Verify factual or evaluative claims by separating fact, inference, and assumption, and by marking missing evidence explicitly."
last_verified: 2026-06-27
verified_against: AGENTS.md@2ee14b5
subordinate_to: host-repo/AGENTS.md
---

# Evidence Check

Use this skill for research, strategy, and evaluation tasks where the answer depends on sources.

## Input

- The core claim or decision to evaluate.
- Any source links or documents already provided.

## Steps

1. Convert the claim into a neutral question.
2. Gather the highest-quality sources available for the topic.
3. Separate:
   - verified fact
   - reasonable inference
   - assumption
3a. **COI check (mandatory when source is a vendor, lab, or funder):**
   For each source that is an AI provider (Anthropic, OpenAI, Google DeepMind, Meta AI),
   platform company, or self-funded research, output one COI block before using the claim:
   ```
   [COI: source=X | incentive=Y | independent replication=yes/no/unknown | conclusion direction=favors X / neutral / unfavorable to X]
   ```
   - If `independent replication=no` and `conclusion direction=favors X`, downgrade the claim
     to `[Inference — vendor self-report, unverified]`. Do not use it as a primary design input.
   - If `conclusion direction=unfavorable to X`, the COI risk is low; use normally.
   - Note: the AI running this check may itself be a product of the vendor being evaluated.
     Name this structural bias explicitly; it cannot be eliminated, only disclosed.
4. Mark any unresolved gap as `insufficient evidence`.
5. If the task is a decision or strategy question, include:
   - 3 failure points
   - 2 missing evidence items
   - 1 concrete action with a time bound

## Validation

- Every non-self-verifiable claim must have source + date.
- Do not fill gaps by guessing.

## Output

- Core judgment first.
- Evidence second.
- Explicit gaps last.

## Stop conditions

- Stop once the core claim is supported enough to answer.
- Do not over-extend into speculative detail.

## 已知失败路径

- **外部来源 URL 失效（404 / 内容被更新）** → 标记为 `insufficient evidence`，不使用训练记忆里的旧版本内容替代；说明来源失效。
- **同一来源被用于支持两个互相矛盾的主张** → 停止推理，标记为 `reasoning error`，上报矛盾而不是选择其中一方。
- **没有外部来源可用但任务要求外部验证** → 明确说 `insufficient evidence`，不用 AI 训练数据内嵌知识填补（训练数据有截止日期，且无法溯源）。
- **把「reasonable inference」当「verified fact」输出** → 每一步都必须显式标注类别；推断不能升级为事实，除非找到新来源支持。
