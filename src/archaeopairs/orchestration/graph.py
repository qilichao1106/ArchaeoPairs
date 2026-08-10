# -*- coding: utf-8 -*-
"""框架中立 DAG 执行器（方案 §3.2/§3.3）。

设计立场：DAG 以"节点顺序 + 跳过谓词"的框架中立原语定义，不依赖任何具体
编排框架 API；P0 PoC 后由适配层映射到 LangGraph/AgentScope（§3.3 映射表）。

语义对应：
- fan-out/fan-in：A1a/A1b/A2/A3 顺序执行等价于并行后 barrier join
  （四者无相互数据依赖，仅共同向 A1c/A4 供数；并行化由适配层负责，见 TODO）；
- 条件路由：A2 结果决定 A5/A6/END 的跳过谓词；
- interrupt/resume：ReviewRequired → checkpoint 持久化 + blocked_review，
  resume() 从断点节点继续；
- fail-closed：AgentError(fatal=True) 立即终止并保留现场。
"""
from __future__ import annotations

import sqlite3
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from ..agent import AgentInterface, AgentContext
from ..errors import AgentError, ReviewRequired
from ..state import PairState

# DAG 拓扑（方案 §3.2 边表的顺序化等价）
NODE_ORDER = ["A0", "A1a", "A1b", "A2", "A3", "A1c", "A4", "A5", "A6", "A7", "A8"]


def _skip(node: str, state: PairState) -> bool:
    """条件边路由谓词：non→存档跳过全链；plate 走 A6 跳 A5；type_a 走 A5 跳 A6。"""
    ft = state.figure_type
    if node in ("A5", "A6", "A7", "A8") and ft == "non":
        return True
    if node == "A5" and ft == "plate":
        return True
    if node == "A6" and ft not in ("plate",):
        return True
    return False


@dataclass
class RunResult:
    figure_id: str
    status: str                 # finished / blocked_review / failed / archived
    pairs: int = 0
    error: str = ""
    review: dict | None = None


class Checkpointer:
    """SQLite checkpoint（LangGraph SqliteSaver 的框架中立等价，§3.3）。"""

    def __init__(self, db_path: str):
        self.db_path = db_path
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(db_path) as c:
            c.execute("PRAGMA journal_mode=WAL")
            c.execute("""CREATE TABLE IF NOT EXISTS checkpoints(
                thread_id TEXT PRIMARY KEY, state_json TEXT NOT NULL,
                current_node TEXT, updated_at TEXT NOT NULL)""")

    def save(self, state: PairState) -> None:
        import json
        with sqlite3.connect(self.db_path) as c:
            c.execute("INSERT OR REPLACE INTO checkpoints VALUES(?,?,?,datetime('now'))",
                      (state.trace_id, json.dumps(state.to_dict(), ensure_ascii=False),
                       state.current_node))

    def load(self, thread_id: str) -> PairState | None:
        import json
        with sqlite3.connect(self.db_path) as c:
            row = c.execute("SELECT state_json FROM checkpoints WHERE thread_id=?",
                            (thread_id,)).fetchone()
        return PairState.from_dict(json.loads(row[0])) if row else None

    def delete(self, thread_id: str) -> None:
        with sqlite3.connect(self.db_path) as c:
            c.execute("DELETE FROM checkpoints WHERE thread_id=?", (thread_id,))


class GraphRunner:
    """单 figure DAG 执行器。"""

    def __init__(self, agents: dict[str, AgentInterface], checkpointer: Checkpointer):
        self.agents = agents
        self.cp = checkpointer

    def run(self, state: PairState, ctx: AgentContext,
            start_from: str | None = None) -> RunResult:
        started = start_from is None
        for node in NODE_ORDER:
            if not started:
                if node == start_from:
                    started = True
                else:
                    continue
            if _skip(node, state):
                continue
            state.current_node = node
            agent = self.agents[node]
            state.agent_states[node] = "running"
            try:
                state = agent.run(state, ctx)
                state.agent_states[node] = "idle"
                self.cp.save(state)                       # 每节点落 checkpoint（断点续跑）
            except ReviewRequired as r:
                state.agent_states[node] = "blocked_review"
                state.review_flag = True
                state.errors.append({"code": r.code.value, "agent": node,
                                     "message": str(r)})
                self.cp.save(state)                       # 持久化现场（可跨天 resume）
                return RunResult(state.figure_id, "blocked_review",
                                 len(state.pairs),
                                 review={"kind": r.kind, "code": r.code.value,
                                         "payload_ref": r.payload_ref,
                                         "resume_node": node})
            except AgentError as e:
                state.agent_states[node] = "failed"
                state.errors.append({"code": e.code.value, "agent": node,
                                     "message": str(e)})
                self.cp.save(state)
                return RunResult(state.figure_id, "failed", len(state.pairs), str(e))
            except Exception as e:                        # noqa: BLE001 — 未分类异常按失败处理
                state.agent_states[node] = "failed"
                state.errors.append({"code": "E_UNCLASSIFIED", "agent": node,
                                     "message": str(e)})
                self.cp.save(state)
                return RunResult(state.figure_id, "failed", len(state.pairs), str(e))
        status = "archived" if state.figure_type == "non" else "finished"
        self.cp.delete(state.trace_id)                    # 完成即清理 checkpoint
        return RunResult(state.figure_id, status, len(state.pairs))

    def resume(self, thread_id: str, ctx: AgentContext,
               human_decision: dict) -> RunResult:
        """人工复核后恢复：按决策类型重放子图（§3.6）。

        映射类→自 A4；掩膜类→自 A5；文本类→自 A1b；qc 类→自 A8。
        """
        state = self.cp.load(thread_id)
        if state is None:
            return RunResult("", "failed", error=f"checkpoint 不存在: {thread_id}")
        replay_from = {"mapping": "A4", "mask": "A5", "text": "A1b", "qc": "A8"}.get(
            human_decision.get("kind", ""), state.current_node)
        # 人工修正数据注入（如修正后的 seq_to_id / mask_path）
        for k, v in (human_decision.get("patch") or {}).items():
            if hasattr(state, k):
                setattr(state, k, v)
        state.review_flag = False
        return self.run(state, ctx, start_from=replay_from)
