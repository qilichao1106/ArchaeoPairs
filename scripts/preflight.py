#!/usr/bin/env python3
"""协作基线预检（stdlib only）：工具、配置、目录、密钥存在性。

退出 0 = 全部通过；1 = 有失败项。不打印任何密钥值。
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RESULTS: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    RESULTS.append((name, bool(ok), detail))


def which(tool: str) -> str:
    return shutil.which(tool) or ""


def version(cmd: list[str]) -> str:
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=20)
        return (p.stdout or p.stderr).strip().splitlines()[0] if (p.stdout or p.stderr) else ""
    except Exception:
        return ""


def user_env(name: str) -> str:
    v = os.environ.get(name, "")
    if v:
        return v
    if os.name == "nt":
        try:
            import winreg
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Environment") as k:
                return str(winreg.QueryValueEx(k, name)[0])
        except Exception:
            return ""
    return ""


# ---- 工具 ----
for tool in ("git", "python", "codex", "dsh", "claude"):
    check(f"tool:{tool}", bool(which(tool)), which(tool))

if which("codex"):
    check("version:codex", True, version(["codex", "--version"]))
if which("dsh"):
    check("version:dsh", True, version(["dsh", "--version"]))

# ---- 目录/文件 ----
required = [
    ".git", "books", "v1",
    "AGENTS.md", "CLAUDE.md", "Plan.md", "IMPLEMENT.md", ".gitignore",
    "docs/协作开发方式.md", "docs/mh/execution-baseline.md", "docs/mh/env.md",
    "collab/board.json", "collab/events.jsonl", "collab/cards",
    "collab/inbox/codex", "collab/inbox/dsh", "collab/inbox/claude",
    "collab/artifacts", "scripts/preflight.py",
]
for rel in required:
    check(f"path:{rel}", (ROOT / rel).exists())

# ---- codex 配置（只读事实，不打印密钥） ----
codex_cfg = Path.home() / ".codex" / "config.toml"
if codex_cfg.is_file():
    t = codex_cfg.read_text(encoding="utf-8", errors="ignore")
    check("codex:model", 'model = "deepseek-v4.1-flash-1017"' in t)
    check("codex:provider", 'model_provider = "maas_deepseek"' in t)
    check("codex:wire_api", 'wire_api = "responses"' in t)
    check("codex:base_url", "llm-1pxqd38dwq24f1gn.cn-beijing.maas.aliyuncs.com" in t)
    check("codex:token-present", "experimental_bearer_token" in t)
else:
    check("codex:config", False, str(codex_cfg))

# ---- dsh 配置 ----
dsh_patch = Path.home() / ".dsh" / "profiles" / "headless" / "cordis.patch.yml"
if dsh_patch.is_file():
    t = dsh_patch.read_text(encoding="utf-8", errors="ignore")
    check("dsh:base_url", "llm-1pxqd38dwq24f1gn.cn-beijing.maas.aliyuncs.com" in t)
    check("dsh:model", "deepseek-v4.1-flash-1017" in t)
    check("dsh:default-model", "provider: dashscope" in t)
else:
    check("dsh:config", False, str(dsh_patch))

# ---- 密钥（只看存在性/长度，不打印值） ----
key = user_env("DASHSCOPE_API_KEY")
check("env:DASHSCOPE_API_KEY", len(key) > 0, f"len={len(key)}")
check("key:looks-valid", key.startswith("sk-") if key else False)

# ---- 仓库内不得出现密钥明文 ----
leaks: list[str] = []
for p in ROOT.rglob("*"):
    if not p.is_file() or "v1" in p.parts or "books" in p.parts:
        continue
    if p.suffix.lower() in {".png", ".jpg", ".jpeg", ".docx", ".sqlite", ".pyc"}:
        continue
    try:
        txt = p.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        continue
    if ("sk-" + "ws-") in txt:
        leaks.append(str(p.relative_to(ROOT)))
check("repo:no-api-key", not leaks, ", ".join(leaks) if leaks else "clean")

# ---- 输出 ----
failed = [r for r in RESULTS if not r[1]]
for name, ok, detail in RESULTS:
    print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f"  {detail}" if detail else ""))
print(f"\n{len(RESULTS) - len(failed)} passed, {len(failed)} failed")
sys.exit(0 if not failed else 1)