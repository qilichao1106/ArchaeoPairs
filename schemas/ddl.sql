-- ArchaeoPairs DDL (SQLite) — 编排 checkpointer 复用同库
PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;

CREATE TABLE IF NOT EXISTS books (
  book_id   TEXT PRIMARY KEY,
  title     TEXT NOT NULL,
  isbn      TEXT,
  pub_date  TEXT,
  ingested_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS figures (
  figure_id   TEXT PRIMARY KEY,
  book_id     TEXT NOT NULL REFERENCES books(book_id),
  figure_no   TEXT,                 -- 归一图号
  fileref     TEXT NOT NULL,
  case_type   TEXT CHECK (case_type IN ('rule_a','rule_b','plate','non')),
  state       TEXT NOT NULL DEFAULT 'indexed'
              CHECK (state IN ('indexed','processing','blocked_review','final','rejected')),
  idem_key    TEXT UNIQUE NOT NULL, -- book_id:figure_id:rule_version:prompt_version
  trace_id    TEXT,
  confidence  REAL,
  updated_at  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_figures_book ON figures(book_id);
CREATE INDEX IF NOT EXISTS idx_figures_state ON figures(state);

CREATE TABLE IF NOT EXISTS artifacts (
  artifact_id TEXT NOT NULL,
  book_id     TEXT NOT NULL REFERENCES books(book_id),
  figure_id   TEXT NOT NULL REFERENCES figures(figure_id),
  class       TEXT,                 -- 器类：铜鼎/瓷碗/...
  confidence  REAL,
  review_flag INTEGER NOT NULL DEFAULT 0 CHECK (review_flag IN (0,1)),
  PRIMARY KEY (artifact_id, book_id)
);
CREATE INDEX IF NOT EXISTS idx_artifacts_class ON artifacts(class);
CREATE INDEX IF NOT EXISTS idx_artifacts_book ON artifacts(book_id);

CREATE TABLE IF NOT EXISTS review_tasks (
  id          INTEGER PRIMARY KEY AUTOINCREMENT,
  thread_id   TEXT NOT NULL,        -- = idem_key，resume 锚点
  figure_id   TEXT NOT NULL REFERENCES figures(figure_id),
  kind        TEXT NOT NULL CHECK (kind IN ('mapping','mask','text','qc')),
  status      TEXT NOT NULL DEFAULT 'open' CHECK (status IN ('open','assigned','done')),
  assignee    TEXT,
  created_at  TEXT NOT NULL,
  closed_at   TEXT
);
CREATE INDEX IF NOT EXISTS idx_review_status ON review_tasks(status);

CREATE TABLE IF NOT EXISTS agent_metrics (
  id          INTEGER PRIMARY KEY AUTOINCREMENT,
  trace_id    TEXT NOT NULL,
  agent       TEXT NOT NULL,
  calls       INTEGER NOT NULL DEFAULT 0,
  successes   INTEGER NOT NULL DEFAULT 0,
  p99_ms      REAL,
  ts          TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_metrics_agent ON agent_metrics(agent);
