---
name: challenge-review
description: "Devil's advocate review: systematically find flaws, failure modes, and unconsidered perspectives in a proposal, decision, or analysis. Use when you want active pushback, not validation."
last_verified: 2026-06-27
verified_against: AGENTS.md@2ee14b5
subordinate_to: host-repo/AGENTS.md
---

# Challenge Review

Invoke this skill when you want the AI to actively find problems — not confirm what you've already decided.

## 触发信号

用户说：「挑战一下」「找漏洞」「质疑这个」「devil's advocate」「压力测试」

## Input

Paste the idea, proposal, decision, or analysis to be challenged.

## Steps

1. **Read the input without immediately supporting it.** Identify the central claim or decision.

2. **Generate the three strongest objections** — not weak strawmen, but the arguments a well-informed skeptic would actually make:
   - What assumption is load-bearing and most likely wrong?
   - What scenario makes this decision fail badly?
   - What perspective is entirely absent from the analysis?

3. **Identify the falsification condition:** Under what conditions would the core claim be demonstrably wrong? If you cannot state one, the claim may be unfalsifiable — flag this explicitly.

4. **Check for sycophancy accumulation:** If this review is happening in the same session that produced the analysis, note: same-session review has documented blind spot rate (Self-Correction Bench: 64.5% avg, arXiv:2507.02778). For high-stakes decisions, recommend running this skill in a fresh session with Mode B handoff.

## Output Format

```
核心主张：[1句话复述]

最强反对理由：
① [反对理由 1 + 依据]
② [反对理由 2 + 依据]
③ [反对理由 3 + 依据]

失效条件：[这个分析/决定在什么情况下会被证明是错的]

缺失视角：[什么重要角度完全没有出现在原始分析里]

建议：[继续 / 修改后继续 / 暂停等更多信息]
```

## Stop Conditions

- Do not provide supporting arguments before completing the objections.
- Do not soften objections to avoid discomfort — weak pushback is worse than none.
- If the input is too vague to generate specific objections, ask for one concrete claim to challenge first.

## 已知失败路径

- **「这个想法总体上是好的，但是…」** → 这是验证模式，不是挑战模式。直接从反对理由开始。
- **同 session 产生 + 同 session 审查** → 按步骤 4 标注，建议 fresh session。
- **没有失效条件** → 这是红旗，说明分析可能是不可证伪的主张，必须标出来。
