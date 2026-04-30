"""Admin API routes: login, CRUD exams/questions/codes, view attempts."""
import os
import secrets
import string
import tempfile
from datetime import datetime
from typing import List

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.orm import Session
from sqlalchemy import func

from .. import models, schemas
from ..auth import (
    create_access_token,
    get_current_admin,
    hash_password,
    password_strength_error,
    require_super,
    require_write,
    verify_password,
)
from ..db import get_db
from ..docx_parser import parse_docx

UPLOAD_DIR = os.environ.get("EXAM_UPLOAD_DIR", "/data/uploads")
UPLOAD_URL_PREFIX = os.environ.get("EXAM_UPLOAD_URL_PREFIX", "/uploads")

router = APIRouter(prefix="/api/admin", tags=["admin"])


# ---- Auth ----
@router.post("/login", response_model=schemas.Token)
def login(form: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)):
    admin = db.query(models.Admin).filter(models.Admin.username == form.username).first()
    if not admin or not verify_password(form.password, admin.password_hash):
        raise HTTPException(status_code=401, detail="Sai tên đăng nhập hoặc mật khẩu")
    token = create_access_token(sub=admin.username)
    return schemas.Token(
        access_token=token,
        role=admin.role or "super",
        must_change_password=bool(admin.must_change_password),
        username=admin.username,
    )


@router.get("/me")
def me(admin: models.Admin = Depends(get_current_admin)):
    return {
        "username": admin.username,
        "role": admin.role or "super",
        "must_change_password": bool(admin.must_change_password),
    }


@router.post("/change-password")
def change_password(
    body: dict,
    admin: models.Admin = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    old = body.get("old_password") or ""
    new = body.get("new_password") or ""
    if not verify_password(old, admin.password_hash):
        raise HTTPException(status_code=400, detail="Sai mật khẩu cũ")
    err = password_strength_error(new)
    if err:
        raise HTTPException(status_code=400, detail=err)
    if verify_password(new, admin.password_hash):
        raise HTTPException(status_code=400, detail="Mật khẩu mới không được trùng với mật khẩu cũ.")
    admin.password_hash = hash_password(new)
    admin.must_change_password = False
    db.commit()
    return {"ok": True}


# ---- Admin user management (super only) ----
VALID_ROLES = {"super", "manager", "viewer"}


@router.get("/users", response_model=List[schemas.AdminUserOut])
def list_admin_users(
    db: Session = Depends(get_db),
    _: models.Admin = Depends(require_super),
):
    rows = db.query(models.Admin).order_by(models.Admin.created_at.asc()).all()
    return rows


@router.post("/users", response_model=schemas.AdminUserOut)
def create_admin_user(
    body: schemas.AdminUserCreate,
    db: Session = Depends(get_db),
    _: models.Admin = Depends(require_super),
):
    username = (body.username or "").strip()
    if not username or len(username) < 3:
        raise HTTPException(400, "Tên đăng nhập phải ≥ 3 ký tự.")
    if body.role not in VALID_ROLES:
        raise HTTPException(400, "Vai trò không hợp lệ.")
    err = password_strength_error(body.password)
    if err:
        raise HTTPException(400, err)
    if db.query(models.Admin).filter(models.Admin.username == username).first():
        raise HTTPException(400, "Tên đăng nhập đã tồn tại.")
    a = models.Admin(
        username=username,
        password_hash=hash_password(body.password),
        role=body.role,
        must_change_password=False,
    )
    db.add(a)
    db.commit()
    db.refresh(a)
    return a


@router.patch("/users/{user_id}", response_model=schemas.AdminUserOut)
def update_admin_user(
    user_id: int,
    body: schemas.AdminUserUpdate,
    db: Session = Depends(get_db),
    current: models.Admin = Depends(require_super),
):
    target = db.query(models.Admin).filter(models.Admin.id == user_id).first()
    if not target:
        raise HTTPException(404, "Không tìm thấy tài khoản.")
    if body.role is not None:
        if body.role not in VALID_ROLES:
            raise HTTPException(400, "Vai trò không hợp lệ.")
        if target.id == current.id and body.role != "super":
            raise HTTPException(400, "Không thể tự hạ quyền của chính mình.")
        if target.role == "super" and body.role != "super":
            remaining = db.query(models.Admin).filter(
                models.Admin.role == "super", models.Admin.id != target.id
            ).count()
            if remaining == 0:
                raise HTTPException(400, "Phải còn ít nhất 1 Super-admin.")
        target.role = body.role
    if body.new_password is not None:
        err = password_strength_error(body.new_password)
        if err:
            raise HTTPException(400, err)
        target.password_hash = hash_password(body.new_password)
        if target.id != current.id:
            target.must_change_password = True
    db.commit()
    db.refresh(target)
    return target


@router.delete("/users/{user_id}")
def delete_admin_user(
    user_id: int,
    db: Session = Depends(get_db),
    current: models.Admin = Depends(require_super),
):
    target = db.query(models.Admin).filter(models.Admin.id == user_id).first()
    if not target:
        raise HTTPException(404, "Không tìm thấy tài khoản.")
    if target.id == current.id:
        raise HTTPException(400, "Không thể tự xoá tài khoản của chính mình.")
    if target.role == "super":
        remaining = db.query(models.Admin).filter(
            models.Admin.role == "super", models.Admin.id != target.id
        ).count()
        if remaining == 0:
            raise HTTPException(400, "Phải còn ít nhất 1 Super-admin.")
    db.delete(target)
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
def create_exam(body: schemas.ExamIn, db: Session = Depends(get_db), _: models.Admin = Depends(require_write)):
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
    _: models.Admin = Depends(require_write),
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
def delete_exam(exam_id: int, db: Session = Depends(get_db), _: models.Admin = Depends(require_write)):
    exam = db.query(models.Exam).filter(models.Exam.id == exam_id).first()
    if not exam:
        raise HTTPException(404, "Không tìm thấy đề thi")
    db.delete(exam)
    db.commit()
    return {"ok": True}


@router.post("/exams/{exam_id}/duplicate", response_model=schemas.ExamSummary)
def duplicate_exam(exam_id: int, db: Session = Depends(get_db), _: models.Admin = Depends(require_write)):
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


# ---- Upload .docx → create exam ----
@router.post("/exams/upload")
async def upload_exam_docx(
    file: UploadFile = File(...),
    title: str = Form(""),
    description: str = Form(""),
    duration_minutes: int = Form(50),
    is_active: bool = Form(True),
    show_leaderboard: bool = Form(True),
    db: Session = Depends(get_db),
    _: models.Admin = Depends(require_write),
):
    if not file.filename or not file.filename.lower().endswith(".docx"):
        raise HTTPException(400, "Vui lòng tải lên file .docx")
    contents = await file.read()
    if len(contents) > 30 * 1024 * 1024:
        raise HTTPException(400, "File quá lớn (>30MB)")
    os.makedirs(UPLOAD_DIR, exist_ok=True)
    with tempfile.NamedTemporaryFile(delete=False, suffix=".docx") as tmp:
        tmp.write(contents)
        tmp_path = tmp.name
    try:
        parsed = parse_docx(tmp_path, UPLOAD_DIR, UPLOAD_URL_PREFIX)
    except Exception as e:
        raise HTTPException(400, f"Không đọc được file docx: {e}")
    finally:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass

    exam_title = title.strip() or os.path.splitext(file.filename)[0]
    exam = models.Exam(
        title=exam_title,
        description=description,
        duration_minutes=duration_minutes,
        is_active=is_active,
        show_leaderboard=show_leaderboard,
    )
    db.add(exam)
    db.flush()

    order = 1
    n_mc = 0
    n_tf = 0
    n_missing_answer = 0
    for section in parsed.get("sections", []):
        for q in section["questions"]:
            db.add(models.Question(
                exam_id=exam.id,
                order_index=order,
                type="mc",
                section=section["title"],
                data={
                    "question": q["question"],
                    "options": q["options"],
                    "answer": q.get("answer"),
                    "images": q.get("images", []),
                },
                points=1.0,
            ))
            order += 1
            n_mc += 1
            if not q.get("answer"):
                n_missing_answer += 1
    for q in parsed.get("tf_questions", []):
        db.add(models.Question(
            exam_id=exam.id,
            order_index=order,
            type="tf",
            section="Phần đúng/sai",
            data={
                "question": q["question"],
                "statements": q["statements"],
                "answers": q["answers"],
                "images": q.get("images", []),
            },
            points=1.0,
        ))
        order += 1
        n_tf += 1
    db.commit()
    db.refresh(exam)
    return {
        "exam": _exam_summary(exam, db),
        "stats": {
            "num_mc": n_mc,
            "num_tf": n_tf,
            "missing_answers": n_missing_answer,
        },
        "warnings": parsed.get("warnings", []),
    }


@router.post("/uploads/image")
async def upload_image(
    file: UploadFile = File(...),
    _: models.Admin = Depends(require_write),
):
    if not file.filename:
        raise HTTPException(400, "Thiếu file")
    contents = await file.read()
    if len(contents) > 10 * 1024 * 1024:
        raise HTTPException(400, "Ảnh quá lớn (>10MB)")
    import hashlib
    digest = hashlib.sha1(contents).hexdigest()[:16]
    ext = os.path.splitext(file.filename)[1].lower() or ".png"
    if ext not in {".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg"}:
        raise HTTPException(400, "Định dạng ảnh không hỗ trợ")
    os.makedirs(UPLOAD_DIR, exist_ok=True)
    filename = f"{digest}{ext}"
    fpath = os.path.join(UPLOAD_DIR, filename)
    if not os.path.exists(fpath):
        with open(fpath, "wb") as f:
            f.write(contents)
    return {"url": f"{UPLOAD_URL_PREFIX.rstrip('/')}/{filename}"}


# ---- Questions CRUD ----
@router.post("/exams/{exam_id}/questions", response_model=schemas.QuestionOut)
def add_question(
    exam_id: int,
    body: schemas.QuestionIn,
    db: Session = Depends(get_db),
    _: models.Admin = Depends(require_write),
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
    _: models.Admin = Depends(require_write),
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
    _: models.Admin = Depends(require_write),
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
    _: models.Admin = Depends(require_write),
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
    _: models.Admin = Depends(require_write),
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
    _: models.Admin = Depends(require_write),
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
    _: models.Admin = Depends(require_write),
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
    _: models.Admin = Depends(require_write),
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
