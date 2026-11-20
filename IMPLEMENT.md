# IMPLEMENT — 决策与偏差日志

> 只追加，不覆盖。偏差必须带失效条件与影响范围。

## D-001 v1 归档，保留 books

- 日期：2026-11-20
- 决策：除 `books/` 与 `.git/` 外，旧项目内容全部移入 `v1/`；`data/` 一并归档。
- 原因：开始新方案，旧实现只作参考；books 是当前可见的图版数据。
- 影响：`v1/.venv` 路径失效，不再使用；旧 `.gitignore` 随 v1 归档，新根目录重建忽略规则。

## D-002 协作档位 L0 + C

- 日期：2026-11-20
- 决策：Claude 编排 / Codex 实现 / dsh 验证，WIP=1；不并行、不引入 mh 内核。
- 原因：单人评审带宽、强耦合视觉链路、尚无单 agent 基线。
- 升级条件：连续两波吞吐 > 单 agent、allow 可切分、人工介入 <3 次/日；否则维持 L0。

## D-003 模型与端点

- 日期：2026-11-20
- 决策：codex 与 dsh 统一使用 `deepseek-v4.1-flash-1017`；OpenAI 兼容端点走阿里云 MaaS
  `/compatible-mode/v1`；codex `wire_api = "responses"`（0.169 已移除 chat）。
- 密钥位置：codex 用户级 `~/.codex/config.toml`；dsh 使用 Windows 用户环境
  `DASHSCOPE_API_KEY`。均不入仓库。
- 验证：两端 `只回复 OK` 冒烟通过。
- 失效条件：端点或模型下线、codex 移除 responses、dsh 更换 provider 配置格式。

## D-004 产品设计待定稿

- 日期：2026-11-20
- 状态：`v1/docs/V1.0_四条工作线架构方案.docx` 为讨论起点，未冻结。
- 影响：M1 之前不建产品卡；只允许 M0 基线与探针卡。