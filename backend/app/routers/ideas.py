"""Content ideas Kanban board (Buffer 'Create' screen)."""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import Idea, IdeaStatus, User
from ..security import get_current_user

router = APIRouter(prefix="/api/ideas", tags=["ideas"])


class IdeaIn(BaseModel):
    text: str
    status: IdeaStatus = IdeaStatus.unassigned


class MoveIn(BaseModel):
    status: IdeaStatus


@router.get("")
def list_ideas(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    rows = db.query(Idea).filter(Idea.user_id == user.id).order_by(Idea.id.desc()).all()
    cols = {s.value: [] for s in IdeaStatus}
    for r in rows:
        cols[r.status.value].append({"id": r.id, "text": r.text,
                                     "status": r.status.value,
                                     "created_at": r.created_at})
    return cols


@router.post("", status_code=201)
def create_idea(data: IdeaIn, db: Session = Depends(get_db),
                user: User = Depends(get_current_user)):
    if not data.text.strip():
        raise HTTPException(400, "idea text is empty")
    idea = Idea(user_id=user.id, text=data.text.strip(), status=data.status)
    db.add(idea)
    db.commit()
    db.refresh(idea)
    return {"id": idea.id, "text": idea.text, "status": idea.status.value}


@router.patch("/{idea_id}")
def move_idea(idea_id: int, data: MoveIn, db: Session = Depends(get_db),
              user: User = Depends(get_current_user)):
    idea = db.get(Idea, idea_id)
    if not idea or idea.user_id != user.id:
        raise HTTPException(404, "not found")
    idea.status = data.status
    db.commit()
    return {"id": idea.id, "status": idea.status.value}


@router.delete("/{idea_id}", status_code=204)
def delete_idea(idea_id: int, db: Session = Depends(get_db),
                user: User = Depends(get_current_user)):
    idea = db.get(Idea, idea_id)
    if not idea or idea.user_id != user.id:
        raise HTTPException(404, "not found")
    db.delete(idea)
    db.commit()
