"""Seed initial data: default admin + example exam from exam_data.json."""
import json
import os
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.orm import Session

from . import models
from .auth import hash_password, verify_password, password_strength_error
from .db import SessionLocal, engine, Base


DEFAULT_ADMIN_USERNAME = os.environ.get("EXAM_ADMIN_USER", "admin")
DEFAULT_ADMIN_PASSWORD = os.environ.get("EXAM_ADMIN_PASSWORD", "admin123")
SEED_FILE = Path(__file__).resolve().parent.parent / "exam_data.json"


def _migrate_columns():
    """Add new columns to existing tables for backwards compatibility (SQLite)."""
    with engine.begin() as conn:
        admin_cols = {row[1] for row in conn.execute(text("PRAGMA table_info(admins)"))}
        if admin_cols and "role" not in admin_cols:
            conn.execute(text("ALTER TABLE admins ADD COLUMN role VARCHAR DEFAULT 'super' NOT NULL"))
        if admin_cols and "must_change_password" not in admin_cols:
            conn.execute(text("ALTER TABLE admins ADD COLUMN must_change_password BOOLEAN DEFAULT 0 NOT NULL"))
        exam_cols = {row[1] for row in conn.execute(text("PRAGMA table_info(exams)"))}
        if exam_cols and "shuffle_mode" not in exam_cols:
            conn.execute(text("ALTER TABLE exams ADD COLUMN shuffle_mode VARCHAR DEFAULT 'none' NOT NULL"))
        attempt_cols = {row[1] for row in conn.execute(text("PRAGMA table_info(attempts)"))}
        if attempt_cols and "question_order" not in attempt_cols:
            conn.execute(text("ALTER TABLE attempts ADD COLUMN question_order JSON"))


def init_db_and_seed():
    Base.metadata.create_all(bind=engine)
    _migrate_columns()
    db: Session = SessionLocal()
    try:
        # Admin
        existing_admin = db.query(models.Admin).filter(models.Admin.username == DEFAULT_ADMIN_USERNAME).first()
        if not existing_admin:
            weak_default = password_strength_error(DEFAULT_ADMIN_PASSWORD) is not None
            admin = models.Admin(
                username=DEFAULT_ADMIN_USERNAME,
                password_hash=hash_password(DEFAULT_ADMIN_PASSWORD),
                role="super",
                must_change_password=weak_default,
            )
            db.add(admin)
            db.commit()
            print(f"[seed] Created default admin: {DEFAULT_ADMIN_USERNAME} (must_change_password={weak_default})")
        else:
            # Force change if currently using the weak default password
            if verify_password(DEFAULT_ADMIN_PASSWORD, existing_admin.password_hash) and \
               password_strength_error(DEFAULT_ADMIN_PASSWORD) is not None:
                existing_admin.must_change_password = True
                if not existing_admin.role:
                    existing_admin.role = "super"
                db.commit()
        # Seed exam if none exists
        existing = db.query(models.Exam).first()
        if existing:
            return
        if not SEED_FILE.exists():
            return
        data = json.loads(SEED_FILE.read_text(encoding="utf-8"))
        exam = models.Exam(
            title=data.get("title", "Đề thi mẫu"),
            description="Đề thi gồm phần trắc nghiệm (chọn 1 đáp án) và phần đúng/sai. Tổng điểm quy về thang 10.",
            duration_minutes=50,
        )
        db.add(exam)
        db.flush()
        order = 1
        for q in data.get("multiple_choice", []):
            db.add(models.Question(
                exam_id=exam.id,
                order_index=order,
                type="mc",
                section=q.get("section", ""),
                data={
                    "question": q["question"],
                    "options": q["options"],
                    "answer": q["answer"],
                },
                points=1.0,
            ))
            order += 1
        for q in data.get("true_false", []):
            db.add(models.Question(
                exam_id=exam.id,
                order_index=order,
                type="tf",
                section="Phần đúng/sai",
                data={
                    "question": q["question"],
                    "statements": q["statements"],
                    "answers": q["answers"],
                },
                points=1.0,
            ))
            order += 1
        db.commit()
        print(f"[seed] Inserted exam '{exam.title}' with {order-1} questions")
    finally:
        db.close()
