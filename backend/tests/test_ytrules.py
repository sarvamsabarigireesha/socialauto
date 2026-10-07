"""Tests for app.services.ytrules — the YT Package rules engine.

Run:  cd backend && python -m pytest tests/test_ytrules.py -q
Deps: none beyond stdlib (no fastapi needed for this file).

Fixtures below use the channel's REAL metadata (Sarvam Sabarigireesha), so a
regression here means a real publish would be mis-flagged.
"""
import os
import sys
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.services import ytrules  # noqa: E402

# Real "before" state: Annadanam Short with a Long-Tail keyword dump + 15 hashtags
DIRTY_TITLE = "100 Meals. One Mission | Annadanam | Sarvam Sabarigireesha"
DIRTY_DESC = """100 Meals. One Mission. One Small Step Towards Humanity. ❤️🙏

With the divine blessings of Lord Ayyappa Swamy, SARVAM SABARIGIREESHA completed our 2nd Annadanam / Food Drive.

#Annadanam #FoodDrive #FoodDistribution #AyyappaSwamy #SwamiyeSaranamAyyappa #Seva #Humanity #FeedTheHungry #FoodFor100 #AyyappaSeva #SarvamSabarigireesha #AnnadanamMahadanam #YouTubeShorts #Shorts #SevaToHumanity

Annadanam
Annadanam Mahadanam
Food Drive
Food Distribution
Food Donation
Feeding 100 People
Free Food Distribution
Long-Tail SEO Keywords:
Annadanam food distribution
Ayyappa Swamy Annadanam
Food seva for the needy"""

# Real "after" state the creator published on 7 Oct 2026 (should pass cleanly)
CLEAN_TITLE = "18 మెట్ల అసలు అర్థం 🙏 | Pathinettampadi in Telugu"
CLEAN_DESC = (
    "\"శరణం\" అంటే కేవలం శరణు కాదు — \"నా బాధ్యత నువ్వే\" అని అర్పణ. "
    "పదినెట్టాంబడి 18 మెట్ల వెనుక అర్థం ఇక్కడ 🙏\n"
    "స్వామియే శరణం అయ్యప్ప · శబరిమల భక్తుల కోసం రోజువారీ దర్శనం, వ్రతం నియమాలు, సేవ.\n\n"
    "#Pathinettampadi #Sabarimala #Ayyappa"
)


def codes(r):
    return {i["code"] for i in r["issues"]}


def test_dirty_channel_desc_is_caught():
    r = ytrules.analyze(DIRTY_TITLE, DIRTY_DESC, "annadanam, sabarimala, shorts, viral, trending", "short")
    assert "kw_dump" in codes(r)
    assert "hash_many" in codes(r)
    assert "tags_generic" in codes(r)
    assert r["grade"] == "fix" and r["score"] < 70


def test_clean_desc_passes_without_false_flags():
    r = ytrules.analyze(CLEAN_TITLE, CLEAN_DESC,
                        "sabarimala, ayyappa, pathinettampadi, sarvam sabarigireesha", "short")
    assert not [i for i in r["issues"] if i["sev"] == "err"]
    assert "kw_dump" not in codes(r)
    assert "hash_many" not in codes(r)
    assert r["score"] >= 85


def test_auto_clean_caps_hashtags_and_strips_dump():
    c = ytrules.auto_clean(DIRTY_TITLE, DIRTY_DESC, "annadanam, sabarimala, shorts, viral")
    assert "Long-Tail" not in c["description"]
    assert len(ytrules.HASHTAG.findall(c["description"])) == 3
    assert "viral" not in c["tags"] and "shorts" not in c["tags"]
    assert c["removedLines"] > 0
    # cleaning must not destroy the meaning
    assert "100 Meals" in c["description"] or "Annadanam" in c["description"]


def test_title_date_moves_to_end():
    c = ytrules.auto_clean("19/09/2026ఈ రోజు పదినెట్టాంబడి దగ్గర విజువల్స్ #ayyappa", "desc 🙏", "")
    assert c["title"].startswith("ఈ రోజు")
    assert c["title"].endswith("19/09/2026")
    assert "#ayyappa" not in c["title"]


def test_seva_videos_need_donation_line():
    without = ytrules.analyze("అయ్యప్ప సేవ: 100 మందికి భోజనం 🙏 | Annadanam",
                              "అన్నదానం సేవ — 100 మందికి భోజనం 🙏\n#Annadanam", "annadanam, ayyappa seva", "short")
    assert "no_donation_line" in codes(without)
    with_line = ytrules.analyze("అయ్యప్ప సేవ: 100 మందికి భోజనం 🙏 | Annadanam",
                                "అన్నదానం సేవ 🙏\n⚠️ మేము డొనేషన్స్ తీసుకోం. ఇది అధికారిక ఆలయ కార్యక్రమం కాదు.\n#Annadanam",
                                "annadanam, ayyappa seva, sarvam sabarigireesha", "short")
    assert "no_donation_line" not in codes(with_line)


def test_bait_and_bell_are_flagged():
    r = ytrules.analyze("Bappa thoughts 🤣🙏", "Press the BELL ICON now!\nComment \"Ganpati Bappa Morya\" if you are a true devotee", "", "short")
    assert "bait" in codes(r)


def test_long_form_requires_chapters():
    r = ytrules.analyze("మణికంఠ జన్మ రహస్యం 🙏", "అయ్యప్ప కథ పూర్తిగా 🙏\n#Ayyappa", "manikanta story telugu, sarvam sabarigireesha", "long")
    assert "no_chapters" in codes(r)


def test_tags_length_limit():
    long_tags = ", ".join("sabarimala topic %d" % i for i in range(40))
    r = ytrules.analyze("శబరిమల వ్రతం 🙏 | Vratham guide", "నియమాలు 🙏\n#Vratham", long_tags, "long")
    assert r["tagChars"] > 500
    assert "tags_len" in codes(r)


def test_viral_score_bands():
    assert ytrules.viral_score([True] * 12)["pct"] == 100
    assert "🚀" in ytrules.viral_score([True] * 12)["verdict"]
    zero = ytrules.viral_score([])
    assert zero["pct"] == 0 and len(zero["missing"]) == 12 and "🔴" in zero["verdict"]
    assert ytrules.viral_score([True] * 10)["pct"] == 83


def test_trend_plan_backs_up_from_event():
    p = ytrules.trend_plan("2026-11-16", [21, 14], today=date(2026, 10, 7))
    assert p["daysOut"] == 40 and not p["late"]
    dates = [r["date"] for r in p["rows"]]
    assert dates == sorted(dates)
    assert "2026-11-16" in dates                      # event day present
    assert "2026-11-09" in dates                      # shoot = event-7
    assert any(r["step"] == "lead-21" for r in p["rows"])
    assert all(not r["over"] for r in p["rows"])       # nothing in the past for a 40-day lead


def test_trend_plan_past_steps_and_bad_input():
    near = ytrules.trend_plan("2026-10-16", [], today=date(2026, 10, 7))
    assert any(r["over"] for r in near["rows"])        # T-10 prep already missed
    assert ytrules.trend_plan("2026-13-45").get("error")
    assert ytrules.trend_plan("not-a-date").get("error")
    assert ytrules.trend_plan("2026-01-01", [], today=date(2026, 10, 7))["late"]


def test_empty_inputs_do_not_crash():
    for r in (ytrules.analyze("", "", "", "short"), ytrules.auto_clean("", "", ""), ytrules.viral_score(None)):
        assert isinstance(r, dict)
