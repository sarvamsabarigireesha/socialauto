"""Password hashing (bcrypt) + JWT auth."""
import os
import secrets
from datetime import datetime, timedelta, timezone

import bcrypt
import jwt as pyjwt
from fastapi import Depends, HTTPException
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.orm import Session

from .database import get_db
from .models import User

JWT_SECRET = os.getenv("JWT_SECRET", "dev-jwt-secret-change-me-in-production")
JWT_ALG = "HS256"
TOKEN_TTL_HOURS = 24 * 7

if JWT_SECRET == "dev-jwt-secret-change-me-in-production" and \
        os.getenv("MOCK_MODE", "true").lower() != "true":
    print("WARNING: JWT_SECRET is the dev default — auth tokens are forgeable. "
          "Set a strong JWT_SECRET environment variable in production.", flush=True)


def hash_password(pw: str) -> str:
    return bcrypt.hashpw(pw.encode(), bcrypt.gensalt()).decode()


def verify_password(pw: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(pw.encode(), hashed.encode())
    except ValueError:
        return False


def create_token(user_id: int) -> str:
    payload = {
        "sub": str(user_id),
        "iat": datetime.now(timezone.utc),
        "exp": datetime.now(timezone.utc) + timedelta(hours=TOKEN_TTL_HOURS),
    }
    return pyjwt.encode(payload, JWT_SECRET, algorithm=JWT_ALG)


RESET_TOKEN_TTL_MINUTES = 30


def generate_reset_token() -> str:
    return secrets.token_urlsafe(32)


def decode_token(token: str) -> int:
    try:
        data = pyjwt.decode(token, JWT_SECRET, algorithms=[JWT_ALG])
        return int(data["sub"])
    except Exception:
        raise HTTPException(401, "Invalid or expired token")


bearer = HTTPBearer(auto_error=False)


def get_current_user(
    creds: HTTPAuthorizationCredentials | None = Depends(bearer),
    db: Session = Depends(get_db),
) -> User:
    if not creds:
        raise HTTPException(401, "Not authenticated — please log in")
    uid = decode_token(creds.credentials)
    user = db.get(User, uid)
    if not user:
        raise HTTPException(401, "User not found")
    return user
