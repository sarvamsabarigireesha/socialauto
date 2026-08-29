"""Pydantic request/response schemas."""
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field

from .models import Platform, PostStatus


# ---------- Accounts ----------
class AccountIn(BaseModel):
    platform: Platform
    display_name: str = Field(..., min_length=1, max_length=200)
    external_id: str = ""
    access_token: str = ""
    auto_comment: bool = True
    comment_template: str = ""


class AccountOut(BaseModel):
    id: int
    platform: Platform
    display_name: str
    external_id: str
    auto_comment: bool
    comment_template: str
    created_at: datetime

    class Config:
        from_attributes = True


# ---------- Posts ----------
class PostIn(BaseModel):
    account_ids: list[int] = Field(..., min_length=1)
    caption: str = Field(..., min_length=1)
    media_url: str = ""
    scheduled_at: datetime


class BulkPostIn(BaseModel):
    """One caption -> many accounts / many times, or CSV-style rows."""
    account_ids: list[int] = Field(..., min_length=1)
    posts: list["BulkRow"] = Field(..., min_length=1)


class BulkRow(BaseModel):
    caption: str
    media_url: str = ""
    scheduled_at: datetime


class PostOut(BaseModel):
    id: int
    account_id: int
    platform: Optional[Platform] = None
    account_name: Optional[str] = None
    caption: str
    media_url: str
    scheduled_at: datetime
    status: PostStatus
    error: str
    published_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class PostUpdate(BaseModel):
    caption: Optional[str] = None
    media_url: Optional[str] = None
    scheduled_at: Optional[datetime] = None
    account_id: Optional[int] = None


# ---------- Comments ----------
class CommentOut(BaseModel):
    id: int
    post_id: int
    author: str
    text: str
    our_reply: str
    replied: bool
    created_at: datetime

    class Config:
        from_attributes = True


class SimulateCommentIn(BaseModel):
    """Demo helper: pretend a follower commented on a post."""
    post_id: int
    author: str = "follower"
    text: str


# ---------- Metrics ----------
class MetricOut(BaseModel):
    id: int
    post_id: int
    likes: int
    comments_count: int
    shares: int
    impressions: int
    reach: int
    fetched_at: datetime

    class Config:
        from_attributes = True


BulkPostIn.model_rebuild()
