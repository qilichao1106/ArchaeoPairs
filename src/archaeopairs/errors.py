"""错误与异常体系（对齐《技术方案 V0.2》§6.4 错误码字典 E100–E1100）。

统一继承链：ArchaeoPairsError -> 各 E-code 异常。硬约束违规抛
HardConstraintError，不可被 Feature Flag 关闭。编排层统一捕获并映射为
状态转移（PENDING_REVIEW / FAILED / DEGRADED）。
"""
from __future__ import annotations


class ArchaeoPairsError(Exception):
    """基类：携带错误码与可重试标记。"""

    code = "E000"
    retryable = False

    def __init__(self, message: str = "", *, retryable: bool | None = None) -> None:
        super().__init__(message or self.__doc__ or self.code)
        if retryable is not None:
            self.retryable = retryable


class HardConstraintError(ArchaeoPairsError):
    """硬约束违规（掩膜禁 bbox/序号硬匹配/报警即停），不可关。"""

    code = "E090"


# ---- XML / 摄入 ----
class E100XmlParseError(ArchaeoPairsError):
    """DocBook 解析失败。"""
    code = "E100"


class E101MediaMissingError(ArchaeoPairsError):
    """媒体文件缺失。"""
    code = "E101"


class E102ContractViolationError(ArchaeoPairsError):
    """上游输入契约违约（caption 无 role / figure-title 缺失）。"""
    code = "E102"


# ---- S2 ----
class E200LowConfidenceClassifyError(ArchaeoPairsError):
    """图类判定低置信。"""
    code = "E200"


# ---- S3 ----
class E300NoteParseError(ArchaeoPairsError):
    """图注解析失败。"""
    code = "E300"


class E301LowConfidenceSplitError(ArchaeoPairsError):
    """正文切分低置信。"""
    code = "E301"


# ---- S4 ----
class E400OcrAllFailError(ArchaeoPairsError):
    """OCR 全失败（链③缺失→降级）。"""
    code = "E400"
    retryable = True


class E401OcrMissKeySeqError(ArchaeoPairsError):
    """OCR 漏读关键序号。"""
    code = "E401"


# ---- S5 ----
class E500ChainConflictError(ArchaeoPairsError):
    """三链冲突。"""
    code = "E500"


# ---- S6 ----
class E600SamFailError(ArchaeoPairsError):
    """SAM 失败。"""
    code = "E600"
    retryable = True


# ---- S7 ----
class E700PlateLayoutError(ArchaeoPairsError):
    """图版版面识别失败。"""
    code = "E700"


# ---- S8 ----
class E800GroupFailError(ArchaeoPairsError):
    """归组失败。"""
    code = "E800"


# ---- S9 ----
class E900SuperviseFailError(ArchaeoPairsError):
    """Supervisor 诊断失败。"""
    code = "E900"
    retryable = True


# ---- 网关 / 存储 ----
class E1000ServiceUnavailableError(ArchaeoPairsError):
    """VLM/SAM/OCR 服务不可用（服务级降级）。"""

    code = "E1000"
    retryable = True

    def __init__(self, message: str = "", *, service: str = "", retryable: bool | None = None) -> None:
        super().__init__(message, retryable=retryable)
        self.service = service


class E1100StorageError(ArchaeoPairsError):
    """磁盘满 / 写入失败。"""
    code = "E1100"


# ---- 异常报警（硬约束，§6.3 E001–E007），触发即 PENDING_REVIEW、禁输出 PNG ----
class AlarmError(HardConstraintError):
    """E001–E007 异常报警基类。"""

    code = "E000"


class E001SeqNoDrawingAlarm(AlarmError):
    """图注声明某 seq，但图面未找到标注该 seq 的线图。"""
    code = "E001"


class E002DrawingNoSeqAlarm(AlarmError):
    """图面存在标注 seq 的线图，但图注无对应声明。"""
    code = "E002"


class E003ScaleUnmatchedAlarm(AlarmError):
    """图面多个带序号比例尺，无法与任一线图 seq 对应。"""
    code = "E003"


class E004ScaleNoSeqAlarm(AlarmError):
    """某比例尺无序号且全图存在多个比例尺（三级规则第三级）。"""
    code = "E004"


class E005MultiNoSeqListAlarm(AlarmError):
    """图面存在多个器物线图，但图注无序号列表。"""
    code = "E005"


class E006MaskIncompleteAlarm(AlarmError):
    """密集排列器物共享公共基准线，分割后掩膜残缺。"""
    code = "E006"


class E007OtherHardConstraintAlarm(AlarmError):
    """附录 A 第二篇定义的其他硬约束场景。"""
    code = "E007"


ALARM_CLASSES: dict[str, type[AlarmError]] = {
    "E001": E001SeqNoDrawingAlarm, "E002": E002DrawingNoSeqAlarm,
    "E003": E003ScaleUnmatchedAlarm, "E004": E004ScaleNoSeqAlarm,
    "E005": E005MultiNoSeqListAlarm, "E006": E006MaskIncompleteAlarm,
    "E007": E007OtherHardConstraintAlarm,
}


ERROR_REGISTRY: dict[str, type[ArchaeoPairsError]] = {
    cls.code: cls
    for cls in [
        E100XmlParseError, E101MediaMissingError, E102ContractViolationError,
        E200LowConfidenceClassifyError, E300NoteParseError, E301LowConfidenceSplitError,
        E400OcrAllFailError, E401OcrMissKeySeqError, E500ChainConflictError,
        E600SamFailError, E700PlateLayoutError, E800GroupFailError, E900SuperviseFailError,
        E1000ServiceUnavailableError, E1100StorageError,
    ]
}
