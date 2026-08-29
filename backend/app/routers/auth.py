"""Email/password auth: register, login, me, password reset."""
import os
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import User
from ..schemas import (
    RegisterIn, LoginIn, TokenOut, UserOut,
    ForgotPasswordIn, ForgotPasswordOut, ResetPasswordIn, ChangePasswordIn,
)
from ..security import (
    hash_password, verify_password, create_token, get_current_user,
    generate_reset_token, RESET_TOKEN_TTL_MINUTES,
)

router = APIRouter(prefix="/api/auth", tags=["auth"])
MOCK_MODE = os.getenv("MOCK_MODE", "true").lower() != "false"


def _token(user: User) -> dict:
    return {"access_token": create_token(user.id), "token_type": "bearer", "user": user}


@router.post("/register", response_model=TokenOut, status_code=201)
def register(data: RegisterIn, db: Session = Depends(get_db)):
    email = data.email.strip().lower()
    if db.query(User).filter(User.email == email).first():
        raise HTTPException(409, "Email already registered — try logging in")
    user = User(email=email, name=data.name.strip() or email.split("@")[0],
                password_hash=hash_password(data.password))
    db.add(user)
    db.commit()
    db.refresh(user)
    return _token(user)


@router.post("/login", response_model=TokenOut)
def login(data: LoginIn, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.email == data.email.strip().lower()).first()
    if not user or not verify_password(data.password, user.password_hash):
        raise HTTPException(401, "Invalid email or password")
    return _token(user)


@router.get("/me", response_model=UserOut)
def me(user: User = Depends(get_current_user)):
    return user


@router.post("/forgot-password", response_model=ForgotPasswordOut)
def forgot_password(data: ForgotPasswordIn, db: Session = Depends(get_db)):
    """Always returns 200 (even for unknown emails) so the endpoint can't be
    used to enumerate registered accounts."""
    email = data.email.strip().lower()
    user = db.query(User).filter(User.email == email).first()
    if not user:
        return {"message": "If that email is registered, a reset link has been sent.", "reset_token": None}
    token = generate_reset_token()
    user.reset_token = token
    user.reset_token_expires = datetime.now(timezone.utc) + timedelta(minutes=RESET_TOKEN_TTL_MINUTES)
    db.commit()
    # No transactional-email service is wired up yet (needs SendGrid/SES free
    # tier or similar). In MOCK_MODE we hand the token straight back so the
    # flow is fully testable end-to-end without one.
    return {
        "message": "If that email is registered, a reset link has been sent."
                   + (" (MOCK_MODE: token returned below since no mailer is configured)" if MOCK_MODE else ""),
        "reset_token": token if MOCK_MODE else None,
    }


@router.post("/reset-password", response_model=TokenOut)
def reset_password(data: ResetPasswordIn, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.reset_token == data.token, User.reset_token != "").first()
    if not user or not user.reset_token_expires:
        raise HTTPException(400, "Reset link is invalid or has expired")
    expires = user.reset_token_expires
    if expires.tzinfo is None:
        expires = expires.replace(tzinfo=timezone.utc)
    if expires < datetime.now(timezone.utc):
        raise HTTPException(400, "Reset link is invalid or has expired")
    user.password_hash = hash_password(data.new_password)
    user.reset_token = ""
    user.reset_token_expires = None
    db.commit()
    db.refresh(user)
    return _token(user)


@router.post("/change-password", response_model=dict)
def change_password(data: ChangePasswordIn, db: Session = Depends(get_db),
                     user: User = Depends(get_current_user)):
    if not verify_password(data.current_password, user.password_hash):
        raise HTTPException(401, "Current password is incorrect")
    user.password_hash = hash_password(data.new_password)
    db.commit()
    return {"message": "Password updated"}
