from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import Account, User
from ..schemas import AccountIn, AccountOut, AccountUpdate
from ..security import get_current_user

router = APIRouter(prefix="/api/accounts", tags=["accounts"])


@router.get("", response_model=list[AccountOut])
def list_accounts(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return db.query(Account).filter(Account.user_id == user.id).order_by(Account.id).all()


@router.patch("/{account_id}", response_model=AccountOut)
def update_account(account_id: int, data: AccountUpdate, db: Session = Depends(get_db),
                   user: User = Depends(get_current_user)):
    """Buffer-style channel settings: posting schedule slots, weekly goal, auto-comments."""
    acc = db.get(Account, account_id)
    if not acc or acc.user_id != user.id:
        raise HTTPException(404, "account not found")
    if data.posting_slots is not None:
        # validate + normalize [{day:0-6, time:'HH:MM'}]
        slots = []
        for s in data.posting_slots:
            if not isinstance(s, dict):
                continue
            try:
                day = int(s.get("day"))
                hh, mm = (int(x) for x in str(s.get("time", "")).split(":")[:2])
                if day < 0 or day > 6 or hh < 0 or hh > 23 or mm < 0 or mm > 59:
                    raise ValueError
            except Exception:
                raise HTTPException(400, "slots must be [{day:0-6, time:'HH:MM'}]")
            slots.append({"day": day, "time": f"{hh:02d}:{mm:02d}"})
        acc.posting_slots = slots
    if data.posting_goal is not None:
        if not 1 <= data.posting_goal <= 70:
            raise HTTPException(400, "posting_goal must be 1-70 posts/week")
        acc.posting_goal = data.posting_goal
    if data.auto_comment is not None:
        acc.auto_comment = data.auto_comment
    if data.comment_template is not None:
        acc.comment_template = data.comment_template
    db.commit()
    db.refresh(acc)
    return acc


@router.post("", response_model=AccountOut, status_code=201)
def create_account(data: AccountIn, db: Session = Depends(get_db),
                   user: User = Depends(get_current_user)):
    acc = Account(user_id=user.id, **data.model_dump())
    db.add(acc)
    db.commit()
    db.refresh(acc)
    return acc


@router.delete("/{account_id}", status_code=204)
def delete_account(account_id: int, db: Session = Depends(get_db),
                   user: User = Depends(get_current_user)):
    acc = db.get(Account, account_id)
    if not acc or acc.user_id != user.id:
        raise HTTPException(404, "account not found")
    db.delete(acc)
    db.commit()
