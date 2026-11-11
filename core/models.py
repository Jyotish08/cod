"""SQLAlchemy 2.x relational tables for the judge problem catalog."""
from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint, Float
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.types import JSON

from core.database import Base


def utcnow():
    return datetime.now(timezone.utc)


class Problem(Base):
    __tablename__ = "problems"
    __table_args__ = (Index("ix_problems_slug", "slug", unique=True),
                      Index("ix_problems_difficulty", "difficulty"),
                      Index("ix_problems_ingestion_status", "ingestion_status"))
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    external_id: Mapped[str | None] = mapped_column(String(255), unique=True, nullable=True)
    slug: Mapped[str] = mapped_column(String(512), nullable=False)
    title: Mapped[str] = mapped_column(String(1024), nullable=False)
    difficulty: Mapped[str] = mapped_column(String(16), nullable=False, default="UNKNOWN")
    number: Mapped[int] = mapped_column(Integer, nullable=False, default=0, index=True)
    acceptance_rate: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    frequency: Mapped[str] = mapped_column(String(16), nullable=False, default="Medium")
    statement_md: Mapped[str] = mapped_column(Text, nullable=False, default="Problem statement pending enrichment.")
    constraints_md: Mapped[str | None] = mapped_column(Text)
    tags: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    time_limit_ms: Mapped[int] = mapped_column(Integer, nullable=False, default=2000)
    memory_limit_kb: Mapped[int] = mapped_column(Integer, nullable=False, default=262144)
    has_statement: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    has_sample_tests: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    has_hidden_tests: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    has_starter_code: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    has_solution: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    ingestion_status: Mapped[str] = mapped_column(String(40), nullable=False, default="NEEDS_MANUAL_REVIEW")
    missing_fields: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    raw_payload_backup: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False)
    test_cases: Mapped[list["TestCase"]] = relationship(back_populates="problem", cascade="all, delete-orphan", order_by="TestCase.order_index")
    code_templates: Mapped[list["CodeTemplate"]] = relationship(back_populates="problem", cascade="all, delete-orphan")
    solutions: Mapped[list["Solution"]] = relationship(back_populates="problem", cascade="all, delete-orphan")
    submissions: Mapped[list["SubmissionModel"]] = relationship(back_populates="problem", cascade="all, delete-orphan")


class TestCase(Base):
    __tablename__ = "test_cases"
    __table_args__ = (Index("ix_test_cases_problem_id", "problem_id"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    problem_id: Mapped[int] = mapped_column(ForeignKey("problems.id", ondelete="CASCADE"), nullable=False)
    input_data: Mapped[str] = mapped_column(Text, nullable=False)
    expected_output: Mapped[str] = mapped_column(Text, nullable=False)
    is_sample: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    explanation: Mapped[str | None] = mapped_column(Text)
    order_index: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    problem: Mapped[Problem] = relationship(back_populates="test_cases")


class CodeTemplate(Base):
    __tablename__ = "code_templates"
    __table_args__ = (UniqueConstraint("problem_id", "language", name="uq_template_problem_language"),
                      Index("ix_code_templates_problem_id", "problem_id"))
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    problem_id: Mapped[int] = mapped_column(ForeignKey("problems.id", ondelete="CASCADE"), nullable=False)
    language: Mapped[str] = mapped_column(String(64), nullable=False, default="python")
    starter_code: Mapped[str] = mapped_column(Text, nullable=False)
    driver_code: Mapped[str | None] = mapped_column(Text)
    problem: Mapped[Problem] = relationship(back_populates="code_templates")


class Solution(Base):
    __tablename__ = "solutions"
    __table_args__ = (Index("ix_solutions_problem_id", "problem_id"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    problem_id: Mapped[int] = mapped_column(ForeignKey("problems.id", ondelete="CASCADE"), nullable=False)
    language: Mapped[str] = mapped_column(String(64), nullable=False, default="python")
    solution_code: Mapped[str] = mapped_column(Text, nullable=False)
    approach_explanation_md: Mapped[str | None] = mapped_column(Text)
    time_complexity: Mapped[str | None] = mapped_column(String(255))
    space_complexity: Mapped[str | None] = mapped_column(String(255))
    problem: Mapped[Problem] = relationship(back_populates="solutions")


class SubmissionModel(Base):
    __tablename__ = "submissions"
    __table_args__ = (Index("ix_submissions_problem_id", "problem_id"),
                      Index("ix_submissions_overall_verdict", "overall_verdict"))
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    problem_id: Mapped[int] = mapped_column(ForeignKey("problems.id", ondelete="CASCADE"), nullable=False)
    language: Mapped[str] = mapped_column(String(64), nullable=False)
    source_code: Mapped[str] = mapped_column(Text, nullable=False)
    mode: Mapped[str] = mapped_column(String(16), nullable=False, default="submit")
    overall_verdict: Mapped[str] = mapped_column(String(16), nullable=False)
    passed_count: Mapped[int] = mapped_column(Integer, nullable=False)
    total_count: Mapped[int] = mapped_column(Integer, nullable=False)
    max_runtime_ms: Mapped[float] = mapped_column(nullable=False, default=0.0)
    ast_metrics_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow,
                                                    nullable=False, index=True)
    problem: Mapped[Problem] = relationship(back_populates="submissions")


class UserProblemStatus(Base):
    __tablename__ = "user_problem_status"
    __table_args__ = (UniqueConstraint("user_id", "problem_id", name="uq_user_problem_status"),
                      Index("ix_user_status_recent", "user_id", "status", "last_attempted_at"))
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    problem_id: Mapped[int] = mapped_column(ForeignKey("problems.id", ondelete="CASCADE"), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="Not started")
    is_bookmarked: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    last_attempted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    time_spent_minutes: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_code_snapshot: Mapped[str | None] = mapped_column(Text)


class UserStats(Base):
    __tablename__ = "user_stats"
    user_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    streak_days: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    monthly_goal_target: Mapped[int] = mapped_column(Integer, nullable=False, default=50)
    monthly_goal_current: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    weekly_activity: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    topic_mastery: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)


class StudyPlan(Base):
    __tablename__ = "study_plans"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(200), nullable=False, default="DSA Foundation")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    topic_progress: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    recommended_problem_ids: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
