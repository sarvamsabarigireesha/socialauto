"""Email/password auth: register, login, me."""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import User
from ..schemas import RegisterIn, LoginIn, TokenOut, UserOut
from ..security import hash_password, verify_password, create_token, get_current_user

router = APIRouter(prefix="/api/auth", tags=["auth"])


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
