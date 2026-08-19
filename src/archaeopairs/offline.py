"""最小离线运行入口：仅单器物（single_line/single_plate），零模型推理。

零模型推理：VLM/SAM/OCR 用严格 No-op stub——**一旦被任一节点调用即抛
NotImplementedError**。S3~S6（multi_line 主通路, V0.5.3 已恢复）需模型，故离线入口
预筛时把 multi_line / multi_plate / discarded 直接标记 SKIPPED_OFFLINE，不进入图；
只有单器物走 ``S1→S2→S7→S8→S10``（整图即 Pair）。

写图可选：缺省只出「记录级 Pair」（image_path 为文件名、不落盘）；
``write_images=True`` 时注入 object_store+compositor，把整图 Pair PNG（拷贝 media 原图）
写盘。
"""
from __future__ import annotations

import uuid
from pathlib import Path

from .agents import Services
from .capability.compose import MockCompositor
from .config import load_flags, load_thresholds
from .gateway import Gateway
from .orchestration import build_graph
from .parsers import s1_xml, s3_note
from .parsers.image_classify import classify_image_type
from .storage import LocalObjectStore


# --------------------------------------------------------------------------- #
# No-op 模型 stub：被调用即抛错（零模型保证）
# --------------------------------------------------------------------------- #
class NoOpVLM:
    """离线占位 VLM——一旦调用即失败，杜绝单器物路径触碰 VLMTrait。"""

    def classify(self, *, image_ref, caption, figure_note=None, trace_id):
        raise NotImplementedError("offline: NoOpVLM.classify 不得在非 multi_line 路径被调用")

    def diagnose(self, *, image_ref, context, trace_id):
        raise NotImplementedError("offline: NoOpVLM.diagnose 不得在非 multi_line 路径被调用")

    def confirm_text(self, *, artifact_id, text, context, trace_id):
        raise NotImplementedError("offline: NoOpVLM.confirm_text 不得在非 multi_line 路径被调用")


class NoOpSAM:
    def segment(self, *, image_ref, prompts, trace_id):
        raise NotImplementedError("offline: NoOpSAM.segment 不得在非 multi_line 路径被调用")


class NoOpOCR:
    def read(self, *, image_ref, regions, trace_id):
        raise NotImplementedError("offline: NoOpOCR.read 不得在非 multi_line 路径被调用")


class OfflineGateway(Gateway):
    """离线网关：拦截一切 `gateway.call`（VLM/SAM/OCR 全经此入口）。"""

    def call(self, service, fn, *, figure_id, trace_id, **kwargs):  # type: ignore[override]
        raise NotImplementedError(f"offline: gateway.call({service}) 不得在单器物路径被调用")


def minimal_services(thresholds, flags, object_store=None, compositor=None) -> Services:
    """最小离线 Services：No-op 模型 + 去重注册表 + （可选）对象存储/合成器。"""
    return Services(
        vlm=NoOpVLM(),
        sam=NoOpSAM(),
        ocr=NoOpOCR(),
        gateway=OfflineGateway(),
        thresholds=thresholds,
        flags=flags,
        object_store=object_store,
        compositor=compositor,
        review_bridge=None,  # 离线不建复核任务
        name_registry={},    # S8 文件名去重注册表
    )


# --------------------------------------------------------------------------- #
# 驱动
# --------------------------------------------------------------------------- #
def _find_data_xml(books_dir: Path, book: str) -> Path:
    for p in (books_dir / book).rglob("data.xml"):
        return p
    raise FileNotFoundError(f"books/{book}/data.xml not found")


def _book_has_artifact(body_paras: list[dict], figures) -> bool:
    for p in body_paras:
        if s3_note.ARTIFACT_RE.search(p.get("text", "")) or s3_note.COMPONENT_RE.search(p.get("text", "")):
            return True
    for fig in figures:
        if fig.figure_note and (s3_note.ARTIFACT_RE.search(fig.figure_note)
                                or s3_note.COMPONENT_RE.search(fig.figure_note)):
            return True
        if s3_note.extract_caption_artifacts(fig.caption):
            return True
    return False


def run_single_offline(book: str, books_dir: str = "books", limit: int | None = None,
                       write_images: bool = False, objects_dir: str | Path = "runs/objects") -> dict:
    """仅跑非 multi_line 的最小编发起，零模型调用（经真实 graph 路由验证）。"""
    from . import naming
    from .agents import s3 as s3_agent

    root = Path(books_dir)
    xml = _find_data_xml(root, book)
    figures, ground, violations = s1_xml.parse_report(xml, book)
    body_paras = s1_xml.parse_body(xml)
    if limit:
        figures = figures[:limit]

    if not _book_has_artifact(body_paras, figures):
        return {"figures": len(figures), "violations": violations, "pairs": 0,
                "statuses": {}, "by_image_type": {}, "excluded_reason": "no_artifact_id"}

    thresholds = load_thresholds()
    flags = load_flags()
    object_store = LocalObjectStore(objects_dir) if write_images else None
    compositor = MockCompositor(object_store) if write_images and object_store else None
    svc = minimal_services(thresholds, flags, object_store, compositor)

    app = build_graph(svc, checkpointer=None)  # 内存跑批，不落库
    statuses: dict[str, str] = {}
    by_itype: dict[str, dict[str, int]] = {}
    records: list[dict] = []
    for fig in figures:
        # 离线单器物入口：预筛只跑单器物路径；multi_line 走 S3~S6 需模型 → 直接标记跳过
        # （不触碰 No-op 模型），multi_plate/discarded 归档。
        img = Path(str(xml.parent)) / str(fig.fileref) if fig.fileref else None
        itype = classify_image_type(fig.caption, fig.figure_note, str(img) if img and img.is_file() else None)
        by_itype.setdefault(itype, {}).setdefault("SKIPPED_OFFLINE", 0)
        if itype not in {"single_line_artifact", "single_plate_artifact"}:
            # 多器物线图/彩图/丢弃：离线(零模型)入口不处理 → 归类跳过
            by_itype[itype]["SKIPPED_OFFLINE"] += 1
            statuses[fig.figure_id] = "SKIPPED_OFFLINE"
            continue
        note_items = s3_note.parse_note(fig.figure_note or "")
        note_arts = {a for it in note_items for a in it.artifact_ids}
        caption_arts = [] if note_arts else s3_note.extract_caption_artifacts(fig.caption)
        fig_number = naming.extract_fig_number(fig.caption)
        paras = s3_agent.select_paras(body_paras, note_arts | set(caption_arts), fig_number)
        init = {
            "book_id": fig.book_id, "figure_id": fig.figure_id, "fileref": fig.fileref,
            "caption": fig.caption, "figure_note": fig.figure_note,
            "book_has_artifact": True, "image_base": str(xml.parent), "body_paras": paras,
            "iteration": 0, "defect_history": [], "assembled": False,
            "trace_id": str(uuid.uuid4()), "flags": flags.model_dump(), "status": "INIT",
        }
        result = app.invoke(init)
        status = result.get("status", "?")
        statuses[fig.figure_id] = status
        by_itype.setdefault(itype, {}).setdefault(status, 0)
        by_itype[itype][status] += 1
        records.extend(result.get("pair_records", []))

    return {"figures": len(figures), "violations": violations, "pairs": len(records),
            "statuses": statuses, "by_image_type": by_itype,
            "records": records}


def image_link(image_path: str, objects_dir: str | Path = "runs/objects") -> str:
    """图片本地链接：runs/objects/<image_path>（P0 对象存储本地实现，接口同 S3）。"""
    return str(Path(objects_dir) / image_path)
