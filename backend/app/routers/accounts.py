from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import Account, User
from ..schemas import AccountIn, AccountOut
from ..security import get_current_user

router = APIRouter(prefix="/api/accounts", tags=["accounts"])


@router.get("", response_model=list[AccountOut])
def list_accounts(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return db.query(Account).filter(Account.user_id == user.id).order_by(Account.id).all()


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
