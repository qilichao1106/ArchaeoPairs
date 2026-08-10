# -*- coding: utf-8 -*-
"""ModelGateway：外部模型调用的统一出入口（方案 §3.4/§9.3）。

职责：重试/指数退避/熔断/metrics/录制回放 hook。
- 所有 VLM/SAM/OCR/LLM 调用必须经此网关，禁止 Agent 直连模型服务；
- MockGateway 用于无 GPU 环境的开发联调与单元测试（录制回放点）。
"""
from __future__ import annotations

import json
import time
from abc import ABC, abstractmethod
from pathlib import Path


class CircuitOpenError(Exception):
    pass


class ModelGateway(ABC):
    @abstractmethod
    def call(self, agent: str, prompt_key: str, payload: dict) -> dict:
        """调用模型，返回结构化结果（须符合 prompts/P-*.md 的 output_format）。"""
        ...


class CircuitBreaker:
    """60s 窗口失败率>50% → open 120s → 半开 3 探针（方案 §9.3）。"""

    def __init__(self, window_s: int = 60, threshold: float = 0.5,
                 open_s: int = 120, half_open_probes: int = 3):
        self.window_s = window_s
        self.threshold = threshold
        self.open_s = open_s
        self.half_open_probes = half_open_probes
        self.events: list[tuple[float, bool]] = []   # (ts, success)
        self.opened_at: float | None = None
        self.probes = 0

    def allow(self) -> bool:
        if self.opened_at is None:
            return True
        if time.time() - self.opened_at < self.open_s:
            return False                      # open：暂停入队不猜测
        self.probes += 1
        return self.probes <= self.half_open_probes   # 半开探针

    def record(self, success: bool) -> None:
        now = time.time()
        self.events.append((now, success))
        self.events = [(t, s) for t, s in self.events if now - t < self.window_s]
        if self.opened_at is not None:
            if success and self.probes >= self.half_open_probes:
                self.opened_at, self.probes = None, 0     # 半开成功→闭合
            elif not success:
                self.opened_at, self.probes = now, 0      # 探针失败→重新 open
            return
        if len(self.events) >= 4:
            fails = sum(1 for _, s in self.events if not s)
            if fails / len(self.events) > self.threshold:
                self.opened_at = now


class RecordingGateway(ModelGateway):
    """包装任意网关：录制每次调用（prompt_version/耗时/结果），支持回放复算。"""

    def __init__(self, inner: ModelGateway, record_path: str | None = None,
                 replay_path: str | None = None, max_retry: int = 2):
        self.inner = inner
        self.breaker = CircuitBreaker()
        self.max_retry = max_retry
        self.record_path = Path(record_path) if record_path else None
        self.replay: list[dict] | None = None
        if replay_path and Path(replay_path).exists():
            self.replay = [json.loads(x) for x in Path(replay_path).read_text("utf-8").splitlines()]
        self.metrics: list[dict] = []

    def call(self, agent: str, prompt_key: str, payload: dict) -> dict:
        if self.replay is not None:                       # 回放模式
            for rec in self.replay:
                if rec["agent"] == agent and rec["prompt_key"] == prompt_key and not rec.get("_used"):
                    rec["_used"] = True
                    return rec["result"]
            raise RuntimeError(f"回放缺失: {agent}/{prompt_key}")
        if not self.breaker.allow():
            raise CircuitOpenError(f"熔断打开：{agent} 暂停调用，任务入队等待（fail-closed）")
        t0, last_err = time.time(), None
        for attempt in range(self.max_retry + 1):         # ≤2 次指数退避
            try:
                result = self.inner.call(agent, prompt_key, payload)
                self.breaker.record(True)
                self._after(agent, prompt_key, payload, result, t0, attempt)
                return result
            except Exception as e:                        # noqa: BLE001
                last_err = e
                self.breaker.record(False)
                time.sleep(min(2 ** attempt, 4) * 0.1)    # 退避（测试环境缩短）
        raise last_err

    def _after(self, agent, prompt_key, payload, result, t0, attempt) -> None:
        rec = {"agent": agent, "prompt_key": prompt_key, "result": result,
               "ms": round((time.time() - t0) * 1000, 1), "attempt": attempt}
        self.metrics.append(rec)
        if self.record_path:
            with self.record_path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")


class MockGateway(ModelGateway):
    """开发联调/单测用 Mock：返回保守结果（宁可触发复核，绝不伪造高置信）。

    TODO: 生产环境替换为 HTTP 客户端（vlm-serve/sam-serve/ocr-serve，§9.1），
    端点与超时由 config 注入；接口签名保持不变。
    """

    def __init__(self, ocr_available: bool = False, sam_available: bool = False):
        self.ocr_available = ocr_available
        self.sam_available = sam_available

    def call(self, agent: str, prompt_key: str, payload: dict) -> dict:
        if agent == "A2":     # 图类判定：无法确定 → 交人工
            return {"type": "uncertain", "reason": "mock: 无 VLM，无法视觉判定",
                    "force_rule_a": False, "confidence": 0.0}
        if agent == "A3":     # 图内 OCR
            if not self.ocr_available:
                raise RuntimeError("mock: OCR 服务不可用")
            return {"seq_set": [], "seq_to_id": {}, "scales": [], "orientation": "h"}
        if agent == "A4":     # 融合仲裁：冲突不可解（fail-closed）
            return {"case_type": "rule_a", "seq_to_id": {},
                    "per_elem_provenance": {}, "conflict_flags": ["mock_unresolvable"],
                    "confidence": 0.0, "review_flag": True}
        if agent == "A5":     # SAM 分割
            if not self.sam_available:
                raise RuntimeError("mock: SAM 服务不可用")
            return {"masks": []}
        if agent == "A8":     # 质检回读：保守判不一致→降置信
            return {"consistent": False, "reason": "mock: 无 VLM 回读",
                    "new_confidence": 0.0, "action": "downgrade"}
        if agent in ("A1a", "A1b", "A6"):
            raise RuntimeError(f"mock: {agent} LLM 二次解析不可用")
        raise RuntimeError(f"mock: 未知 agent {agent}")
