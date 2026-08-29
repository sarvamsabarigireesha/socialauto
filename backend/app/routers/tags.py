"""Buffer-style tags: create, list, delete + assign/unassign posts."""
import re

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import Post, Tag, User
from ..security import get_current_user

router = APIRouter(prefix="/api/tags", tags=["tags"])

PALETTE = ["#5b6cff", "#e1306c", "#f5a524", "#22a06b", "#8b5cf6",
           "#1877f2", "#e5484d", "#0ea5e9", "#10b981", "#f97316"]


class TagIn(BaseModel):
    name: str
    color: str = ""


class AssignIn(BaseModel):
    post_ids: list[int]
    tag_ids: list[int] = []   # replace-mode: final tag set for these posts


def _clean_name(name: str) -> str:
    name = re.sub(r"\s+", " ", name.strip())
    return name[:60]


@router.get("")
def list_tags(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    tags = db.query(Tag).filter(Tag.user_id == user.id).order_by(Tag.name).all()
    out = []
    for t in tags:
        out.append({"id": t.id, "name": t.name, "color": t.color,
                    "posts": db.query(Post).filter(Post.tags.any(Tag.id == t.id),
                                                   Post.user_id == user.id).count()})
    return out


@router.post("", status_code=201)
def create_tag(data: TagIn, db: Session = Depends(get_db),
               user: User = Depends(get_current_user)):
    name = _clean_name(data.name)
    if not name:
        raise HTTPException(400, "tag name is empty")
    if db.query(Tag).filter(Tag.user_id == user.id, Tag.name == name).first():
        raise HTTPException(409, "tag already exists")
    n = db.query(Tag).filter(Tag.user_id == user.id).count()
    color = data.color or PALETTE[n % len(PALETTE)]
    t = Tag(user_id=user.id, name=name, color=color)
    db.add(t)
    db.commit()
    db.refresh(t)
    return {"id": t.id, "name": t.name, "color": t.color, "posts": 0}


@router.patch("/{tag_id}")
def rename_tag(tag_id: int, data: TagIn, db: Session = Depends(get_db),
               user: User = Depends(get_current_user)):
    t = db.get(Tag, tag_id)
    if not t or t.user_id != user.id:
        raise HTTPException(404, "tag not found")
    name = _clean_name(data.name)
    if not name:
        raise HTTPException(400, "tag name is empty")
    t.name = name
    if data.color:
        t.color = data.color
    db.commit()
    return {"id": t.id, "name": t.name, "color": t.color}


@router.delete("/{tag_id}", status_code=204)
def delete_tag(tag_id: int, db: Session = Depends(get_db),
               user: User = Depends(get_current_user)):
    t = db.get(Tag, tag_id)
    if not t or t.user_id != user.id:
        raise HTTPException(404, "tag not found")
    db.delete(t)
    db.commit()


@router.post("/assign")
def assign_tags(data: AssignIn, db: Session = Depends(get_db),
                user: User = Depends(get_current_user)):
    """Set the final tag list on the given posts (replace mode)."""
    posts = (db.query(Post).filter(Post.user_id == user.id,
                                   Post.id.in_(data.post_ids)).all()
             if data.post_ids else [])
    if len(posts) != len(set(data.post_ids)):
        raise HTTPException(404, "one or more posts not found")
    tags = (db.query(Tag).filter(Tag.user_id == user.id,
                                 Tag.id.in_(data.tag_ids)).all()
            if data.tag_ids else [])
    for p in posts:
        p.tags = tags
    db.commit()
    return {"updated": len(posts)}
