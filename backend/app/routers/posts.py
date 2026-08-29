import csv
import io
import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Query
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import Post, PostStatus, Account, User
from ..schemas import PostIn, BulkPostIn, PostOut, PostUpdate
from ..security import get_current_user
from ..services import engine

router = APIRouter(prefix="/api/posts", tags=["posts"])


def _to_out(p: Post) -> dict:
    return {
        "id": p.id, "account_id": p.account_id,
        "platform": p.account.platform.value if p.account else None,
        "account_name": p.account.display_name if p.account else None,
        "caption": p.caption, "media_url": p.media_url, "post_type": getattr(p, "post_type", "feed") or "feed",
        "scheduled_at": p.scheduled_at, "status": p.status,
        "error": p.error, "published_at": p.published_at, "group_id": p.group_id or "",
    }


def _owned_accounts(db: Session, user: User, ids: list[int]) -> list[Account]:
    accs = db.query(Account).filter(Account.user_id == user.id,
                                    Account.id.in_(ids)).all()
    if len(accs) != len(set(ids)):
        raise HTTPException(404, "one or more accounts not found")
    return accs


@router.get("", response_model=list[PostOut])
def list_posts(status: PostStatus | None = None, db: Session = Depends(get_db),
               user: User = Depends(get_current_user)):
    q = db.query(Post).filter(Post.user_id == user.id)
    if status:
        q = q.filter(Post.status == status)
    return [_to_out(p) for p in q.order_by(Post.scheduled_at).all()]


@router.post("", response_model=list[PostOut], status_code=201)
def create_post(data: PostIn, db: Session = Depends(get_db),
                user: User = Depends(get_current_user)):
    _owned_accounts(db, user, data.account_ids)
    created = []
    group = uuid.uuid4().hex[:16]
    for aid in data.account_ids:
        p = Post(user_id=user.id, account_id=aid, caption=data.caption,
                 media_url=data.media_url, post_type=(data.post_type or "feed"), scheduled_at=data.scheduled_at,
                 status=PostStatus.scheduled, group_id=group)
        db.add(p)
        created.append(p)
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
        for aid in data.account_ids:
            p = Post(user_id=user.id, account_id=aid, caption=row.caption,
                     media_url=row.media_url, post_type=(row.post_type or "feed"), scheduled_at=row.scheduled_at,
                     status=PostStatus.scheduled, group_id=group)
            db.add(p)
            created.append(p)
    db.commit()
    for p in created:
        db.refresh(p)
    return [_to_out(p) for p in created]


@router.post("/bulk/csv", response_model=list[PostOut], status_code=201)
async def bulk_csv(account_ids: str = Query(..., description="comma-separated account ids"),
                   file: UploadFile = File(...), db: Session = Depends(get_db),
                   user: User = Depends(get_current_user)):
    aids = [int(x) for x in account_ids.split(",") if x.strip()]
    _owned_accounts(db, user, aids)

    raw = (await file.read()).decode("utf-8-sig")
    reader = csv.DictReader(io.StringIO(raw))
    headers = {c.strip() for c in (reader.fieldnames or [])}
    if not {"caption", "scheduled_at"}.issubset(headers):
        raise HTTPException(400, "CSV must have headers: caption,scheduled_at (media_url and post_type are optional)")

    created = []
    for row in reader:
        caption = (row.get("caption") or "").strip()
        when = (row.get("scheduled_at") or "").strip()
        if not caption or not when:
            continue
        try:
            dt = datetime.fromisoformat(when.replace("Z", "+00:00"))
        except ValueError:
            raise HTTPException(400, f"bad scheduled_at: {when}")
        group = uuid.uuid4().hex[:16]
        for aid in aids:
            p = Post(user_id=user.id, account_id=aid, caption=caption,
                     media_url=(row.get("media_url") or "").strip(),
                     post_type=(row.get("post_type") or "feed").strip() or "feed",
                     scheduled_at=dt, status=PostStatus.scheduled, group_id=group)
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
    for tgt in targets:
        if tgt.status == PostStatus.published:
            continue
        for field, value in payload.items():
            setattr(tgt, field, value)
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
