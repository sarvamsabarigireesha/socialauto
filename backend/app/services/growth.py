"""VidIQ-style growth toolkit for YouTube (and general content).

Pure heuristics, no external API — scores title/description/tags, suggests
SEO tags, best upload times, thumbnail ideas and a monetization checklist.
"""
import re

POWER_WORDS = ("you", "your", "how", "why", "best", "top", "free", "easy",
               "ultimate", "secret", "proven", "fast", "new", "2026",
               "tutorial", "guide", "mistakes", "vs", "step")
EMOTION = ("🔥", "😱", "🚀", "💡", "✅", "❌", "😮", "💰", "🎯", "shorts")


def title_score(title: str) -> dict:
    t = title.strip()
    n = len(t)
    score = 0
    checks = []
    if 40 <= n <= 70:
        score += 30; checks.append(("Ideal length (40–70 chars)", True))
    elif n >= 30:
        score += 18; checks.append(("Length OK; aim 40–70 chars", True))
    else:
        checks.append(("Too short — add detail (aim 40–70 chars)", False))
    if re.search(r"\d", t):
        score += 12; checks.append(("Contains a number (boosts CTR)", True))
    else:
        checks.append(("Add a number (e.g. '5 tips', '2026')", False))
    low = t.lower()
    if any(w in low for w in POWER_WORDS):
        score += 18; checks.append(("Power word present", True))
    else:
        checks.append(("Add a power word (How/Best/Top/Free/Secret)", False))
    if any(e in t for e in EMOTION) or t.isupper() is False and re.search(r"[!?]", t):
        score += 10; checks.append(("Emotion/curiosity hook", True))
    else:
        checks.append(("Add curiosity hook or emoji", False))
    if t[:1].isupper() or t[:1].isdigit():
        score += 10; checks.append(("Strong opening", True))
    caps_ratio = sum(1 for c in t if c.isupper()) / max(1, len(t.replace(" ", "")))
    if caps_ratio < 0.35:
        score += 10; checks.append(("Not over-capitalized", True))
    else:
        checks.append(("Too many CAPS — reduces trust", False))
    if "[" in t or "(" in t:
        score += 10; checks.append(("Bracket tag (e.g. [Tutorial]) adds CTR", True))
    score = min(100, score)
    grade = ("A 🔥" if score >= 80 else "B 👍" if score >= 60 else
             "C 📈" if score >= 40 else "D ✏️")
    return {"score": score, "grade": grade, "checks": checks, "length": n}


def seo_tags(title: str, description: str) -> list[str]:
    text = f"{title} {description}".lower()
    words = re.findall(r"[a-z0-9]{3,}", text)
    stop = set("the and for you your this that with from how what why are was were "
               "will can have has not but all any out get got new one two our their".split())
    freq = {}
    for w in words:
        if w in stop:
            continue
        freq[w] = freq.get(w, 0) + 1
    ranked = sorted(freq, key=lambda w: (-freq[w], w))[:12]
    # single words -> short phrases
    tags = []
    for w in ranked:
        tag = w.replace(" ", "")
        if tag not in tags:
            tags.append(tag)
    boosters = ["shorts", "viral", "trending", "howto", "tutorial", "2026",
                "tips", "beginner guide"]
    for b in boosters:
        if b not in tags and len(tags) < 20:
            tags.append(b)
    return tags[:20]


BEST_UPLOAD = {
    "youtube": "Fri–Sun, 2–4 PM IST (weekend watch peaks); Shorts: 12 PM & 8 PM",
    "instagram": "11 AM–1 PM & 7–9 PM IST",
    "facebook": "1–4 PM IST weekdays",
    "threads": "9–11 AM & 8–10 PM IST",
}

MONETIZATION = [
    {"task": "Post Shorts weekly — Shorts Fund eligibility & watch hours", "why": "Consistent shorts bring subs + views fast"},
    {"task": "Use end-screen + 'Subscribe' CTA in first 10 seconds", "why": "Sub conversion rate ↑"},
    {"task": "Pin a comment asking viewers to subscribe", "why": "1 free CTA per video"},
    {"task": "Cross-post: same video as Reels/Shorts/Moj/ShareChat", "why": "Multi-platform growth, zero extra cost"},
    {"task": "Upload 3+ times/week to trigger algorithm momentum", "why": "Consistency is the #1 ranking signal"},
    {"task": "SEO title with keyword in first 40 chars", "why": "YouTube search discovery"},
    {"task": "Add chapters & a 200-word description with keywords", "why": "More indexable text → suggested videos"},
    {"task": "Thumbnail: big face + 3-word text + high contrast", "why": "CTR is 80% thumbnail"},
    {"task": "Monetization targets: 1,000 subs + 4,000 watch hrs (long) OR 10M Shorts views/90 days", "why": "YPP threshold"},
    {"task": "Reply to every comment in the first hour", "why": "Early engagement spike boosts reach"},
]


def growth_report(title: str, description: str) -> dict:
    ts = title_score(title)
    tags = seo_tags(title, description)
    tips = []
    if ts["score"] < 70:
        tips.append("Rewrite title to hit 70+ score using the checklist 👇")
    tips += [
        "First 30 seconds: promise the value clearly (hook)",
        "Say the keyword out loud in the video (captions get indexed)",
        "Use #shorts for vertical videos under 60s",
    ]
    return {
        "title_score": ts,
        "seo_tags": tags,
        "best_upload_times": BEST_UPLOAD,
        "monetization_checklist": MONETIZATION,
        "growth_tips": tips,
    }
