"""对象存储封装（MinIO/S3 兼容；P0 用本地文件系统实现，接口一致）。"""
from __future__ import annotations

import shutil
from pathlib import Path


class LocalObjectStore:
    """本地 FS 实现的对象存储（生产替换为 minio/S3）。"""

    def __init__(self, root: str | Path = "runs/objects") -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def put(self, key: str, src: str | Path) -> str:
        dst = self.root / key
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(str(src), str(dst))
        return str(dst)

    def get(self, key: str) -> Path:
        return self.root / key

    def exists(self, key: str) -> bool:
        return (self.root / key).exists()
