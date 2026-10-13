"""Persistence model for the LockX Recovery service.

The user/account relationship deliberately remains a string foreign key so this
module can plug into an existing LockX authentication service.
"""
from datetime import datetime, timezone
from enum import Enum
from uuid import uuid4

from sqlalchemy import DateTime, Enum as SqlEnum, ForeignKey, JSON, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class CaseStatus(str, Enum):
    monitoring = "monitoring"
    paused = "paused"
    closed = "closed"


class MatchStatus(str, Enum):
    new = "new"
    reviewing = "reviewing"
    dismissed = "dismissed"
    escalated = "escalated"


class RecoveryCase(Base):
    __tablename__ = "recovery_cases"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    owner_id: Mapped[str] = mapped_column(String(128), index=True)
    brand: Mapped[str] = mapped_column(String(120))
    model: Mapped[str] = mapped_column(String(160))
    reference: Mapped[str | None] = mapped_column(String(120))
    serial_number: Mapped[str | None] = mapped_column(String(120))
    distinctive_details: Mapped[str | None] = mapped_column(Text)
    status: Mapped[CaseStatus] = mapped_column(SqlEnum(CaseStatus), default=CaseStatus.monitoring)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)
    photos: Mapped[list["CasePhoto"]] = relationship(back_populates="case", cascade="all, delete-orphan")
    matches: Mapped[list["ListingCandidate"]] = relationship(back_populates="case", cascade="all, delete-orphan")


class CasePhoto(Base):
    __tablename__ = "case_photos"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    case_id: Mapped[str] = mapped_column(ForeignKey("recovery_cases.id"), index=True)
    object_key: Mapped[str] = mapped_column(String(500))
    sha256: Mapped[str] = mapped_column(String(64), index=True)
    descriptor: Mapped[dict | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    case: Mapped[RecoveryCase] = relationship(back_populates="photos")


class ListingCandidate(Base):
    __tablename__ = "listing_candidates"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    case_id: Mapped[str] = mapped_column(ForeignKey("recovery_cases.id"), index=True)
    connector_key: Mapped[str] = mapped_column(String(120), index=True)
    source_url: Mapped[str] = mapped_column(String(2000))
    title: Mapped[str] = mapped_column(String(500))
    normalized_listing: Mapped[dict] = mapped_column(JSON)
    text_score: Mapped[float]
    image_score: Mapped[float | None]
    confidence: Mapped[float]
    status: Mapped[MatchStatus] = mapped_column(SqlEnum(MatchStatus), default=MatchStatus.new)
    found_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    case: Mapped[RecoveryCase] = relationship(back_populates="matches")
    evidence: Mapped[list["EvidenceSnapshot"]] = relationship(back_populates="candidate", cascade="all, delete-orphan")


class EvidenceSnapshot(Base):
    __tablename__ = "evidence_snapshots"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    candidate_id: Mapped[str] = mapped_column(ForeignKey("listing_candidates.id"), index=True)
    object_key: Mapped[str] = mapped_column(String(500))
    sha256: Mapped[str] = mapped_column(String(64), unique=True)
    captured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    provenance: Mapped[dict] = mapped_column(JSON)
    candidate: Mapped[ListingCandidate] = relationship(back_populates="evidence")
