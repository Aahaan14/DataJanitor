"""
DataJanitor — ORM models (SQLite via SQLAlchemy 2.0).

Entity overview
───────────────
DatasetRow 1──* ScanRow 1──* IssueRow
DatasetRow 1──* PlanRow *──1 ScanRow
PlanRow    1──* ProposalRow 1──* DecisionRow
PlanRow    1──* RuleRow
AuditRow   (append-only log; references entities by id, no foreign keys, so
            it survives every cleanup or deletion)

What is deliberately NOT stored: dataset contents. Only metadata, issue
records, proposals (which hold the specific cell values under review) and
decisions are kept. Files stay on disk under random UUID names.
"""

from datetime import datetime
from typing import List, Optional

from sqlalchemy import (
    JSON, Boolean, ForeignKey, Index, Integer, String, Text, UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import Base, UTCDateTime


class SchemaInfoRow(Base):
    """Key/value table holding the schema version (see init_db.py)."""
    __tablename__ = "schema_info"
    key: Mapped[str] = mapped_column(String(50), primary_key=True)
    value: Mapped[str] = mapped_column(String(100))


class DatasetRow(Base):
    __tablename__ = "datasets"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)  # uuid hex = file name
    original_filename: Mapped[str] = mapped_column(String(200))     # display only
    size_bytes: Mapped[int] = mapped_column(Integer)
    sha256: Mapped[str] = mapped_column(String(64))
    encoding: Mapped[str] = mapped_column(String(30))
    delimiter: Mapped[str] = mapped_column(String(4))
    row_count: Mapped[int] = mapped_column(Integer)
    column_count: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(10), default="active", index=True)  # active|deleted|expired
    uploaded_at: Mapped[datetime] = mapped_column(UTCDateTime, index=True)
    file_removed_at: Mapped[Optional[datetime]] = mapped_column(UTCDateTime, nullable=True)

    scans: Mapped[List["ScanRow"]] = relationship(
        back_populates="dataset", cascade="all, delete-orphan", order_by="ScanRow.started_at.desc()")
    plans: Mapped[List["PlanRow"]] = relationship(
        back_populates="dataset", cascade="all, delete-orphan", order_by="PlanRow.created_at.desc()")


class ScanRow(Base):
    __tablename__ = "scans"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    dataset_id: Mapped[str] = mapped_column(ForeignKey("datasets.id"), index=True)
    status: Mapped[str] = mapped_column(String(10), index=True)  # running|completed|failed
    started_at: Mapped[datetime] = mapped_column(UTCDateTime, index=True)
    completed_at: Mapped[Optional[datetime]] = mapped_column(UTCDateTime, nullable=True)
    issue_total: Mapped[int] = mapped_column(Integer, default=0)       # all issues found
    stored_issue_count: Mapped[int] = mapped_column(Integer, default=0)  # rows kept in `issues`
    truncated: Mapped[bool] = mapped_column(Boolean, default=False)
    summary: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    error_message: Mapped[Optional[str]] = mapped_column(String(300), nullable=True)

    dataset: Mapped[DatasetRow] = relationship(back_populates="scans")
    issues: Mapped[List["IssueRow"]] = relationship(
        back_populates="scan", cascade="all, delete-orphan", order_by="IssueRow.id")


class IssueRow(Base):
    __tablename__ = "issues"
    __table_args__ = (
        UniqueConstraint("scan_id", "issue_id"),
        Index("ix_issues_scan_type", "scan_id", "issue_type"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    scan_id: Mapped[str] = mapped_column(ForeignKey("scans.id"), index=True)
    issue_id: Mapped[str] = mapped_column(String(10))
    issue_type: Mapped[str] = mapped_column(String(40))
    severity: Mapped[str] = mapped_column(String(10))
    column_name: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    row_number: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    observed_value: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    explanation: Mapped[str] = mapped_column(Text)
    suggested_action: Mapped[str] = mapped_column(Text)
    details: Mapped[dict] = mapped_column(JSON, default=dict)

    scan: Mapped[ScanRow] = relationship(back_populates="issues")


class PlanRow(Base):
    __tablename__ = "repair_plans"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    dataset_id: Mapped[str] = mapped_column(ForeignKey("datasets.id"), index=True)
    scan_id: Mapped[str] = mapped_column(ForeignKey("scans.id"))
    fingerprint: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(12), default="active", index=True)  # active|superseded|stale
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, index=True)
    row_count: Mapped[int] = mapped_column(Integer)
    column_count: Mapped[int] = mapped_column(Integer)
    issue_count: Mapped[int] = mapped_column(Integer)
    truncated: Mapped[bool] = mapped_column(Boolean, default=False)
    no_proposal: Mapped[list] = mapped_column(JSON, default=list)
    validation: Mapped[dict] = mapped_column(JSON, default=dict)

    dataset: Mapped[DatasetRow] = relationship(back_populates="plans")
    rules: Mapped[List["RuleRow"]] = relationship(
        back_populates="plan", cascade="all, delete-orphan")
    proposals: Mapped[List["ProposalRow"]] = relationship(
        back_populates="plan", cascade="all, delete-orphan", order_by="ProposalRow.seq")


class RuleRow(Base):
    """One validation rule (a ColumnRule as JSON) used by a plan."""
    __tablename__ = "validation_rules"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    plan_id: Mapped[str] = mapped_column(ForeignKey("repair_plans.id"), index=True)
    column_name: Mapped[str] = mapped_column(String(200))
    definition: Mapped[dict] = mapped_column(JSON)

    plan: Mapped[PlanRow] = relationship(back_populates="rules")


class ProposalRow(Base):
    __tablename__ = "repair_proposals"
    __table_args__ = (Index("ix_proposals_plan_status", "plan_id", "status"),)

    id: Mapped[str] = mapped_column(String(20), primary_key=True)
    plan_id: Mapped[str] = mapped_column(ForeignKey("repair_plans.id"), index=True)
    seq: Mapped[int] = mapped_column(Integer)  # stable order within the plan
    issue_id: Mapped[str] = mapped_column(String(10))
    issue_type: Mapped[str] = mapped_column(String(40))
    action: Mapped[str] = mapped_column(String(20))
    classification: Mapped[str] = mapped_column(String(10))
    confidence: Mapped[str] = mapped_column(String(10))
    column_name: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    row_number: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    original_value: Mapped[Optional[str]] = mapped_column(Text, nullable=True)   # never edited
    proposed_value: Mapped[Optional[str]] = mapped_column(Text, nullable=True)   # never edited
    alternatives: Mapped[list] = mapped_column(JSON, default=list)
    allow_custom_value: Mapped[bool] = mapped_column(Boolean, default=False)
    reason: Mapped[str] = mapped_column(Text)
    conflicts_with: Mapped[list] = mapped_column(JSON, default=list)
    status: Mapped[str] = mapped_column(String(10), default="pending")  # pending|approved|rejected
    approved_value: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    decided_at: Mapped[Optional[datetime]] = mapped_column(UTCDateTime, nullable=True)

    plan: Mapped[PlanRow] = relationship(back_populates="proposals")
    decisions: Mapped[List["DecisionRow"]] = relationship(
        back_populates="proposal", cascade="all, delete-orphan", order_by="DecisionRow.id")


class DecisionRow(Base):
    """Every approve/reject ever made — the full decision history of a proposal."""
    __tablename__ = "decisions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    proposal_id: Mapped[str] = mapped_column(ForeignKey("repair_proposals.id"), index=True)
    decision: Mapped[str] = mapped_column(String(10))
    chosen_value: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    decided_at: Mapped[datetime] = mapped_column(UTCDateTime)

    proposal: Mapped[ProposalRow] = relationship(back_populates="decisions")


class AuditRow(Base):
    """
    Append-only audit trail. Details hold ids and counts, never cell values
    (those live in proposals/decisions where the review needs them).
    """
    __tablename__ = "audit_logs"
    __table_args__ = (Index("ix_audit_entity", "entity_type", "entity_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    timestamp: Mapped[datetime] = mapped_column(UTCDateTime, index=True)
    event_type: Mapped[str] = mapped_column(String(40), index=True)
    entity_type: Mapped[str] = mapped_column(String(20))
    entity_id: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    dataset_id: Mapped[Optional[str]] = mapped_column(String(32), nullable=True, index=True)
    plan_id: Mapped[Optional[str]] = mapped_column(String(32), nullable=True, index=True)
    actor: Mapped[str] = mapped_column(String(50), default="anonymous")  # real users arrive with auth
    details: Mapped[dict] = mapped_column(JSON, default=dict)


class CleanedRow(Base):
    """One generated cleaned copy. The CSV lives in the cleaned folder; the original upload is never touched."""
    __tablename__ = "cleaned_datasets"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    dataset_id: Mapped[str] = mapped_column(ForeignKey("datasets.id"), index=True)
    plan_id: Mapped[str] = mapped_column(ForeignKey("repair_plans.id"), index=True)
    status: Mapped[str] = mapped_column(String(10), index=True)  # running|completed|failed|expired|deleted
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, index=True)
    completed_at: Mapped[Optional[datetime]] = mapped_column(UTCDateTime, nullable=True)
    sha256: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    size_bytes: Mapped[int] = mapped_column(Integer, default=0)
    rows_before: Mapped[int] = mapped_column(Integer, default=0)
    rows_after: Mapped[int] = mapped_column(Integer, default=0)
    rows_deleted: Mapped[int] = mapped_column(Integer, default=0)
    cells_changed: Mapped[int] = mapped_column(Integer, default=0)
    applied_count: Mapped[int] = mapped_column(Integer, default=0)
    skipped_count: Mapped[int] = mapped_column(Integer, default=0)
    rejected_count: Mapped[int] = mapped_column(Integer, default=0)
    pending_count: Mapped[int] = mapped_column(Integer, default=0)
    validation: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    error_message: Mapped[Optional[str]] = mapped_column(String(300), nullable=True)
    file_removed_at: Mapped[Optional[datetime]] = mapped_column(UTCDateTime, nullable=True)

    outcomes: Mapped[List["OutcomeRow"]] = relationship(
        back_populates="cleaned", cascade="all, delete-orphan", order_by="OutcomeRow.id")


class OutcomeRow(Base):
    """What happened to each proposal in one cleaning run: applied, skipped, rejected or pending."""
    __tablename__ = "repair_outcomes"
    __table_args__ = (Index("ix_outcomes_cleaned_outcome", "cleaned_id", "outcome"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    cleaned_id: Mapped[str] = mapped_column(ForeignKey("cleaned_datasets.id"), index=True)
    proposal_id: Mapped[str] = mapped_column(ForeignKey("repair_proposals.id"))
    outcome: Mapped[str] = mapped_column(String(10))  # applied|skipped|rejected|pending
    reason: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)

    cleaned: Mapped[CleanedRow] = relationship(back_populates="outcomes")


class EmailReportRow(Base):
    """
    One emailed report (or an attempt to send it). The email body is NOT stored;
    it is rebuilt from the database on retry. The recipient is stored masked.
    """
    __tablename__ = "email_reports"
    __table_args__ = (Index("ix_email_reports_target", "kind", "scan_id", "cleaned_id"),)

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    kind: Mapped[str] = mapped_column(String(10))                       # scan | cleaning
    trigger: Mapped[str] = mapped_column(String(10))                    # auto | manual
    dataset_id: Mapped[str] = mapped_column(ForeignKey("datasets.id"), index=True)
    scan_id: Mapped[Optional[str]] = mapped_column(ForeignKey("scans.id"), nullable=True)
    plan_id: Mapped[Optional[str]] = mapped_column(ForeignKey("repair_plans.id"), nullable=True)
    cleaned_id: Mapped[Optional[str]] = mapped_column(ForeignKey("cleaned_datasets.id"), nullable=True)
    recipient_masked: Mapped[str] = mapped_column(String(120), default="")
    subject: Mapped[str] = mapped_column(String(200), default="")
    status: Mapped[str] = mapped_column(String(10), index=True)         # pending|sent|failed|skipped
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    error_message: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, index=True)
    last_attempt_at: Mapped[Optional[datetime]] = mapped_column(UTCDateTime, nullable=True)
    sent_at: Mapped[Optional[datetime]] = mapped_column(UTCDateTime, nullable=True)
