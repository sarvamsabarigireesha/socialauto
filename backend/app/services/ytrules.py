"""YouTube packaging rules — SocialAuto integration (backend service).

Pure Python port of the rules used by the YT Package tab (frontend/yt-rules.js).
No DB, no network: safe to call from the publish engine before a YouTube post goes out.

Wire-up (2 lines):
  from app.services import ytrules          # anywhere: engine.py, routers/posts.py
  report = ytrules.analyze(title, description, tags, fmt="youtube")
"""
import re
from datetime import date, timedelta

HASHTAG = re.compile(r"#[\w\-]+", re.UNICODE)
TELUGU = re.compile(r"[\u0c00-\u0c7f]")
DUMP_HDR = re.compile(
    r"(?:SEO|Long[- ]?Tail|🔎|🔔\s*Subscribe\s*CTA|#️⃣).{0,18}(?:Keywords?|Hashtags?|CTA)|\bKeywords?\s*:?\s*$",
    re.IGNORECASE,
)
GENERIC_TAGS = re.compile(r"^(?:shorts?|viral|trending|yt|new|video|latest|hot|status|\d{4})$", re.IGNORECASE)
BAIT = re.compile(r"if you are a true|press the bell|comment\s*[\"'“][^\"'”]{2,40}[\"'”]\s*(?:if|to)", re.IGNORECASE)
SEVA = re.compile(r"annadanam|\bseva\b|donation|donate|food distribution", re.IGNORECASE)
OFFICIAL_NOTE = re.compile(r"official|అధికారిక|Devaswom|తిరుమల", re.IGNORECASE)
DONATION_LINE = re.compile(r"డొనేషన్స్\s*తీసుకోం|(?:don't|do\s+not|never|we\s+don't)\s+collect|not\s+collect\s+donation", re.IGNORECASE)
BHAKTI = re.compile(r"sabarimala|శబరిమల|ఐయ్యప్ప|అయ్యప్ప|ayyappa", re.IGNORECASE)
CHAPTER_TS = re.compile(r"^\s*(?:0|[1-9]\d?):[0-5]\d\s*\S", re.MULTILINE)

WEIGHT = {"err": 14, "warn": 8, "info": 3}

VIRAL_CHECKS = [
    "Season/event window lo unnaya (Nov 16 – Jan 20 = peak)",
    "Topic demand proof (10K+ views similar video exists)",
    "Title lo Telugu promise + English search term rendu",
    "Thumbnail 2 variants → Test & Compare ON",
    "First 15s lo darshan/result kanipisthunda",
    "Nee voice narration unda (reused-content risk clear)",
    "8+ min → chapters 0:00 nunchi 3+",
    "End screen + playlist link → next video sell",
    "Pinned comment lo specific prashnam",
    "Publish ki 2 ghantalu comments ki reply free na",
    "Auto-dubbing (Malayalam/Hindi/Tamil) ON",
    "Shorts → long-form funnel (tease + link) unda",
]

MILESTONES = [
    ("script+ideas", 10, "Script + 5 hook variants + thumbnail 2 concepts lock"),
    ("shoot", 7, "Shoot/bank footage — 2 intro versions record chey"),
    ("teaser", 4, "Teaser Short + community countdown post"),
    ("pre", 2, "Long-form #1 publish (search demand starts)"),
    ("day", 0, "EVENT DAY — live/premiere + Short #2 (2h comment sprint)"),
    ("recap", -1, "Same/next-day recap + photo post (velocity tail)"),
    ("tail", 3, "Evergreen 'what happened' — search tail"),
]


def _cplen(s):
    return len(s or "")


def _is_kw_line(line):
    s = (line or "").strip()
    if not s or TELUGU.search(s):
        return False
    if re.search(r"[.!?]|:", s):
        return False
    return len(s.split()) <= 7 and _cplen(s) <= 44


def analyze(title="", description="", tags="", fmt="short"):
    """Return {score, grade, issues[], counts} — issues: list of dicts."""
    t = (title or "").strip()
    d = description or ""
    g = tags or ""
    issues = []

    def add(sev, code, head, detail=""):
        issues.append({"sev": sev, "code": code, "head": head, "detail": detail})

    if not t:
        add("err", "title_empty", "Title khali", "Okka line promise rayandi.")
    th = HASHTAG.findall(t)
    if th:
        add("warn", "title_hashtag", "Title lo %d hashtags" % len(th), "Tags title nunchi tgeseyi — CTR drop.")
    if re.search(r"whatsapp\s*status", t, re.I):
        add("err", "title_status", '"WhatsApp Status" title lo undi', "Repost channel ga kanipisthundi.")
    if re.search(r"\b(?:trending|viral|must\s*watch|super\s*hit|breaking)\b", t, re.I):
        add("warn", "title_bait", "Bait words (trending/viral)", "Reach ki labam ledu.")
    if re.match(r"^\s*\d{1,2}\s*[/.\-]\s*\d{1,2}", t):
        add("warn", "title_date_first", "Date title start lo undi", "Benefit mundu, date chivarilo.")
    if _cplen(t) > 60:
        add("info", "title_long", "Title %d chars" % _cplen(t), "Mobile lo trim — first 55 chars lo promise.")
    if t and not TELUGU.search(t):
        add("warn", "title_no_telugu", "Title lo Telugu ledu", "Audience Telugu-first ga search chesthundi.")
    if t and not re.search(r"\d|[?]|అసలు|ఎందుకు|రహస్యం|నియమాలు|షెడ్యూల్|time|date|how|why|what", t, re.I):
        add("info", "title_flat", "Title lo number/question/curiosity ledu", "Hook formulas chudandi.")

    if not d.strip():
        add("warn", "desc_empty", "Description khali", "First 2 lines = search snippet.")
    dlines = re.split(r"\r?\n", d)
    dump_hdr = sum(1 for l in dlines if DUMP_HDR.search(l.strip()))
    comma_runs = sum(1 for l in dlines if l.count(",") >= 5 and not TELUGU.search(l))
    best = cur = 0
    for l in dlines:
        if _is_kw_line(l):
            cur += 1
            best = max(best, cur)
        else:
            cur = 0
    if dump_hdr or comma_runs or best >= 6:
        add("err", "kw_dump",
            "Keyword dump undi (%d headers, %d comma lists, %d-line run)" % (dump_hdr, comma_runs, best),
            "Ranking ki vaadaru; spam ga flag avvakuddi. Delete cheyandi.")
    dh = HASHTAG.findall(d)
    if len(dh) > 3:
        add("warn", "hash_many", "Description lo %d hashtags" % len(dh), "Max 3 — %d tgeseyi." % (len(dh) - 3))
    duph = [x for i, x in enumerate(dh) if x in dh[:i]]
    if duph:
        add("warn", "hash_dup", "Duplicate hashtags: %s" % ", ".join(sorted(set(duph))), "Deduplicate.")
    if sum(1 for l in dlines if l.strip()) > 40:
        add("warn", "desc_long", "Description pedda", "12–15 lines chalu.")
    if d and not TELUGU.search(d):
        add("warn", "desc_no_telugu", "Description lo Telugu ledu", "Telugu-first rayandi.")
    if BAIT.search(d):
        add("warn", "bait", "Engagement-bait phrasing", "Generic 'comment cheyandi' badulu specific prashnam.")
    if SEVA.search(d) and not DONATION_LINE.search(d):
        add("warn", "no_donation_line", 'Seva video — "మేము డొనేషన్స్ తీసుకోం" line ledu',
            "Trust + safety: rendu lines add cheyandi.")
    if BHAKTI.search(d) and not OFFICIAL_NOTE.search(d):
        add("info", "no_official_note", '"అధికారిక ఆలయ చానల్ కాదు" note ledu', "Impersonation complaint risk thaggisthundi.")
    if fmt in ("long", "live", "youtube_long"):
        if not re.search(r"^\s*0:00\s*\S", d, re.M):
            add("warn", "no_chapters", "Chapters ledu (0:00 nunchi)", "3+ timestamps, gaps 10s+.")
        elif len(CHAPTER_TS.findall(d)) < 3:
            add("info", "few_chapters", "Chapters taggaga unnayi", "5–8 best.")
        if not re.search(r"https?://|playlist", d, re.I):
            add("info", "no_link", "Playlist/next-video link ledu", "Session signal ki pettandi.")

    tag_list = [x.strip() for x in g.split(",") if x.strip()]
    tag_len = len(", ".join(tag_list))
    if tag_list and tag_len > 500:
        add("err", "tags_len", "Tags total %d chars (>500)" % tag_len, "Studio limit 500 — 12 ki teeyi.")
    if len(tag_list) > 12:
        add("warn", "tags_many", "%d tags" % len(tag_list), "8–12 best.")
    gen = [x for x in tag_list if GENERIC_TAGS.match(x)]
    if gen:
        add("warn", "tags_generic", "Generic tags: %s" % ", ".join(gen), "Ivi labam ichche tags kaadu.")
    if len({x.lower() for x in tag_list}) != len(tag_list):
        add("info", "tags_dup", "Duplicate tags", "Dedupe.")
    if tag_list and not any(re.search(r"sarvam\s*sabari", x, re.I) for x in tag_list):
        add("info", "tags_brand", "Brand tag ledu", '"sarvam sabarigireesha" add cheyandi.')

    penalty = sum(WEIGHT.get(i["sev"], 0) for i in issues)
    score = max(0, 100 - penalty)
    grade = "ready" if score >= 85 else ("minor" if score >= 70 else "fix")
    return {
        "score": score, "grade": grade, "issues": issues,
        "hashtags": len(dh), "tagCount": len(tag_list), "tagChars": tag_len,
        "titleChars": _cplen(t), "preview": re.sub(r"\s+", " ", d.strip())[:125],
    }


def auto_clean(title="", description="", tags=""):
    """Strip keyword dumps, cap hashtags at 3, remove generic tags, move leading date to end."""
    t = re.sub(HASHTAG, "", title or "")
    t = re.sub(r"\s{2,}", " ", t).strip().rstrip("|-–—•·:,").strip()
    m = re.match(r"^(\d{1,2}\s*[/.\-]\s*\d{1,2}(?:\s*[/.\-]\s*\d{2,4})?)\s*", t)
    if m:
        t = "%s | %s" % (t[m.end():].strip(), m.group(1).replace(" ", ""))
    out, skip = [], False
    for line in re.split(r"\r?\n", (description or "").replace("\r", "")):
        s = line.strip()
        if DUMP_HDR.search(s):
            skip = True
            continue
        if skip:
            if s == "":
                skip = False
            continue
        if s.count(",") >= 5 and not TELUGU.search(s):
            continue
        out.append(line)
    keep, j = [], 0
    while j < len(out):
        if _is_kw_line(out[j]):
            k = j
            while k < len(out) and _is_kw_line(out[k]):
                k += 1
            if k - j >= 5:
                j = k
                continue
        keep.append(out[j])
        j += 1
    seen, ordered = set(), []
    for x in HASHTAG.findall(description or ""):
        if x not in seen:
            seen.add(x)
            ordered.append(x)
    body = "\n".join(re.sub(HASHTAG, "", l) for l in keep)
    body = re.sub(r"[ \t]{2,}", " ", re.sub(r"\n{3,}", "\n\n", body)).strip().rstrip("|—–-:,").strip()
    if ordered[:3]:
        body = (body + "\n\n" + " ".join(ordered[:3])).strip()
    tl = []
    for x in (tags or "").split(","):
        x = x.strip().lower()
        if x and not GENERIC_TAGS.match(x) and x not in tl:
            tl.append(x)
    return {"title": t, "description": body, "tags": ", ".join(tl[:12]),
            "removedLines": len(re.split(r"\r?\n", description or "")) - len(keep),
            "keptHashtags": ordered[:3]}


def viral_score(flags):
    flags = list(flags or [])
    on = [bool(flags[i]) if i < len(flags) else False for i in range(len(VIRAL_CHECKS))]
    n = sum(on)
    pct = round(100 * n / len(VIRAL_CHECKS))
    verdict = ("🚀 Viral window open — publish cheyi" if pct >= 85 else
               "🟡 Packaging ready, gaps meeku" if pct >= 60 else
               "🟠 Fix munde — reach waste avuthundi" if pct >= 35 else
               "🔴 Ippudu publish cheyaku")
    return {"count": n, "total": len(VIRAL_CHECKS), "pct": pct, "verdict": verdict,
            "missing": [VIRAL_CHECKS[i] for i, v in enumerate(on) if not v]}


def trend_plan(event_date, lead_days=(), today=None):
    """Backward-schedule a season/event push. event_date: date or 'YYYY-MM-DD'."""
    if isinstance(event_date, str):
        try:
            ev = date.fromisoformat(event_date)
        except ValueError:
            return {"error": "date format YYYY-MM-DD cheyandi"}
    else:
        ev = event_date
    today = today or date.today()
    rows = []
    for step, off, note in MILESTONES:
        d = ev - timedelta(days=off)
        rows.append({"step": step, "note": note, "date": d.isoformat(), "over": d < today})
    for n in lead_days:
        d = ev - timedelta(days=int(n))
        rows.append({"step": "lead-%s" % n, "note": "Pre-heat Short/poll: 'ee pandugu ki %s rojulu' — audience test" % n,
                     "date": d.isoformat(), "over": d < today})
    rows.sort(key=lambda r: r["date"])
    days_out = (ev - today).days
    return {"event": ev.isoformat(), "daysOut": days_out,
            "urgent": 0 <= days_out <= 10, "late": days_out < 0, "rows": rows}
