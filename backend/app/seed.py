"""Seed initial data: default admin + example exam from exam_data.json."""
import json
import os
from pathlib import Path

from sqlalchemy.orm import Session

from . import models
from .auth import hash_password
from .db import SessionLocal, engine, Base


DEFAULT_ADMIN_USERNAME = os.environ.get("EXAM_ADMIN_USER", "admin")
DEFAULT_ADMIN_PASSWORD = os.environ.get("EXAM_ADMIN_PASSWORD", "admin123")
SEED_FILE = Path(__file__).resolve().parent.parent / "exam_data.json"


def init_db_and_seed():
    Base.metadata.create_all(bind=engine)
    db: Session = SessionLocal()
    try:
        # Admin
        if not db.query(models.Admin).filter(models.Admin.username == DEFAULT_ADMIN_USERNAME).first():
            admin = models.Admin(
                username=DEFAULT_ADMIN_USERNAME,
                password_hash=hash_password(DEFAULT_ADMIN_PASSWORD),
            )
            db.add(admin)
            db.commit()
            print(f"[seed] Created default admin: {DEFAULT_ADMIN_USERNAME}")
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
