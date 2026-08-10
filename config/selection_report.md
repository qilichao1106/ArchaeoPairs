# selection_report.md — 技术选型冻结报告（P0 实验后填写）
# 红线：禁止冻结未经对照实验验证的具体模型/参数量；禁止未经 PoC 冻结编排框架。

## 1. 实验设定
- 数据：golden 100 图子集（case1 12 + case2 60 + 规则B 12 + 密集 8 + 彩板 8）
- 评估口径：见 eval/metrics.py；通过线见第七章
- 实验人：2 人周；temperature=0；录制回放

## 2. 组件选型结论（待实验后冻结）

| 组件 | 候选 | 关键指标 | 实测结果 | 冻结选择 | 版本 |
|---|---|---|---|---|---|
| 实例分割 | SAM系列 / YOLOv8-seg / Mask2Former | IoU≥0.9通过率；≤3s/图 | _待填_ | _待冻结_ | _ |
| VLM | 开源档A(≈8B) / 开源档B(≈30B) | 类型/仲裁/回读三任务准确率 | _待填_ | _待冻结_ | _ |
| OCR | PaddleOCR / Tesseract | 序号/中文小字准确率；纵排 | _待填_ | _待冻结_ | _ |
| 文本LLM | 开源档A / 档B | 切分F1；范围式展开正确率 | _待填_ | _待冻结_ | _ |
| 编排框架 | LangGraph / AgentScope / AutoGen / 自研 | 8维PoC(见3) | _待填_ | _待冻结_ | _ |

## 3. 编排框架 PoC（8维，5图fixture）
# 维度见方案第三章；同一mini管线：A0→{A1a,A2}→A1c→A4→A8 interrupt→resume→END
| 维度 | 权重 | LangGraph | AgentScope | AutoGen | 自研 |
|---|---|---|---|---|---|
| D1 确定性DAG | 20% | _ | _ | _ | _ |
| D2 断点续跑 | 18% | _ | _ | _ | _ |
| D3 HITL | 18% | _ | _ | _ | _ |
| D4 并行join | 10% | _ | _ | _ | _ |
| D5 容错 | 8% | _ | _ | _ | _ |
| D6 类型化State | 8% | _ | _ | _ | _ |
| D7 可观测 | 8% | _ | _ | _ | _ |
| D8 生态维护 | 10% | _ | _ | _ | _ |
| 加权总分 | | _ | _ | _ | _ |

## 4. PoC 验收项实测
- [ ] 并行join正确性（A1c恰执行一次）
- [ ] interrupt/resume（kill后断点续跑、不重跑已完成节点）
- [ ] 幂等（同thread_id输出一致无重复写）
- [ ] 超时/看门狗（VLM卡死60s→重试→review）
- [ ] State Schema校验（非法字段被拒）
- [ ] 观测接入（trace_id贯穿、metrics落SQLite）

## 5. 冻结决策（签字）
- 编排框架：__（P0 PoC后冻结；推荐优先级：LangGraph / AgentScope 并列待实验）
- 模型选型：__
- 签核人/日期：__
