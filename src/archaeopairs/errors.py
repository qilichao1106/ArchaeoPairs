# -*- coding: utf-8 -*-
"""错误码与异常定义（对应方案 §4 各 Agent 卡片 error_schema）。

约定：
- 任何不确定场景一律 fail-closed：抛出 ReviewRequired 或直接 halt，禁止猜测配对。
- ErrorCode 枚举与 schemas/vision_segments.schema.json 的 alarms 枚举保持一致。
"""
from enum import Enum


class ErrorCode(str, Enum):
    # A0 预处理
    E_XML_INVALID = "E_XML_INVALID"          # DocBook 结构校验失败 → halt
    E_FILE_MISSING = "E_FILE_MISSING"        # imagedata fileref 指向文件缺失 → 复核
    # A1b 正文
    E_REF_NOFIGURE = "E_REF_NOFIGURE"        # 正文引用未命中 figure → 低置信
    # A1c 聚合
    E_TEXT_SIDE_MISSING = "E_TEXT_SIDE_MISSING"  # 双文本源均失败 → A4 走 image_only
    # A4 融合
    E_SEQ_UNRESOLVABLE = "E_SEQ_UNRESOLVABLE"    # 三源冲突不可解 → 复核（禁猜测）
    # A5 分割（与 vision_segments.schema.json alarms 对齐）
    E_MASK_INCOMPLETE = "E_MASK_INCOMPLETE"      # 掩膜轮廓不完整 → 复核
    E_SCALE_AMBIGUOUS = "E_SCALE_AMBIGUOUS"      # 多比例尺无序号归属（三级报警）
    E_SEQ_NOTFOUND = "E_SEQ_NOTFOUND"            # 图底有序号但图面找不到对应线图
    E_NOSCOPE_MULTI = "E_NOSCOPE_MULTI"          # 无序号多器物图 → 复核
    # A6 彩板
    E_PLATE_MISALIGN = "E_PLATE_MISALIGN"        # 条目号三方对齐失败 → 复核
    # A7 组装
    E_KEY_MISSING = "E_KEY_MISSING"              # join 键缺失 → 复核
    E_SCHEMA_VIOLATION = "E_SCHEMA_VIOLATION"    # 产物 schema 违例 → halt


class AgentError(Exception):
    """Agent 执行错误。fatal=True 时 halt 整个 figure；否则入复核队列。"""

    def __init__(self, code: ErrorCode, message: str, fatal: bool = False):
        super().__init__(f"[{code.value}] {message}")
        self.code = code
        self.fatal = fatal


class ReviewRequired(Exception):
    """触发人工复核（interrupt）：编排层捕获后持久化现场并置 blocked_review。"""

    def __init__(self, code: ErrorCode, kind: str, payload_ref: str, message: str = ""):
        super().__init__(f"[{code.value}] {message}")
        self.code = code
        self.kind = kind              # mapping / mask / text / qc（对应 review_tasks.kind）
        self.payload_ref = payload_ref
