"""Auto-comment engine — reply like a person, not a bot.

Match what they wrote: same greeting, same emojis. Never "thanks a lot".
"""
from __future__ import annotations

import random
import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..models import Account

# Phone-keyboard style. Short. No corporate "Thanks for commenting!".
HUMAN_POOL = {
    "question": [
        "Will share in the next post 🙏",
        "Good question — checking and updating 🙌",
        "Ask anytime 🙏",
    ],
    "praise": [
        "❤️",
        "🙏 Super",
        "Means a lot 🙏",
    ],
    "purchase_intent": [
        "Yes — details in bio / DM 🙏",
        "Available, check the bio link 🙌",
    ],
    "support": [
        "Sorry — DMing you now 🙏",
        "Let’s sort this, sent you a DM 🙏",
    ],
    "generic": [
        "🙏",
        "Swamy Saranam Ayyappa 🙏",
        "Yes 🙏",
    ],
}

QUESTION_WORDS = ("how", "what", "when", "where", "which", "can i", "do you", "is it", "?")
PRAISE_WORDS = ("love", "amazing", "great", "awesome", "nice", "best", "beautiful", "wow",
                "super", "superb", "beautiful", "good")
PURCHASE_WORDS = ("want", "need", "buy", "price", "cost", "how much", "link", "dm", "order", "available", "get this")
SUPPORT_WORDS = ("not working", "issue", "problem", "refund", "bad", "worst", "error", "failed", "broken")

# Devotional greetings we echo back instead of thanking.
_GREETING_RES = [
    re.compile(r"(om\s+)?swam[iy]ye?\s+saranam\s+ayyappa", re.I),
    re.compile(r"swamy\s+saranam\s+ayyappa", re.I),
    re.compile(r"saranam\s+ayyappa", re.I),
    re.compile(r"jai\s+shri\s+ram", re.I),
    re.compile(r"har\s+har\s+mahad[eé]v", re.I),
    re.compile(r"om\s+namah\s+shivaya", re.I),
]

_EMOJI_RE = re.compile(
    "["
    "\U0001F300-\U0001FAFF"
    "\U00002700-\U000027BF"
    "\U0001F1E0-\U0001F1FF"
    "\U00002600-\U000026FF"
    "\U0001F900-\U0001F9FF"
    "\U0000200D\U0000FE0F"
    "]+",
    flags=re.UNICODE,
)


def _emojis(text: str) -> str:
    found = _EMOJI_RE.findall(text or "")
    if not found:
        return ""
    # keep order, drop repeats, cap length so we don't spam
    out, seen = [], set()
    for chunk in found:
        if chunk in seen:
            continue
        seen.add(chunk)
        out.append(chunk)
        if len("".join(out)) >= 12:
            break
    return "".join(out)


def _letters(text: str) -> str:
    return re.sub(r"[\W_]+", " ", text or "", flags=re.UNICODE).strip()


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


def _echo_greeting(text: str) -> str | None:
    for rx in _GREETING_RES:
        m = rx.search(text)
        if not m:
            continue
        phrase = m.group(0).strip()
        # Keep their spelling; tidy extra spaces.
        phrase = re.sub(r"\s+", " ", phrase)
        extra = _emojis(text)
        if not extra:
            extra = "🙏"
        if extra and extra not in phrase:
            return f"{phrase} {extra}".strip()
        return phrase
    return None


def generate_reply(comment_text: str, account: Account) -> str:
    """Reply the way a person in the comments would.

    1. Echo mantras/greetings they wrote (Swamy Saranam Ayyappa → same).
    2. If they only sent emojis, send those emojis back.
    3. One-word comments get the same word back.
    4. Account template only if nothing above matched.
    5. Otherwise a short human line, plus their emojis.
    """
    raw = (comment_text or "").strip()
    if not raw:
        return "🙏"

    echoed = _echo_greeting(raw)
    if echoed:
        return echoed

    emojis = _emojis(raw)
    letters = _letters(raw)

    if emojis and len(letters) < 2:
        return emojis

    words = letters.split()
    if len(words) == 1 and 2 <= len(words[0]) <= 24:
        word = words[0]
        # keep ALLCAPS if they shouted it
        out = word if word.isupper() else word.capitalize()
        return f"{out} {emojis}".strip() if emojis else f"{out} 🙏"

    tmpl = (getattr(account, "comment_template", None) or "").strip()
    if tmpl:
        # Don't let a fixed "thanks" template override a human echo, but if they
        # set a template, honour it and still stick their emojis on.
        if emojis and emojis not in tmpl:
            return f"{tmpl} {emojis}"
        return tmpl

    intent = _intent(raw)
    reply = random.choice(HUMAN_POOL.get(intent, HUMAN_POOL["generic"]))
    if emojis and emojis not in reply:
        reply = f"{reply} {emojis}"
    return reply


def post_reply(account: Account, platform_post_id: str, external_comment_id: str, text: str) -> bool:
    from ..config import settings
    if settings.MOCK_MODE:
        return True
    return True
