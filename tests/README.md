# tests/ — 冻结验收测试（唯一写者：Verifier）

纪律：

- 按 AC 写冻结测试；AC 场景在 `agent-orchestration workspace/specs/`；实现者只读。
- 断言不得放宽/删除/跳过；flake 不计 pass。
- 每条 AC 至少一个 nodeid；声明通过必须引用真实 `N passed; M failed`（N>0）。
- 负向对照：注入真实故障证明测试由绿转红；`assert 1==2` 不算。
- 测试输出与退出码落 `agent-orchestration workspace/artifacts/<task>/`。
- `python -m pytest` 需排除 `agent-orchestration workspace/worktrees/`（pytest 配置 `norecursedirs`）。