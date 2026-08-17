"""对象存储封装（MinIO/S3 兼容；P0 用本地文件系统实现，接口一致）。

安全：key 经校验禁止路径穿越（图像源解析器（§4.4）/ 存储安全（§9.6））；写入采用 tmp+rename 原子语义（§5.8）。
"""
from __future__ import annotations

import os
import shutil
from pathlib import Path

from ..errors import E1100StorageError


class LocalObjectStore:
    """本地 FS 实现的对象存储（生产替换为 minio/S3）。"""

    def __init__(self, root: str | Path = "runs/objects") -> None:
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def _safe(self, key: str) -> Path:
        if not key or key.startswith(("/", "\\")) or ".." in key.split("/"):
            raise E1100StorageError(f"非法对象键: {key}")
        dst = (self.root / key).resolve()
        if not str(dst).startswith(str(self.root) + os.sep):
            raise E1100StorageError(f"路径穿越: {key}")
        return dst

    def put(self, key: str, src: str | Path) -> str:
        dst = self._safe(key)
        dst.parent.mkdir(parents=True, exist_ok=True)
        tmp = dst.with_suffix(dst.suffix + ".tmp")
        shutil.copy2(str(src), str(tmp))
        os.replace(str(tmp), str(dst))
        return str(dst)

    def put_bytes(self, key: str, data: bytes) -> str:
        dst = self._safe(key)
        dst.parent.mkdir(parents=True, exist_ok=True)
        tmp = dst.with_suffix(dst.suffix + ".tmp")
        tmp.write_bytes(data)
        os.replace(str(tmp), str(dst))
        return str(dst)

    def get(self, key: str) -> Path:
        return self._safe(key)

    def exists(self, key: str) -> bool:
        return self._safe(key).exists()
