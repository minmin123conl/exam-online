"""Auth helpers for admin login."""
import os
import re
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt
from passlib.context import CryptContext
from sqlalchemy.orm import Session

from .db import get_db
from .models import Admin


WEAK_PASSWORDS = {"admin", "admin123", "password", "123456", "12345678"}


def password_strength_error(pw: str) -> Optional[str]:
    if pw is None:
        return "Mật khẩu không được trống."
    if pw.lower() in WEAK_PASSWORDS:
        return "Mật khẩu này quá phổ biến, vui lòng chọn mật khẩu khác."
    if len(pw) < 10:
        return "Mật khẩu phải có ít nhất 10 ký tự."
    if not re.search(r"[a-z]", pw):
        return "Mật khẩu phải có chữ thường."
    if not re.search(r"[A-Z]", pw):
        return "Mật khẩu phải có chữ in hoa."
    if not re.search(r"\d", pw):
        return "Mật khẩu phải có chữ số."
    if not re.search(r"[^A-Za-z0-9]", pw):
        return "Mật khẩu phải có ký tự đặc biệt (vd: !@#$%^&*)."
    return None

SECRET_KEY = os.environ.get("EXAM_SECRET_KEY", "dev-secret-change-me")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 24 * 7  # 7 days

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/admin/login", auto_error=False)


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return pwd_context.verify(plain, hashed)
    except Exception:
        return False


def create_access_token(sub: str, expires_minutes: int = ACCESS_TOKEN_EXPIRE_MINUTES) -> str:
    expire = datetime.now(timezone.utc) + timedelta(minutes=expires_minutes)
    to_encode = {"sub": sub, "exp": expire}
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)


def get_current_admin(
    token: Optional[str] = Depends(oauth2_scheme),
    db: Session = Depends(get_db),
) -> Admin:
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Không xác thực được",
        headers={"WWW-Authenticate": "Bearer"},
    )
    if not token:
        raise credentials_exception
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        username: str = payload.get("sub")
        if username is None:
            raise credentials_exception
    except JWTError:
        raise credentials_exception
    admin = db.query(Admin).filter(Admin.username == username).first()
    if not admin:
        raise credentials_exception
    return admin


def require_roles(*allowed: str):
    """Dependency factory: only allow admins with role in `allowed`."""
    def dep(admin: Admin = Depends(get_current_admin)) -> Admin:
        if admin.role not in allowed:
            raise HTTPException(status_code=403, detail="Không đủ quyền cho thao tác này.")
        return admin
    return dep


def require_write(admin: Admin = Depends(get_current_admin)) -> Admin:
    """Allow super or manager (anyone except viewer)."""
    if admin.role not in ("super", "manager"):
        raise HTTPException(status_code=403, detail="Tài khoản chỉ có quyền xem.")
    if admin.must_change_password:
        raise HTTPException(status_code=403, detail="Bạn cần đổi mật khẩu trước khi thực hiện thao tác.")
    return admin


def require_super(admin: Admin = Depends(get_current_admin)) -> Admin:
    if admin.role != "super":
        raise HTTPException(status_code=403, detail="Chỉ Super-admin mới có quyền.")
    if admin.must_change_password:
        raise HTTPException(status_code=403, detail="Bạn cần đổi mật khẩu trước khi thực hiện thao tác.")
    return admin
