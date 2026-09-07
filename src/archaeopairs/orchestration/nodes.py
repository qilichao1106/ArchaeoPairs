"""各 Node 函数：输入 State 键 -> 调用智能体 -> 输出 State 键（节点映射表（§3.4.1）映射）。

Node id（V0.5.4 对齐 §3.4.1）：s1_index / s2_classify / s3_text / s4_segment /
s5_recognize / s6_compose / s7_single / s8_assemble / s9_supervise / s10_review。

统一异常拦截（多智能体协作架构（§3.1）/ 异常报警字典（§6.3）/ 服务级降级与熔断（§3.7））：
* AlarmError/HardConstraintError → PENDING_REVIEW + 报警码（报警即停、禁输出 PNG）；
* E400 OCR 全失败 / E1000(OCR) 熔断 → 链③缺失降级，按降级矩阵继续；
* E1000(VLM/SAM) 熔断 → PENDING_REVIEW（批次挂起由调度层处理；S9 质检不可用
  同样全部转复核，宁复核不误放 §4.9.2）；
* E102/E101 摄入违约 → EXCLUDED；caption 缺失为 S1 非阻断告警；
"""
from __future__ import annotations

from typing import Callable

from ..agents import Services, s1, s2, s3, s4, s5, s6, s7, s8, s9, s10
from ..errors import (
    AlarmError,
    ArchaeoPairsError,
    E101MediaMissingError,
    E102ContractViolationError,
    E400OcrAllFailError,
    E1000ServiceUnavailableError,
    HardConstraintError,
)

NodeFn = Callable[[dict], dict]


def _guard(fn: NodeFn) -> NodeFn:
    def wrapped(st: dict) -> dict:
        try:
            return fn(st)
        except AlarmError as exc:
            return {"alarms": [exc.code], "status": "PENDING_REVIEW"}
        except HardConstraintError:
            return {"alarms": ["E007"], "status": "PENDING_REVIEW"}
        except E400OcrAllFailError:
            # OCR 全失败（S5 识别器）→ 链③缺失降级（错误码字典（§6.4）E400）
            return {"seq_annotations": [], "scale_annotations": [], "orientation": "h",
                    "degraded": True}
        except E1000ServiceUnavailableError as exc:
            if getattr(exc, "service", "") == "ocr":
                # OCR 服务熔断 → 同链③缺失降级
                return {"seq_annotations": [], "scale_annotations": [], "orientation": "h",
                        "degraded": True}
            return {"status": "PENDING_REVIEW", "exclude_reason": exc.code}
        except (E101MediaMissingError, E102ContractViolationError) as exc:
            return {"status": "EXCLUDED", "exclude_reason": exc.code}
        except ArchaeoPairsError as exc:
            return {"status": "PENDING_REVIEW", "exclude_reason": exc.code}
    return wrapped


def build_nodes(svc: Services) -> dict[str, NodeFn]:
    """Node id 对齐《技术方案 V0.5.4》§3.4.1 节点映射表。"""
    raw = {
        "s1_index": lambda st: s1.run(st, svc),
        "s2_classify": lambda st: s2.run(st, svc),
        "s3_text": lambda st: s3.run(st, svc),
        "s4_segment": lambda st: s4.run(st, svc),
        "s5_recognize": lambda st: s5.run(st, svc),
        "s6_compose": lambda st: s6.run(st, svc),
        "s7_single": lambda st: s7.run(st, svc),
        "s8_assemble": lambda st: s8.run(st, svc),
        "s9_supervise": lambda st: s9.run(st, svc),
        "s10_review": lambda st: s10.run(st, svc),
    }
    return {name: _guard(fn) for name, fn in raw.items()}
