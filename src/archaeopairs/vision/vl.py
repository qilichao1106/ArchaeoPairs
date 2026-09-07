# archea_vl.py -> archaeopairs/vision/vl.py（extract 原型迁移，Step 4）
# 三层：配置层 PRESETS/VLConfig/load_config + 客户端层 VLClient
#       （OpenAI 兼容 HTTP + retry + cache + dump）+ 仲裁层 VlArbiter
#       （5 任务方法，三态 True/False/None）。
"""VL 兜底仲裁（配置层/客户端层/仲裁层 三层；OpenAI-compatible 协议）。

迁移说明（V0.5.5）：本模块自 legacy/extract/archea_vl.py 原样迁移
（prompt/配方不重写）；dotenv 自动加载移除（config/settings 统一加载），
CLI 调试入口不迁移（经 capability/providers.VlArbiterService 接入管线）。

模块分层（三层）：
  ┌─ 配置层   PRESETS / VLConfig / load_config（env + preset 名）
  ├─ 客户端层 VLClient（OpenAI-compatible HTTP + retry + cache + dump_resp
  │           + 按 stage 分桶统计）
  └─ 仲裁层   VlArbiter：全部任务逻辑（裁片 / prompt / 解析 / records /
              单 stage 启停 / 三态兜底）+ 组装管线（S6 E1–E4）的全部已用接口
              （_crop / enabled / judge_view_candidates_v2 / confirm_absorption /
               same_artifact / read_scale_prefix / read_serial_crops /
               n_calls / n_success / records / failed / stats）

一键切换模型（任意一种）：
  - 环境变量：VL_PRESET=doubao-vision VL_MODEL=... VL_BASE_URL=... VL_API_KEY=...
  - 代码：VlArbiter(preset="doubao-vision") 或 VlArbiter(config=VLConfig(...))

调试开关（环境变量）：
  VL_CACHE_DIR=<dir>  缓存 prompt+响应（JSON 文件）
  VL_REPLAY_ONLY=1    只读缓存，不再发请求（保证重跑一致）
  VL_DUMP_CROPS=<dir> 保存每个调用的裁片 PNG（便于人工复核）
  VL_DUMP_RESP=<dir>  保存每个调用的 prompt+raw_response（诊断 prompt）
  VL_VERBOSE=1        打印每个 stage 决策与延迟
  VL_TASK=name:on|off 单 stage 启停（view_rescue_v2/fragment_check/
                      serial_rescue/group_arb/scale_prefix）

用法：
  from archaeopairs.vision.vl import VlArbiter
  vl = VlArbiter(enabled=True)               # 默认：glm-5.3-flash + 火山 Ark
  vl = VlArbiter(enabled=True, preset="doubao-vision")
  flags, note = vl.judge_view_candidates_v2(bgr, [{"bbox": [...]}, ...])
  same,  note = vl.same_artifact(bgr, box_a, box_b, use_full=True)

依赖：cv2 / numpy / requests（标准 OpenAI 协议，无厂商 SDK 依赖）
"""

from __future__ import annotations

import base64
import hashlib
import json
import logging
import os
import re
import time
from pathlib import Path

import cv2
import numpy as np
import requests

_log = logging.getLogger("archaeopairs.vl")


# ============================================================================
# 配置层：预设 + 配置 dataclass + 加载器
# ============================================================================
# 预置模型清单（"模型名" -> 一键切换）。
# 协议均为 OpenAI 兼容 /chat/completions（image_url 多模态块）；
# api_key_env 为空表示无鉴权（Ollama/本地 vLLM 等）。
PRESETS: dict[str, dict] = {
    # 默认（2026-09-04 实测切换：火山方舟 Ark + glm-5.3-flash。
    # 调研结论见 _plan_tmp/vl_validation/：孪生判别对（弯钩vs印刷7）6/6，
    # 优于 qwen3-vl-plus 5/6 与 qwen3.8-max 4/6，且延迟 7-20s/批）
    "glm-53-flash": {
        "model": "glm-5.3-flash",
        "base_url": "https://ark.cn-beijing.volces.com/api/plan/v3",
        "api_key_env": "VOLCENGINE_API_KEY",
        "desc": "火山方舟 glm-5.3-flash（默认，2026-09 实测最优）",
    },
    "qwen3-vl-plus": {
        "model": "qwen3-vl-plus",
        "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "api_key_env": "DASHSCOPE_API_KEY",
        "desc": "阿里云百炼 qwen3-vl-plus（历史默认，备选）",
    },
    "qwen-vl-max": {
        "model": "qwen-vl-max",
        "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "api_key_env": "DASHSCOPE_API_KEY",
        "desc": "阿里云百炼 qwen-vl-max",
    },
    "qwen2.5-vl-72b": {
        "model": "Qwen/Qwen2.5-VL-72B-Instruct",
        "base_url": "https://api.siliconflow.cn/v1",
        "api_key_env": "SILICONFLOW_API_KEY",
        "desc": "SiliconFlow Qwen2.5-VL-72B",
    },
    "doubao-vision": {
        "model": "doubao-1-5-vision-pro-32k-250115",
        "base_url": "https://ark.cn-beijing.volces.com/api/v3",
        "api_key_env": "VOLCENGINE_API_KEY",
        "desc": "火山方舟 doubao-1.5-vision-pro",
    },
    "glm-4v": {
        "model": "glm-4v-plus",
        "base_url": "https://open.bigmodel.cn/api/paas/v4",
        "api_key_env": "ZHIPU_API_KEY",
        "desc": "智谱 BigModel glm-4v-plus",
    },
    "gpt-4o": {
        "model": "gpt-4o",
        "base_url": "https://api.openai.com/v1",
        "api_key_env": "OPENAI_API_KEY",
        "desc": "OpenAI gpt-4o（国际）",
    },
    "ollama-qwen2.5vl": {
        "model": "qwen2.5vl:7b",
        "base_url": "http://localhost:11434/v1",
        "api_key_env": None,
        "desc": "本地 Ollama qwen2.5vl（无鉴权）",
    },
    "vllm": {
        # model 由 VL_MODEL 提供；vLLM 起 OpenAI 兼容服务
        "model": None,
        "base_url": "http://localhost:8000/v1",
        "api_key_env": None,
        "desc": "本地 vLLM OpenAI 兼容服务（model 由 VL_MODEL 指定）",
    },
}


class VLConfig:
    """VL 调用配置（构造后按只读使用）。"""

    def __init__(self,
                 preset: str = "glm-53-flash",
                 model: str = "glm-5.3-flash",
                 base_url: str = "https://ark.cn-beijing.volces.com/api/plan/v3",
                 api_key: str | None = None,
                 timeout: float = 60.0,
                 max_retries: int = 2,
                 temperature: float = 0.0,
                 json_mode: bool = True,
                 max_image_side: int = 1500,
                 cache_dir: str | None = None,
                 replay_only: bool = False,
                 dump_crops_dir: str | None = None,
                 dump_resp_dir: str | None = None,
                 verbose: bool = False,
                 tasks_enabled: dict | None = None):
        self.preset = preset
        self.model = model
        self.base_url = base_url
        self.api_key = api_key
        self.timeout = timeout
        self.max_retries = max_retries
        self.temperature = temperature
        self.json_mode = json_mode              # response_format={json_object}
        self.max_image_side = max_image_side    # 整图缩放上限；token 控制
        # 调试
        self.cache_dir = cache_dir
        self.replay_only = replay_only
        self.dump_crops_dir = dump_crops_dir
        self.dump_resp_dir = dump_resp_dir
        self.verbose = verbose
        # 单 stage 启停（默认全开）
        self.tasks_enabled = dict(tasks_enabled) if tasks_enabled else {
            "view_rescue_v2": True, "fragment_check": True,
            "serial_rescue": True, "group_arb": True,
            "scale_prefix": True,
        }


def _read_env(name: str) -> str | None:
    """env 读取（VOLCENGINE_API_KEY 等已由 settings._load_dotenv 注入环境）。"""
    return os.environ.get(name) or None


def _parse_task_spec(spec: str) -> dict:
    """VL_TASK 字符串解析，例如 'view_rescue_v2:on,group_arb:off' -> {..}。"""
    out = {}
    for seg in spec.split(","):
        seg = seg.strip()
        if not seg or ":" not in seg:
            continue
        k, v = seg.split(":", 1)
        out[k.strip()] = v.strip().lower() in ("1", "on", "true", "yes")
    return out


def load_config(preset: str | None = None,
                config: "VLConfig | None" = None,
                **overrides) -> VLConfig:
    """从 preset / 环境变量 / 显式 overrides 构造 VLConfig。

    优先级：explicit overrides > 环境变量 > preset 默认 > 默认值。
    """
    if config is not None:
        return config

    env_preset = os.environ.get("VL_PRESET")
    preset = preset or env_preset or "glm-53-flash"
    if preset not in PRESETS:
        raise ValueError(
            f"未知 VL preset: {preset!r}（可选: {sorted(PRESETS)}）")
    p = PRESETS[preset]

    # api_key 解析：override > env 命名 > preset.api_key_env
    api_key = overrides.pop("api_key", None) or os.environ.get("VL_API_KEY")
    if api_key is None and p.get("api_key_env"):
        api_key = _read_env(p["api_key_env"])

    # model 解析：override > env > preset
    model = (overrides.pop("model", None)
             or os.environ.get("VL_MODEL")
             or p["model"])
    base_url = (overrides.pop("base_url", None)
                or os.environ.get("VL_BASE_URL")
                or p["base_url"])
    if not model:
        raise ValueError(
            f"preset {preset!r} 未指定 model，请用 VL_MODEL=... 或 model=... 提供")
    if not base_url:
        raise ValueError(
            f"preset {preset!r} 未指定 base_url，请用 VL_BASE_URL=... 提供")

    task_spec = overrides.pop("tasks_enabled", None) or os.environ.get("VL_TASK")
    tasks_enabled = None
    if isinstance(task_spec, str) and task_spec:
        tasks_enabled = dict(VLConfig().tasks_enabled)
        tasks_enabled.update(_parse_task_spec(task_spec))

    return VLConfig(
        preset=preset,
        model=model,
        base_url=base_url.rstrip("/"),
        api_key=api_key,
        timeout=float(overrides.pop("timeout",
                                    os.environ.get("VL_TIMEOUT", "60"))),
        max_retries=int(overrides.pop("max_retries",
                                      os.environ.get("VL_MAX_RETRIES", "2"))),
        cache_dir=(overrides.pop("cache_dir", None)
                   or os.environ.get("VL_CACHE_DIR")),
        replay_only=(overrides.pop("replay_only", None)
                     or os.environ.get("VL_REPLAY_ONLY", "").lower()
                     in ("1", "on", "true")),
        dump_crops_dir=(overrides.pop("dump_crops_dir", None)
                        or os.environ.get("VL_DUMP_CROPS")),
        dump_resp_dir=(overrides.pop("dump_resp_dir", None)
                       or os.environ.get("VL_DUMP_RESP")),
        verbose=(overrides.pop("verbose", None)
                 or os.environ.get("VL_VERBOSE", "").lower()
                 in ("1", "on", "true")),
        tasks_enabled=tasks_enabled,
        **overrides,
    )


# ============================================================================
# 客户端层：VLClient（OpenAI-compatible HTTP + retry + cache + dump_resp）
# ============================================================================
# 反偏差声明（同器物判断专用，保持可外部引用）。
# 实验（_plan_tmp/exp_ctx*.py，31 对判定集）结论：
# 仅叠加原图会让模型把"同版面/相邻"当同器物证据；原图 + 本反偏差声明后
# 总准确率 48.4% -> 74.2%，正对召回 0/16 -> 8/16，负对拒真保持 15/15。
ANTI_BIAS_NOTE = (
    "重要：这两张裁片来自同一张图版的不同位置——同一图版上通常排布着多件"
    "不同的器物，因此“来自同一张图”“在原图中位置相邻”都不构成同器物的证据；"
    "请只依据两张裁片内器物自身的形态特征（轮廓、口径、纹饰、部件对应关系）判断。"
)


def _b64_image(img, ext: str = ".png") -> str:
    """BGR ndarray -> data:image/<ext>;base64,...（PNG 为默认无损）。"""
    ok, buf = cv2.imencode(ext, img)
    if not ok:
        raise ValueError("cv2.imencode failed")
    return f"data:image/{ext.lstrip('.')};base64," + base64.b64encode(
        buf.tobytes()).decode("ascii")


def _hash_request(model: str, content_blocks: list) -> str:
    """请求 hash（用于 cache key）。"""
    h = hashlib.sha256()
    h.update(model.encode("utf-8"))
    for blk in content_blocks:
        if blk.get("type") == "text":
            h.update(b"\x00t:")
            h.update(blk["text"].encode("utf-8"))
        elif blk.get("type") == "image_url":
            url = blk["image_url"]["url"]
            # 截断 base64 长度用于 hash（前 256 字符足够区分；避免大字符串拷贝）
            h.update(b"\x00i:")
            h.update(url[:256].encode("utf-8", errors="ignore"))
            h.update(b":len=")
            h.update(str(len(url)).encode())
    return h.hexdigest()[:24]


class VLClient:
    """通用 OpenAI-compatible VL 客户端（厂商无关）。

    行为：构造时绑定 VLConfig；chat() 接收 content_blocks（OpenAI 多模态格式）；
    支持：retry/backoff、JSON mode、缓存命中/落盘、replay-only、
    prompt/response 落盘（dump_resp）、按 stage 分桶统计、verbose 日志。
    """

    def __init__(self, config: VLConfig):
        self.cfg = config
        # 阶段统计：{stage_name: {calls, success, abandoned, latency_ms_sum}}
        self._stats: dict = {}
        # dump_resp 序号（每 stage 递增，保证文件名唯一）
        self._dump_seq: dict = {}

    # -- 阶段统计 ------------------------------------------------------
    def _stat_inc(self, stage: str, *, ok: bool, latency_ms: float,
                  abandoned: bool = False) -> None:
        s = self._stats.setdefault(stage,
                                   {"calls": 0, "success": 0,
                                    "abandoned": 0, "latency_ms": 0.0})
        s["calls"] += 1
        if ok:
            s["success"] += 1
        if abandoned:
            s["abandoned"] += 1
        s["latency_ms"] += float(latency_ms)

    def stats(self) -> dict:
        """按 stage 分桶的统计快照。"""
        out = {}
        for k, v in self._stats.items():
            calls = v["calls"]
            out[k] = {
                "calls": int(calls),
                "success": int(v["success"]),
                "abandoned": int(v["abandoned"]),
                "avg_latency_ms": round(v["latency_ms"] / calls, 1) if calls else 0.0,
            }
        return out

    # -- 核心：chat -----------------------------------------------------
    def chat(self, content_blocks: list, *,
             stage: str = "default",
             response_format: dict | None = None) -> dict:
        """发送一次多模态聊天，返回 {"ok", "content", "raw", "latency_ms",
        "source": "api|cache", "request_hash"}.

        任何异常都不会抛出（调用方按 ok=False 自行处理）；返回内容
        已尽力 JSON 解析（若失败保留 raw 字符串）。
        """
        t0 = time.time()
        cfg = self.cfg

        # cache 命中
        rh = _hash_request(cfg.model, content_blocks)
        cached = None
        if cfg.cache_dir:
            cached = self._cache_get(rh)
        if cached is not None:
            dt = (time.time() - t0) * 1000
            self._stat_inc(stage, ok=True, latency_ms=dt)
            self._dump_resp(stage, content_blocks, cached.get("raw", ""),
                            rh, dt, "cache")
            if cfg.verbose:
                _log.info("[vl.%s] cache hit rh=%s", stage, rh)
            return {"ok": True, "content": cached.get("content", ""),
                    "raw": cached.get("raw", ""),
                    "latency_ms": dt, "source": "cache",
                    "request_hash": rh}

        if cfg.replay_only and cfg.cache_dir:
            dt = (time.time() - t0) * 1000
            self._stat_inc(stage, ok=False, latency_ms=dt, abandoned=True)
            return {"ok": False, "content": "", "raw": "",
                    "latency_ms": dt, "source": "replay_miss",
                    "request_hash": rh, "error": "replay_only, no cache"}

        # 实际请求
        rf = response_format
        if rf is None and cfg.json_mode:
            rf = {"type": "json_object"}
        payload = {
            "model": cfg.model,
            "messages": [{"role": "user", "content": content_blocks}],
            "temperature": cfg.temperature,
        }
        if rf is not None:
            payload["response_format"] = rf
        headers = {
            "Authorization": f"Bearer {cfg.api_key or 'no-key'}",
            "Content-Type": "application/json",
        }
        url = f"{cfg.base_url}/chat/completions"

        last_err = None
        for attempt in range(cfg.max_retries + 1):
            try:
                resp = requests.post(url, headers=headers, json=payload,
                                     timeout=cfg.timeout)
                resp.raise_for_status()
                data = resp.json()
                content = data["choices"][0]["message"]["content"]
                dt = (time.time() - t0) * 1000
                self._stat_inc(stage, ok=True, latency_ms=dt)
                # 写 cache（按需）
                if cfg.cache_dir:
                    self._cache_put(rh, {"content": content,
                                         "raw": json.dumps(data,
                                                           ensure_ascii=False)})
                if cfg.verbose:
                    _log.info("[vl.%s] api ok rh=%s dt=%.0fms",
                              stage, rh, dt)
                self._dump_resp(stage, content_blocks,
                                json.dumps(data, ensure_ascii=False),
                                rh, dt, "api")
                return {"ok": True, "content": content,
                        "raw": json.dumps(data, ensure_ascii=False),
                        "latency_ms": dt, "source": "api",
                        "request_hash": rh}
            except Exception as e:
                last_err = f"{type(e).__name__}: {e}"
                if attempt < cfg.max_retries:
                    time.sleep(0.6 * (2 ** attempt))
                    continue
                break
        # 全部重试失败
        dt = (time.time() - t0) * 1000
        self._stat_inc(stage, ok=False, latency_ms=dt, abandoned=True)
        if cfg.verbose:
            _log.warning("[vl.%s] api fail rh=%s err=%s",
                         stage, rh, last_err)
        return {"ok": False, "content": "", "raw": "",
                "latency_ms": dt, "source": "api_error",
                "request_hash": rh, "error": last_err}

    # -- dump_resp：prompt + raw response 落盘 --------------------------
    def _dump_resp(self, stage: str, content_blocks: list,
                   raw: str, request_hash: str, latency_ms: float,
                   source: str) -> None:
        d = self.cfg.dump_resp_dir
        if not d:
            return
        seq = self._dump_seq.get(stage, 0) + 1
        self._dump_seq[stage] = seq
        prompt_text = "\n".join(
            blk.get("text", "") for blk in content_blocks
            if blk.get("type") == "text")
        n_imgs = sum(1 for blk in content_blocks
                     if blk.get("type") == "image_url")
        try:
            p = Path(d)
            p.mkdir(parents=True, exist_ok=True)
            rec = {
                "ts": time.time(),
                "stage": stage,
                "seq": seq,
                "source": source,
                "n_images": n_imgs,
                "request_hash": request_hash,
                "latency_ms": round(latency_ms, 1),
                "prompt_text": prompt_text,
                "raw_response": (raw or "")[:8000],
            }
            (p / f"{stage}_{seq:04d}.json").write_text(
                json.dumps(rec, ensure_ascii=False, indent=2),
                encoding="utf-8")
        except Exception as e:
            _log.debug("dump resp failed: %s", e)

    # -- cache I/O ------------------------------------------------------
    def _cache_get(self, rh: str) -> dict | None:
        p = Path(self.cfg.cache_dir) / f"{rh}.json"
        if p.exists():
            try:
                return json.loads(p.read_text(encoding="utf-8"))
            except Exception:
                return None
        return None

    def _cache_put(self, rh: str, obj: dict) -> None:
        try:
            Path(self.cfg.cache_dir).mkdir(parents=True, exist_ok=True)
            Path(self.cfg.cache_dir, f"{rh}.json").write_text(
                json.dumps(obj, ensure_ascii=False), encoding="utf-8")
        except Exception as e:
            _log.debug("cache write failed: %s", e)


# ============================================================================
# 仲裁层：VlArbiter（全部任务逻辑 + 组装管线 S6 E1–E4 的全部已用接口）
# ============================================================================
# ----- Prompt 模板（模块级常量，便于人工审查/调试/导出）-----
# V3 优化版（2026-09-04 实测定稿）：项目背景 + 图版构成 + 归一化尺寸警示 +
# 质感优先判别规则。实测与短 prompt 同分（002 判别对 6/6），但规则显式、
# 对更难样本（多部件/贴边碎片）更稳；配套掩膜白底裁片（≤128px）使用，
# 严禁再叠加整图上下文（2 prompt × 3 模型 × 3 尺寸实验一致劣化）。
PROMPT_VIEW_CANDIDATES_V3 = (
    "【项目背景】\n"
    "你在协助考古报告数字化管线做图版元素分类。考古报告的器物图版需要被自动切分为单件器物图，\n"
    "图版中的每个墨迹单元要么是\"器物图形（视图或部件）\"，要么是\"版面文字\"。分类错误会导致\n"
    "器物被漏切、或把笔画误当序号造成重复编号，因此两类必须严格区分。\n"
    "\n"
    "【图版构成（背景知识）】\n"
    "典型图版自上而下由三层构成：器物白描线图（常成组排列，同一件器物可有多个视图，或由多个\n"
    "部件组成一套、共用一个序号，例如钉体与弯钩、正面与侧面）；器物序号（每个器物组下方标注\n"
    "一个印刷阿拉伯数字 1、2、3…，全版等高、字体一致，通常仅十余像素高）；比例尺（带刻度的\n"
    "横尺与\"0—x厘米\"文字）。送检裁片是从图版各位置抠出的单个墨迹单元。\n"
    "\n"
    "【重要：尺寸说明】\n"
    "各裁片已按自身最长边独立归一化（不超过128像素），裁片在画布中的绝对大小不代表原图中的\n"
    "真实大小，请勿以\"占满画布的程度\"作为判断依据；笔画质感与字形结构才是唯一可靠判据。\n"
    "\n"
    "【器物与数字的判别方法】\n"
    "- 判 is_view=true（器物图形/部件）：\n"
    "  a) 线条属于器物白描：笔画粗细有变化（起笔收笔、转折处变粗），常带阴影斑点、晕染、\n"
    "     剖面线、断口符号等手工绘制质感；\n"
    "  b) 形态是器物或其部件的轮廓（钉、钩、环、簪、刃、柄等），而非任何标准印刷字符字形；\n"
    "  c) 器物部件可能很细长（如钩、簪），细长本身不代表\"不是器物\"。\n"
    "- 判 is_view=false（版面文字/杂符）：\n"
    "  a) 印刷阿拉伯数字与标点：笔画粗细均匀纤细、边缘锐利、无质感填充，字形与标准印刷体\n"
    "     完全一致；\n"
    "  b) 断裂符\"-\"、图内残笔等无器物形态特征的小墨迹。\n"
    "- 关键规则：若笔画同时像\"某个字符\"又带\"手绘质感\"，一律按笔画质感判定——考古图版的\n"
    "  印刷序号由铅字印制，质感均匀一致；器物线条为手工描绘，必有粗细与浓淡变化。\n"
    "只输出 JSON：{\"views\":[{\"i\":0,\"is_view\":true},{\"i\":1,\"is_view\":false}]}，不要输出其它文字。"
)

PROMPT_SERIAL_CROPS = (
    "以上是考古图版上印刷阿拉伯数字的局部裁剪（按顺序对应 i=0..N-1）。"
    "逐一读出每张裁片中的数字（1-2 位整数；若裁片内为两个相邻数字组成的编号，按原样连读）。"
    "数字为印刷体，若裁片过小看不清，读其最可能值。只输出 JSON："
    '{"reads":[{"i":0,"no":"1"},{"i":1,"no":"2"}]}'
)

PROMPT_SCALE_ROW = (
    "以下是考古图版中比例尺行的局部裁剪（按顺序对应 i=0..N-1）。"
    "逐一读取：前缀编号 prefix（比例尺左侧标注的适用器物编号，如 \"1\"、\"2、3\"、\"1~7\"；没有则空串 \"\"），"
    "以及比例尺文字 text（如 \"0—4厘米\"、\"0—2厘米\"）。只输出 JSON："
    '{"rows":[{"i":0,"prefix":"1~7","text":"0—2厘米"}]}'
)

PROMPT_SAME_ARTIFACT = (
    "给定两张考古器物线图。请判断它们是否是“同一件器物”的两个不同视角。\n"
    "注意：同一器物的俯视图（顶视）与侧视图在外形上通常差异很大——俯视多呈圆形轮廓或纹饰，"
    "侧视呈高度/轮廓；不能仅因“外形不同”就判否。\n"
    "判断关键：① 两者是否可能出自同一器物组（口径/宽度一致、中轴对齐、上下或左右相邻、"
    "底部同基线）；② 是否有相同序号/编号；③ 部件能否对应（如俯视口沿 = 侧视口沿高度）。\n"
)

PROMPT_FRAGMENT = (
    "给定两张考古器物线图裁片。第一张是一个器物视图（宿主），第二张是从其附近"
    "裁出的较小区域。请判断第二张是否是第一张器物的内部组成部分（器内笔画、"
    "剖面残段、纹饰碎片、断裂细部），而不是一件独立的器物或另一个器物的视图。\n"
    "判断关键：① 碎片的线条风格/粗细是否与宿主一致；② 它是否能与宿主的"
    "轮廓/纹饰自然衔接；③ 它自身是否具备独立器物的完整形态特征。\n"
    "只输出 JSON：{\"is_fragment\": true|false, \"reason\": \"一句依据\"}。"
)


def _parse_json(content: str) -> dict | None:
    """从模型输出中提取 JSON 对象；失败返回 None。"""
    s = content.find("{")
    e = content.rfind("}")
    if s < 0 or e < 0 or e <= s:
        return None
    try:
        return json.loads(content[s:e + 1])
    except Exception:
        return None


def unit_ink_mask(binary: np.ndarray, box, tol: int = 2,
                  min_area: int = 5) -> np.ndarray:
    """单元专属墨迹掩膜：组件 bbox 完全落在 box+tol 内的连通域（bool HxW）。

    box 为该单元在 rec/seg 结果中的 bbox（[x0,y0,x1,y1]）。tol 收紧到 2px
    可避免把紧邻的断裂符/残笔并进来（002 弯钩与 '-' 破折号相距 6px 的实测）。
    """
    H, W = binary.shape[:2]
    x0, y0, x1, y1 = box[0] - tol, box[1] - tol, box[2] + tol, box[3] + tol
    m = np.zeros((H, W), bool)
    n, lab, stats, _ = cv2.connectedComponentsWithStats(
        binary.astype(np.uint8), connectivity=8)
    for i in range(1, n):
        ax, ay, aw, ah, area = stats[i]
        if area >= min_area and ax >= x0 and ay >= y0 \
                and ax + aw <= x1 and ay + ah <= y1:
            m[lab == i] = True
    return m


def masked_white_crop(binary: np.ndarray, bgr: np.ndarray, box,
                      pad: int = 6, max_side: int = 128) -> np.ndarray:
    """最终配方裁片：白底 + 单元墨迹像素 + 最长边归一 ≤max_side（cubic）。

    实测矩阵（_plan_tmp/vl_crops_v2/）：≤128px 安全（原生/128 均 6/6），
    256px 双误判（印刷数字失去锐利边缘特征）；整图/标注原图形态已证伪。
    """
    H, W = bgr.shape[:2]
    x0, y0 = max(0, int(box[0]) - pad), max(0, int(box[1]) - pad)
    x1, y1 = min(W, int(box[2]) + pad), min(H, int(box[3]) + pad)
    sub = unit_ink_mask(binary, box)[y0:y1, x0:x1]
    crop = np.full((y1 - y0, x1 - x0, 3), 255, np.uint8)
    crop[sub] = bgr[y0:y1, x0:x1][sub]
    s = max_side / max(crop.shape[:2])
    if s != 1:
        crop = cv2.resize(crop, None, fx=s, fy=s, interpolation=cv2.INTER_CUBIC)
    return crop


def _maybe_dump_crop(client: VLClient, stage: str, call_id: int,
                     crop_idx: int, img: np.ndarray) -> None:
    """落盘 crop PNG（若配置 dump_crops_dir）。"""
    d = client.cfg.dump_crops_dir
    if not d or img is None or img.size == 0:
        return
    try:
        p = Path(d)
        p.mkdir(parents=True, exist_ok=True)
        cv2.imwrite(str(p / f"{stage}_{call_id:04d}_c{crop_idx}.png"), img)
    except Exception as e:
        _log.debug("dump crop failed: %s", e)


class VlArbiter:
    """VL 兜底仲裁器（S6 组装持有实例，调用 5 个任务方法）。

    三层中的仲裁层：全部任务逻辑在此——裁片、prompt 拼装、响应解析、
    records 记录、单 stage 启停、三态兜底。方法与组装管线的
    触发场景一一对应：
      judge_view_candidates_v2  E1.R1 视图救援 + E1.5 候选漏斗
                                （view_rescue_v2；v1 入口已删除）
      confirm_absorption        E1.R2 碎片吸收（fragment_check）
      read_serial_crops         E2.5 序号漏检补救（serial_rescue）
      same_artifact             E3   视图分组仲裁（group_arb）
      read_scale_prefix         E4   比例尺前缀兜底（scale_prefix）

    三态返回（与历史约定一致）：
      None  = VL 不可用 / 禁用 / 解析失败 → 放弃（abandoned）
      True  = 采信（VL 给正判断）
      False = 采信（VL 给负判断）
    """

    def __init__(self, enabled: bool = True,
                 preset: str | None = None,
                 config: "VLConfig | None" = None,
                 **kwargs):
        self.enabled = enabled
        self._cfg = load_config(preset=preset, config=config, **kwargs)
        self._client = VLClient(self._cfg)
        # 统计（保留旧字段名以兼容调用方读取）
        self.failed: str | None = None
        self.records: list = []                  # list[dict]
        self.n_calls: int = 0
        self.n_success: int = 0
        # crop 落盘序号（每 stage 递增）
        self._crop_seq: dict = {}

    # -- 配置 ----------------------------------------------------------
    @property
    def config(self) -> VLConfig:
        return self._cfg

    # -- 记录（Stage 完成一次调用后写 records / n_calls / n_success）----
    def _record(self, stage: str, *, ok: bool, decision,
                source: str, input_summary: str, reason: str = "",
                latency_ms: float = 0.0, request_hash: str = "",
                error: str = "") -> dict:
        rec = {
            "ts": time.time(),
            "stage": stage,
            "ok": ok,
            "abandoned": not ok,
            "source": source,
            "latency_ms": round(latency_ms, 1),
            "input_summary": input_summary,
            "decision": decision,
            "reason": reason,
            "request_hash": request_hash,
            "error": error,
        }
        self.records.append(rec)
        self.n_calls += 1
        if ok:
            self.n_success += 1
        if not ok and error:
            self.failed = f"{stage}: {error}"
        return rec

    def _dump_crops(self, stage: str, imgs: list) -> None:
        """按 stage 递增序号落盘本调用的全部裁片。"""
        if not self._cfg.dump_crops_dir:
            return
        seq = self._crop_seq.get(stage, 0) + 1
        self._crop_seq[stage] = seq
        for i, img in enumerate(imgs):
            _maybe_dump_crop(self._client, stage, seq, i, img)

    # -- E1.R1 视图救援 -------------------------------------------------
    # -- 视图判定共享核心 ------------------------------------------------
    def _view_flags_chat(self, crops: list, *, stage: str, prompt: str,
                         chunk_size: int, context: str = "",
                         retry_parse: bool = True) -> tuple[list, str]:
        """分块批量判定 is_view 的共享实现（唯一判定通路）。

        拼 blocks（图片j + prompt）-> chat -> JSON 解析（失败降级重试一次，
        去掉 json_object 约束）-> 逐块 _record -> 合并为逐单元三态 flags。
        任何一块失败该块单元为 None，其余块结果不受影响（分块隔离是
        2026-09 实测结论：大批次放大解析失败率且批内邻居污染判定）。
        """
        merged: list = [None] * len(crops)
        ok_chunks = fail_chunks = 0
        for c0 in range(0, len(crops), max(1, chunk_size)):
            idx = list(range(c0, min(c0 + max(1, chunk_size), len(crops))))
            blocks = []
            for j, i in enumerate(idx):
                blocks.append({"type": "image_url",
                               "image_url": {"url": _b64_image(crops[i])}})
                blocks.append({"type": "text", "text": f"图片{j}："})
            blocks.append({"type": "text", "text": prompt})
            self._dump_crops(stage, [crops[i] for i in idx])
            r = self._client.chat(blocks, stage=stage)
            obj = None
            if r["ok"]:
                obj = _parse_json(r["content"])
                if obj is None and retry_parse:
                    r2 = self._client.chat(blocks, stage=stage,
                                           response_format=None)
                    if r2["ok"]:
                        obj = _parse_json(r2["content"])
                        r = r2
            flags = None
            if obj:
                flags = [False] * len(idx)
                for it in obj.get("views", []):
                    try:
                        j = int(it["i"])
                    except Exception:
                        continue
                    if 0 <= j < len(idx):
                        flags[j] = bool(it.get("is_view", False))
            ok = flags is not None
            ok_chunks += ok
            fail_chunks += not ok
            self._record(stage, ok=ok, decision=flags,
                         source=r["source"],
                         input_summary=f"n_crops={len(crops)}",
                         reason="" if ok else (r.get("error") or "parse fail"),
                         latency_ms=r["latency_ms"],
                         request_hash=r.get("request_hash", ""),
                         error=r.get("error", ""))
            if ok:
                for j, i in enumerate(idx):
                    merged[i] = flags[j]
        note = (f"vl flags={merged} chunks={ok_chunks}ok/{fail_chunks}fail "
                f"{context}".strip())
        return merged, note

    # -- E1.5 视图仲裁 v2（最终配方：掩膜白底裁片 ≤128 + PROMPT_V3）------
    def judge_view_candidates_v2(self, bgr: np.ndarray, units: list,
                                 context: str = "", chunk_size: int = 8
                                 ) -> tuple[list, str]:
        """按最终配方批量仲裁候选单元 is_view（生产入口）。

        配方依据（2026-09 多轮实测，详见 _plan_tmp/vl_validation/）：
          1) 裁片 = 白底掩膜裁片（单元专属连通域，≤128px），不再用原图 bbox
             裁片——邻接笔画会带入干扰，归一化警示写进 prompt 后方可用；
          2) prompt = PROMPT_VIEW_CANDIDATES_V3（背景+构成+质感优先规则）；
          3) 分块 ≤chunk_size（默认 8）逐批判定——批内邻居会污染单裁片判断
             （同单元跨批翻转实测 8/18），大批次还会放大解析失败率；
          4) 解析失败自动降级重试一次（去掉 json_object 约束）。

        units: [{"bbox":[x0,y0,x1,y1], ...}]（其余字段原样带回 note 统计）。
        返回 (flags, note)：flags 与 units 等长，逐单元 True/False/None
        （None = 该批调用/解析失败，调用方按报警降级，不得猜测）。
        """
        if not self.enabled:
            return None, "vl disabled"
        if not self._cfg.tasks_enabled.get("view_rescue_v2", True):
            return [None] * len(units), "task disabled"
        if not units:
            return [], "no units"
        gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
        _, binary = cv2.threshold(gray, 0, 255,
                                  cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
        binary = (binary > 0).astype(np.uint8)
        crops = [masked_white_crop(binary, bgr, u["bbox"]) for u in units]
        return self._view_flags_chat(
            crops, stage="view_rescue_v2", prompt=PROMPT_VIEW_CANDIDATES_V3,
            chunk_size=chunk_size, context=context)

    # -- E1.R2 碎片吸收 -------------------------------------------------
    def confirm_absorption(self, bgr: np.ndarray,
                           host_box: list, frag_box: list
                           ) -> tuple[bool | None, str]:
        """确认 frag 是否为 host 的器内碎片。返回 (is_frag | None, reason)。"""
        if not self._cfg.tasks_enabled.get("fragment_check", True):
            return None, "task disabled"
        if not self.enabled:
            return None, "vl disabled"
        host = self._crop(bgr, host_box, pad=6)
        frag = self._crop(bgr, frag_box, pad=6)
        self._dump_crops("fragment_check", [host, frag])
        blocks = [
            {"type": "image_url", "image_url": {"url": _b64_image(host)}},
            {"type": "image_url", "image_url": {"url": _b64_image(frag)}},
            {"type": "text", "text": PROMPT_FRAGMENT},
        ]
        r = self._client.chat(blocks, stage="fragment_check")

        is_frag = None
        reason = ""
        if r["ok"]:
            obj = _parse_json(r["content"])
            if obj:
                is_frag = bool(obj.get("is_fragment", False))
                reason = str(obj.get("reason", "")).strip()
            else:
                reason = f"parse fail: {r['content'][:120]}"
        else:
            reason = f"api fail: {r.get('error', '?')}"
        ok = is_frag is not None
        self._record("fragment_check", ok=ok, decision=is_frag,
                     source=r["source"], input_summary="host+frag crops",
                     reason=reason, latency_ms=r["latency_ms"],
                     request_hash=r.get("request_hash", ""),
                     error=r.get("error", ""))
        return is_frag, reason

    # -- E2.5 序号漏检补救 ----------------------------------------------
    def read_serial_crops(self, crops: list, context: str = ""
                          ) -> tuple[list | None, str]:
        """批量读疑似序号裁片。返回 (reads | None, note)。"""
        if not self._cfg.tasks_enabled.get("serial_rescue", True):
            return None, "task disabled"
        if not self.enabled:
            return None, "vl disabled"
        if not crops:
            return [], "no crops"
        self._dump_crops("serial_rescue", crops)
        blocks = []
        for i, c in enumerate(crops):
            blocks.append({"type": "image_url",
                           "image_url": {"url": _b64_image(c)}})
            blocks.append({"type": "text", "text": f"图片{i}："})
        blocks.append({"type": "text", "text": PROMPT_SERIAL_CROPS})
        r = self._client.chat(blocks, stage="serial_rescue")

        reads = None
        if r["ok"]:
            obj = _parse_json(r["content"])
            if obj:
                reads = [""] * len(crops)
                for rd in obj.get("reads", []):
                    try:
                        i = int(rd["i"])
                    except Exception:
                        continue
                    if 0 <= i < len(crops):
                        reads[i] = str(rd.get("no", "")).strip()
        ok = reads is not None
        self._record("serial_rescue", ok=ok, decision=reads,
                     source=r["source"],
                     input_summary=f"n_crops={len(crops)}",
                     reason=context,
                     latency_ms=r["latency_ms"],
                     request_hash=r.get("request_hash", ""),
                     error=r.get("error", ""))
        has_read = ok and any((s or "").strip() for s in reads)
        note = (f"vl reads={reads} {context}".strip() if has_read
                else f"vl parse/api failed {context}".strip())
        return reads, note

    # -- E3 视图分组仲裁（默认 use_full=True，实验最优变体）--------------
    def same_artifact(self, bgr: np.ndarray,
                      box_a: list, box_b: list,
                      use_full: bool = True) -> tuple[bool | None, str]:
        """判断两视图是否同一器物。返回 (same | None, note)。"""
        if not self._cfg.tasks_enabled.get("group_arb", True):
            return None, "task disabled"
        if not self.enabled:
            return None, "vl disabled"
        ca = self._crop(bgr, box_a, pad=6)
        cb = self._crop(bgr, box_b, pad=6)
        full = bgr if use_full else None
        self._dump_crops("group_arb",
                         [ca, cb] + ([full] if full is not None else []))

        instruction = PROMPT_SAME_ARTIFACT
        if full is not None:
            instruction += (
                "第三张完整大图是这两张裁片的来源原图，可参考其中的版面布局、"
                "两区域的相对位置、序号标注与连接符等上下文证据。\n"
            )
            instruction += ANTI_BIAS_NOTE + "\n"
        instruction += (
            "只输出 JSON：{\"same\": true|false, \"reason\": \"一句依据\"}。"
            "若确实是同一器物的不同视角，same 为 true；"
            "若为不同器物或同一视角的重复，same 为 false。"
            "不要输出其它文字。"
        )
        blocks = []
        if full is not None:
            blocks.append({"type": "image_url",
                           "image_url": {"url": _b64_image(full)}})
            blocks.append({"type": "text", "text": "（完整原图，供参考上下文）"})
        blocks += [
            {"type": "image_url", "image_url": {"url": _b64_image(ca)}},
            {"type": "image_url", "image_url": {"url": _b64_image(cb)}},
            {"type": "text", "text": instruction},
        ]
        r = self._client.chat(blocks, stage="group_arb")

        same = None
        reason = ""
        if r["ok"]:
            obj = _parse_json(r["content"])
            if obj:
                same = bool(obj.get("same", False))
                reason = str(obj.get("reason", "")).strip()
            else:
                reason = f"parse fail: {r['content'][:120]}"
        else:
            reason = f"api fail: {r.get('error', '?')}"
        ok = same is not None
        self._record("group_arb", ok=ok, decision=same,
                     source=r["source"],
                     input_summary=f"used_full={use_full}",
                     reason=reason, latency_ms=r["latency_ms"],
                     request_hash=r.get("request_hash", ""),
                     error=r.get("error", ""))
        if not ok:
            return None, f"vl error: {reason}"
        tag = "vl+ctx" if use_full else "vl"
        return same, f"{tag} same={same} reason={reason}"

    # -- E4 比例尺前缀兜底 ----------------------------------------------
    def read_scale_prefix(self, bgr: np.ndarray, scale: dict,
                          where: str = "scale_prefix"
                          ) -> tuple[list | None, str]:
        """VL 读比例尺行前缀。返回 (nums | None, note)。"""
        if not self._cfg.tasks_enabled.get("scale_prefix", True):
            return None, "task disabled"
        if not self.enabled:
            return None, "vl disabled"
        crop = self._crop(bgr, scale["bbox"], pad=14)
        self._dump_crops("scale_prefix", [crop])
        blocks = [
            {"type": "image_url", "image_url": {"url": _b64_image(crop)}},
            {"type": "text", "text": "图片0："},
            {"type": "text", "text": PROMPT_SCALE_ROW},
        ]
        r = self._client.chat(blocks, stage="scale_prefix")

        nums = None
        prefix = ""
        if r["ok"]:
            obj = _parse_json(r["content"])
            if obj:
                rows = obj.get("rows", [])
                if rows:
                    prefix = str(rows[0].get("prefix", "")).strip()
                nums = [int(n) for n in re.findall(r"\d{1,2}", prefix)]
        ok = nums is not None
        self._record("scale_prefix", ok=ok, decision=nums,
                     source=r["source"], input_summary=where,
                     reason=f"where={where}", latency_ms=r["latency_ms"],
                     request_hash=r.get("request_hash", ""),
                     error=r.get("error", ""))
        if ok:
            return nums, f"vl prefix={prefix!r}"
        return None, "vl parse/api failed"

    # -- 通用工具 -----------------------------------------------------
    def _crop(self, bgr: np.ndarray, box, pad: int = 10) -> np.ndarray:
        H, W = bgr.shape[:2]
        x0 = max(0, int(box[0]) - pad)
        y0 = max(0, int(box[1]) - pad)
        x1 = min(W, int(box[2]) + pad)
        y1 = min(H, int(box[3]) + pad)
        return bgr[y0:y1, x0:x1]

    # -- 调试导出 -----------------------------------------------------
    def stats(self) -> dict:
        """按 stage 分桶的统计 + 总体统计。"""
        per_stage = self._client.stats()
        per_stage["__total__"] = {
            "calls": self.n_calls,
            "success": self.n_success,
            "abandoned": self.n_calls - self.n_success,
            "avg_latency_ms": 0.0,
        }
        return {
            "preset": self._cfg.preset,
            "model": self._cfg.model,
            "enabled": self.enabled,
            "failed": self.failed,
            "per_stage": per_stage,
            "n_records": len(self.records),
        }

    def dump_records(self, path: str | os.PathLike) -> None:
        """records 列表导出为 JSON（供外部分析/复核）。"""
        out = {
            "config": {
                "preset": self._cfg.preset,
                "model": self._cfg.model,
                "base_url": self._cfg.base_url,
            },
            "stats": self.stats(),
            "records": self.records,
        }
        Path(path).write_text(json.dumps(out, ensure_ascii=False, indent=2),
                              encoding="utf-8")

    def reset_stats(self) -> None:
        """清零统计与 records（保留 enabled/preset/配置）。"""
        self.records.clear()
        self.n_calls = 0
        self.n_success = 0
        self.failed = None
        self._client._stats.clear()
        self._crop_seq.clear()
