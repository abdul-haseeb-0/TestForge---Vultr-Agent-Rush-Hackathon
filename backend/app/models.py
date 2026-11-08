from datetime import datetime, timezone
from sqlalchemy import String, Text, DateTime, Integer, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship
from .db import Base

def now(): return datetime.now(timezone.utc)
class Run(Base):
    __tablename__="runs"
    id: Mapped[str]=mapped_column(String(36), primary_key=True)
    url: Mapped[str]=mapped_column(String(2048))
    depth: Mapped[str]=mapped_column(String(20), default="standard")
    workflow_json: Mapped[str]=mapped_column(Text, default="[]")
    evidence_json: Mapped[str]=mapped_column(Text, default="{}")
    status: Mapped[str]=mapped_column(String(20), default="queued", index=True)
    created_at: Mapped[datetime]=mapped_column(DateTime(timezone=True), default=now)
    finished_at: Mapped[datetime|None]=mapped_column(DateTime(timezone=True), nullable=True)
    summary: Mapped[str]=mapped_column(Text, default="")
    score: Mapped[int]=mapped_column(Integer, default=0)
    error: Mapped[str]=mapped_column(Text, default="")
    mode: Mapped[str]=mapped_column(String(30), default="local")
    findings: Mapped[list["Finding"]]=relationship(back_populates="run", cascade="all, delete-orphan")
class Finding(Base):
    __tablename__="findings"
    id: Mapped[int]=mapped_column(Integer, primary_key=True)
    run_id: Mapped[str]=mapped_column(ForeignKey("runs.id"), index=True)
    severity: Mapped[str]=mapped_column(String(20)); category: Mapped[str]=mapped_column(String(60))
    title: Mapped[str]=mapped_column(String(250)); description: Mapped[str]=mapped_column(Text)
    evidence: Mapped[str]=mapped_column(Text); recommendation: Mapped[str]=mapped_column(Text)
    run: Mapped[Run]=relationship(back_populates="findings")
class Artifact(Base):
    __tablename__="artifacts"
    id: Mapped[int]=mapped_column(Integer, primary_key=True)
    run_id: Mapped[str]=mapped_column(ForeignKey("runs.id"), index=True)
    filename: Mapped[str]=mapped_column(String(255)); path: Mapped[str]=mapped_column(String(2048))

from sqlalchemy import JSON, LargeBinary, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
JsonType = JSON().with_variant(JSONB(), "postgresql")
class AppSetting(Base):
    __tablename__="app_settings"
    key: Mapped[str]=mapped_column(String(80), primary_key=True); value: Mapped[str]=mapped_column(Text, default="")
    updated_at: Mapped[datetime]=mapped_column(DateTime(timezone=True), default=now)
class RepairJob(Base):
    __tablename__="repair_jobs"
    id: Mapped[str]=mapped_column(String(32), primary_key=True); name: Mapped[str]=mapped_column(String(255), default="")
    status: Mapped[str]=mapped_column(String(30), default="queued", index=True)
    created_at: Mapped[datetime]=mapped_column(DateTime(timezone=True), default=now); updated_at: Mapped[datetime]=mapped_column(DateTime(timezone=True), default=now)
    data: Mapped[dict]=mapped_column(JsonType, default=dict)
class RepairBlob(Base):  # original upload zip, screenshots, command logs
    __tablename__="repair_blobs"; __table_args__=(UniqueConstraint("job_id","kind","name"),)
    id: Mapped[int]=mapped_column(Integer, primary_key=True); job_id: Mapped[str]=mapped_column(String(32), index=True)
    kind: Mapped[str]=mapped_column(String(20)); name: Mapped[str]=mapped_column(String(255)); data: Mapped[bytes]=mapped_column(LargeBinary)
