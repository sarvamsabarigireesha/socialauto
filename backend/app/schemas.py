"""Pydantic request/response schemas."""
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field

from .models import Platform, PostStatus


# ---------- Auth ----------
class RegisterIn(BaseModel):
    email: str = Field(..., min_length=3, max_length=255)
    password: str = Field(..., min_length=6, max_length=200)
    name: str = ""


class LoginIn(BaseModel):
    email: str
    password: str


class ForgotPasswordIn(BaseModel):
    email: str


class ForgotPasswordOut(BaseModel):
    message: str
    # MOCK_MODE only: no email service is wired up yet, so the reset link is
    # handed back directly instead of being emailed. Remove this field once
    # a real mailer (SendGrid/SES free tier etc.) sends the link instead.
    reset_token: Optional[str] = None


class ResetPasswordIn(BaseModel):
    token: str
    new_password: str = Field(..., min_length=6, max_length=200)


class ChangePasswordIn(BaseModel):
    current_password: str
    new_password: str = Field(..., min_length=6, max_length=200)


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: "UserOut"


class UserOut(BaseModel):
    id: int
    email: str
    name: str
    timezone: str = "Asia/Kolkata"
    created_at: datetime

    class Config:
        from_attributes = True


class ProfileUpdate(BaseModel):
    timezone: Optional[str] = None
    name: Optional[str] = None


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
    posting_slots: list = []
    posting_goal: int = 7
    created_at: datetime

    class Config:
        from_attributes = True


class AccountUpdate(BaseModel):
    """Buffer-style channel settings: weekly posting slots + goal."""
    posting_slots: Optional[list] = None
    posting_goal: Optional[int] = None
    auto_comment: Optional[bool] = None
    comment_template: Optional[str] = None


# ---------- Posts ----------
class PerAccountVariant(BaseModel):
    """Buffer-style 'Customize for each network': per-account caption/media."""
    account_id: int
    caption: str = ""
    media_url: str = ""
    post_type: str = "feed"


class PostIn(BaseModel):
    account_ids: list[int] = Field(..., min_length=1)
    caption: str = Field(..., min_length=1)
    media_url: str = ""
    post_type: str = "feed"   # feed | video | short | community
    source: str = "scheduled"  # scheduled | queue | next | now | draft
    tag_ids: list[int] = []
    per_account: list[PerAccountVariant] = []
    scheduled_at: datetime
    status: str | None = None   # optional: pass "draft" to save without scheduling


class BulkPostIn(BaseModel):
    """One caption -> many accounts / many times, or CSV-style rows."""
    account_ids: list[int] = Field(..., min_length=1)
    posts: list["BulkRow"] = Field(..., min_length=1)


class BulkRow(BaseModel):
    caption: str
    media_url: str = ""
    post_type: str = "feed"
    scheduled_at: datetime


class PostOut(BaseModel):
    id: int
    account_id: int
    platform: Optional[Platform] = None
    account_name: Optional[str] = None
    caption: str
    media_url: str
    post_type: str = "feed"
    source: str = "scheduled"
    scheduled_at: datetime
    status: PostStatus
    error: str
    published_at: Optional[datetime] = None
    group_id: str = ""
    tags: list["TagOut"] = []

    class Config:
        from_attributes = True


class TagOut(BaseModel):
    id: int
    name: str
    color: str

    class Config:
        from_attributes = True


class PostUpdate(BaseModel):
    post_type: Optional[str] = None
    caption: Optional[str] = None
    media_url: Optional[str] = None
    scheduled_at: Optional[datetime] = None
    account_id: Optional[int] = None
    tag_ids: Optional[list[int]] = None


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
TokenOut.model_rebuild()
PostOut.model_rebuild()
