from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.ext.declarative import declarative_base
from .config import settings
import os

# FIX: Render free Postgres sleeps -> SSL closed error fix
connect_args = {}
if "render" in settings.DATABASE_URL or "postgres" in settings.DATABASE_URL:
    connect_args = {"sslmode": "require", "connect_timeout": 10}

engine = create_engine(
    settings.DATABASE_URL,
    pool_pre_ping=True,  # critical fix for SSL closed
    pool_recycle=300,
    pool_size=5,
    max_overflow=10,
    connect_args=connect_args
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
