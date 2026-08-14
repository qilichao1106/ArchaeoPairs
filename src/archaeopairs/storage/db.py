"""存储层：SQLAlchemy 模型（对应 ddl.sql）+ 会话管理（§6.5 / 9.x）。"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import BigInteger, DateTime, Integer, Text, UniqueConstraint, create_engine
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker
from sqlalchemy.types import JSON


def _json_type():
    try:
        return JSONB()
    except Exception:
        return JSON()


class Base(DeclarativeBase):
    pass


class FigureStateRow(Base):
    __tablename__ = "figure_states"
    id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer(), "sqlite"), primary_key=True)
    book_id: Mapped[str] = mapped_column(Text)
    figure_id: Mapped[str] = mapped_column(Text)
    fileref: Mapped[str] = mapped_column(Text)
    caption: Mapped[str | None] = mapped_column(Text)
    figure_note: Mapped[str | None] = mapped_column(Text)
    parent_section_id: Mapped[str | None] = mapped_column(Text)
    image_type: Mapped[str | None] = mapped_column(Text)
    case_type: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text, default="INIT")
    iteration: Mapped[int] = mapped_column(Integer, default=0)
    rule_version: Mapped[str] = mapped_column(Text, default="r1")
    prompt_version: Mapped[str] = mapped_column(Text, default="p1")
    judge_prompt_version: Mapped[str] = mapped_column(Text, default="j1")
    exclude_reason: Mapped[str | None] = mapped_column(Text)
    trace_id: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))
    __table_args__ = (
        UniqueConstraint("book_id", "figure_id", "rule_version", "prompt_version",
                         "judge_prompt_version", name="uq_figure_idem"),
    )


class PairRecordRow(Base):
    __tablename__ = "pair_records"
    id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer(), "sqlite"), primary_key=True)
    book_id: Mapped[str] = mapped_column(Text)
    artifact_id: Mapped[str] = mapped_column(Text)
    image_path: Mapped[str] = mapped_column(Text)
    candidate_images: Mapped[list | None] = mapped_column(JSON)
    image_merge_mode: Mapped[str] = mapped_column(Text, default="line_only")
    description_text: Mapped[str | None] = mapped_column(Text)
    provenance: Mapped[dict | None] = mapped_column(JSON)
    quality_flags: Mapped[dict | None] = mapped_column(JSON)
    __table_args__ = (UniqueConstraint("book_id", "artifact_id", name="uq_pair_key"),)


class ReviewTaskRow(Base):
    __tablename__ = "review_tasks"
    id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer(), "sqlite"), primary_key=True)
    figure_state_id: Mapped[int] = mapped_column(BigInteger)
    event_id: Mapped[str] = mapped_column(Text, unique=True)
    ls_task_id: Mapped[str | None] = mapped_column(Text)
    payload: Mapped[dict | None] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(Text, default="OPEN")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))


class DiagnosticReportRow(Base):
    __tablename__ = "diagnostic_reports"
    id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer(), "sqlite"), primary_key=True)
    figure_state_id: Mapped[int] = mapped_column(BigInteger)
    iteration: Mapped[int] = mapped_column(Integer, default=0)
    report: Mapped[dict | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))


def claim_figure(session, book_id: str, figure_id: str) -> bool:
    """Concurrent claim: atomic UPDATE only claims INIT rows."""
    n = session.query(FigureStateRow).filter_by(
        book_id=book_id, figure_id=figure_id, status="INIT"
    ).update({"status": "PARSED", "updated_at": datetime.now(timezone.utc)})
    return n == 1


def make_session_factory(database_url: str = "sqlite:///archaeopairs.sqlite3"):
    engine = create_engine(database_url)
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)
