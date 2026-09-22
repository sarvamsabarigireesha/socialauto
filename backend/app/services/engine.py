"""Publishing + sync engine.

This is the orchestration layer that sits on top of the platform clients in
`platforms.py`. It is responsible for:

  * queue / slot assignment (Buffer-style "Next slot" + "Share next in queue")
  * publishing due posts (driven by the cron tick: GitHub Actions or the
    Cloudflare Worker)
  * importing existing channel content so old posts/comments show up
  * syncing comments (and firing auto-replies) and metrics snapshots
  * aggregating the analytics numbers the dashboard renders

Every datetime that touches the database is UTC. Rows come back naive from
SQLite/Postgres TIMESTAMP columns, so `_aware()` re-stamps UTC on them before
they are compared or sent to the API (the browser needs the offset).
"""
import random
import uuid
from datetime import datetime, timedelta, timezone

from ..config import settings
from ..models import Account, Comment, Metric, Post, PostStatus
from . import platforms
from .autocomment import generate_reply, post_reply

UTC = timezone.utc

# Posts we already tried to hand-publish (no API available) are tagged with this
# prefix in `Post.error` so the cron never retries them forever.
MANUAL_PREFIX = "MANUAL:"

# Default weekly slots (Sunday = 0), matching the frontend schedule editor's
# fallback grid. Used when a channel has no `posting_slots` configured.
DEFAULT_SLOTS = (
    (0, 9, 0), (0, 18, 30), (1, 9, 0), (1, 18, 30), (2, 9, 0), (2, 18, 30),
    (3, 9, 0), (3, 18, 30), (4, 9, 0), (4, 18, 30), (5, 11, 0), (5, 17, 0),
    (6, 11, 0), (6, 17, 0),
)

# Intent-flavoured sample comments used in MOCK_MODE so the community inbox and
# the auto-comment engine are demoable without any real API.
MOCK_COMMENTS = (
    ("Aditi", "How much is this? I want to order 😍"),
    ("Rahul", "Love this! Amazing work 🔥"),
    ("Sneha", "Is this available in Hyderabad?"),
    ("Vikram", "This is not working for me, tried twice 😞"),
    ("Priya", "Wow, beautiful shot 🔥"),
    ("Imran", "Can I get the link please?"),
    ("Meghana", "Best one so far 👏"),
)


# ---------------------------------------------------------------- time helpers
def _now() -> datetime:
    """Timezone-aware "now" in UTC."""
    return datetime.now(UTC)


def _aware(dt: datetime | None) -> datetime | None:
    """Normalize any datetime to timezone-aware UTC.

    SQLite (and `TIMESTAMP WITHOUT TIME ZONE` on Postgres) drops the tzinfo on
    write and hands back a naive value on read. Everything we store is UTC, so a
    naive value simply gets UTC stamped on it.
    """
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


def _naive_utc(dt: datetime | None = None) -> datetime:
    """UTC datetime without tzinfo — the shape the DB columns actually hold.

    Used for WHERE comparisons so SQLite and Postgres behave identically.
    """
    return _aware(dt or _now()).replace(tzinfo=None)


def _user_tz(account: Account):
    """The channel owner's timezone (slots are wall-clock times in it)."""
    name = getattr(getattr(account, "user", None), "timezone", "") or "Asia/Kolkata"
    try:
        from zoneinfo import ZoneInfo

        return ZoneInfo(name)
    except Exception:
        # No tzdata available (or a bad value) → fall back to a fixed IST offset
        # so scheduling still works instead of blowing up.
        return timezone(timedelta(hours=5, minutes=30))


def _parse_slots(account: Account) -> list[tuple[int, int, int]]:
    """`[{"day":0,"time":"09:00"}]` -> sorted `[(dow, hour, minute)]`."""
    out = set()
    for slot in account.posting_slots or []:
        try:
            day = int(slot.get("day"))
            hh, mm = str(slot.get("time", "")).split(":")
            if 0 <= day <= 6 and 0 <= int(hh) <= 23 and 0 <= int(mm) <= 59:
                out.add((day, int(hh), int(mm)))
        except (AttributeError, TypeError, ValueError):
            continue
    return sorted(out)


def _slot_dow(day) -> int:
    """Python weekday (Mon=0) -> frontend day index (Sun=0)."""
    return (day.weekday() + 1) % 7


# ------------------------------------------------------------- queue / slots
def next_slot_for(db, account: Account, anchor: datetime,
                  exclude_post_id: int | None = None) -> datetime:
    """First free posting slot strictly after `anchor` (UTC) for this channel.

    Slots are stored as wall-clock times in the owner's timezone; the returned
    datetime is UTC so it can be dropped straight into `Post.scheduled_at`.
    """
    anchor = _aware(anchor)
    tz = _user_tz(account)

    slots = _parse_slots(account)
    if not slots:
        slots = list(DEFAULT_SLOTS)

    # Slots already promised to other queued posts on this channel.
    q = db.query(Post.id, Post.scheduled_at).filter(
        Post.account_id == account.id,
        Post.status.in_((PostStatus.scheduled, PostStatus.publishing)),
    )
    if exclude_post_id:
        q = q.filter(Post.id != exclude_post_id)
    taken = {_naive_utc(row[1]) for row in q.all() if row[1] is not None}

    start_local = anchor.astimezone(tz)
    for offset in range(15):  # look up to two weeks ahead
        day = start_local.date() + timedelta(days=offset)
        dow = _slot_dow(day)
        for slot_day, hh, mm in slots:
            if slot_day != dow:
                continue
            candidate = datetime(day.year, day.month, day.day, hh, mm, tzinfo=tz)
            candidate_utc = candidate.astimezone(UTC)
            if candidate_utc <= anchor:
                continue
            if _naive_utc(candidate_utc) in taken:
                continue
            return candidate_utc

    # No slot fits (fully booked / no matching day) — just go an hour out.
    return anchor + timedelta(hours=1)


def reorder_queue(db, user_id: int, ordered_ids: list[int]) -> list[Post]:
    """Buffer-style drag-to-reorder: re-slot queued posts in the given order.

    Only unpublished posts are touched; each one is pushed into the next free
    slot of its own channel, in order.
    """
    posts = []
    for pid in ordered_ids:
        post = db.get(Post, pid)
        if (not post or post.user_id != user_id
                or post.status in (PostStatus.published, PostStatus.draft)):
            continue
        posts.append(post)

    anchor = _now()
    for post in posts:
        account = post.account or db.get(Account, post.account_id)
        if not account:
            continue
        slot = next_slot_for(db, account, anchor, exclude_post_id=post.id)
        post.scheduled_at = slot
        anchor = slot  # keep the dragged order strictly increasing

    db.commit()
    for post in posts:
        db.refresh(post)
    return posts


# ---------------------------------------------------------------- publishing
async def publish_one(db, post_id: int) -> Post | None:
    """Publish a single post through its platform client.

    The post is atomically claimed first (`scheduled`/`failed`/`draft` ->
    `publishing`) so two cron ticks firing at once can't double-post.
    """
    claimable = (PostStatus.scheduled, PostStatus.failed, PostStatus.draft)
    claimed = (db.query(Post)
               .filter(Post.id == post_id, Post.status.in_(claimable))
               .update({Post.status: PostStatus.publishing},
                       synchronize_session=False))
    db.commit()

    post = db.get(Post, post_id)
    if post is None or not claimed:
        # Already published, or another worker is on it right now.
        return post

    account = post.account or db.get(Account, post.account_id)
    if account is None:
        post.status = PostStatus.failed
        post.error = "account no longer connected"
        db.commit()
        return post

    post.error = ""
    db.commit()

    try:
        result = await platforms.get_client(account.platform).publish(
            account, post.caption, post.media_url, post_type=post.post_type)
    except Exception as exc:  # a client blowing up must not kill the whole tick
        result = platforms.PublishResult(
            False, error=f"{type(exc).__name__}: {exc}")

    if result.ok:
        post.status = PostStatus.published
        post.platform_post_id = result.platform_post_id or post.platform_post_id
        post.published_at = _now()
        post.error = ""
    elif getattr(result, "manual", False):
        # No publishing API for this platform/format (YouTube video, Moj,
        # ShareChat…). Keep it queued with a hint and let the user finish it by
        # hand and tap "Mark done" — publish_due_posts() skips MANUAL: posts.
        post.status = PostStatus.scheduled
        post.error = result.error or f"{MANUAL_PREFIX} publish manually"
    else:
        post.status = PostStatus.failed
        post.error = (result.error or "publish failed")[:2000]

    db.commit()
    db.refresh(post)
    return post


async def publish_due_posts(db, limit: int = 25) -> dict:
    """Publish everything that is due. Called by the cron tick."""
    due = (db.query(Post)
           .filter(Post.status == PostStatus.scheduled,
                   Post.scheduled_at <= _naive_utc(),
                   ~Post.error.like(f"{MANUAL_PREFIX}%"))
           .order_by(Post.scheduled_at)
           .limit(limit)
           .all())

    published = failed = manual = 0
    for post in due:
        try:
            result = await publish_one(db, post.id)
        except Exception as exc:
            print(f"publish_due_posts: post {post.id} crashed: {exc}", flush=True)
            continue
        if result is None:
            continue
        if result.status == PostStatus.published:
            published += 1
        elif result.status == PostStatus.failed:
            failed += 1
        elif (result.error or "").startswith(MANUAL_PREFIX):
            manual += 1

    return {"ok": True, "scanned": len(due), "published": published,
            "failed": failed, "manual": manual}


# ------------------------------------------------------------------ comments
def _mock_incoming(post: Post) -> list[dict]:
    """Fake follower comments so MOCK_MODE has a live-looking inbox."""
    if not settings.MOCK_MODE:
        return []
    if post.published_at and _aware(post.published_at) < _now() - timedelta(
            hours=settings.COMMENT_WATCH_WINDOW_HOURS):
        return []
    return [
        {"id": f"mock_{post.id}_{uuid.uuid4().hex[:8]}", "author": author, "text": text}
        for author, text in random.sample(MOCK_COMMENTS, k=random.choice((1, 2)))
    ]


def simulate_incoming_comment(db, post_id: int, author: str, text: str) -> Comment | None:
    """Demo helper: a follower comments, the bot replies immediately."""
    post = db.get(Post, post_id)
    if post is None:
        return None
    account = post.account or db.get(Account, post.account_id)

    comment = Comment(
        post_id=post.id,
        external_comment_id=f"sim_{uuid.uuid4().hex[:12]}",
        author=(author or "follower")[:200],
        author_avatar=(author or "?")[:1].upper(),
        text=text or "",
    )
    db.add(comment)
    db.flush()

    if settings.AUTO_COMMENT_ENABLED and account is not None and account.auto_comment:
        reply = generate_reply(comment.text, account)
        post_reply(account, post.platform_post_id, comment.external_comment_id, reply)
        comment.our_reply = reply
        comment.replied = True
        comment.reply_type = "auto"

    db.commit()
    db.refresh(comment)
    return comment


async def sync_comments(db, user_id: int | None = None, limit: int = 50) -> dict:
    """Pull new comments on our published posts and run auto-replies.

    Pass `user_id` to scope it to one workspace; omit it for the global cron.
    """
    q = (db.query(Post)
         .filter(Post.status == PostStatus.published,
                 Post.platform_post_id != "")
         .order_by(Post.published_at.desc()))
    if user_id:
        q = q.filter(Post.user_id == user_id)
    posts = q.limit(limit).all()

    new_comments = auto_replies = 0
    for post in posts:
        account = post.account
        if account is None:
            continue
        client = platforms.get_client(account.platform)
        try:
            fetched = await client.fetch(account, post.platform_post_id)
            incoming = list(getattr(fetched, "comments", None) or [])
        except Exception as exc:
            print(f"sync_comments: {account.display_name} fetch failed: {exc}",
                  flush=True)
            incoming = []
        if not incoming:
            incoming = _mock_incoming(post)

        for item in incoming:
            external_id = str(item.get("id") or item.get("external_comment_id") or "")
            if external_id and (db.query(Comment)
                                .filter(Comment.post_id == post.id,
                                        Comment.external_comment_id == external_id)
                                .first()):
                continue
            author = str(item.get("author") or item.get("from") or "someone")[:200]
            comment = Comment(post_id=post.id, external_comment_id=external_id,
                              author=author, author_avatar=author[:1].upper(),
                              text=str(item.get("text") or item.get("message") or ""))
            db.add(comment)
            db.flush()
            new_comments += 1

            if not (settings.AUTO_COMMENT_ENABLED and account.auto_comment):
                continue
            if not comment.text.strip():
                continue
            reply = generate_reply(comment.text, account)
            try:
                ok = await client.reply_to_comment(account, post.platform_post_id,
                                                   external_id, reply)
            except Exception as exc:
                print(f"sync_comments: reply failed: {exc}", flush=True)
                ok = False
            if ok:
                comment.our_reply = reply
                comment.replied = True
                comment.reply_type = "auto"
                auto_replies += 1
        db.commit()

    return {"new_comments": new_comments, "auto_replies": auto_replies,
            "posts_scanned": len(posts)}


# ------------------------------------------------------------------- metrics
async def sync_metrics(db, user_id: int | None = None, limit: int = 50,
                       min_age_minutes: int = 30) -> dict:
    """Refresh the analytics snapshot for published posts.

    When called for a whole user (dashboard "Refresh") every post is re-fetched.
    The global cron pass skips posts that already have a fresh snapshot.
    """
    q = (db.query(Post)
         .filter(Post.status == PostStatus.published,
                 Post.platform_post_id != "")
         .order_by(Post.published_at.desc()))
    if user_id:
        q = q.filter(Post.user_id == user_id)
    posts = q.limit(limit).all()

    snapshots = 0
    for post in posts:
        account = post.account
        if account is None:
            continue
        client = platforms.get_client(account.platform)
        try:
            metrics = dict(getattr(await client.fetch(account, post.platform_post_id),
                                   "metrics", None) or {})
        except Exception as exc:
            print(f"sync_metrics: {account.display_name} fetch failed: {exc}",
                  flush=True)
            continue
        if not metrics:
            continue

        row = (db.query(Metric).filter(Metric.post_id == post.id)
               .order_by(Metric.fetched_at.desc()).first())
        if (row is not None and user_id is None
                and _aware(row.fetched_at) > _now() - timedelta(minutes=min_age_minutes)):
            continue

        def _num(key, fallback=0):
            try:
                return int(metrics.get(key, fallback) or 0)
            except (TypeError, ValueError):
                return int(fallback or 0)

        if row is None:
            row = Metric(post_id=post.id)
            db.add(row)
        row.likes = _num("likes")
        row.comments_count = _num("comments_count")
        row.shares = _num("shares")
        row.impressions = _num("impressions")
        row.reach = _num("reach")
        row.raw = metrics
        row.fetched_at = _now()
        snapshots += 1

    db.commit()
    return {"snapshots": snapshots, "posts_scanned": len(posts)}


# ------------------------------------------------------------------- imports
async def import_channel_content(db, user_id: int, account_id: int) -> dict:
    """Import a connected channel's existing videos/posts.

    Already-imported content is matched on `platform_post_id`, so this is safe
    to run repeatedly (it's what the first-login bootstrap sync does).
    """
    account = db.get(Account, account_id)
    if account is None or account.user_id != user_id:
        return {"ok": False, "imported": 0, "scanned": 0,
                "error": "account not found"}

    result = {"ok": True, "account_id": account.id, "name": account.display_name,
              "platform": account.platform.value, "scanned": 0, "imported": 0,
              "note": "", "error": ""}

    client = platforms.get_client(account.platform)
    try:
        items = list(await client.list_recent_videos(account) or [])
    except Exception as exc:
        result["ok"] = False
        result["error"] = f"{account.display_name}: {type(exc).__name__}: {exc}"
        return result

    result["scanned"] = len(items)
    for item in items:
        external_id = str(item.get("id") or item.get("video_id") or "")
        if not external_id:
            continue
        exists = (db.query(Post)
                  .filter(Post.account_id == account.id,
                          Post.platform_post_id == external_id)
                  .first())
        if exists:
            continue

        raw_date = item.get("published_at") or item.get("timestamp") or ""
        try:
            published = _aware(datetime.fromisoformat(
                str(raw_date).replace("Z", "+00:00"))) if raw_date else _now()
        except ValueError:
            published = _now()

        db.add(Post(
            user_id=user_id,
            account_id=account.id,
            caption=item.get("title") or item.get("caption") or "(imported post)",
            media_url=item.get("url") or item.get("media_url") or "",
            post_type=item.get("post_type") or "video",
            source="scheduled",
            scheduled_at=published,
            status=PostStatus.published,
            platform_post_id=external_id,
            published_at=published,
        ))
        result["imported"] += 1

    if not items:
        result["note"] = ("connect a real account to import" if settings.MOCK_MODE
                          else "nothing new to import")
    db.commit()
    return result


async def auto_import_all(db, user_id: int | None = None, run_sync: bool = False,
                          force_all_sync: bool = False) -> dict:
    """Import existing content from every connected account.

    Called by the cron tick (all users), and by the workspace bootstrap sync
    (one user, `run_sync=True`) that the dashboard fires on first login.
    """
    q = db.query(Account)
    if user_id:
        q = q.filter(Account.user_id == user_id)
    accounts = q.all()

    imported = 0
    per_account: list[dict] = []
    errors: list[str] = []

    for account in accounts:
        try:
            result = await import_channel_content(db, account.user_id, account.id)
        except Exception as exc:
            errors.append(f"{account.display_name}: {type(exc).__name__}: {exc}")
            continue
        imported += result.get("imported", 0)
        if result.get("error"):
            errors.append(result["error"])
        per_account.append({
            "name": account.display_name,
            "platform": account.platform.value,
            "scanned": result.get("scanned", 0),
            "imported": result.get("imported", 0),
            "note": result.get("note") or result.get("error", ""),
        })

    out = {"ok": True, "imported": imported, "per_account": per_account,
           "errors": errors, "comments_sync": None, "metrics_sync": None}
    if run_sync or force_all_sync:
        out["comments_sync"] = await sync_comments(db, user_id)
        out["metrics_sync"] = await sync_metrics(db, user_id)
    return out


# ----------------------------------------------------------------- analytics
def analytics_summary(db, user_id: int, days: int | None = None) -> dict:
    """Aggregated numbers behind the Insights screen and the CSV export."""
    since = _now() - timedelta(days=days) if days else None

    published = (db.query(Post)
                 .filter(Post.user_id == user_id,
                         Post.status == PostStatus.published)
                 .order_by(Post.published_at.desc())
                 .all())
    posts_scheduled = (db.query(Post)
                       .filter(Post.user_id == user_id,
                               Post.status == PostStatus.scheduled)
                       .count())

    totals = {"likes": 0, "comments": 0, "shares": 0, "impressions": 0, "reach": 0}
    by_platform: dict[str, dict] = {}
    by_tag: dict[str, dict] = {}
    per_post: list[dict] = []

    for post in published:
        published_at = _aware(post.published_at or post.scheduled_at)
        if since and published_at < since:
            continue

        snapshot = (db.query(Metric).filter(Metric.post_id == post.id)
                    .order_by(Metric.fetched_at.desc()).first())
        likes = snapshot.likes if snapshot else 0
        comments_count = snapshot.comments_count if snapshot else 0
        shares = snapshot.shares if snapshot else 0
        impressions = snapshot.impressions if snapshot else 0
        reach = snapshot.reach if snapshot else 0

        account = post.account
        platform = account.platform.value if account else "instagram"

        totals["likes"] += likes
        totals["comments"] += comments_count
        totals["shares"] += shares
        totals["impressions"] += impressions
        totals["reach"] += reach

        bucket = by_platform.setdefault(platform, {
            "posts": 0, "likes": 0, "comments": 0, "shares": 0,
            "impressions": 0, "reach": 0})
        bucket["posts"] += 1
        bucket["likes"] += likes
        bucket["comments"] += comments_count
        bucket["shares"] += shares
        bucket["impressions"] += impressions
        bucket["reach"] += reach

        for tag in post.tags:
            tag_bucket = by_tag.setdefault(tag.name, {
                "color": tag.color, "posts": 0, "likes": 0, "comments": 0,
                "shares": 0})
            tag_bucket["posts"] += 1
            tag_bucket["likes"] += likes
            tag_bucket["comments"] += comments_count
            tag_bucket["shares"] += shares

        per_post.append({
            "post_id": post.id,
            "platform": platform,
            "account": account.display_name if account else "",
            "caption": (post.caption or "")[:200],
            "published_at": published_at,
            "likes": likes,
            "comments": comments_count,
            "shares": shares,
            "impressions": impressions,
            "reach": reach,
        })

    comment_rows = (db.query(Comment)
                    .join(Post, Comment.post_id == Post.id)
                    .filter(Post.user_id == user_id))
    if since:
        comment_rows = comment_rows.filter(
            Comment.created_at >= _naive_utc(since))
    comment_rows = comment_rows.all()
    comments_total = len(comment_rows)
    auto_replied = sum(1 for c in comment_rows
                       if c.replied and c.reply_type == "auto")

    return {
        "days": days,
        "posts_published": len(per_post),
        "posts_scheduled": posts_scheduled,
        "comments_total": comments_total,
        "auto_replied": auto_replied,
        "totals": totals,
        "by_platform": by_platform,
        "by_tag": by_tag,
        "per_post": per_post,
    }


# ------------------------------------------------------- backwards-compat API
# Older modules imported these helpers straight from `engine`; keep them working
# by delegating to the platform client layer.
class Result:
    def __init__(self, ok, platform_post_id="", error=""):
        self.ok = ok
        self.platform_post_id = platform_post_id
        self.error = error


async def publish_post(account: Account, caption: str, media_url: str,
                       post_type: str = "feed") -> Result:
    res = await platforms.publish_post(account, caption, media_url, post_type=post_type)
    return Result(res.ok, res.platform_post_id, res.error)


async def list_recent_videos(account: Account):
    return await platforms.get_client(account.platform).list_recent_videos(account)


async def fetch_post(account: Account, platform_post_id: str):
    return await platforms.fetch_post(account, platform_post_id)


def get_client(platform):
    return platforms.get_client(platform)


async def reply_to_comment(*args, **kwargs) -> bool:
    return False
