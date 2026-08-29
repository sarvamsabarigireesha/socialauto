"""Core background jobs: publish due posts, sync comments + auto-reply, sync analytics."""
from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session

from ..models import Post, PostStatus, Comment, Metric, Account, User
from ..config import settings
from . import platforms, autocomment


def _aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


# Buffer-style default weekly posting slots (used until user sets their own).
DEFAULT_SLOTS = [
    {"day": 0, "time": "09:00"}, {"day": 0, "time": "18:30"},
    {"day": 1, "time": "09:00"}, {"day": 1, "time": "18:30"},
    {"day": 2, "time": "09:00"}, {"day": 2, "time": "18:30"},
    {"day": 3, "time": "09:00"}, {"day": 3, "time": "18:30"},
    {"day": 4, "time": "09:00"}, {"day": 4, "time": "18:30"},
    {"day": 5, "time": "11:00"}, {"day": 5, "time": "17:00"},
    {"day": 6, "time": "11:00"}, {"day": 6, "time": "17:00"},
]


def _tz_for(db: Session, user_id: int) -> ZoneInfo:
    u = db.get(User, user_id)
    name = (u.timezone if u and u.timezone else "Asia/Kolkata")
    try:
        return ZoneInfo(name)
    except Exception:
        return ZoneInfo("Asia/Kolkata")


def _slots_of(account: Account) -> list[dict]:
    slots = account.posting_slots if isinstance(account.posting_slots, list) else []
    return slots or DEFAULT_SLOTS


def _next_occurrence(slot: dict, tz: ZoneInfo, after_local: datetime) -> datetime | None:
    """Next local datetime matching {day:0-6, time:'HH:MM'} strictly after after_local."""
    try:
        hh, mm = (int(x) for x in str(slot["time"]).split(":")[:2])
        day = int(slot["day"])
    except Exception:
        return None
    base = after_local.date()
    for offset in range(8):  # up to a week ahead
        d = base + timedelta(days=offset)
        if d.weekday() != day:
            continue
        cand = datetime(d.year, d.month, d.day, hh, mm, tzinfo=tz)
        if cand > after_local:
            return cand
    return None


def next_slot_for(db: Session, account: Account, after_utc: datetime | None = None,
                  exclude_post_id: int | None = None) -> datetime:
    """Buffer-style: next FREE posting slot for this channel (skips taken ones)."""
    now = datetime.now(timezone.utc)
    after = _aware(after_utc) if after_utc else now
    tz = _tz_for(db, account.user_id)
    taken = {
        p.scheduled_at.replace(tzinfo=timezone.utc) if p.scheduled_at and p.scheduled_at.tzinfo is None else p.scheduled_at
        for p in (db.query(Post)
                  .filter(Post.account_id == account.id,
                          Post.status == PostStatus.scheduled,
                          Post.source.in_(["queue", "next"]),
                          Post.id != (exclude_post_id or -1))
                  .all())
    }
    candidate = after
    for _ in range(300):
        cand_local = candidate.astimezone(tz)
        options = [_next_occurrence(s, tz, cand_local) for s in _slots_of(account)]
        options = [o for o in options if o]
        if not options:
            # no valid slots -> fall back to 1 hour from now
            return candidate + timedelta(hours=1)
        nxt = min(options)
        if nxt.astimezone(timezone.utc) not in taken:
            return nxt.astimezone(timezone.utc)
        candidate = nxt.astimezone(timezone.utc) + timedelta(minutes=1)
    return candidate + timedelta(minutes=30)


def reorder_queue(db: Session, user_id: int, ordered_ids: list[int]) -> list[Post]:
    """Drag-reorder: reassign slot times so queued posts follow the new order,
    per channel, keeping the earliest scheduled date as the anchor."""
    posts = (db.query(Post)
             .filter(Post.user_id == user_id, Post.id.in_(ordered_ids),
                     Post.status == PostStatus.scheduled,
                     Post.source.in_(["queue", "next"]))
             .all())
    by_id = {p.id: p for p in posts}
    ordered = [by_id[i] for i in ordered_ids if i in by_id]
    by_account: dict[int, list[Post]] = {}
    for p in ordered:
        by_account.setdefault(p.account_id, []).append(p)
    now = datetime.now(timezone.utc)
    for acc_id, group in by_account.items():
        acc = db.get(Account, acc_id)
        if not acc:
            continue
        tz = _tz_for(db, user_id)
        existing = [p for p in group if p.scheduled_at]
        anchor = min(p.scheduled_at for p in existing)
        if anchor.tzinfo is None:
            anchor = anchor.replace(tzinfo=timezone.utc)
        anchor = max(anchor - timedelta(minutes=1), now - timedelta(days=1))
        t = anchor
        for p in group:
            cand = t
            for _ in range(300):
                cand_local = cand.astimezone(tz)
                options = [_next_occurrence(s, tz, cand_local) for s in _slots_of(acc)]
                options = [o for o in options if o]
                if not options:
                    nxt = cand + timedelta(hours=1)
                else:
                    nxt = min(options).astimezone(timezone.utc)
                if nxt > t:
                    break
                cand = cand + timedelta(minutes=1)
            t = nxt
            p.scheduled_at = t
    db.commit()
    for p in ordered:
        db.refresh(p)
    return ordered


# ------------------------------------------------------------------ publishing
async def publish_due_posts(db: Session, user_id: int | None = None) -> dict:
    """Publish every scheduled post whose time has come (optionally one user)."""
    now = datetime.now(timezone.utc)
    q = (db.query(Post)
         .filter(Post.status == PostStatus.scheduled)
         .filter(Post.scheduled_at <= now))
    if user_id is not None:
        q = q.filter(Post.user_id == user_id)
    due = q.all()
    published, failed = 0, 0
    for post in due:
        post.status = PostStatus.publishing
        db.commit()
        result = await platforms.publish_post(post.account, post.caption, post.media_url,
                                              post_type=getattr(post, "post_type", "feed") or "feed")
        if result.ok:
            post.status = PostStatus.published
            post.platform_post_id = result.platform_post_id
            post.published_at = now
            published += 1
        else:
            post.status = PostStatus.failed
            post.error = result.error
            failed += 1
        db.commit()
    return {"checked": len(due), "published": published, "failed": failed}


async def publish_one(db: Session, post_id: int) -> Post:
    post = db.get(Post, post_id)
    if not post or post.status != PostStatus.scheduled:
        return post
    result = await platforms.publish_post(post.account, post.caption, post.media_url,
                                          post_type=getattr(post, "post_type", "feed") or "feed")
    if result.ok:
        post.status = PostStatus.published
        post.platform_post_id = result.platform_post_id
        post.published_at = datetime.now(timezone.utc)
    else:
        post.status = PostStatus.failed
        post.error = result.error
    db.commit()
    return post


# ------------------------------------------------------- comments + auto-reply
async def sync_comments(db: Session, user_id: int | None = None,
                        force_all: bool = False) -> dict:
    """Fetch new comments on published posts and auto-reply to each once."""
    q = (db.query(Post)
         .filter(Post.status == PostStatus.published)
         .filter(Post.platform_post_id != ""))
    if not force_all:
        cutoff = datetime.now(timezone.utc) - timedelta(hours=settings.COMMENT_WATCH_WINDOW_HOURS)
        q = q.filter(Post.published_at >= cutoff)
    if user_id is not None:
        q = q.filter(Post.user_id == user_id)
    posts = q.all()
    ingested, replied = 0, 0
    for post in posts:
        result = await platforms.fetch_post(post.account, post.platform_post_id)
        for c in result.comments:
            exists = (db.query(Comment)
                      .filter(Comment.post_id == post.id)
                      .filter(Comment.external_comment_id == c["external_id"])
                      .first())
            if exists:
                continue
            comment = Comment(
                post_id=post.id,
                external_comment_id=c["external_id"],
                author=c["author"],
                author_avatar=(c["author"][:1].upper() if c.get("author") else "?"),
                text=c["text"],
            )
            db.add(comment)
            db.commit()
            ingested += 1

            # auto-reply via the real platform comment-reply API (mock in demo mode)
            if settings.AUTO_COMMENT_ENABLED and post.account.auto_comment:
                reply = autocomment.generate_reply(c["text"], post.account)
                client = platforms.get_client(post.account.platform)
                ok = await client.reply_to_comment(post.account, post.platform_post_id,
                                                   c["external_id"], reply)
                if ok:
                    comment.our_reply = reply
                    comment.replied = True
                    replied += 1
                    db.commit()
    return {"posts_scanned": len(posts), "new_comments": ingested, "auto_replies": replied}


def simulate_incoming_comment(db: Session, post_id: int, author: str, text: str) -> Comment | None:
    """Demo helper: inject a comment as if the platform sent it, then auto-reply."""
    post = db.get(Post, post_id)
    if not post:
        return None
    comment = Comment(post_id=post_id, external_comment_id=f"sim_{post_id}_{datetime.now(timezone.utc).timestamp()}",
                      author=author, author_avatar=(author[:1].upper() if author else "?"), text=text)
    db.add(comment)
    db.commit()
    if settings.AUTO_COMMENT_ENABLED and post.account.auto_comment:
        reply = autocomment.generate_reply(text, post.account)
        if autocomment.post_reply(post.account, post.platform_post_id, comment.external_comment_id, reply):
            comment.our_reply = reply
            comment.replied = True
            db.commit()
    return comment


# ------------------------------------------------------------------ analytics
async def sync_metrics(db: Session, user_id: int | None = None) -> dict:
    """Pull latest metrics for published posts and store a snapshot row."""
    q = (db.query(Post)
         .filter(Post.status == PostStatus.published)
         .filter(Post.platform_post_id != ""))
    if user_id is not None:
        q = q.filter(Post.user_id == user_id)
    posts = q.all()
    updated = 0
    for post in posts:
        result = await platforms.fetch_post(post.account, post.platform_post_id)
        m = result.metrics
        if "error" in m:
            continue
        snap = Metric(
            post_id=post.id,
            likes=m.get("likes", 0),
            comments_count=m.get("comments_count", 0),
            shares=m.get("shares", 0),
            impressions=m.get("impressions", 0),
            reach=m.get("reach", 0),
            raw=m,
        )
        db.add(snap)
        updated += 1
    db.commit()
    return {"posts_scanned": len(posts), "snapshots": updated}


async def import_channel_content(db: Session, user_id: int, account_id: int,
                                 *, sync_after: bool = True,
                                 force_all_sync: bool = True) -> dict:
    """Import an account's existing videos/posts as 'published' posts so their
    comments show up in the Community inbox. Optionally sync comments + metrics."""
    acc = db.query(Account).filter(Account.id == account_id,
                                   Account.user_id == user_id).first()
    if not acc:
        return {"imported": 0, "error": "account not found"}
    client = platforms.get_client(acc.platform)
    if not hasattr(client, "list_recent_videos"):
        return {"imported": 0, "error": "import not supported on this platform"}
    try:
        videos = await client.list_recent_videos(acc)
    except Exception as e:
        return {"imported": 0, "scanned": 0, "error": f"{acc.platform.value}: {e}"}
    imported = 0
    for v in videos:
        exists = db.query(Post).filter(
            Post.account_id == acc.id,
            Post.platform_post_id == v["id"]).first()
        if exists:
            continue
        pub_at = datetime.now(timezone.utc)
        try:
            dt = datetime.fromisoformat(str(v["published_at"]).replace("Z", "+00:00"))
            if dt.tzinfo:
                pub_at = dt
        except Exception:
            pass
        p = Post(user_id=user_id, account_id=acc.id,
                 platform_post_id=v["id"],
                 caption=v.get("title", "imported post"),
                 media_url=v.get("thumb", ""),
                 scheduled_at=pub_at, published_at=pub_at,
                 status=PostStatus.published)
        db.add(p)
        imported += 1
    db.commit()
    comments_sync = {"posts_scanned": 0, "new_comments": 0, "auto_replies": 0}
    metrics_sync = {"posts_scanned": 0, "snapshots": 0}
    if sync_after:
        comments_sync = await sync_comments(db, user_id, force_all=force_all_sync)
        metrics_sync = await sync_metrics(db, user_id)
    note = ""
    if not videos:
        if acc.platform.value == "youtube":
            note = ("No UPLOADED videos found on this channel. Note: YouTube "
                    "Community posts (text/image posts) can NOT be read via any "
                    "API — only uploaded videos & shorts sync. If you have videos, "
                    "make sure they're uploaded as Public on THIS channel.")
        else:
            note = "No recent posts found on this account (or the API returned none)."
    elif imported == 0:
        note = f"{len(videos)} posts already synced — comments refreshed."
    return {"imported": imported, "scanned": len(videos), "note": note,
            "comments_sync": comments_sync, "metrics_sync": metrics_sync}


async def auto_import_all(db: Session, user_id: int | None = None,
                          *, run_sync: bool = True,
                          force_all_sync: bool = True) -> dict:
    """Background safety net: for every connected account that supports it,
    make sure existing channel content is imported (idempotent). Called after
    OAuth connect and periodically by cron — that's what makes the app feel
    'connected for real' without a manual button press."""
    q = db.query(Account).filter(Account.access_token != "")
    if user_id is not None:
        q = q.filter(Account.user_id == user_id)
    accs = q.all()
    total = 0
    results, errors = [], []
    supported = 0
    for acc in accs:
        client = platforms.get_client(acc.platform)
        if not hasattr(client, "list_recent_videos"):
            continue  # Moj/ShareChat/Threads/manual helpers — no data API
        supported += 1
        try:
            res = await import_channel_content(db, acc.user_id, acc.id, sync_after=False)
            total += res.get("imported", 0)
            if res.get("error"):
                errors.append(f"{acc.display_name}: {res['error']}")
            else:
                results.append({"platform": acc.platform.value,
                                "name": acc.display_name,
                                "imported": res.get("imported", 0),
                                "scanned": res.get("scanned", 0),
                                "note": res.get("note", "")})
        except Exception as e:
            errors.append(f"{acc.display_name}: {e}")
    comments_sync = {"posts_scanned": 0, "new_comments": 0, "auto_replies": 0}
    metrics_sync = {"posts_scanned": 0, "snapshots": 0}
    if run_sync:
        comments_sync = await sync_comments(db, user_id, force_all=force_all_sync)
        metrics_sync = await sync_metrics(db, user_id)
    return {"imported": total, "accounts": len(accs), "supported_accounts": supported,
            "per_account": results, "errors": errors,
            "comments_sync": comments_sync, "metrics_sync": metrics_sync}


def analytics_summary(db: Session, user_id: int | None = None, days: int | None = None) -> dict:
    """Aggregate dashboard numbers for one user (optional last-N-days filter)."""
    q = db.query(Post).filter(Post.status == PostStatus.published)
    if user_id is not None:
        q = q.filter(Post.user_id == user_id)
    if days:
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)
        q = q.filter(Post.published_at >= cutoff)
    posts = q.all()
    totals = {"likes": 0, "comments": 0, "shares": 0, "impressions": 0, "reach": 0}
    by_platform: dict[str, dict] = {}
    by_tag: dict[str, dict] = {}
    per_post = []
    for p in posts:
        latest = (db.query(Metric).filter(Metric.post_id == p.id)
                  .order_by(Metric.fetched_at.desc()).first())
        row = {
            "post_id": p.id, "platform": p.account.platform.value,
            "account": p.account.display_name,
            "caption": p.caption[:60],
            "published_at": p.published_at.isoformat() if p.published_at else None,
            "likes": latest.likes if latest else 0,
            "comments": latest.comments_count if latest else 0,
            "shares": latest.shares if latest else 0,
            "impressions": latest.impressions if latest else 0,
            "reach": latest.reach if latest else 0,
        }
        per_post.append(row)
        for k in totals:
            totals[k] += row[{"likes": "likes", "comments": "comments",
                              "shares": "shares", "impressions": "impressions",
                              "reach": "reach"}[k]]
        bp = by_platform.setdefault(p.account.platform.value,
                                    {"likes": 0, "comments": 0, "shares": 0, "posts": 0})
        bp["likes"] += row["likes"]; bp["comments"] += row["comments"]
        bp["shares"] += row["shares"]; bp["posts"] += 1
        for t in p.tags:
            bt = by_tag.setdefault(t.name, {"posts": 0, "likes": 0, "comments": 0,
                                            "shares": 0, "color": t.color})
            bt["posts"] += 1
            bt["likes"] += row["likes"]
            bt["comments"] += row["comments"]
            bt["shares"] += row["shares"]

    post_ids = [p.id for p in posts]
    cq = db.query(Comment)
    if post_ids:
        cq = cq.filter(Comment.post_id.in_(post_ids))
    else:
        cq = cq.filter(Comment.id == -1)
    auto_replied = cq.filter(Comment.replied == True).count()
    total_comments = cq.count()
    sq = db.query(Post).filter(Post.status == PostStatus.scheduled)
    if user_id is not None:
        sq = sq.filter(Post.user_id == user_id)
    return {
        "totals": totals,
        "by_platform": by_platform,
        "by_tag": by_tag,
        "per_post": per_post,
        "comments_total": total_comments,
        "auto_replied": auto_replied,
        "posts_published": len(posts),
        "posts_scheduled": sq.count(),
    }
