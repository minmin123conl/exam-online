"""Admin API routes: login, CRUD exams/questions/codes, view attempts."""
import secrets
import string
from datetime import datetime
from typing import List

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.orm import Session
from sqlalchemy import func

from .. import models, schemas
from ..auth import (
    create_access_token,
    get_current_admin,
    hash_password,
    verify_password,
)
from ..db import get_db

router = APIRouter(prefix="/api/admin", tags=["admin"])


# ---- Auth ----
@router.post("/login", response_model=schemas.Token)
def login(form: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)):
    admin = db.query(models.Admin).filter(models.Admin.username == form.username).first()
    if not admin or not verify_password(form.password, admin.password_hash):
        raise HTTPException(status_code=401, detail="Sai tên đăng nhập hoặc mật khẩu")
    token = create_access_token(sub=admin.username)
    return schemas.Token(access_token=token)


@router.get("/me")
def me(admin: models.Admin = Depends(get_current_admin)):
    return {"username": admin.username}


@router.post("/change-password")
def change_password(
    body: dict,
    admin: models.Admin = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    old = body.get("old_password") or ""
    new = body.get("new_password") or ""
    if not new or len(new) < 4:
        raise HTTPException(status_code=400, detail="Mật khẩu mới phải có ít nhất 4 ký tự")
    if not verify_password(old, admin.password_hash):
        raise HTTPException(status_code=400, detail="Sai mật khẩu cũ")
    admin.password_hash = hash_password(new)
    db.commit()
    return {"ok": True}


# ---- Exams CRUD ----
def _exam_summary(exam: models.Exam, db: Session) -> schemas.ExamSummary:
    num_codes = db.query(func.count(models.ExamCode.id)).filter(models.ExamCode.exam_id == exam.id).scalar() or 0
    num_codes_used = db.query(func.count(models.ExamCode.id)).filter(
        models.ExamCode.exam_id == exam.id, models.ExamCode.used_at.isnot(None)
    ).scalar() or 0
    num_attempts = db.query(func.count(models.Attempt.id)).filter(
        models.Attempt.exam_id == exam.id, models.Attempt.submitted_at.isnot(None)
    ).scalar() or 0
    return schemas.ExamSummary(
        id=exam.id,
        title=exam.title,
        description=exam.description or "",
        duration_minutes=exam.duration_minutes,
        is_active=exam.is_active,
        show_leaderboard=exam.show_leaderboard,
        created_at=exam.created_at,
        num_questions=len(exam.questions),
        num_codes=num_codes,
        num_codes_used=num_codes_used,
        num_attempts=num_attempts,
    )


@router.get("/exams", response_model=List[schemas.ExamSummary])
def list_exams(db: Session = Depends(get_db), _: models.Admin = Depends(get_current_admin)):
    exams = db.query(models.Exam).order_by(models.Exam.created_at.desc()).all()
    return [_exam_summary(e, db) for e in exams]


@router.post("/exams", response_model=schemas.ExamSummary)
def create_exam(body: schemas.ExamIn, db: Session = Depends(get_db), _: models.Admin = Depends(get_current_admin)):
    exam = models.Exam(
        title=body.title,
        description=body.description,
        duration_minutes=body.duration_minutes,
        is_active=body.is_active,
        show_leaderboard=body.show_leaderboard,
    )
    db.add(exam)
    db.commit()
    db.refresh(exam)
    return _exam_summary(exam, db)


@router.get("/exams/{exam_id}", response_model=schemas.ExamFull)
def get_exam(exam_id: int, db: Session = Depends(get_db), _: models.Admin = Depends(get_current_admin)):
    exam = db.query(models.Exam).filter(models.Exam.id == exam_id).first()
    if not exam:
        raise HTTPException(404, "Không tìm thấy đề thi")
    s = _exam_summary(exam, db)
    return schemas.ExamFull(
        **s.model_dump(),
        questions=[schemas.QuestionOut.model_validate(q) for q in exam.questions],
    )


@router.put("/exams/{exam_id}", response_model=schemas.ExamSummary)
def update_exam(
    exam_id: int,
    body: schemas.ExamIn,
    db: Session = Depends(get_db),
    _: models.Admin = Depends(get_current_admin),
):
    exam = db.query(models.Exam).filter(models.Exam.id == exam_id).first()
    if not exam:
        raise HTTPException(404, "Không tìm thấy đề thi")
    exam.title = body.title
    exam.description = body.description
    exam.duration_minutes = body.duration_minutes
    exam.is_active = body.is_active
    exam.show_leaderboard = body.show_leaderboard
    db.commit()
    db.refresh(exam)
    return _exam_summary(exam, db)


@router.delete("/exams/{exam_id}")
def delete_exam(exam_id: int, db: Session = Depends(get_db), _: models.Admin = Depends(get_current_admin)):
    exam = db.query(models.Exam).filter(models.Exam.id == exam_id).first()
    if not exam:
        raise HTTPException(404, "Không tìm thấy đề thi")
    db.delete(exam)
    db.commit()
    return {"ok": True}


@router.post("/exams/{exam_id}/duplicate", response_model=schemas.ExamSummary)
def duplicate_exam(exam_id: int, db: Session = Depends(get_db), _: models.Admin = Depends(get_current_admin)):
    exam = db.query(models.Exam).filter(models.Exam.id == exam_id).first()
    if not exam:
        raise HTTPException(404, "Không tìm thấy đề thi")
    new_exam = models.Exam(
        title=exam.title + " (copy)",
        description=exam.description,
        duration_minutes=exam.duration_minutes,
        is_active=exam.is_active,
        show_leaderboard=exam.show_leaderboard,
    )
    db.add(new_exam)
    db.flush()
    for q in exam.questions:
        db.add(models.Question(
            exam_id=new_exam.id,
            order_index=q.order_index,
            type=q.type,
            section=q.section,
            data=q.data,
            points=q.points,
        ))
    db.commit()
    db.refresh(new_exam)
    return _exam_summary(new_exam, db)


# ---- Questions CRUD ----
@router.post("/exams/{exam_id}/questions", response_model=schemas.QuestionOut)
def add_question(
    exam_id: int,
    body: schemas.QuestionIn,
    db: Session = Depends(get_db),
    _: models.Admin = Depends(get_current_admin),
):
    exam = db.query(models.Exam).filter(models.Exam.id == exam_id).first()
    if not exam:
        raise HTTPException(404, "Không tìm thấy đề thi")
    if body.type not in ("mc", "tf"):
        raise HTTPException(400, "Loại câu hỏi không hợp lệ")
    max_order = db.query(func.max(models.Question.order_index)).filter(models.Question.exam_id == exam_id).scalar() or 0
    q = models.Question(
        exam_id=exam_id,
        order_index=body.order_index if body.order_index else max_order + 1,
        type=body.type,
        section=body.section,
        data=body.data,
        points=body.points,
    )
    db.add(q)
    db.commit()
    db.refresh(q)
    return q


@router.put("/questions/{question_id}", response_model=schemas.QuestionOut)
def update_question(
    question_id: int,
    body: schemas.QuestionIn,
    db: Session = Depends(get_db),
    _: models.Admin = Depends(get_current_admin),
):
    q = db.query(models.Question).filter(models.Question.id == question_id).first()
    if not q:
        raise HTTPException(404, "Không tìm thấy câu hỏi")
    q.type = body.type
    q.section = body.section
    q.data = body.data
    q.points = body.points
    if body.order_index:
        q.order_index = body.order_index
    db.commit()
    db.refresh(q)
    return q


@router.delete("/questions/{question_id}")
def delete_question(
    question_id: int,
    db: Session = Depends(get_db),
    _: models.Admin = Depends(get_current_admin),
):
    q = db.query(models.Question).filter(models.Question.id == question_id).first()
    if not q:
        raise HTTPException(404, "Không tìm thấy câu hỏi")
    db.delete(q)
    db.commit()
    return {"ok": True}


# ---- Codes ----
def _gen_code(length: int = 8) -> str:
    # Avoid confusing chars: no 0, O, 1, I, l
    alphabet = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"
    return "".join(secrets.choice(alphabet) for _ in range(length))


@router.get("/exams/{exam_id}/codes", response_model=List[schemas.ExamCodeOut])
def list_codes(exam_id: int, db: Session = Depends(get_db), _: models.Admin = Depends(get_current_admin)):
    codes = (
        db.query(models.ExamCode)
        .filter(models.ExamCode.exam_id == exam_id)
        .order_by(models.ExamCode.created_at.desc())
        .all()
    )
    return codes


@router.post("/exams/{exam_id}/codes/generate", response_model=List[schemas.ExamCodeOut])
def generate_codes(
    exam_id: int,
    body: schemas.GenerateCodesRequest,
    db: Session = Depends(get_db),
    _: models.Admin = Depends(get_current_admin),
):
    exam = db.query(models.Exam).filter(models.Exam.id == exam_id).first()
    if not exam:
        raise HTTPException(404, "Không tìm thấy đề thi")
    created = []
    for i in range(body.count):
        for _try in range(20):
            code = _gen_code()
            if not db.query(models.ExamCode).filter(models.ExamCode.code == code).first():
                break
        else:
            raise HTTPException(500, "Không tạo được mã ngẫu nhiên duy nhất, thử lại")
        note = f"{body.note_prefix}{i + 1:02d}" if body.note_prefix else ""
        c = models.ExamCode(exam_id=exam_id, code=code, note=note)
        db.add(c)
        created.append(c)
    db.commit()
    for c in created:
        db.refresh(c)
    return created


@router.post("/exams/{exam_id}/codes/custom", response_model=schemas.ExamCodeOut)
def add_code(
    exam_id: int,
    body: schemas.AddCodeRequest,
    db: Session = Depends(get_db),
    _: models.Admin = Depends(get_current_admin),
):
    exam = db.query(models.Exam).filter(models.Exam.id == exam_id).first()
    if not exam:
        raise HTTPException(404, "Không tìm thấy đề thi")
    code = body.code.strip().upper()
    if not code:
        raise HTTPException(400, "Mã không được rỗng")
    if db.query(models.ExamCode).filter(models.ExamCode.code == code).first():
        raise HTTPException(400, "Mã đã tồn tại")
    c = models.ExamCode(exam_id=exam_id, code=code, note=body.note)
    db.add(c)
    db.commit()
    db.refresh(c)
    return c


@router.delete("/codes/{code_id}")
def delete_code(
    code_id: int,
    db: Session = Depends(get_db),
    _: models.Admin = Depends(get_current_admin),
):
    c = db.query(models.ExamCode).filter(models.ExamCode.id == code_id).first()
    if not c:
        raise HTTPException(404, "Không tìm thấy mã")
    db.delete(c)
    db.commit()
    return {"ok": True}


@router.post("/codes/{code_id}/reset")
def reset_code(
    code_id: int,
    db: Session = Depends(get_db),
    _: models.Admin = Depends(get_current_admin),
):
    """Cho phép học sinh dùng lại mã (reset trạng thái đã dùng)."""
    c = db.query(models.ExamCode).filter(models.ExamCode.id == code_id).first()
    if not c:
        raise HTTPException(404, "Không tìm thấy mã")
    c.used_by = None
    c.used_at = None
    db.commit()
    return {"ok": True}


# ---- Attempts / results ----
@router.get("/exams/{exam_id}/attempts")
def list_attempts(exam_id: int, db: Session = Depends(get_db), _: models.Admin = Depends(get_current_admin)):
    rows = (
        db.query(models.Attempt)
        .filter(models.Attempt.exam_id == exam_id)
        .order_by(models.Attempt.score.desc(), models.Attempt.duration_seconds.asc())
        .all()
    )
    out = []
    for a in rows:
        out.append({
            "id": a.id,
            "student_name": a.student_name,
            "student_class": a.student_class or "",
            "score": a.score,
            "total_points": a.total_points,
            "score_on_ten": round(a.score / a.total_points * 10, 2) if a.total_points else 0,
            "started_at": a.started_at,
            "submitted_at": a.submitted_at,
            "duration_seconds": a.duration_seconds,
            "code": a.code.code if a.code else None,
        })
    return out


@router.delete("/attempts/{attempt_id}")
def delete_attempt(
    attempt_id: int,
    db: Session = Depends(get_db),
    _: models.Admin = Depends(get_current_admin),
):
    a = db.query(models.Attempt).filter(models.Attempt.id == attempt_id).first()
    if not a:
        raise HTTPException(404, "Không tìm thấy lượt làm bài")
    db.delete(a)
    db.commit()
    return {"ok": True}


@router.get("/attempts/{attempt_id}")
def get_attempt(attempt_id: int, db: Session = Depends(get_db), _: models.Admin = Depends(get_current_admin)):
    from ..scoring import grade_attempt

    a = db.query(models.Attempt).filter(models.Attempt.id == attempt_id).first()
    if not a:
        raise HTTPException(404, "Không tìm thấy lượt làm bài")
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
