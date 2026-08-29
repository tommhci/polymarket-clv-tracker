---
name: handoff
description: "Hand off work cleanly when switching between AI tools (Claude Code → Codex → Cursor → Kiro) under a single human orchestrator. Produces a transition brief, locks/releases edit ownership, and version-stamps the snapshot to prevent mutual overwrite. NOT a peer-to-peer agent handoff."
last_verified: 2026-06-27
verified_against: AGENTS.md@2ee14b5
subordinate_to: host-repo/AGENTS.md
---

# Handoff

Use this skill when the human (you) is moving the same work from one AI tool to
another. The human is the orchestrator; the tools are workers. This is a
*session/tool transition*, not an autonomous agent-to-agent handoff.

## 为什么这个 skill 是「manager-owned」而不是「peer-to-peer」

[Fact] 2026 业界共识：用单一 orchestrator 持有完整 context，spawn 临时 worker，
**agent 之间无点对点通信**。无限 handoff 循环（A→B→C→A）是多 agent 系统最高频的
单一失败模式（来源：Beam.ai / Cogent / nasscom 行业 playbook, 2026；行业博客非同行评审）。

[Fact] 本仓库已采用 manager-owned pattern（`.agents/skills/README.md` Operating Rule +
Evidence Notes）。本 skill 强化这一点，不引入 P2P handoff。

**因此本 skill 不做循环检测**——在人类居中调度的结构里，自主循环不会发生。
真正的风险是 **state divergence / 互相覆盖**：两个工具各写一份 HANDOVER 快照，后写的
覆盖先写的。本 skill 防的是这个。

## 触发信号

用户说：「交接给另一个 AI」「换到 Codex / Cursor / Kiro 继续」「handoff to [tool]」
「我要在另一个工具里接着做」

**不触发：** 「我开个新 session 做别的事」是新任务声明，不是交接。

## Input

- 当前工作状态（节点、改动、未完成项）。
- 目标工具（接手方）。

## Steps

1. **确认单一真相源。** HANDOVER.md 是唯一状态源。如果接手工具会读不同文件，先指明
   它必须以 HANDOVER.md 为准。
2. **快照版本戳。** 在 HANDOVER SNAPSHOT 的 `Last updated:` 行追加交接标记：
   `[handoff → <tool> @ <date>]`。接手方必须保留这个戳；若接手方要写 HANDOVER，先确认
   戳未被第三方更新过（防止覆盖）。
3. **移交编辑所有权。** 在 `.agents/ACTIVE_EDIT_OWNERSHIP.md` 写一条 release（移交方）
   + 一条 active（接手方），明确 owned files。两条都写，不能只 release 不指定接手。
4. **产出交接简报（transition brief）**，给接手工具，包含：
   - 当前节点 / 分析状态（指向 NODE_QUEUE 或 HANDOVER ANALYTICAL STATE）
   - 已完成 + 未完成项（一句话各一条）
   - 接手方第一步该做什么
   - 哪些文件正被锁定、不要碰
5. **不发起回交期待。** 简报里显式声明：「本次交接不期待你交接回来。若你认为需要回交，
   先停下问人类，不要自动回写本工具的范围。」（防 state divergence，替代自主循环检测。）

## Output

- 一份可直接粘贴给接手工具的 transition brief。
- 更新后的 ACTIVE_EDIT_OWNERSHIP（release + active 两条）。
- HANDOVER SNAPSHOT 带 handoff 戳。

## Stop conditions

- 不替接手工具执行它的第一步——本 skill 在交接简报产出后结束。
- 不在未写 ACTIVE_EDIT_OWNERSHIP 移交的情况下宣布交接完成。
- 不 commit / push（如需，走 publish-safe，且需用户确认）。
- 不引入工具间自动回交或点对点循环。

## 已知失败路径

- **两个工具各写一份 HANDOVER** → 后写覆盖先写。靠步骤 2 的版本戳 + 步骤 3 的所有权
  移交防止；接手方写前必须确认戳未变。
- **只 release 不指定接手** → 出现「无主」状态，下一个 agent 不知道谁在负责。两条都要写。
- **被误用为 P2P agent handoff** → 本 skill 是人类居中的工具切换，不是自主 agent 互转；
  若出现「让 AI 自己决定交给哪个 AI」，停止，回到 manager-owned 模式。

## Status / validation gap

[Insufficient evidence] v1，由 Codex 并发编辑的真实摩擦驱动，但本 skill 流程本身尚未经
一次完整真实交接验证。首次真实使用后在 EFFECTIVENESS_LOG 记一条：交接是否真的避免了
覆盖 / 状态分叉，据此精简或修正。

## Session Close

本 skill 不替代 session-close。若交接同时意味着移交方今天收工，移交方仍需跑 session-close。
