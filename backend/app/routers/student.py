"""Student API: start attempt with code, submit answers, view results, leaderboard."""
import asyncio
from datetime import datetime
from typing import List

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from .. import models, schemas
from ..db import get_db
from ..scoring import grade_attempt
from ..ws_manager import manager

router = APIRouter(prefix="/api", tags=["student"])


def _build_public_questions(exam: models.Exam):
    out = []
    for q in exam.questions:
        d = q.data or {}
        if q.type == "mc":
            out.append({
                "id": q.id,
                "type": "mc",
                "section": q.section or "",
                "order_index": q.order_index,
                "points": q.points,
                "question": d.get("question", ""),
                "options": d.get("options", {}),
            })
        elif q.type == "tf":
            out.append({
                "id": q.id,
                "type": "tf",
                "section": q.section or "",
                "order_index": q.order_index,
                "points": q.points,
                "question": d.get("question", ""),
                "statements": d.get("statements", {}),
            })
    return out


@router.get("/exams/active")
def list_active_exams(db: Session = Depends(get_db)):
    """Public list of active exams (name + id only)."""
    rows = (
        db.query(models.Exam)
        .filter(models.Exam.is_active == True)  # noqa: E712
        .order_by(models.Exam.created_at.desc())
        .all()
    )
    return [
        {"id": e.id, "title": e.title, "description": e.description or "", "duration_minutes": e.duration_minutes}
        for e in rows
    ]


@router.post("/exam/start", response_model=schemas.StartAttemptResponse)
def start_attempt(body: schemas.StartAttemptRequest, db: Session = Depends(get_db)):
    code = (body.code or "").strip().upper()
    if not code:
        raise HTTPException(400, "Vui lòng nhập mã thi")
    if not body.student_name or len(body.student_name.strip()) < 2:
        raise HTTPException(400, "Vui lòng nhập họ tên đầy đủ")
    c = db.query(models.ExamCode).filter(models.ExamCode.code == code).first()
    if not c:
        raise HTTPException(404, "Mã thi không tồn tại")
    if c.used_at is not None:
        raise HTTPException(
            403,
            f"Mã thi này đã được dùng bởi {c.used_by}. Mỗi mã chỉ sử dụng một lần.",
        )
    exam = c.exam
    if not exam.is_active:
        raise HTTPException(403, "Đề thi hiện đang bị khoá")
    # Mark code used and create attempt
    c.used_by = body.student_name.strip()
    c.used_at = datetime.utcnow()
    attempt = models.Attempt(
        exam_id=exam.id,
        code_id=c.id,
        student_name=body.student_name.strip(),
        student_class=(body.student_class or "").strip(),
        started_at=datetime.utcnow(),
        answers={},
    )
    db.add(attempt)
    db.commit()
    db.refresh(attempt)
    return schemas.StartAttemptResponse(
        attempt_id=attempt.id,
        exam={
            "id": exam.id,
            "title": exam.title,
            "description": exam.description or "",
            "duration_minutes": exam.duration_minutes,
            "show_leaderboard": exam.show_leaderboard,
        },
        questions=_build_public_questions(exam),
        started_at=attempt.started_at,
        duration_minutes=exam.duration_minutes,
        student_name=attempt.student_name,
    )


@router.post("/exam/submit")
async def submit_attempt(body: schemas.SubmitAttemptRequest, db: Session = Depends(get_db)):
    a = db.query(models.Attempt).filter(models.Attempt.id == body.attempt_id).first()
    if not a:
        raise HTTPException(404, "Không tìm thấy lượt làm bài")
    if a.submitted_at is not None:
        raise HTTPException(403, "Bạn đã nộp bài rồi")
    exam = a.exam
    score, total, num_correct, details = grade_attempt(exam, body.answers or {})
    a.answers = body.answers or {}
    a.score = score
    a.total_points = total
    a.submitted_at = datetime.utcnow()
    a.duration_seconds = max(0, int((a.submitted_at - a.started_at).total_seconds()))
    db.commit()
    db.refresh(a)

    # Broadcast leaderboard update
    try:
        entries = _get_leaderboard_entries(db, exam.id)
        await manager.broadcast(exam.id, {
            "type": "leaderboard",
            "payload": {
                "exam_id": exam.id,
                "exam_title": exam.title,
                "entries": [e.model_dump(mode="json") for e in entries],
            },
        })
    except Exception:
        pass

    return {
        "attempt_id": a.id,
        "exam_id": exam.id,
        "exam_title": exam.title,
        "student_name": a.student_name,
        "student_class": a.student_class or "",
        "score": a.score,
        "total_points": a.total_points,
        "score_on_ten": round(a.score / a.total_points * 10, 2) if a.total_points else 0,
        "num_correct": num_correct,
        "num_questions": len(exam.questions),
        "duration_seconds": a.duration_seconds,
        "submitted_at": a.submitted_at,
        "details": details,
    }


@router.get("/exam/result/{attempt_id}")
def get_result(attempt_id: int, db: Session = Depends(get_db)):
    a = db.query(models.Attempt).filter(models.Attempt.id == attempt_id).first()
    if not a:
        raise HTTPException(404, "Không tìm thấy lượt làm bài")
    if a.submitted_at is None:
        raise HTTPException(403, "Bạn chưa nộp bài")
    exam = a.exam
    score, total, num_correct, details = grade_attempt(exam, a.answers or {})
    return {
        "attempt_id": a.id,
        "exam_id": exam.id,
        "exam_title": exam.title,
        "student_name": a.student_name,
        "student_class": a.student_class or "",
        "score": a.score,
        "total_points": a.total_points,
        "score_on_ten": round(a.score / a.total_points * 10, 2) if a.total_points else 0,
        "num_correct": num_correct,
        "num_questions": len(exam.questions),
        "duration_seconds": a.duration_seconds,
        "submitted_at": a.submitted_at,
        "details": details,
    }


def _get_leaderboard_entries(db: Session, exam_id: int, limit: int = 100) -> List[schemas.LeaderboardEntry]:
    rows = (
        db.query(models.Attempt)
        .filter(models.Attempt.exam_id == exam_id, models.Attempt.submitted_at.isnot(None))
        .order_by(
            models.Attempt.score.desc(),
            models.Attempt.duration_seconds.asc(),
            models.Attempt.submitted_at.asc(),
        )
        .limit(limit)
        .all()
    )
    out = []
    for a in rows:
        out.append(schemas.LeaderboardEntry(
            attempt_id=a.id,
            student_name=a.student_name,
            student_class=a.student_class or "",
            score=a.score,
            total_points=a.total_points,
            score_on_ten=round(a.score / a.total_points * 10, 2) if a.total_points else 0,
            submitted_at=a.submitted_at,
            duration_seconds=a.duration_seconds,
        ))
    return out


@router.get("/exams/{exam_id}/leaderboard", response_model=schemas.LeaderboardPayload)
def leaderboard(exam_id: int, db: Session = Depends(get_db)):
    exam = db.query(models.Exam).filter(models.Exam.id == exam_id).first()
    if not exam:
        raise HTTPException(404, "Không tìm thấy đề thi")
    if not exam.show_leaderboard:
        # Still return but empty if hidden
        return schemas.LeaderboardPayload(exam_id=exam.id, exam_title=exam.title, entries=[])
    return schemas.LeaderboardPayload(
        exam_id=exam.id,
        exam_title=exam.title,
        entries=_get_leaderboard_entries(db, exam.id),
    )
