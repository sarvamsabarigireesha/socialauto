"""AI assistant for the composer.

Given a caption (+ optional uploaded media), suggests:
  - an improved caption (hook + structure + emojis)
  - hashtags (niche + reach mix)
  - SEO keywords (YouTube/Google discoverability)
  - compliance disclaimers (#ad / sponsored / affiliate / AI-content)

Works fully offline with rule-based heuristics. If GEMINI_API_KEY is set
(Google Gemini free tier), it upgrades to a real LLM — including vision
understanding of the uploaded image when its public URL is available.
"""
import base64
import json
import re

import httpx

from ..config import settings

STOPWORDS = set("""the a an and or but is are was were be been being for to of in on at with by from as
it this that these those i you we they he she your our their my me us them not no so if then than when
what which who whom whose how why all any both each few more most other some such only own same too very
can will just should now get got let lets like really very much also here there out up down over new""".split())

PROMO_WORDS = ("offer", "discount", "buy", "sale", "coupon", "code", "link in bio", "price",
               "order", "shop", "affiliate", "sponsor", "ad", "deal", "% off", "free", "dm to")
HEALTH_WORDS = ("health", "weight", "lose", "fitness", "supplement", "cure", "treatment", "protein")
FINANCE_WORDS = ("invest", "trading", "crypto", "profit", "earn", "returns", "money", "stock")

EMOJI_MAP = {
    "food": "🍛", "biryani": "🍛", "chai": "☕", "coffee": "☕", "recipe": "👨‍🍳",
    "sale": "🎉", "offer": "🎉", "discount": "💰", "video": "🎬", "new": "✨",
    "tips": "💡", "travel": "✈️", "fitness": "💪", "tech": "💻", "music": "🎵",
}


def _keywords(text: str, n: int = 8) -> list[str]:
    words = re.findall(r"[A-Za-z]{3,}", text.lower())
    freq: dict[str, int] = {}
    for w in words:
        if w in STOPWORDS:
            continue
        freq[w] = freq.get(w, 0) + 1
    ranked = sorted(freq.items(), key=lambda kv: (-kv[1], kv[0]))
    return [w for w, _ in ranked[:n]]


def _hashtags(caption: str, platforms: list[str]) -> list[str]:
    kws = _keywords(caption, 10)
    tags = [f"#{w.replace(' ', '')}" for w in kws]
    # niche/reach boosters
    boosters = ["#contentcreator", "#trending", "#viral", "#explore", "#fyp", "#smallbusiness"]
    if "youtube" in platforms:
        boosters = ["#shorts", "#youtube", "#videos", "#trending", "#subscribe", "#contentcreator"]
    if "linkedin" in platforms:
        boosters = ["#networking", "#growth", "#business", "#contentstrategy", "#personalbranding"]
    out = []
    for t in tags + boosters:
        if t not in out:
            out.append(t)
    return out[:15]


def _disclaimers(caption: str) -> list[dict]:
    t = caption.lower()
    out = []
    if any(w in t for w in PROMO_WORDS):
        out.append({"label": "#ad / sponsored", "text": "#ad #Sponsored",
                    "why": "Promotional keywords detected — FTC/ASCI compliance"})
        out.append({"label": "Affiliate disclosure",
                    "text": "Disclosure: links may be affiliate links. We may earn a small commission at no extra cost to you.",
                    "why": "Required when using affiliate/shopping links"})
    if any(w in t for w in HEALTH_WORDS):
        out.append({"label": "Health disclaimer",
                    "text": "Disclaimer: This content is for informational purposes only and is not medical advice. Consult a qualified professional.",
                    "why": "Health/wellness claims need a safety disclaimer"})
    if any(w in t for w in FINANCE_WORDS):
        out.append({"label": "Finance disclaimer",
                    "text": "Disclaimer: Not financial advice. Investments are subject to market risks; do your own research.",
                    "why": "Finance content needs a risk disclaimer"})
    out.append({"label": "AI-assisted content note",
                "text": "(Optional) Content assisted by AI.",
                "why": "Label AI-assisted creative per platform policies"})
    return out


def _rule_based(caption: str, platforms: list[str]) -> dict:
    kws = _keywords(caption)
    tags = _hashtags(caption, platforms)
    emoji = next((e for w, e in EMOJI_MAP.items() if w in caption.lower()), "🚀")
    improved = caption.strip()
    if improved and not improved.endswith(("!", "?", ".", ")", "👉")):
        improved += " 👇"
    hook = f"{emoji} {improved.splitlines()[0] if improved else 'Your hook line here'}"
    if len(improved.splitlines()) <= 1:
        improved = f"{hook}\n\n💡 {(' '.join(kws[:3]).title() if kws else 'Value line')} — save this post!\n\n{' '.join(tags[:8])}"
    best_times = {
        "instagram": "11 AM–1 PM & 7–9 PM IST (lunch/evening scroll peaks)",
        "facebook": "1–4 PM IST on weekdays",
        "youtube": "Fri–Sun, 2–4 PM IST (weekend watch time)",
        "x": "8–10 AM & 6–9 PM IST",
        "linkedin": "Tue–Thu, 9–11 AM IST",
    }
    return {
        "engine": "rules",
        "caption_suggestion": improved,
        "hashtags": tags,
        "keywords": [k.title() for k in kws],
        "disclaimers": _disclaimers(caption),
        "best_times": {p: best_times.get(p, "") for p in platforms} or best_times,
        "title_youtube": (caption.strip().splitlines()[0][:90] if caption else "") + (" #shorts" if "youtube" in platforms else ""),
    }


PROMPT = """You are a social-media growth assistant. Given a draft post (and optionally an image),
return STRICT JSON only, no markdown fences, with this exact shape:
{
  "caption_suggestion": "improved caption with a strong hook, emojis, line breaks; respect platform limits",
  "hashtags": ["#tag1", "#tag2", "... up to 15"],
  "keywords": ["SEO keyword phrases, 6-10, for YouTube/search discoverability"],
  "disclaimers": [{"label":"short label","text":"full disclaimer text","why":"when to use"}],
  "best_times": {"instagram":"...","youtube":"..."},
  "title_youtube": "click-worthy YouTube title under 100 chars if youtube is targeted, else empty string"
}
Target platforms: {platforms}.
Only include disclaimers that actually apply (promo/affiliate/health/finance/AI-content).
Draft caption:
{caption}
"""


async def _gemini(caption: str, media_url: str, platforms: list[str], public_base: str) -> dict | None:
    if not settings.GEMINI_API_KEY:
        return None
    url = (f"https://generativelanguage.googleapis.com/v1beta/models/"
           f"{settings.GEMINI_MODEL}:generateContent?key={settings.GEMINI_API_KEY}")
    prompt = (PROMPT
              .replace("{platforms}", ", ".join(platforms) or "instagram")
              .replace("{caption}", caption or "(no caption yet — describe the image)"))
    parts: list[dict] = [{"text": prompt}]
    # attach image if publicly fetchable
    img_url = media_url if media_url.startswith("http") else ""
    if not img_url and media_url.startswith("/media/") and public_base:
        img_url = public_base.rstrip("/") + media_url
    if img_url and not img_url.startswith("https://app."):
        try:
            async with httpx.AsyncClient(timeout=20) as c:
                r = await c.get(img_url)
                if r.status_code == 200 and "image" in r.headers.get("content-type", ""):
                    parts.append({"inline_data": {
                        "mime_type": r.headers["content-type"],
                        "data": base64.b64encode(r.content).decode()}})
        except Exception:
            pass
    try:
        async with httpx.AsyncClient(timeout=90) as c:
            r = await c.post(url, json={"contents": [{"parts": parts}]})
            r.raise_for_status()
            text = r.json()["candidates"][0]["content"]["parts"][0]["text"]
            text = re.sub(r"^```(json)?|```$", "", text.strip(), flags=re.M).strip()
            data = json.loads(text)
            data["engine"] = "gemini"
            return data
    except Exception:
        return None


async def suggest(caption: str, media_url: str, platforms: list[str], public_base: str = "") -> dict:
    llm = await _gemini(caption, media_url, platforms, public_base)
    if llm:
        # merge: guarantee all keys exist
        base = _rule_based(caption, platforms)
        for k in ("caption_suggestion", "hashtags", "keywords", "disclaimers", "best_times", "title_youtube"):
            base[k] = llm.get(k) or base[k]
        base["engine"] = "gemini"
        return base
    return _rule_based(caption, platforms)
