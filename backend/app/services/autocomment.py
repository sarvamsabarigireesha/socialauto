"""Auto-comment engine.

Rule-based + lightweight sentiment/intent detection. In production you can
swap `generate_reply` for an LLM call (e.g. free-tier Gemini / Groq) —
the interface stays the same.
"""
import random

from ..models import Account

# Intent -> replies. Kept human, varied, emoji-light to avoid spam flags.
REPLY_POOL = {
    "question": [
        "Great question! 🙌 Sending you the details in DM.",
        "Hey! Happy to help — check your DMs, just messaged you.",
        "Good one! Full details are in the link in bio, DM if stuck.",
    ],
    "praise": [
        "Thank you so much! Means a lot ❤️",
        "Glad you loved it! More coming soon 🔥",
        "Thanks for the love! 🙏 Follow along for updates.",
    ],
    "purchase_intent": [
        "Awesome! 🙌 Just sent you the link in DM.",
        "Thank you! DMing you how to get it right away.",
        "Excited to have you! Check your DMs for next steps.",
    ],
    "support": [
        "Sorry about that! DMing you now so we can fix it fast.",
        "Let's sort this out — sent you a DM 🙏",
    ],
    "generic": [
        "Thanks for commenting! 🙌",
        "Appreciate you! Stay tuned for more.",
        "Thanks for stopping by! 👋",
    ],
}

QUESTION_WORDS = ("how", "what", "when", "where", "which", "can i", "do you", "is it", "?")
PRAISE_WORDS = ("love", "amazing", "great", "awesome", "nice", "best", "beautiful", "wow", "🔥", "❤️", "good")
PURCHASE_WORDS = ("want", "need", "buy", "price", "cost", "link", "dm", "order", "available", "get this")
SUPPORT_WORDS = ("not working", "issue", "problem", "refund", "bad", "worst", "error", "failed", "broken")


def _intent(text: str) -> str:
    t = text.lower()
    if any(w in t for w in SUPPORT_WORDS):
        return "support"
    if any(w in t for w in PURCHASE_WORDS):
        return "purchase_intent"
    if "?" in t or any(w in t for w in QUESTION_WORDS):
        return "question"
    if any(w in t for w in PRAISE_WORDS):
        return "praise"
    return "generic"


def generate_reply(comment_text: str, account: Account) -> str:
    """Return the auto-reply for an incoming comment.

    Priority: account's fixed comment_template -> intent-based pool.
    Swap this body for an LLM call later (same signature).
    """
    if account.comment_template.strip():
        return account.comment_template.strip()
    intent = _intent(comment_text)
    return random.choice(REPLY_POOL[intent])


def post_reply(account: Account, platform_post_id: str, external_comment_id: str, text: str) -> bool:
    """Post the reply to the platform.

    Real API (Meta Graph example):
        POST /{comment_id}/replies  with message=... & access_token=...
    In mock mode we always succeed.
    """
    from ..config import settings
    if settings.MOCK_MODE:
        return True
    # Real implementation would do the httpx call here; kept stub-safe.
    return True
