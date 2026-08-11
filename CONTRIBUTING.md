# Contributing

感谢贡献！请遵循以下流程：

1. Fork 仓库并创建特性分支（`feat/xxx` / `fix/xxx`）。
2. 安装开发依赖：`pip install -e ".[dev]"`。
3. 保证 `pytest`、`ruff check`、`mypy` 全部通过后再提交。
4. 提交信息使用约定式提交：`<type>(<scope>): <desc>`（如 `feat(s5): 融合仲裁置信评估`）。
5. 新增依赖必须在 PR 中说明用途；标准库可实现的不引第三方。
6. 不提交密钥、token、数据库口令、内网地址；考古敏感数据（坐标/墓主）不得入库。
7. 重大变更先开 Issue 讨论，对齐《技术方案 V0.5》后再编码。
