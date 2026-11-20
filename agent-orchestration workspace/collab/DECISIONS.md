# DECISIONS — ADR / CR

> 只记正式决策，不记口头约定。编号永不复用；偏差必须带失效条件。

## ADR-001 v1 归档，books 保留

- 日期：2026-11-20
- 决策：除 `books/` 与 `.git/` 外，旧内容移入 `v1/`；`data/` 一并归档。
- 后果：旧实现只作参考；新根目录重建 `.gitignore` 与协同基线。

## ADR-002 协作档位 L0 + C

- 日期：2026-11-20
- 决策：Claude 编排 / Codex 实现 / dsh 验证，WIP=1。
- 失效条件：连续两波吞吐 ≤ 单 agent；人工介入 >3 次/日；冲突率 >20%。

## ADR-003 模型与端点

- 日期：2026-11-20
- 决策：codex/dsh 统一 `deepseek-v4.1-flash-1017`；codex 走 OpenAI 兼容 `/responses`，dsh 走 `openai-completions`。
- 失效条件：端点/模型下线；codex 移除 responses；dsh 配置格式变更。