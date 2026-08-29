"""Caption templates (Buffer-style) — built-ins + user's own."""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import Template, User
from ..security import get_current_user

router = APIRouter(prefix="/api/templates", tags=["templates"])

BUILTINS = [
    ("Engagement question", "engagement",
     "Drop your answer in the comments 👇\n\nQuestion of the day: [ask something fun about your niche] 🔥\n\n#QOTD #community #[niche]"),
    ("Behind the scenes", "story",
     "BTS from today 👀\n\nNobody shows you the messy middle — so here it is 🙌\n\n[screenshot / clip] 💛\n\n#behindthescenes #[niche]life"),
    ("Product / offer launch", "promo",
     "🎉 IT’S LIVE! 🎉\n\n[Product/offer name] is here — [1-line benefit].\n\n⏳ Early bird valid till [date]. Link in bio!\n\n#[brand] #launch #offer"),
    ("Value / tips carousel", "education",
     "Save this 🔖\n\n[3–5 quick tips about your topic, one per line]\n\nWhich one are you trying first? 👇\n\n#tips #[niche] #howto"),
    ("Testimonial / social proof", "promo",
     "“[Short customer quote]” ⭐\n\nThis is why we do what we do 🙏 Want results like this? Link in bio.\n\n#reviews #results #[brand]"),
    ("YouTube Shorts hook", "video",
     "Wait for it… 👀\n\n[3-sec visual hook]\n\nFull video on the channel — subscribe for daily [niche] tips 🔔\n\n#shorts #viral #[niche]"),
]


class TemplateIn(BaseModel):
    title: str
    content: str
    category: str = "general"


@router.get("")
def list_templates(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    owned = db.query(Template).filter(Template.user_id == user.id).all()
    # built-ins merged (not stored per user)
    out = [{"id": f"b{i}", "title": t, "category": c, "content": x, "builtin": True}
           for i, (t, c, x) in enumerate(BUILTINS)]
    out += [{"id": str(t.id), "title": t.title, "category": t.category,
             "content": t.content, "builtin": False} for t in owned]
    return out


@router.post("", status_code=201)
def create_template(data: TemplateIn, db: Session = Depends(get_db),
                    user: User = Depends(get_current_user)):
    if not data.title.strip() or not data.content.strip():
        raise HTTPException(400, "title + content required")
    t = Template(user_id=user.id, title=data.title.strip(),
                 content=data.content, category=data.category or "general")
    db.add(t); db.commit(); db.refresh(t)
    return {"id": str(t.id), "title": t.title, "category": t.category,
            "content": t.content, "builtin": False}


@router.delete("/{template_id}", status_code=204)
def delete_template(template_id: str, db: Session = Depends(get_db),
                    user: User = Depends(get_current_user)):
    if template_id.startswith("b"):
        raise HTTPException(400, "builtin templates can't be deleted")
    t = db.get(Template, int(template_id))
    if not t or t.user_id != user.id:
        raise HTTPException(404, "not found")
    db.delete(t); db.commit()
