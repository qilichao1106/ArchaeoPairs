"""数据契约（对齐《技术方案 V0.3》核心数据结构（§6.1）/ State Schema（§3.4.2））。

八个核心数据结构 + 子模型用 pydantic v2 定义；GraphState 为 LangGraph
全局 State（TypedDict），承载跨节点共享字段。节点局部变量不进 State。
整改：FusedMapping 支持 seq→多 artifact（同号/区间拆 Pair）；新增
alarms/degraded/body_paras 支撑硬约束报警与链②正文切分。
"""
from __future__ import annotations

from typing import Literal, Optional, TypedDict

from pydantic import BaseModel, Field

# ---- 枚举（图类判定器（§4.2）/ 融合仲裁器（§4.5）/ 状态机（§6.2），落入 Literal） ----
ImageType = Literal[
    "single_line", "multi_line", "line_drawing",
    "plate_artifact", "plate_scene", "multi_plate", "discarded",
]
CaseType = Literal[
    "rule_a", "rule_b", "split_same_seq", "range_split", "seq_missing",
    "single_line", "single_plate", "discarded",
]
FigureStatus = Literal[
    "INIT", "PARSED", "CLASSIFIED", "CLASSIFIED_PLATE", "ALIGNED",
    "SEG_DIAGNOSED", "SEGMENTED", "ASM_VALIDATED", "OUTPUT",
    "PENDING_REVIEW", "EXCLUDED", "FAILED", "DEGRADED",
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
    """S4 图内序号标注（图像源解析器（§4.4））。"""
    text: str
    bbox: tuple[int, int, int, int]
    group: Optional[list[int]] = None


class ScaleAnnotation(BaseModel):
    """S4 比例尺标注（图像源解析器（§4.4））。"""
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
    """S5 融合仲裁输出（融合仲裁器（§4.5））。seq→多 artifact 以支撑同号/区间拆 Pair。"""
    seq_to_artifacts: dict[str, list[str]] = Field(default_factory=dict)
    caption_artifacts: list[str] = Field(
        default_factory=list,
        description="图题兜底器物号（图题器物号兜底识别（§2.2.5））：图注解析不出器物号时自图题抽取")
    case_type: CaseType
    available_chains: tuple[bool, bool, bool] = (False, False, False)
    confidence: float = Field(0.0, ge=0, le=1)
    conflicts: list[str] = Field(default_factory=list, description="链① vs 链③ 序号冲突")


class MaskRecord(BaseModel):
    """S6 掩膜记录（视觉分割器（§4.6），掩膜三件套）。"""
    mask_rle: str
    bbox: tuple[int, int, int, int]
    area: int
    seq: Optional[str] = None
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


class DiagnosticReport(BaseModel):
    """S9 诊断报告（Supervisor VLM（§4.9）/ Supervisor-Worker Loop（§5.2））。"""
    trace_id: str
    report_id: str
    figure_id: str
    defect_list: list[Defect] = Field(default_factory=list)
    target_agent: Optional[Literal["S3", "S4", "S6", "S8"]] = None
    correction_action: Optional[str] = None
    action_params: dict = Field(default_factory=dict)
    expected_result: Optional[str] = None
    iteration: int = Field(0, ge=0, le=3)
    escalation_level: int = Field(1, ge=1, le=3, description="逐级升级档位")


class PairRecord(BaseModel):
    """S8 Pair 产出（匹配组装器（§4.8）/ 输出契约（§7））。"""
    book_id: str
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
    iteration: int = 0
    exclude_reason: Optional[str] = None
    trace_id: str = ""


class PipelineFlags(BaseModel):
    """Feature Flag（功能开关与配置管理（§7.5））。硬约束不在此、不可关。"""
    s3_llm_confirm: bool = True
    s9_loop: bool = True
    cross_fig_merge: bool = False
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
    body_paras: list[dict]
    image_type: Optional[ImageType]
    note_items: list[dict]
    caption_artifacts: list[str]
    single_artifacts: list[dict]
    text_artifacts: list[dict]
    seq_annotations: list[dict]
    scale_annotations: list[dict]
    orientation: Optional[str]
    fused: Optional[dict]
    case_type: Optional[CaseType]
    confidence: float
    degraded: bool
    alarms: list[AlarmCode]
    masks: list[dict]
    assembled: bool
    pair_records: list[dict]
    diagnostic: Optional[dict]
    iteration: int
    defect_history: list[int]
    no_improve: bool
    status: FigureStatus
    exclude_reason: Optional[str]
    trace_id: str
    flags: dict
