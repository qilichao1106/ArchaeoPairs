# 任务卡模板（复制为 collab/cards/T-xxx.md）

```yaml
id: T-xxx
title: <一句话行为增量>
stream: pipeline
owner: codex
verifier: dsh
allow: []                      # 精确路径；同波两两不相交
accept: []                     # AC 指针
non_goals: []                  # 必填
goal: <可观察行为>
stop_condition: "<命令>::<期望退出码>"   # 禁时间型
max_files: 10
max_lines: 400
max_selfcheck_lines: 200
max_depth: 0
max_rounds: 3
budget: {tokens: 200000, wall_minutes: 90}
wave: 1
deps: []
serial_group: null
contract_refs: []
spec_refs: []
```

## 场景 / 备注

- 背景：
- 输入/输出：
- 已知风险：
- Handoff 必填：branch / commit / files / cmd 三元组 / cwd / risks / verifier_entry / unfinished