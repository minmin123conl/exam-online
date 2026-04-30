"""Pydantic schemas for API."""
from datetime import datetime
from typing import Optional, Any, Dict, List
from pydantic import BaseModel, Field


class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"
    role: str = "super"
    must_change_password: bool = False
    username: str = ""


class LoginRequest(BaseModel):
    username: str
    password: str


class AdminUserOut(BaseModel):
    id: int
    username: str
    role: str
    must_change_password: bool
    created_at: datetime

    class Config:
        from_attributes = True


class AdminUserCreate(BaseModel):
    username: str
    password: str
    role: str = "manager"  # super | manager | viewer


class AdminUserUpdate(BaseModel):
    role: Optional[str] = None
    new_password: Optional[str] = None


class QuestionIn(BaseModel):
    type: str  # "mc" or "tf"
    section: str = ""
    data: Dict[str, Any]
    points: float = 1.0
    order_index: int = 0


class QuestionOut(QuestionIn):
    id: int

    class Config:
        from_attributes = True


class QuestionPublicMC(BaseModel):
    """MC question as sent to students (no answer)."""
    id: int
    type: str = "mc"
    section: str = ""
    order_index: int = 0
    points: float = 1.0
    question: str
    options: Dict[str, str]


class QuestionPublicTF(BaseModel):
    id: int
    type: str = "tf"
    section: str = ""
    order_index: int = 0
    points: float = 1.0
    question: str
    statements: Dict[str, str]


class ExamIn(BaseModel):
    title: str
    description: str = ""
    duration_minutes: int = 45
    is_active: bool = True
    show_leaderboard: bool = True
    shuffle_mode: str = "none"  # none | by_group | all


class ExamSummary(ExamIn):
    id: int
    created_at: datetime
    num_questions: int = 0
    num_codes: int = 0
    num_codes_used: int = 0
    num_attempts: int = 0

    class Config:
        from_attributes = True


class ExamFull(ExamSummary):
    questions: List[QuestionOut] = []


class ExamCodeOut(BaseModel):
    id: int
    exam_id: int
    code: str
    note: str = ""
    used_by: Optional[str] = None
    used_at: Optional[datetime] = None
    created_at: datetime

    class Config:
        from_attributes = True


class GenerateCodesRequest(BaseModel):
    count: int = Field(1, ge=1, le=500)
    note_prefix: str = ""


class AddCodeRequest(BaseModel):
    code: str
    note: str = ""


class StartAttemptRequest(BaseModel):
    code: str
    student_name: str
    student_class: str = ""


class StartAttemptResponse(BaseModel):
    attempt_id: int
    exam: Dict[str, Any]
    questions: List[Dict[str, Any]]
    started_at: datetime
    duration_minutes: int
    student_name: str


class SubmitAttemptRequest(BaseModel):
    attempt_id: int
    answers: Dict[str, Any]  # {str(question_id): "A"} or {"qid": {"a": true, ...}}


class AttemptResultDetail(BaseModel):
    question_id: int
    type: str
    section: str
    question: str
    options: Optional[Dict[str, str]] = None
    statements: Optional[Dict[str, str]] = None
    correct: Any
    your_answer: Any
    is_correct: bool
    points: float
    earned: float


class AttemptResult(BaseModel):
    attempt_id: int
    exam_id: int
    exam_title: str
    student_name: str
    student_class: str = ""
    score: float
    total_points: float
    score_on_ten: float
    num_correct: int
    num_questions: int
    duration_seconds: int
    submitted_at: datetime
    details: List[AttemptResultDetail] = []


class LeaderboardEntry(BaseModel):
    attempt_id: int
    student_name: str
    student_class: str = ""
    score: float
    total_points: float
    score_on_ten: float
    submitted_at: datetime
    duration_seconds: int


class LeaderboardPayload(BaseModel):
    exam_id: int
    exam_title: str
    entries: List[LeaderboardEntry]
