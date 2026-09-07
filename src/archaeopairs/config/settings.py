"""配置加载（pydantic-settings + YAML，对齐《技术方案 V0.5.1》正文切分算法（§5.5）/ 功能开关与配置管理（§7.5））。

thresholds.yaml（阈值常量）与 flags.yaml（Feature Flag）。真实配置不入库，
提交 *.example.yaml。缺失时回退到内置默认值，保证 P0 可直接运行。
"""
from __future__ import annotations

from pathlib import Path
from typing import Literal, Optional

import yaml
from pydantic import BaseModel, Field

from ..state import PipelineFlags

try:  # .env 加载（VL API key 等；缺库时静默跳过，环境变量仍可手工注入）
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover
    load_dotenv = None

_CONFIG_DIR = Path(__file__).resolve().parents[3] / "config"
_REPO_ROOT = Path(__file__).resolve().parents[3]


def _load_dotenv() -> None:
    """加载仓库根 .env（VOLCENGINE_API_KEY 等）。幂等；缺 python-dotenv 时跳过。"""
    if load_dotenv is not None:
        load_dotenv(_REPO_ROOT / ".env")


class Thresholds(BaseModel):
    mask_iou_target: float = 0.85
    seq_match_accuracy_target: float = 0.95
    artifact_naming_accuracy_target: float = 0.98
    text_recall_target: float = 0.92
    # V0.5.4：max_iteration/no_improve_rounds 移除（S9 纯质检，无迭代回环）
    confidence: dict[str, float] = Field(default_factory=lambda: {
        "chain123": 0.95, "chain12": 0.85, "chain13": 0.85,
        "chain23": 0.70, "chain2": 0.60, "chain3": 0.50,
    })
    pending_pause_ratio: float = 0.20
    # 能力接口契约（§5.1.4/T25）：超时可配；模型网关按 Worker 配额限流（§6.3）
    timeouts: dict[str, float] = Field(default_factory=lambda: {
        "vlm": 30.0, "sam": 20.0, "ocr": 10.0, "vl": 60.0,
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
        # V0.5.4：loop 节移除（S9 纯质检无迭代），保留解析兼容但不再生效
        pass
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


class ProviderSettings(BaseModel):
    """能力 provider 选择与参数（providers.yaml，缺省 VL 启用 ark）。

    provider 段选实现：sam: mock|cv（本地轮廓掩膜，无远程模型）；ocr: mock|paddle；
    vl: mock|ark（火山方舟 VL 三态仲裁）；compositor: mock|pixel（真像素合成）。
    cv_seg/paddle/vl_config/assembly/compose 为对应实现的透传参数。
    """
    sam: Literal["mock", "cv"] = "mock"
    ocr: Literal["mock", "paddle"] = "mock"
    vl: Literal["mock", "ark"] = "ark"
    compositor: Literal["mock", "pixel"] = "mock"
    cv_seg: dict = Field(default_factory=lambda: {"dilate_k": 5, "min_area": 15.0})
    paddle: dict = Field(default_factory=dict)
    vl_config: dict = Field(default_factory=lambda: {
        "preset": "glm-53-flash", "cache_dir": "runs/vl_cache", "strict": True,
    })
    assembly: dict = Field(default_factory=dict)
    compose: dict = Field(default_factory=dict)


def load_providers() -> ProviderSettings:
    """读取 providers.yaml（不存在时其余能力 mock，VL 默认 ark）并预载 .env。"""
    _load_dotenv()
    raw = _load_yaml("providers.yaml")
    section = dict(raw.get("provider") or {})
    params = {k: raw.get(k) for k in
              ("cv_seg", "paddle", "vl_config", "assembly", "compose") if raw.get(k)}
    return ProviderSettings(**section, **params)


class Settings(BaseModel):
    """运行期设置（环境变量注入敏感项，不入库）。"""
    database_url: str = "sqlite:///archaeopairs.sqlite3"
    object_store_endpoint: Optional[str] = None
    books_dir: str = "books"
    providers: ProviderSettings = Field(default_factory=ProviderSettings)
