"""错误与异常体系（对齐《技术方案 V0.1》§6.4 错误码字典 E100–E1100）。

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


class E1100StorageError(ArchaeoPairsError):
    """磁盘满 / 写入失败。"""
    code = "E1100"


# ---- 异常报警（硬约束，§6.3 E001–E007） ----
class AlarmError(HardConstraintError):
    """E001–E007 异常报警，触发即 PENDING_REVIEW、禁输出 PNG。"""

    code = "E001"


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
