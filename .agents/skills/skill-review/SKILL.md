---
name: skill-review
description: "Audit and improve an existing skill using evidence-based criteria. Use when a skill feels too rigid, produces wrong outputs, lacks grounding, or has not been validated on real tasks."
last_verified: 2026-06-27
verified_against: AGENTS.md@2ee14b5
subordinate_to: host-repo/AGENTS.md
---

# Skill Review

Use this skill to audit one skill at a time. It applies the same criteria used to improve `learn-system` to any skill in this repository.

## 触发信号

用户说：「审查这个 skill」「优化这个 skill」「这个 skill 有问题吗」「review the skill」「skill 质量检查」

**不触发：** 「这个 skill 怎么用」（这是 README 的路由表问题）；「帮我执行这个 skill」（执行技能，不审查它）。

## 四个非谈判约束（C-08 bounded）

1. **先读 EFFECTIVENESS_LOG。** 任何已记录的 outcome 比直觉判断优先。
2. **停止条件必须基于结果，不是步骤数。** 如果 skill 以"完成 N 步"作为终止条件，这是缺陷。
3. **每个核心步骤必须有 why。** 步骤背后没有原理或来源支撑 = 可能被 AI 跳过或曲解。
4. **改动必须有外部来源支撑，或显式标注 [Insufficient evidence]。** 不凭直觉重写。

## 审查流程

### 第一步：读 EFFECTIVENESS_LOG 里此 skill 的所有记录

- 有没有 `unsafe` / `wrong-trigger` / `unclear` 条目？
- 有没有 `watch` 条目但从未 follow up？
- 有没有 action="update skill" 但 skill 没有实际更新的记录？

### 第二步：用七条标准逐项检查

| 标准 | 检查问题 | 通过 / 失败 |
|---|---|---|
| **Trigger** | 是否有明确、具体的触发词？用户说什么才能激活它？ | |
| **Scope boundary** | 是否有 "do not use for"？AI 会不会把它用错地方？ | |
| **Stop condition** | 停止条件是结果导向还是步骤数导向？ | |
| **Failure paths** | 已知失败路径是否来自真实观察，还是凭空写的？ | |
| **Evidence grounding** | 每个核心步骤有没有 why？有没有来源？ | |
| **C-08 compliance** | 硬约束是否 ≤ 4 条？规则总数是否会导致 AI 选择性遵守？ | |
| **Real-task validation** | EFFECTIVENESS_LOG 里有没有真实任务（非 meta-session）的使用记录？ | |

### 第三步：外部验证（只对有问题的步骤）

- 找相关研究、文档条目、或 governance 规则
- 来源必须包含 arXiv ID / DOI / 文档路径 + 日期
- 找不到来源 → 标注 [Insufficient evidence]，不填空

### 第四步：写 proposed fix

格式：
```
问题：[一句话描述]
来源：[arXiv / 文档 / EFFECTIVENESS_LOG 条目]
修复：[具体改动，引用来源]
```

每条修复对应一个问题。不打包多个问题进一条修复。

### 第五步：记录到 EFFECTIVENESS_LOG

```
[日期] skill=skill-review outcome=helped trigger="[被审查的 skill 名]" evidence="[发现了什么问题，怎么修复]" action="update skill"
```

## 最小可用版本（低容量）

只运行第二步的前三项：trigger / stop condition / failure paths。
输出：pass / fail + 一句话理由。不做外部验证，不写 proposed fix。

## 不要用这个 skill 做的事

- 不审查整个 skill 目录（一次一个）
- 不重写 skill 全文（只写 proposed fix，改动由用户确认后执行）
- 不因为"感觉太长"就删步骤（长度不是问题，冗余才是）

## 已知失败路径

- **「这个 skill 看起来挺好的」** → 这是验证模式，不是审查模式。必须逐项对照七条标准，不能靠印象。
- **改动太大，一次改完** → 每次只改一个 skill，改完记 log，下次再改下一个。
- **外部来源找不到就跳过** → 必须标注 [Insufficient evidence]；跳过 = 默认这步有来源，违反 citation integrity。
- **只审查"看起来有问题"的 skill** → EFFECTIVENESS_LOG 里 outcome=helped 的记录同样需要审查，因为"有效"可能来自 meta-session，不代表真实任务验证。
