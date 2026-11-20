# 环境台账 env.md

> 环境事实不写下来就会反复踩。密钥只记存在方式，不记值。
> 编排工作区：`agent-orchestration workspace/`；功能代码与契约在项目根 `src/`、`tests/`、`contracts/`；验收辅助 `specs/`、`selfcheck/` 在工作区。

## 工具

| 工具 | 版本 | 入口 | 备注 |
|---|---|---|---|
| git | 2.53.0.windows.2 | `git` | 仓库根 `.git/` 保留 |
| Python | 3.12.10 | `python` | Windows 中文路径统一 `-X utf8` |
| Codex CLI | 0.169.0 | `codex exec` | provider `maas_deepseek`；`wire_api="responses"` |
| dsh | 0.2.2-rc.1 | `dsh --profile headless` | provider `dashscope` |
| Claude Code | 2.1.329 | `claude` | Orchestrator |

## 模型与端点

- 模型：`deepseek-v4.1-flash-1017`（codex/dsh 统一）
- OpenAI 兼容：`https://llm-1pxqd38dwq24f1gn.cn-beijing.maas.aliyuncs.com/compatible-mode/v1`
- Anthropic 兼容：`https://llm-1pxqd38dwq24f1gn.cn-beijing.maas.aliyuncs.com/apps/anthropic`
- 已实测：`/responses` 与 `/chat/completions` 均 HTTP 200。

## 凭据

| 变量 | 使用方 | 存放 |
|---|---|---|
| codex bearer token | Codex | `~/.codex/config.toml`（用户级，不入库） |
| `DASHSCOPE_API_KEY` | dsh | Windows 用户环境变量（新开终端生效） |

配置备份：`~/.codex/config.toml.bak-20261120`、`~/.dsh/profiles/headless/cordis.patch.yml.bak-20261120`、`~/.dsh/.credentials.yaml.bak-20261120`。

## 已知坑

1. **codex 0.169 移除 `wire_api="chat"`**：必须 `responses`；模型元数据已补进 `~/.codex/cc-switch-model-catalog.json`。
2. **dsh 凭据**：`.credentials.yaml` 的 `refs` 改动不被 headless 直接采用；必须用户环境 `DASHSCOPE_API_KEY` 或显式 export。修改后需新开终端。
3. **Windows 中文路径**：Python 统一 `-X utf8`；脚本避免非 UTF-8 输出。
4. **v1/.venv 已失效**：旧虚拟环境随 v1 移动，路径不可用；新实现重建环境。
5. **books 2GB**：`books/` 未入库；新方案需明确 `--media-root`。
6. **dsh/codex 沙箱写不了 worktree `.git`**：实现者留工作区，Orchestrator 代提交。
7. **本机无 make**：在工作区内统一用 `python scripts/preflight.py` 或 `scripts\doctor.cmd`；从项目根执行：`python "agent-orchestration workspace/scripts/preflight.py"`。`Makefile` 仅作有 make 环境的等价入口。
8. **dsh Windows 沙箱**：`--permission-mode workspace-write` 在 ACL 授权阶段失败（`SetNamedSecurityInfoW failed (Win32 5)` / `sandbox-local windows-acl temp grant materialization failed`），shell 不可用；`--permission-mode read-only` 的 shell 可运行，但 pytest 无法创建 tmp 目录。**验证任务统一用 `--permission-mode danger-full-access --approval-policy never`**，配合 `PYTHONDONTWRITEBYTECODE=1 python -m pytest ... -p no:cacheprovider`；实现任务 dsh 可用文件工具写代码，pytest 由 Orchestrator/Verifier 实跑。