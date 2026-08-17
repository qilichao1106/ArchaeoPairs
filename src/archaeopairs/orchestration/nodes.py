"""各 Node 函数：输入 State 键 -> 调用智能体 -> 输出 State 键（节点映射表（§3.4.1）映射）。

统一异常拦截（多智能体协作架构（§3.1）/ 异常报警字典（§6.3）/ 服务级降级与熔断（§3.7））：
* AlarmError/HardConstraintError → PENDING_REVIEW + 报警码（报警即停、禁输出 PNG）；
* E400 OCR 全失败 / E1000(OCR) 熔断 → 链③缺失降级，按降级矩阵继续；
* E1000(VLM/SAM) 熔断 → PENDING_REVIEW（批次挂起由调度层处理）；
* E102/E101 摄入违约 → EXCLUDED；
* CostCapExceeded → PENDING_REVIEW。
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
from ..gateway import CostCapExceeded

NodeFn = Callable[[dict], dict]


def _guard(fn: NodeFn) -> NodeFn:
    def wrapped(st: dict) -> dict:
        try:
            return fn(st)
        except AlarmError as exc:
            return {"alarms": [exc.code], "status": "PENDING_REVIEW"}
        except HardConstraintError:
            return {"alarms": ["E007"], "status": "PENDING_REVIEW"}
        except CostCapExceeded:
            return {"status": "PENDING_REVIEW", "exclude_reason": "cost_cap"}
        except E400OcrAllFailError:
            # OCR 全失败 → 链③缺失降级（错误码字典（§6.4）E400）
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
    """Node 名对齐《编码开发要求》4.1 映射表。"""
    raw = {
        "parse_report": lambda st: s1.run(st, svc),
        "classify_figure": lambda st: s2.run(st, svc),
        "parse_text": lambda st: s3.run(st, svc),
        "parse_image": lambda st: s4.run(st, svc),
        "fuse": lambda st: s5.run(st, svc),
        "segment": lambda st: s6.run(st, svc),
        "parse_single": lambda st: s7.run(st, svc),
        "assemble": lambda st: s8.run(st, svc),
        "supervise": lambda st: s9.run(st, svc),
        "bridge_review": lambda st: s10.run(st, svc),
    }
    return {name: _guard(fn) for name, fn in raw.items()}
