"""Services 构造工厂：按 ProviderSettings 选择 mock/真实 provider。

视觉/合成能力默认 mock（P0 测试与离线路径不变）；VL 默认 ark，
providers.yaml / CLI --real 切真实实现。
真实 provider（providers.py 的 CvSegmenter/PaddleOCRReader/VlArbiterService 与
compose.py 的 PixelCompositor）延迟导入——mock 缺省路径不触发视觉依赖加载。
"""
from __future__ import annotations

import os

from ..agents import Services
from ..config import Thresholds
from ..config.settings import ProviderSettings
from ..gateway import Gateway
from ..state import PipelineFlags
from ..storage.object_store import LocalObjectStore
from . import MockOCR, MockSAM, MockVLM
from .compose import MockCompositor


def build_services(*, ground: dict, thresholds: Thresholds, flags: PipelineFlags,
                   providers: ProviderSettings | None = None,
                   object_store: LocalObjectStore | None = None,
                   vl_enabled: bool = True) -> Services:
    """按 provider 配置构造 Services。

    vl_enabled=False（CLI --no-vl）强制 vl_arbiter=None（纯 CV+OCR 真实链路）。
    vlm 槽位（S2 classify / S9 diagnose）暂保持 MockVLM（分类本就像素确定性，
    S9 真实化为后续任务）。
    """
    p = providers or ProviderSettings()

    sam = MockSAM(ground) if p.sam == "mock" else _build_cv_segmenter(p)
    ocr = MockOCR(ground) if p.ocr == "mock" else _build_paddle_ocr(p)
    vlm = MockVLM(ground)

    vl_arbiter = None
    if p.vl == "ark" and vl_enabled and os.environ.get("VOLCENGINE_API_KEY"):
        vl_arbiter = _build_vl_arbiter(p)

    compositor = None
    if object_store is not None:
        compositor = (MockCompositor(object_store) if p.compositor == "mock"
                      else _build_pixel_compositor(object_store, p))

    gateway = Gateway(timeouts=thresholds.timeouts, rate_limits=thresholds.rate_limits)
    return Services(vlm=vlm, sam=sam, ocr=ocr, gateway=gateway,
                    thresholds=thresholds, flags=flags,
                    object_store=object_store, compositor=compositor,
                    vl_arbiter=vl_arbiter, assembly_params=dict(p.assembly),
                    compose_params=dict(p.compose), ground=ground)


def _build_cv_segmenter(p: ProviderSettings):
    from .providers import CvSegmenter  # 延迟导入：mock 路径不加载视觉依赖

    return CvSegmenter(**p.cv_seg)


def _build_paddle_ocr(p: ProviderSettings):
    from .providers import PaddleOCRReader

    return PaddleOCRReader(**p.paddle)


def _build_vl_arbiter(p: ProviderSettings):
    from .providers import VlArbiterService

    return VlArbiterService(**p.vl_config)


def _build_pixel_compositor(store: LocalObjectStore, p: ProviderSettings):
    from .compose import PixelCompositor

    return PixelCompositor(store, **p.compose)
