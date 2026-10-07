/* yt-rules.js — shared YouTube packaging rules for SocialAuto (frontend)
 *
 * Same ruleset as backend/app/services/ytrules.py — keep both in sync.
 * Load once in frontend/index.html:  <script src="./yt-rules.js"></script>
 *
 * Used by:
 *   • the YT Package tab (full UI)
 *   • the composer's existing "AI suggest" — call window.YtRules.analyze(...)
 *     so a scheduled YouTube post gets flagged BEFORE it hits the queue.
 */
(function (global) {
  'use strict';
  var HT = /#[\p{L}\p{N}_][\p{L}\p{N}_-]*/gu;
  var TEL = /[\u0C00-\u0C7F]/;
  var DUMP_HDR = /(?:SEO|Long[- ]?Tail|🔎|🔔\s*Subscribe\s*CTA|#️⃣)\s*.{0,18}(Keywords?|Hashtags?|CTA)|\bKeywords?\s*:$/i;
  var GENERIC = /^(?:shorts?|viral|trending|yt|new|video|latest|hot|status|2026|2027)$/i;
  var BAIT = /if you are a true|press the bell|comment\s*["'“][^"'”]{2,40}["'”]\s*(if|to)/i;
  var SEVA = /annadanam|\bseva\b|donation|donate|food distribution/i;
  var DONATION_LINE = /డొనేషన్స్\s*తీసుకోం|(?:don'?t|do\s+not|never)\s+collect|not\s+collect\s+donation/i;
  var OFFICIAL = /official|అధికారిక|Devaswom|తిరుమల/i;
  var BHAKTI = /sabarimala|శబరిమల|ఐయ్యప్ప|అయ్యప్ప|ayyappa/i;
  var WEIGHT = { err: 14, warn: 8, info: 3 };

  function tel(s) { return TEL.test(s || ''); }
  function cp(s) { return Array.from(s || '').length; }
  function uniq(a) { var o = [], m = {}; a.forEach(function (x) { if (!m[x]) { m[x] = 1; o.push(x); } }); return o; }
  function kwLine(l) {
    var s = (l || '').trim();
    if (!s || tel(s)) return false;
    if (/[.!?]|:/.test(s)) return false;
    return s.split(/\s+/).length <= 7 && cp(s) <= 44;
  }

  function analyze(o) {
    o = o || {};
    var t = (o.title || '').trim(), d = o.description != null ? o.description : (o.desc || ''), g = o.tags || '', type = o.format || o.type || 'short';
    var iss = [];
    function add(sev, code, head, detail) { iss.push({ sev: sev, code: code, head: head, detail: detail || '' }); }

    if (!t) add('err', 'title_empty', 'Title khali', 'Okka line promise rayandi.');
    var th = t.match(HT) || [];
    if (th.length) add('warn', 'title_hashtag', 'Title lo ' + th.length + ' hashtags', 'Title nunchi tgeseyi.');
    if (/whatsapp\s*status/i.test(t)) add('err', 'title_status', '"WhatsApp Status" title lo undi', 'Repost ga kanipisthundi.');
    if (/\b(?:trending|viral|must\s*watch|super\s*hit|breaking)\b/i.test(t)) add('warn', 'title_bait', 'Bait words', 'Labam ledu.');
    if (/^\s*\d{1,2}\s*[/.\-]\s*\d{1,2}/.test(t)) add('warn', 'title_date_first', 'Date title start lo undi', 'Benefit mundu pettandi.');
    if (cp(t) > 60) add('info', 'title_long', 'Title ' + cp(t) + ' chars', 'First 55 chars lo promise.');
    if (t && !tel(t)) add('warn', 'title_no_telugu', 'Title lo Telugu ledu', 'Telugu-first search chesthundi.');
    if (t && !/\d|[?]|అసలు|ఎందుకు|రహస్యం|నియమాలు|షెడ్యూల్|time|date|how|why|what/i.test(t)) add('info', 'title_flat', 'Title lo number/question/curiosity ledu', 'Hook formulas chudandi.');

    if (!String(d).trim()) add('warn', 'desc_empty', 'Description khali', 'First 2 lines = snippet.');
    var dl = String(d).split(/\r?\n/);
    var hdr = dl.filter(function (l) { return DUMP_HDR.test(l.trim()); }).length;
    var comma = dl.filter(function (l) { return (l.match(/,/g) || []).length >= 5 && !tel(l); }).length;
    var best = 0, cur = 0;
    dl.forEach(function (l) { if (kwLine(l)) { cur++; if (cur > best) best = cur; } else cur = 0; });
    if (hdr || comma || best >= 6) add('err', 'kw_dump', 'Keyword dump undi (' + hdr + ' headers, ' + comma + ' comma lists, ' + best + '-line run)', 'Delete cheyandi.');
    var dh = String(d).match(HT) || [];
    if (dh.length > 3) add('warn', 'hash_many', 'Description lo ' + dh.length + ' hashtags', 'Max 3.');
    if (dh.filter(function (x, i) { return dh.indexOf(x) !== i; }).length) add('warn', 'hash_dup', 'Duplicate hashtags', 'Dedupe.');
    if (dl.filter(function (l) { return l.trim(); }).length > 40) add('warn', 'desc_long', 'Description pedda', '12–15 lines chalu.');
    if (String(d) && !tel(String(d))) add('warn', 'desc_no_telugu', 'Description lo Telugu ledu', 'Telugu-first rayandi.');
    if (BAIT.test(d)) add('warn', 'bait', 'Engagement-bait phrasing', 'Specific prashnam adagandi.');
    if (SEVA.test(d) && !DONATION_LINE.test(d)) add('warn', 'no_donation_line', 'Seva video — "డొనేషన్స్ తీసుకోం" line ledu', 'Trust + safety lines add cheyandi.');
    if (BHAKTI.test(d) && !OFFICIAL.test(d)) add('info', 'no_official_note', '"అధికారిక చానల్ కాదు" note ledu', 'Complaint risk thaggisthundi.');
    if (type === 'long' || type === 'live' || type === 'youtube_long') {
      if (!/^\s*0:00\s*\S/m.test(d)) add('warn', 'no_chapters', 'Chapters ledu', '0:00 nunchi 3+ timestamps.');
      else if (((String(d).match(/^\s*(?:0|[1-9]\d?):[0-5]\d\s*\S/gm)) || []).length < 3) add('info', 'few_chapters', 'Chapters taggaga unnayi', '5–8 best.');
      if (!/https?:\/\/|playlist/i.test(d)) add('info', 'no_link', 'Playlist link ledu', 'Session signal.');
    }
    var tl = g.split(',').map(function (x) { return x.trim(); }).filter(Boolean);
    var len = tl.join(', ').length;
    if (tl.length && len > 500) add('err', 'tags_len', 'Tags ' + len + ' chars (>500)', '12 ki teeyi.');
    if (tl.length > 12) add('warn', 'tags_many', tl.length + ' tags', '8–12 best.');
    var gen = tl.filter(function (x) { return GENERIC.test(x); });
    if (gen.length) add('warn', 'tags_generic', 'Generic tags: ' + gen.join(', '), 'Remove.');
    if (uniq(tl.map(function (x) { return x.toLowerCase(); })).length !== tl.length) add('info', 'tags_dup', 'Duplicate tags', 'Dedupe.');
    if (tl.length && !tl.some(function (x) { return /sarvam\s*sabari/i.test(x); })) add('info', 'tags_brand', 'Brand tag ledu', '"sarvam sabarigireesha" add cheyandi.');

    var pen = iss.reduce(function (a, i) { return a + (WEIGHT[i.sev] || 0); }, 0);
    var score = Math.max(0, 100 - pen);
    return { score: score, grade: score >= 85 ? 'ready' : score >= 70 ? 'minor' : 'fix', issues: iss,
      hashtags: dh.length, tagCount: tl.length, tagChars: len, titleChars: cp(t),
      preview: String(d).trim().replace(/\s+/g, ' ').slice(0, 125) };
  }

  function autoClean(o) {
    o = o || {};
    var t = (o.title || '').replace(HT, '').replace(/\s{2,}/g, ' ').replace(/[|\-–—•·:,]\s*$/, '').trim();
    var lead = t.match(/^(\d{1,2}\s*[\/.\-]\s*\d{1,2}(?:\s*[\/.\-]\s*\d{2,4})?)\s*/);
    if (lead) { t = t.slice(lead[1].length).trim() + ' | ' + lead[1].replace(/\s/g, ''); }
    var lines = String(o.description != null ? o.description : (o.desc || '')).replace(/\r/g, '').split('\n');
    var out = [], skip = false;
    lines.forEach(function (line) {
      var s = line.trim();
      if (DUMP_HDR.test(s)) { skip = true; return; }
      if (skip) { if (s === '') skip = false; return; }
      if ((s.match(/,/g) || []).length >= 5 && !tel(s)) return;
      out.push(line);
    });
    var keep = [], j = 0;
    while (j < out.length) {
      if (kwLine(out[j])) { var k = j; while (k < out.length && kwLine(out[k])) k++; if (k - j >= 5) { j = k; continue; } }
      keep.push(out[j]); j++;
    }
    var all = uniq(String(o.description != null ? o.description : (o.desc || '')).match(HT) || []).slice(0, 3);
    var body = keep.map(function (l) { return l.replace(HT, ''); }).join('\n')
      .replace(/[ \t]{2,}/g, ' ').replace(/\n{3,}/g, '\n\n').trim().replace(/[|—–\-:,]\s*$/, '').trim();
    if (all.length) body += '\n\n' + all.join(' ');
    var tg = uniq((o.tags || '').split(',').map(function (x) { return x.trim(); }).filter(Boolean)
      .filter(function (x) { return !GENERIC.test(x); }).map(function (x) { return x.toLowerCase(); })).slice(0, 12);
    return { title: t, description: body, tags: tg.join(', '),
      removedLines: lines.length - keep.length, keptHashtags: all };
  }

  var MILE = [['script+ideas', 10], ['shoot', 7], ['teaser', 4], ['pre', 2], ['day', 0], ['recap', -1], ['tail', 3]];
  function ymd(d) { return d.getFullYear() + '-' + String(d.getMonth() + 1).padStart(2, '0') + '-' + String(d.getDate()).padStart(2, '0'); }
  function trendPlan(eventISO, lead) {
    if (!/^\d{4}-\d{2}-\d{2}$/.test(eventISO || '')) return { error: 'Date format: YYYY-MM-DD' };
    var ev = new Date(eventISO + 'T12:00:00'), today = new Date(); today.setHours(12, 0, 0, 0);
    if (isNaN(ev)) return { error: 'Date valid kaadu' };
    var rows = MILE.map(function (m) {
      var d = new Date(ev.getTime()); d.setDate(d.getDate() - m[1]);
      return { step: m[0], date: ymd(d), over: d < today };
    });
    (lead || []).forEach(function (n) {
      var d = new Date(ev.getTime() - (+n || 0) * 864e5);
      rows.push({ step: 'lead-' + n, date: ymd(d), over: d < new Date(today.getTime()) });
    });
    rows.sort(function (a, b) { return a.date < b.date ? -1 : 1; });
    var daysOut = Math.round((ev - today) / 864e5);
    return { event: ymd(ev), daysOut: daysOut, urgent: daysOut >= 0 && daysOut <= 10, late: daysOut < 0, rows: rows };
  }

  var CHECKS = [
    'Season/event window lo unnaya', 'Topic demand proof unda', 'Title lo Telugu + English search term',
    'Thumbnail 2 variants + Test & Compare', 'First 15s lo payoff', 'Nee voice narration unda',
    'Chapters 0:00 nunchi 3+ (8min+)', 'End screen + playlist link', 'Pinned comment question',
    '2h comment sprint free na', 'Auto-dubbing ON', 'Shorts→long funnel unda'
  ];
  function viralScore(flags) {
    flags = flags || [];
    var n = CHECKS.filter(function (_, i) { return !!flags[i]; }).length;
    var pct = Math.round(n / CHECKS.length * 100);
    return { count: n, total: CHECKS.length, pct: pct,
      verdict: pct >= 85 ? '🚀 publish cheyi' : pct >= 60 ? '🟡 gaps unnayi' : pct >= 35 ? '🟠 fix munde' : '🔴 itsina publish cheyaku',
      missing: CHECKS.filter(function (c, i) { return !flags[i]; }) };
  }

  var api = { analyze: analyze, autoClean: autoClean, trendPlan: trendPlan, viralScore: viralScore, CHECKS: CHECKS };
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  global.YtRules = api;
})(typeof window !== 'undefined' ? window : globalThis);
