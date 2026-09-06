"""数据契约（对齐《技术方案 V0.5.4》核心数据结构（§6.1）/ State Schema（§3.4.2））。

八个核心数据结构 + 子模型用 pydantic v2 定义；GraphState 为 LangGraph
全局 State（TypedDict），承载跨节点共享字段。节点局部变量不进 State。
V0.5.4：S4 视觉分割器输出原子掩膜（atom_masks），S5 识别器产出链③，
S6 组装器承接融合仲裁与组装成图；S9 纯质检（QCReport：defect_list +
qc_verdict + evidence），移除 iteration/defect_history/target_agent 等
回环字段（诊断修正回环删除，不合格转人工复核）。
"""
from __future__ import annotations

from typing import Literal, Optional, TypedDict

from pydantic import BaseModel, Field

# ---- 枚举（图类判定器（§4.2）/ 融合仲裁器（§4.5）/ 状态机（§6.2），落入 Literal） ----
# V0.4.1 五分类重构：判定以 XML 器物号个数为主（0→discarded；1→单器件；N≥2→多器件）；
# 线/彩家族由像素统计（line/gray/color）+ 拓图词组合判定（图像不可读时关键词 图版/圖版 兜底）；
# 枚举精简为 5 类（*_artifact），移除 line_drawing/plate_scene（plate_scene 并入 discarded，multi_plate 归档）。
ImageType = Literal[
    "single_line_artifact", "multi_line_artifact",
    "single_plate_artifact", "multi_plate_artifact", "discarded",
]
# case_type 口径（V0.5.2 评审 P1）：S6 域 5 值 + S7 单器物路径标记 2 值；
# multi_plate_artifact / discarded 在 S2 即归档，不产生 case_type，不在枚举内。
CaseType = Literal[
    "rule_a", "rule_b", "split_same_seq", "range_split", "seq_missing",
    "single_line_artifact", "single_plate_artifact",
]
# FigureStatus 口径（V0.5.4 对齐 §6.2）：S4 分割→SEGMENTED、S5 识别→RECOGNIZED、
# S6 组装→COMPOSED；移除 ALIGNED（融合仲裁并入 S6，不再有独立对齐态）。
FigureStatus = Literal[
    "INIT", "PARSED", "CLASSIFIED", "CLASSIFIED_SINGLE_LINE", "CLASSIFIED_PLATE",
    "SEGMENTED", "RECOGNIZED", "COMPOSED", "ASM_VALIDATED", "OUTPUT",
    "EXCLUDED", "PENDING_REVIEW", "FAILED", "DEGRADED",
]
DefectType = Literal[
    "under_seg", "over_seg", "mask_incomplete", "scale_mismatch", "seq_mismatch",
    "ocr_miss", "group_error", "text_split_err", "orientation_err", "view_split",
]
AlarmCode = Literal["E001", "E002", "E003", "E004", "E005", "E006", "E007"]

# ---- 子模型 ----
class NoteItem(BaseModel):
    """图注语法解析结果（图注解析器（§4.3.1））。"""
    seq: str = Field(description="图内序号原文，如 '1'/'1-4'/'2,3'")
    seq_list: list[int] = Field(default_factory=list)
    name: Optional[str] = None
    artifact_ids: list[str] = Field(default_factory=list)


class TextArtifact(BaseModel):
    """正文切分输出（正文切分决策树（§4.3.2））。"""
    artifact_id: str
    text: str
    source_para_ids: list[str] = Field(default_factory=list)
    markers: list[str] = Field(default_factory=list)
    figure_refs: list[str] = Field(default_factory=list)
    confidence: float = Field(1.0, ge=0, le=1)


class SeqAnnotation(BaseModel):
    """S5 序号标注（识别器（§4.5），链③）。"""
    text: str
    bbox: tuple[int, int, int, int]
    group: Optional[list[int]] = None


class ScaleAnnotation(BaseModel):
    """S5 比例尺标注（识别器（§4.5），链③）。"""
    text: str
    bbox: tuple[int, int, int, int]
    unit: str = "cm"
    value: Optional[float] = None
    seq_ref: Optional[str] = None


class ImageRef(BaseModel):
    """Pair 候选图像引用，保留同 artifact_id 的跨图/图版候选。"""
    path: str
    role: Literal["line_drawing", "plate", "candidate"] = "line_drawing"
    source_figure_id: Optional[str] = None
    confidence: Optional[float] = Field(None, ge=0, le=1)


class FusedMapping(BaseModel):
    """S6 融合仲裁输出（组装器（§4.6.3））。seq→多 artifact 以支撑同号/区间拆 Pair。"""
    seq_to_artifacts: dict[str, list[str]] = Field(default_factory=dict)
    caption_artifacts: list[str] = Field(
        default_factory=list,
        description="图题兜底器物号（图题器物号兜底识别（§2.2.5））：图注解析不出器物号时自图题抽取")
    case_type: CaseType
    available_chains: tuple[bool, bool, bool] = (False, False, False)
    confidence: float = Field(0.0, ge=0, le=1)
    conflicts: list[str] = Field(default_factory=list, description="链① vs 链③ 序号冲突")


class MaskRecord(BaseModel):
    """S4/S6 掩膜记录（视觉分割器（§4.4）/ 组装器（§4.6.1），掩膜三件套）。

    S4 输出原子掩膜：mask_rle/bbox/area，seq_id/artifact_id 留空待 S6 绑定；
    S6 经序号绑定/视图归组后定稿。
    """
    mask_rle: str
    bbox: tuple[int, int, int, int]
    area: int
    seq_id: Optional[str] = None
    artifact_id: Optional[str] = None
    note_text_region: Optional[str] = None
    scale_level: Literal[1, 2, 3] = 2
    incomplete: bool = Field(False, description="轮廓不完整/共享基准线残缺（E006）")
    aux_regions: dict = Field(default_factory=dict, description="并入掩膜的说明文字/比例尺区域")
    rotation: Optional[str] = Field(None, description="整图旋转校正标记")


class Defect(BaseModel):
    type: DefectType
    location: Optional[str] = None
    severity: Literal["low", "mid", "high"] = "mid"


class QCReport(BaseModel):
    """S9 质检报告（Supervisor VLM（§4.9）/ 质检报告契约（§5.2））。

    V0.5.4 纯质检门：defect_list 为空 → pass 经 S10 输出入库；非空 → reject
    随复核任务下发（§8.2）转人工复核，不驱动修正回环（无 target_agent/
    correction_action/iteration 等回环字段）。
    """
    trace_id: str
    report_id: str
    figure_id: str
    defect_list: list[Defect] = Field(default_factory=list)
    qc_verdict: Literal["pass", "reject"] = "pass"
    evidence: dict = Field(default_factory=dict, description="缺陷证据（随复核任务下发）")


class PairRecord(BaseModel):
    """S8 Pair 产出（匹配组装器（§4.8）/ 输出契约（§7））。

    figure_id 入逻辑键：当前版本单图独立输出、不跨图聚合，同一 artifact_id
    跨图出现时各图独立成 Pair（幂等键 = book_id+figure_id+artifact_id）。
    """
    book_id: str
    figure_id: str
    artifact_id: str
    image_path: str
    candidate_images: list[ImageRef] = Field(default_factory=list)
    image_merge_mode: Literal["line_only", "plate_only", "line_plus_plate", "multi_candidate"] = "line_only"
    description_text: Optional[str] = None
    provenance: dict = Field(default_factory=dict)
    quality_flags: dict = Field(default_factory=dict)


class FigureState(BaseModel):
    """单图生命周期状态（核心数据结构（§6.1）/ 状态机（§6.2））。"""
    book_id: str
    figure_id: str
    fileref: str
    caption: Optional[str] = None
    figure_note: Optional[str] = None
    parent_section_id: Optional[str] = None
    image_type: Optional[ImageType] = None
    status: FigureStatus = "INIT"
    exclude_reason: Optional[str] = None
    trace_id: str = ""


class PipelineFlags(BaseModel):
    """Feature Flag（功能开关与配置管理（§7.5））。硬约束不在此、不可关。

    V0.5.4：s9_loop 移除（S9 纯质检无自动回环）。
    """
    s3_llm_confirm: bool = True
    rotation_correct: bool = True
    require_human: bool = False


# ---- LangGraph 全局 State（shared 字段；node-local 不进） ----
class GraphState(TypedDict, total=False):
    book_id: str
    figure_id: str
    fileref: str
    caption: Optional[str]
    figure_note: Optional[str]
    parent_section_id: Optional[str]
    book_has_artifact: bool
    image_base: Optional[str]  # media 文件相对解析基准目录（fileref 相对此读取像素）
    body_paras: list[dict]
    image_type: Optional[ImageType]
    note_items: list[dict]
    caption_artifacts: list[str]
    single_artifacts: list[dict]
    text_artifacts: list[dict]
    atom_masks: list[dict]  # S4 原子掩膜；S6 绑定/归组后定稿（掩膜三件套）
    seq_annotations: list[dict]  # S5 链③序号
    scale_annotations: list[dict]  # S5 链③比例尺
    orientation: Optional[str]
    fused: Optional[dict]
    case_type: Optional[CaseType]
    confidence: float
    degraded: bool
    alarms: list[AlarmCode]
    qc_report: Optional[dict]  # S9 QCReport
    assembled: bool
    pair_records: list[dict]
    status: FigureStatus
    exclude_reason: Optional[str]
    trace_id: str
    flags: dict
