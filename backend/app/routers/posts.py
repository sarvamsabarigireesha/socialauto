import csv
import io
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Query
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import Post, PostStatus, Account
from ..schemas import PostIn, BulkPostIn, PostOut, PostUpdate
from ..services import engine

router = APIRouter(prefix="/api/posts", tags=["posts"])


def _to_out(p: Post) -> dict:
    return {
        "id": p.id, "account_id": p.account_id,
        "platform": p.account.platform.value if p.account else None,
        "account_name": p.account.display_name if p.account else None,
        "caption": p.caption, "media_url": p.media_url,
        "scheduled_at": p.scheduled_at, "status": p.status,
        "error": p.error, "published_at": p.published_at,
    }


@router.get("", response_model=list[PostOut])
def list_posts(status: PostStatus | None = None, db: Session = Depends(get_db)):
    q = db.query(Post)
    if status:
        q = q.filter(Post.status == status)
    return [_to_out(p) for p in q.order_by(Post.scheduled_at).all()]


@router.post("", response_model=list[PostOut], status_code=201)
def create_post(data: PostIn, db: Session = Depends(get_db)):
    created = []
    for aid in data.account_ids:
        if not db.get(Account, aid):
            raise HTTPException(404, f"account {aid} not found")
        p = Post(account_id=aid, caption=data.caption, media_url=data.media_url,
                 scheduled_at=data.scheduled_at, status=PostStatus.scheduled)
        db.add(p)
        created.append(p)
    db.commit()
    for p in created:
        db.refresh(p)
    return [_to_out(p) for p in created]


@router.post("/bulk", response_model=list[PostOut], status_code=201)
def bulk_create(data: BulkPostIn, db: Session = Depends(get_db)):
    """Bulk schedule: same caption set across accounts via JSON rows."""
    created = []
    for aid in data.account_ids:
        if not db.get(Account, aid):
            raise HTTPException(404, f"account {aid} not found")
        for row in data.posts:
            p = Post(account_id=aid, caption=row.caption, media_url=row.media_url,
                     scheduled_at=row.scheduled_at, status=PostStatus.scheduled)
            db.add(p)
            created.append(p)
    db.commit()
    for p in created:
        db.refresh(p)
    return [_to_out(p) for p in created]


@router.post("/bulk/csv", response_model=list[PostOut], status_code=201)
async def bulk_csv(account_ids: str = Query(..., description="comma-separated account ids"),
                   file: UploadFile = File(...),
                   db: Session = Depends(get_db)):
    """Upload a CSV with columns: caption, media_url, scheduled_at (ISO 8601).

    One row -> one post per account id. 500 posts x 4 accounts = 2000 in one upload.
    """
    aids = [int(x) for x in account_ids.split(",") if x.strip()]
    for aid in aids:
        if not db.get(Account, aid):
            raise HTTPException(404, f"account {aid} not found")

    raw = (await file.read()).decode("utf-8-sig")
    reader = csv.DictReader(io.StringIO(raw))
    required = {"caption", "scheduled_at"}
    if not required.issubset({c.strip() for c in (reader.fieldnames or [])}):
        raise HTTPException(400, "CSV must have headers: caption, media_url, scheduled_at")

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
        for aid in aids:
            p = Post(account_id=aid, caption=caption,
                     media_url=(row.get("media_url") or "").strip(),
                     scheduled_at=dt, status=PostStatus.scheduled)
            db.add(p)
            created.append(p)
    db.commit()
    for p in created:
        db.refresh(p)
    return [_to_out(p) for p in created]


@router.patch("/{post_id}", response_model=PostOut)
def update_post(post_id: int, data: PostUpdate, db: Session = Depends(get_db)):
    p = db.get(Post, post_id)
    if not p:
        raise HTTPException(404, "post not found")
    if p.status == PostStatus.published:
        raise HTTPException(400, "published posts can't be edited")
    for field, value in data.model_dump(exclude_none=True).items():
        if field == "account_id":
            if not db.get(Account, value):
                raise HTTPException(404, f"account {value} not found")
            p.account_id = value
        else:
            setattr(p, field, value)
    db.commit()
    db.refresh(p)
    return _to_out(p)


@router.post("/{post_id}/publish-now", response_model=PostOut)
async def publish_now(post_id: int, db: Session = Depends(get_db)):
    p = await engine.publish_one(db, post_id)
    if not p:
        raise HTTPException(404, "post not found")
    return _to_out(p)


@router.delete("/{post_id}", status_code=204)
def delete_post(post_id: int, db: Session = Depends(get_db)):
    p = db.get(Post, post_id)
    if not p:
        raise HTTPException(404, "post not found")
    db.delete(p)
    db.commit()


@router.get("/csv-template")
def csv_template():
    """Returns a sample CSV (handled in frontend as a blob)."""
    return {"filename": "posts_template.csv",
            "content": "caption,media_url,scheduled_at\n"
                       "Hello world! First post 🚧,https://example.com/img.jpg,2026-09-01T09:00:00\n"
                       "Tip of the day,,2026-09-02T18:30:00\n"}
