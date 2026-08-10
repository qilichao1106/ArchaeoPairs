# -*- coding: utf-8 -*-
"""存储层：SQLite DDL 初始化与产物目录（方案 §6.2，含附录C-B4 修复）。

B4 修复落点：review_tasks 复核锚点改为版本无关的 (figure_id, kind)，
idem_key 仅作幂等键；figures.state 枚举增补 'assembled'（与 A7 卡片对齐）。
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

DDL = """
PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;
CREATE TABLE IF NOT EXISTS books (
  book_id TEXT PRIMARY KEY, title TEXT NOT NULL,
  isbn TEXT, pub_date TEXT, ingested_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS figures (
  figure_id TEXT PRIMARY KEY, book_id TEXT NOT NULL REFERENCES books(book_id),
  figure_no TEXT, fileref TEXT NOT NULL,
  case_type TEXT CHECK (case_type IN ('rule_a','rule_b','plate','non')),
  state TEXT NOT NULL DEFAULT 'indexed'
        CHECK (state IN ('indexed','processing','assembled','blocked_review','final','rejected')),
  idem_key TEXT UNIQUE NOT NULL, trace_id TEXT,
  confidence REAL, updated_at TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS idx_figures_book ON figures(book_id);
CREATE INDEX IF NOT EXISTS idx_figures_state ON figures(state);
CREATE TABLE IF NOT EXISTS artifacts (
  artifact_id TEXT NOT NULL, book_id TEXT NOT NULL REFERENCES books(book_id),
  figure_id TEXT NOT NULL REFERENCES figures(figure_id),
  class TEXT, confidence REAL,
  review_flag INTEGER NOT NULL DEFAULT 0 CHECK (review_flag IN (0,1)),
  PRIMARY KEY (artifact_id, book_id));
CREATE TABLE IF NOT EXISTS review_tasks (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  figure_id TEXT NOT NULL REFERENCES figures(figure_id),
  kind TEXT NOT NULL CHECK (kind IN ('mapping','mask','text','qc')),
  anchor TEXT NOT NULL,              -- B4: 版本无关复合锚 figure_id:kind（resume 锚点）
  thread_id TEXT NOT NULL,           -- 运行期 trace（含版本），仅溯源不作锚
  status TEXT NOT NULL DEFAULT 'open' CHECK (status IN ('open','assigned','done')),
  assignee TEXT, created_at TEXT NOT NULL, closed_at TEXT,
  UNIQUE (figure_id, kind, status)   -- 同 figure 同类型仅一条 open 任务
);
CREATE INDEX IF NOT EXISTS idx_review_status ON review_tasks(status);
CREATE TABLE IF NOT EXISTS agent_metrics (
  id INTEGER PRIMARY KEY AUTOINCREMENT, trace_id TEXT NOT NULL,
  agent TEXT NOT NULL, calls INTEGER NOT NULL DEFAULT 0,
  successes INTEGER NOT NULL DEFAULT 0, p99_ms REAL, ts TEXT NOT NULL);
"""

SUBDIRS = ["raw", "index", "sides", "fused", "segments", "pairs", "review", "logs"]


def init_db(db_path: str) -> sqlite3.Connection:
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.executescript(DDL)
    return conn


def init_book_dirs(root: str, book_id: str) -> Path:
    base = Path(root) / book_id
    for d in SUBDIRS:
        (base / d).mkdir(parents=True, exist_ok=True)
    return base


def upsert_figure(conn: sqlite3.Connection, state, status: str) -> None:
    conn.execute(
        """INSERT INTO figures(figure_id, book_id, figure_no, fileref, case_type,
                               state, idem_key, trace_id, confidence, updated_at)
           VALUES(?,?,?,?,?,?,?,?,?,datetime('now'))
           ON CONFLICT(figure_id) DO UPDATE SET
             state=excluded.state, idem_key=excluded.idem_key,
             confidence=excluded.confidence, updated_at=excluded.updated_at""",
        (state.figure_id, state.book_id,
         state.figure_index.get("figure_no", {}).get("norm", ""),
         state.figure_index.get("fileref", ""),
         {"rule_a": "rule_a", "rule_b": "rule_b", "plate": "plate"}.get(
             (state.fused_mapping or {}).get("case_type", ""), "non")
         if state.figure_type != "non" else "non",
         status, state.idem_key, state.trace_id, state.confidence))


def open_review_task(conn: sqlite3.Connection, state, kind: str) -> None:
    conn.execute(
        """INSERT OR IGNORE INTO review_tasks(figure_id, kind, anchor, thread_id,
                                              status, created_at)
           VALUES(?,?,?,?,'open',datetime('now'))""",
        (state.figure_id, kind, f"{state.figure_id}:{kind}", state.trace_id))
    conn.commit()
