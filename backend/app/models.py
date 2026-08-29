"""Database models."""
import enum
from datetime import datetime, timezone

from sqlalchemy import (
    Column, Integer, String, Text, DateTime, Boolean, Enum, JSON, ForeignKey
)
from sqlalchemy.orm import relationship

from .database import Base


def utcnow():
    return datetime.now(timezone.utc)


class User(Base):
    """App user with login (email + password). All data is scoped per user."""
    __tablename__ = "users"

    id = Column(Integer, primary_key=True)
    email = Column(String(255), unique=True, nullable=False, index=True)
    name = Column(String(200), default="")
    password_hash = Column(String(255), nullable=False)
    created_at = Column(DateTime, default=utcnow)

    accounts = relationship("Account", back_populates="user", cascade="all, delete-orphan")


class Platform(str, enum.Enum):
    instagram = "instagram"
    facebook = "facebook"
    x = "x"
    linkedin = "linkedin"
    youtube = "youtube"
    threads = "threads"
    moj = "moj"
    sharechat = "sharechat"


class IdeaStatus(str, enum.Enum):
    unassigned = "unassigned"
    todo = "todo"
    inprogress = "inprogress"
    done = "done"


class Idea(Base):
    """Content idea in the Buffer-style Kanban board."""
    __tablename__ = "ideas"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    text = Column(Text, nullable=False)
    status = Column(Enum(IdeaStatus), default=IdeaStatus.unassigned, nullable=False)
    created_at = Column(DateTime, default=utcnow)


class PostStatus(str, enum.Enum):
    draft = "draft"
    scheduled = "scheduled"
    publishing = "publishing"
    published = "published"
    failed = "failed"


class Account(Base):
    """A connected social account (one row per platform account)."""
    __tablename__ = "accounts"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    platform = Column(Enum(Platform), nullable=False)
    display_name = Column(String(200), nullable=False)          # e.g. "@mybrand"
    external_id = Column(String(200), default="")              # page/ig/user id from the platform
    access_token = Column(String(1000), default="")            # stored token (encrypt in prod!)
    auto_comment = Column(Boolean, default=True)               # reply to comments automatically
    comment_template = Column(Text, default="")                # optional fixed reply; "" = AI pool
    created_at = Column(DateTime, default=utcnow)

    user = relationship("User", back_populates="accounts")
    posts = relationship("Post", back_populates="account", cascade="all, delete-orphan")


class Post(Base):
    __tablename__ = "posts"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    account_id = Column(Integer, ForeignKey("accounts.id"), nullable=False)
    group_id = Column(String(40), default="", index=True)   # shared by same-post multi-account rows
    platform_post_id = Column(String(200), default="")        # id returned after publishing
    caption = Column(Text, nullable=False)
    media_url = Column(String(500), default="")               # image/video URL (or local path)
    scheduled_at = Column(DateTime, nullable=False)
    status = Column(Enum(PostStatus), default=PostStatus.scheduled, nullable=False)
    error = Column(Text, default="")
    created_at = Column(DateTime, default=utcnow)
    published_at = Column(DateTime, nullable=True)

    account = relationship("Account", back_populates="posts")
    comments = relationship("Comment", back_populates="post", cascade="all, delete-orphan")
    metrics = relationship("Metric", back_populates="post", cascade="all, delete-orphan")


class Comment(Base):
    """A comment on one of our posts (ingested) and our auto-reply."""
    __tablename__ = "comments"

    id = Column(Integer, primary_key=True)
    post_id = Column(Integer, ForeignKey("posts.id"), nullable=False)
    external_comment_id = Column(String(200), default="")
    author = Column(String(200), default="someone")
    text = Column(Text, default="")
    our_reply = Column(Text, default="")                      # auto-comment we posted
    replied = Column(Boolean, default=False)
    created_at = Column(DateTime, default=utcnow)

    post = relationship("Post", back_populates="comments")


class Metric(Base):
    """Analytics snapshot for a published post."""
    __tablename__ = "metrics"

    id = Column(Integer, primary_key=True)
    post_id = Column(Integer, ForeignKey("posts.id"), nullable=False)
    likes = Column(Integer, default=0)
    comments_count = Column(Integer, default=0)
    shares = Column(Integer, default=0)
    impressions = Column(Integer, default=0)
    reach = Column(Integer, default=0)
    fetched_at = Column(DateTime, default=utcnow)
    raw = Column(JSON, default=dict)

    post = relationship("Post", back_populates="metrics")
