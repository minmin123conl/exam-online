"""SQLAlchemy ORM models."""
from datetime import datetime
from sqlalchemy import (
    Column, Integer, String, Text, DateTime, Float, Boolean, ForeignKey, JSON, Index
)
from sqlalchemy.orm import relationship

from .db import Base


class Admin(Base):
    __tablename__ = "admins"
    id = Column(Integer, primary_key=True)
    username = Column(String, unique=True, nullable=False)
    password_hash = Column(String, nullable=False)
    role = Column(String, default="super", nullable=False)  # "super" | "manager" | "viewer"
    must_change_password = Column(Boolean, default=False, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)


class Exam(Base):
    __tablename__ = "exams"
    id = Column(Integer, primary_key=True)
    title = Column(String, nullable=False)
    description = Column(Text, default="")
    duration_minutes = Column(Integer, default=45)
    is_active = Column(Boolean, default=True)
    show_leaderboard = Column(Boolean, default=True)
    shuffle_mode = Column(String, default="none", nullable=False)  # none | by_group | all
    created_at = Column(DateTime, default=datetime.utcnow)
    questions = relationship("Question", back_populates="exam", cascade="all, delete-orphan", order_by="Question.order_index")
    codes = relationship("ExamCode", back_populates="exam", cascade="all, delete-orphan")
    attempts = relationship("Attempt", back_populates="exam", cascade="all, delete-orphan")


class Question(Base):
    __tablename__ = "questions"
    id = Column(Integer, primary_key=True)
    exam_id = Column(Integer, ForeignKey("exams.id", ondelete="CASCADE"), nullable=False)
    order_index = Column(Integer, default=0)
    type = Column(String, nullable=False)  # "mc" or "tf"
    section = Column(String, default="")
    # For MC: {"question": str, "options": {"A": str, "B": str, "C": str, "D": str}, "answer": "A"}
    # For TF: {"question": str, "statements": {"a": str, ...}, "answers": {"a": bool, ...}}
    data = Column(JSON, nullable=False)
    points = Column(Float, default=1.0)
    exam = relationship("Exam", back_populates="questions")


class ExamCode(Base):
    __tablename__ = "exam_codes"
    id = Column(Integer, primary_key=True)
    exam_id = Column(Integer, ForeignKey("exams.id", ondelete="CASCADE"), nullable=False)
    code = Column(String, unique=True, nullable=False, index=True)
    note = Column(String, default="")  # e.g., student name this code is reserved for
    # Last user info (set/overwritten on each use)
    used_by = Column(String, nullable=True)
    used_at = Column(DateTime, nullable=True)
    # 0 = unlimited; otherwise the maximum number of times this code can be used
    max_uses = Column(Integer, nullable=False, default=1)
    uses_count = Column(Integer, nullable=False, default=0)
    created_at = Column(DateTime, default=datetime.utcnow)
    exam = relationship("Exam", back_populates="codes")
    attempts = relationship("Attempt", back_populates="code")


class Attempt(Base):
    __tablename__ = "attempts"
    id = Column(Integer, primary_key=True)
    exam_id = Column(Integer, ForeignKey("exams.id", ondelete="CASCADE"), nullable=False)
    code_id = Column(Integer, ForeignKey("exam_codes.id", ondelete="SET NULL"), nullable=True)
    student_name = Column(String, nullable=False)
    student_class = Column(String, default="")
    started_at = Column(DateTime, default=datetime.utcnow)
    submitted_at = Column(DateTime, nullable=True)
    # answers: dict {question_id: "A"} for MC; {question_id: {"a": true, ...}} for TF
    answers = Column(JSON, default=dict)
    question_order = Column(JSON, default=list)  # list of question IDs in display order (if shuffled)
    score = Column(Float, default=0.0)
    total_points = Column(Float, default=0.0)
    duration_seconds = Column(Integer, default=0)
    exam = relationship("Exam", back_populates="attempts")
    code = relationship("ExamCode", back_populates="attempts")


Index("idx_attempt_exam_score", Attempt.exam_id, Attempt.score.desc())
