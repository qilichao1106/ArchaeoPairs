"""配置加载（pydantic-settings + YAML，对齐《技术方案 V0.4》正文切分算法（§5.5）/ 功能开关与配置管理（§7.5））。

thresholds.yaml（阈值常量）与 flags.yaml（Feature Flag）。真实配置不入库，
提交 *.example.yaml。缺失时回退到内置默认值，保证 P0 可直接运行。
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

import yaml
from pydantic import BaseModel, Field

from ..state import PipelineFlags

_CONFIG_DIR = Path(__file__).resolve().parents[3] / "config"


class Thresholds(BaseModel):
    mask_iou_target: float = 0.85
    seq_match_accuracy_target: float = 0.95
    artifact_naming_accuracy_target: float = 0.98
    text_recall_target: float = 0.92
    max_iteration: int = 3
    no_improve_rounds: int = 2
    confidence: dict[str, float] = Field(default_factory=lambda: {
        "chain123": 0.95, "chain12": 0.85, "chain13": 0.85,
        "chain23": 0.70, "chain2": 0.60, "chain3": 0.50,
    })
    pending_pause_ratio: float = 0.20
    # 能力接口契约（§5.1.4/T25）：超时可配；模型网关按 Worker 配额限流（§6.3）
    timeouts: dict[str, float] = Field(default_factory=lambda: {
        "vlm": 30.0, "sam": 20.0, "ocr": 10.0,
    })
    rate_limits: dict[str, float] = Field(default_factory=dict)  # {service: QPS}，空=不限


def _load_yaml(name: str) -> dict:
    path = _CONFIG_DIR / name
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def load_thresholds() -> Thresholds:
    raw = _load_yaml("thresholds.yaml")
    # 展平 yaml 结构到扁平字段
    flat: dict = {}
    if "mask" in raw:
        flat["mask_iou_target"] = raw["mask"].get("iou_target", flat.get("mask_iou_target"))
    if "loop" in raw:
        flat["max_iteration"] = raw["loop"].get("max_iteration", 3)
        flat["no_improve_rounds"] = raw["loop"].get("no_improve_rounds", 2)
    if "confidence" in raw:
        flat["confidence"] = raw["confidence"]
    if "review" in raw:
        flat["pending_pause_ratio"] = raw["review"].get("pending_pause_ratio", 0.20)
    if "capability" in raw:
        flat["timeouts"] = raw["capability"].get("timeouts", flat.get("timeouts"))
        flat["rate_limits"] = raw["capability"].get("rate_limits", flat.get("rate_limits"))
    return Thresholds(**{k: v for k, v in flat.items() if v is not None})


def load_flags() -> PipelineFlags:
    raw = _load_yaml("flags.yaml")
    return PipelineFlags(**{k: v for k, v in raw.items() if k in PipelineFlags.model_fields})


class Settings(BaseModel):
    """运行期设置（环境变量注入敏感项，不入库）。"""
    database_url: str = "sqlite:///archaeopairs.sqlite3"
    object_store_endpoint: Optional[str] = None
    books_dir: str = "books"
