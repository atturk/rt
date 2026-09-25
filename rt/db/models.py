"""
rt.db.models
Modelli SQLAlchemy 2.0. Ogni modifica qui va accompagnata da una revisione Alembic in
rt/db/migrations/versions (tests/test_db_schema.py verifica che coincidano).
"""
from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy import JSON, DateTime, Float, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


class Base(DeclarativeBase):
    pass


class Lesson(Base):
    """Una cartella di lezione. path è il percorso assoluto reale (chiave naturale)."""
    __tablename__ = "lessons"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    path: Mapped[str] = mapped_column(String(1024), unique=True)
    folder_name: Mapped[str] = mapped_column(String(512))
    data: Mapped[str] = mapped_column(String(32), default="")
    materia: Mapped[str] = mapped_column(String(256), default="")
    titolo: Mapped[str] = mapped_column(Text, default="")
    argomenti: Mapped[str] = mapped_column(Text, default="")
    workflow_state: Mapped[str] = mapped_column(String(64), default="")
    # sha256 dell'ultimo review_decisions.json esportato dal DB (o importato): se il file
    # cambia fuori da RT, al prossimo accesso il DB lo reimporta.
    ledger_sha: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)

    phase_runs: Mapped[list["PhaseRun"]] = relationship(back_populates="lesson", cascade="all, delete-orphan", passive_deletes=True)
    issues: Mapped[list["Issue"]] = relationship(back_populates="lesson", cascade="all, delete-orphan", passive_deletes=True)
    decisions: Mapped[list["ReviewDecision"]] = relationship(back_populates="lesson", cascade="all, delete-orphan", passive_deletes=True)


class PhaseRun(Base):
    """Ultimo stato registrato di una fase (da manifest.json phase_records)."""
    __tablename__ = "phase_runs"
    __table_args__ = (UniqueConstraint("lesson_id", "phase", name="uq_phase_runs_lesson_phase"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    lesson_id: Mapped[int] = mapped_column(ForeignKey("lessons.id", ondelete="CASCADE"), index=True)
    phase: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(32))
    source_fingerprint: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    processor_version: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    stale_reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    started_at: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    finished_at: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)

    lesson: Mapped[Lesson] = relationship(back_populates="phase_runs")


class Issue(Base):
    """Issue scientifica o ASR prodotta dalla review. issue_id è l'id esterno (del file)."""
    __tablename__ = "issues"
    __table_args__ = (UniqueConstraint("lesson_id", "issue_id", name="uq_issues_lesson_issue"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    lesson_id: Mapped[int] = mapped_column(ForeignKey("lessons.id", ondelete="CASCADE"), index=True)
    issue_id: Mapped[str] = mapped_column(String(256))
    kind: Mapped[str] = mapped_column(String(32), default="science")
    type: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    severity: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)

    lesson: Mapped[Lesson] = relationship(back_populates="issues")


class ReviewDecision(Base):
    """Decisione del ledger. issue_id è l'id esterno: una decisione può riferirsi a
    un'issue ASR o a un'issue non più presente nel file. reverted_at marca le decisioni
    annullate (restano per storico, non sono esportate in review_decisions.json)."""
    __tablename__ = "review_decisions"
    __table_args__ = (Index("ix_review_decisions_lesson_active", "lesson_id", "reverted_at"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    lesson_id: Mapped[int] = mapped_column(ForeignKey("lessons.id", ondelete="CASCADE"))
    issue_id: Mapped[str] = mapped_column(String(256), index=True)
    decision: Mapped[str] = mapped_column(String(32))
    resolved_text: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    resolved_by: Mapped[str] = mapped_column(String(64), default="user")
    timestamp: Mapped[str] = mapped_column(String(64))
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    original_context: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    channel: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    actor: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    reverted_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    lesson: Mapped[Lesson] = relationship(back_populates="decisions")


class LlmCall(Base):
    """Un tentativo di chiamata LLM (una riga di llm_debug.log). payload conserva la riga
    completa, così 'rt cost' produce lo stesso report leggendo dal DB."""
    __tablename__ = "llm_calls"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    lesson_id: Mapped[Optional[int]] = mapped_column(ForeignKey("lessons.id", ondelete="CASCADE"), nullable=True, index=True)
    execution_id: Mapped[Optional[str]] = mapped_column(String(128), nullable=True, index=True)
    request_id: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    job: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    unit_id: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    route_role: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    provider: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    model: Mapped[Optional[str]] = mapped_column(String(256), nullable=True)
    input_tokens: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    output_tokens: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    reasoning_tokens: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    total_tokens: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    estimated_cost: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    status: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    failure_class: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    timestamp: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


class Setting(Base):
    """Impostazione chiave/valore JSON (non segreta: i segreti vivono nel SecretStore)."""
    __tablename__ = "settings"

    key: Mapped[str] = mapped_column(String(256), primary_key=True)
    value: Mapped[Any] = mapped_column(JSON, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)


class StateDocument(Base):
    """Documento JSON di stato che prima viveva in un file (stato del daemon Telegram:
    sessioni attive, registro, coda issue, feedback atteso...). key è il percorso assoluto
    del file originale, così ogni modulo mantiene la propria struttura dati."""
    __tablename__ = "state_documents"

    key: Mapped[str] = mapped_column(String(1024), primary_key=True)
    payload: Mapped[Any] = mapped_column(JSON, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)
