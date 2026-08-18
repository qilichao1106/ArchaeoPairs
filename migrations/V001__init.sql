-- ArchaeoPairs DDL (PostgreSQL) — 对齐《技术方案 V0.4》数据库 Schema 与索引设计（§6.5）
-- 与 src/archaeopairs/storage/db.py SQLAlchemy 模型一一对应

CREATE TABLE IF NOT EXISTS figure_states (
    id BIGSERIAL PRIMARY KEY,
    book_id TEXT NOT NULL,
    figure_id TEXT NOT NULL,
    fileref TEXT NOT NULL,
    caption TEXT,
    figure_note TEXT,
    parent_section_id TEXT,
    image_type TEXT,
    case_type TEXT,
    status TEXT NOT NULL DEFAULT 'INIT',
    iteration INT NOT NULL DEFAULT 0,
    rule_version TEXT NOT NULL DEFAULT 'r1',
    prompt_version TEXT NOT NULL DEFAULT 'p1',
    judge_prompt_version TEXT NOT NULL DEFAULT 'j1',
    exclude_reason TEXT,
    trace_id TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_figure_idem UNIQUE (book_id, figure_id, rule_version, prompt_version, judge_prompt_version)
);
CREATE INDEX IF NOT EXISTS idx_fs_poll ON figure_states (status, updated_at);
CREATE INDEX IF NOT EXISTS idx_fs_book ON figure_states (book_id);

CREATE TABLE IF NOT EXISTS diagnostic_reports (
    id BIGSERIAL PRIMARY KEY,
    figure_state_id BIGINT NOT NULL REFERENCES figure_states(id) ON DELETE CASCADE,
    iteration INT NOT NULL,
    report JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_dr_fig ON diagnostic_reports (figure_state_id, iteration);
CREATE INDEX IF NOT EXISTS idx_dr_gin ON diagnostic_reports USING GIN (report jsonb_path_ops);

CREATE TABLE IF NOT EXISTS pair_records (
    id BIGSERIAL PRIMARY KEY,
    book_id TEXT NOT NULL,
    artifact_id TEXT NOT NULL,
    image_path TEXT NOT NULL,
    candidate_images JSONB NOT NULL DEFAULT '[]'::jsonb,
    image_merge_mode TEXT NOT NULL DEFAULT 'line_only',
    description_text TEXT,
    provenance JSONB,
    quality_flags JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_pair_key UNIQUE (book_id, artifact_id)
);

CREATE TABLE IF NOT EXISTS review_tasks (
    id BIGSERIAL PRIMARY KEY,
    figure_state_id BIGINT NOT NULL REFERENCES figure_states(id) ON DELETE CASCADE,
    event_id TEXT NOT NULL UNIQUE,
    ls_task_id TEXT,
    payload JSONB,
    status TEXT NOT NULL DEFAULT 'OPEN',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_rt_status ON review_tasks (status, updated_at);
