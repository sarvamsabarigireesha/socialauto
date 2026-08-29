"""Core background jobs: publish due posts, sync comments + auto-reply, sync analytics."""
from datetime import datetime, timezone, timedelta

from sqlalchemy.orm import Session

from ..models import Post, PostStatus, Comment, Metric, Account
from ..config import settings
from . import platforms, autocomment


def _aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


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
        result = await platforms.publish_post(post.account, post.caption, post.media_url)
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
    result = await platforms.publish_post(post.account, post.caption, post.media_url)
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
async def sync_comments(db: Session, user_id: int | None = None) -> dict:
    """Fetch new comments on published posts and auto-reply to each once."""
    cutoff = datetime.now(timezone.utc) - timedelta(hours=settings.COMMENT_WATCH_WINDOW_HOURS)
    q = (db.query(Post)
         .filter(Post.status == PostStatus.published)
         .filter(Post.platform_post_id != "")
         .filter(Post.published_at >= cutoff))
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


async def import_channel_content(db: Session, user_id: int, account_id: int) -> dict:
    """Import an account's existing videos/posts as 'published' posts so their
    comments show up in the Community inbox. Then sync comments + metrics."""
    acc = db.query(Account).filter(Account.id == account_id,
                                   Account.user_id == user_id).first()
    if not acc:
        return {"imported": 0, "error": "account not found"}
    client = platforms.get_client(acc.platform)
    if not hasattr(client, "list_recent_videos"):
        return {"imported": 0, "error": "import not supported on this platform"}
    videos = await client.list_recent_videos(acc)
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
    await sync_comments(db, user_id)
    await sync_metrics(db, user_id)
    return {"imported": imported, "scanned": len(videos)}


def analytics_summary(db: Session, user_id: int | None = None) -> dict:
    """Aggregate dashboard numbers for one user."""
    q = db.query(Post).filter(Post.status == PostStatus.published)
    if user_id is not None:
        q = q.filter(Post.user_id == user_id)
    posts = q.all()
    totals = {"likes": 0, "comments": 0, "shares": 0, "impressions": 0, "reach": 0}
    by_platform: dict[str, dict] = {}
    per_post = []
    for p in posts:
        latest = (db.query(Metric).filter(Metric.post_id == p.id)
                  .order_by(Metric.fetched_at.desc()).first())
        row = {
            "post_id": p.id, "platform": p.account.platform.value,
            "account": p.account.display_name,
            "caption": p.caption[:60],
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
        "per_post": per_post,
        "comments_total": total_comments,
        "auto_replied": auto_replied,
        "posts_published": len(posts),
        "posts_scheduled": sq.count(),
    }
