import csv
import io
import uuid
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import Post, PostStatus, Account, User, Tag
from ..schemas import PostIn, BulkPostIn, PostOut, PostUpdate
from ..security import get_current_user
from ..services import engine
from ..services.engine import _aware, next_slot_for

router = APIRouter(prefix="/api/posts", tags=["posts"])

VALID_POST_TYPES = {"feed", "video", "short", "community"}


def _normalize_post_type(value: str | None, *, default: str = "feed") -> str:
    ptype = (value or default or "feed").strip().lower()
    if ptype not in VALID_POST_TYPES:
        raise HTTPException(400, "post_type must be one of: feed, video, short, community")
    return ptype


def _to_out(p: Post) -> dict:
    return {
        "id": p.id, "account_id": p.account_id,
        "platform": p.account.platform.value if p.account else None,
        "account_name": p.account.display_name if p.account else None,
        "caption": p.caption, "media_url": p.media_url, "post_type": getattr(p, "post_type", "feed") or "feed",
        "source": getattr(p, "source", "scheduled") or "scheduled",
        "scheduled_at": p.scheduled_at, "status": p.status,
        "error": p.error, "published_at": p.published_at, "group_id": p.group_id or "",
        "tags": [{"id": t.id, "name": t.name, "color": t.color} for t in p.tags],
    }


def _owned_accounts(db: Session, user: User, ids: list[int]) -> list[Account]:
    accs = db.query(Account).filter(Account.user_id == user.id,
                                    Account.id.in_(ids)).all()
    if len(accs) != len(set(ids)):
        raise HTTPException(404, "one or more accounts not found")
    return accs


@router.get("", response_model=list[PostOut])
def list_posts(status: PostStatus | None = None, include_drafts: int = 0,
               db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    q = db.query(Post).filter(Post.user_id == user.id)
    if status:
        q = q.filter(Post.status == status)
    elif not include_drafts:
        q = q.filter(Post.status != PostStatus.draft)
    return [_to_out(p) for p in q.order_by(Post.scheduled_at).all()]


class ReorderIn(BaseModel):
    ordered_ids: list[int]


@router.post("/reorder")
def reorder(data: ReorderIn, db: Session = Depends(get_db),
            user: User = Depends(get_current_user)):
    """Buffer-style queue: drag to reorder — queued posts get new slot times."""
    posts = engine.reorder_queue(db, user.id, data.ordered_ids)
    return {"reordered": len(posts), "posts": [_to_out(p) for p in posts]}


def _owned_tags(db: Session, user: User, tag_ids: list[int]) -> list[Tag]:
    if not tag_ids:
        return []
    tags = db.query(Tag).filter(Tag.user_id == user.id, Tag.id.in_(tag_ids)).all()
    if len(tags) != len(set(tag_ids)):
        raise HTTPException(404, "one or more tags not found")
    return tags


@router.post("", response_model=list[PostOut], status_code=201)
def create_post(data: PostIn, db: Session = Depends(get_db),
                user: User = Depends(get_current_user)):
    accs = _owned_accounts(db, user, data.account_ids)
    tags = _owned_tags(db, user, data.tag_ids or [])
    created = []
    group = uuid.uuid4().hex[:16]
    base_post_type = _normalize_post_type(data.post_type)
    post_status = PostStatus.draft if data.status == "draft" else PostStatus.scheduled
    source = (data.source or "scheduled").lower()
    if data.status == "draft":
        source = "draft"
    elif source not in ("scheduled", "queue", "next", "now"):
        source = "scheduled"
    now_utc = datetime.now(timezone.utc)
    when = _aware(data.scheduled_at)
    if source == "now":
        when = now_utc
    # per-account custom variants (Buffer "Customize for each network")
    variants = {v.account_id: v for v in (data.per_account or [])}
    by_aid = {a.id: a for a in accs}
    for aid in data.account_ids:
        acc = by_aid[aid]
        v = variants.get(aid)
        p = Post(user_id=user.id, account_id=aid,
                 caption=v.caption if v else data.caption,
                 media_url=v.media_url if v else data.media_url,
                 post_type=_normalize_post_type(v.post_type if v else base_post_type),
                 scheduled_at=when, status=post_status, group_id=group,
                 source=source)
        p.tags = tags
        db.add(p)
        created.append(p)
    # Buffer-style slot assignment for queue/next sources
    if source in ("next", "queue"):
        now_utc = datetime.now(timezone.utc)
        anchor = max(now_utc, when)
        for i, p in enumerate(sorted(created, key=lambda x: x.account_id)):
            t = engine.next_slot_for(db, by_aid[p.account_id], anchor,
                                     exclude_post_id=p.id)
            p.scheduled_at = t
            if source == "queue" and i == 0:
                anchor = max(anchor, t - timedelta(minutes=1))
    db.commit()
    for p in created:
        db.refresh(p)
    return [_to_out(p) for p in created]


@router.post("/bulk", response_model=list[PostOut], status_code=201)
def bulk_create(data: BulkPostIn, db: Session = Depends(get_db),
                user: User = Depends(get_current_user)):
    _owned_accounts(db, user, data.account_ids)
    created = []
    for row in data.posts:
        group = uuid.uuid4().hex[:16]
        row_type = _normalize_post_type(row.post_type)
        for aid in data.account_ids:
            p = Post(user_id=user.id, account_id=aid, caption=row.caption,
                     media_url=row.media_url, post_type=row_type,
                     scheduled_at=_aware(row.scheduled_at),
                     status=PostStatus.scheduled, group_id=group,
                     source="scheduled")
            db.add(p)
            created.append(p)
    db.commit()
    for p in created:
        db.refresh(p)
    return [_to_out(p) for p in created]


@router.post("/bulk/csv", response_model=list[PostOut], status_code=201)
async def bulk_csv(account_ids: str = Query(..., description="comma-separated account ids"),
                   tag_ids: str = Query("", description="comma-separated tag ids"),
                   file: UploadFile = File(...), db: Session = Depends(get_db),
                   user: User = Depends(get_current_user)):
    aids = [int(x) for x in account_ids.split(",") if x.strip()]
    tids = [int(x) for x in tag_ids.split(",") if x.strip()]
    _owned_accounts(db, user, aids)
    tags = _owned_tags(db, user, tids)

    raw = (await file.read()).decode("utf-8-sig")
    reader = csv.DictReader(io.StringIO(raw))
    headers = {c.strip() for c in (reader.fieldnames or [])}
    if not {"caption", "scheduled_at"}.issubset(headers):
        raise HTTPException(400, "CSV must have headers: caption,scheduled_at (media_url and post_type are optional)")

    created = []
    for row in reader:
        caption = (row.get("caption") or "").strip()
        when = (row.get("scheduled_at") or "").strip()
        ptype = _normalize_post_type((row.get("post_type") or "feed").strip() or "feed")
        if not caption or not when:
            continue
        try:
            dt = datetime.fromisoformat(when.replace("Z", "+00:00"))
        except ValueError:
            raise HTTPException(400, f"bad scheduled_at: {when}")
        # CSV rows often omit the UTC offset (e.g. "2026-09-01T09:00:00"), which
        # fromisoformat parses as a naive datetime. Normalize to UTC-aware so it
        # compares correctly against `now` in the publish-due-posts cron job —
        # otherwise CSV-scheduled posts silently never get picked up.
        dt = _aware(dt)
        group = uuid.uuid4().hex[:16]
        for aid in aids:
            p = Post(user_id=user.id, account_id=aid, caption=caption,
                     media_url=(row.get("media_url") or "").strip(),
                     post_type=ptype,
                     scheduled_at=dt, status=PostStatus.scheduled,
                     group_id=group, source="scheduled")
            p.tags = tags
            db.add(p)
            created.append(p)
    db.commit()
    for p in created:
        db.refresh(p)
    return [_to_out(p) for p in created]


@router.patch("/{post_id}", response_model=PostOut)
def update_post(post_id: int, data: PostUpdate, db: Session = Depends(get_db),
                user: User = Depends(get_current_user), apply_all: int = 0):
    p = db.get(Post, post_id)
    if not p or p.user_id != user.id:
        raise HTTPException(404, "post not found")
    targets = [p]
    if apply_all and p.group_id:
        siblings = (db.query(Post).filter(Post.group_id == p.group_id,
                                          Post.user_id == user.id,
                                          Post.status != PostStatus.published).all())
        targets = siblings or [p]
    payload = data.model_dump(exclude_none=True)
    new_account = payload.pop("account_id", None)
    tag_ids = payload.pop("tag_ids", None)
    if "scheduled_at" in payload:
        payload["scheduled_at"] = _aware(payload["scheduled_at"])
    if "post_type" in payload:
        payload["post_type"] = _normalize_post_type(payload.get("post_type"))
    tags = _owned_tags(db, user, tag_ids) if tag_ids is not None else None
    for tgt in targets:
        if tgt.status == PostStatus.published:
            continue
        for field, value in payload.items():
            setattr(tgt, field, value)
        if tags is not None:
            tgt.tags = tags
    if new_account is not None and not apply_all:
        _owned_accounts(db, user, [new_account])
        p.account_id = new_account
    db.commit()
    db.refresh(p)
    return _to_out(p)


@router.post("/{post_id}/publish-now", response_model=PostOut)
async def publish_now(post_id: int, db: Session = Depends(get_db),
                      user: User = Depends(get_current_user)):
    p = db.get(Post, post_id)
    if not p or p.user_id != user.id:
        raise HTTPException(404, "post not found")
    p = await engine.publish_one(db, post_id)
    return _to_out(p)


@router.post("/{post_id}/mark-done", response_model=PostOut)
def mark_done(post_id: int, db: Session = Depends(get_db),
              user: User = Depends(get_current_user)):
    """User finished a MANUAL platform step (e.g. YouTube Community post,
    Moj/ShareChat) — mark it published here too."""
    from datetime import datetime, timezone
    p = db.get(Post, post_id)
    if not p or p.user_id != user.id:
        raise HTTPException(404, "post not found")
    p.status = PostStatus.published
    p.error = ""
    p.published_at = datetime.now(timezone.utc)
    if not p.platform_post_id:
        p.platform_post_id = f"manual_{p.id}"
    db.commit()
    db.refresh(p)
    return _to_out(p)


@router.delete("/{post_id}", status_code=204)
def delete_post(post_id: int, db: Session = Depends(get_db),
                user: User = Depends(get_current_user)):
    p = db.get(Post, post_id)
    if not p or p.user_id != user.id:
        raise HTTPException(404, "post not found")
    db.delete(p)
    db.commit()


@router.get("/csv-template")
def csv_template():
    return {"filename": "posts_template.csv",
            "content": "caption,media_url,post_type,scheduled_at\n"
                       "Hello world! Text-only post works 🚧,,feed,2026-09-01T09:00:00\n"
                       "My new Short 🎬,https://example.com/clip.mp4,short,2026-09-02T18:30:00\n"
                       "YouTube community note,,community,2026-09-03T10:00:00\n"}
