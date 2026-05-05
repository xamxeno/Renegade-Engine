"""
Renegade Records — Content Creator Discovery Engine v3
Targets: aesthetic lifestyle/fitness/fashion/travel influencers on YouTube with IG presence
Requirements: active, English-speaking, Western market, visual/aesthetic content, solo creators
Source: YouTube channel search -> About page API
Run: python content_discovery.py [--no-prompt]
"""
import sys, subprocess
for _pkg in ['requests', 'python-dotenv']:
    try: __import__(_pkg.replace('-', '_').split('.')[0])
    except ImportError: subprocess.check_call([sys.executable, '-m', 'pip', 'install', _pkg], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

import os, json, time, re, requests, io, random, urllib.parse
from datetime import datetime, timezone, timedelta
from dotenv import load_dotenv

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

load_dotenv()

CLAUDE_API_KEY = os.getenv("CLAUDE_API_KEY", "")
SUPABASE_URL   = os.getenv("SUPABASE_URL", "")
SUPABASE_KEY   = os.getenv("SUPABASE_KEY", "")

TARGET_LEADS        = 100
MIN_SUBS            = 5_000
MAX_SUBS            = 500_000
MIN_SCORE           = 65
MAX_INACTIVE_MONTHS = 6    # Skip channels with no upload in the last 6 months

_YT_KEY = "AIzaSyAO_FJ2SlqU8Q4STEHLGCilw_Y9_11qcW8"

_BROWSER_HEADERS = {
    "User-Agent":      "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept":          "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}

# Hard block — any match disqualifies the channel immediately
BLOCKED_REGIONS = [
    # South Asia
    "india","indian","pakistan","pakistani","hindi","bollywood","desi","bangladesh","bengali",
    "urdu","karachi","lahore","islamabad","mumbai","delhi","kolkata","bangalore","hyderabad",
    "punjabi","rajasthan","kerala","tamil","telugu","marathi","gujarati","nepali","sri lanka",
    # Africa
    "kenya","ethiopia","tanzania","nigeria","ghana","lagos","nairobi","johannesburg","africa","african",
    "cameroon","uganda","rwanda","zimbabwe","zambia","south africa",
    # Southeast Asia
    "indonesia","indonesian","philippines","filipino","malaysia","malay","thai","thailand",
    "myanmar","vietnam","vietnamese","singapore","cambodia",
    # East Asia
    "japan","japanese","korea","korean","china","chinese","taiwan","hong kong",
    # Latin America
    "mexico","mexican","colombia","colombian","brazil","brazilian","spanish","espanol","español",
    "venezuela","argentina","peru","chile","dominican",
    # Other
    "arab","arabic","turkish","turkey","russia","russian","hindi",
]

# Hard block on content type — these channels won't need video editors
BLOCKED_CONTENT = [
    # Family / kids
    "family vlog","family channel","mom vlog","dad vlog","kids channel","children",
    "parenting","our family","baby","pregnancy","homeschool","couple vlog","married life",
    "husband and wife","wife and husband","family of","our kids","mum vlog",
    # Religious / political
    "islamic","muslim","christian","church","sermon","gospel","bible","quran","pastor",
    "politics","political","republican","democrat","news channel","breaking news",
    # Low-quality / irrelevant
    "gaming","gamer","minecraft","fortnite","roblox","anime","cartoon","compilation",
    "funny videos","prank","reaction video","reacting to","asmr","mukbang",
    "cooking channel","recipe","food vlog","kitchen","baking","chef",
    "tech review","unboxing","gadget","software tutorial","programming","coding",
    "real estate","mortgage","insurance","finance only","stock market","crypto only",
    "music producer","beats","rap music","hip hop music","music channel",
    "car review","automotive","vehicle","mechanic",
]

# At least one of these should appear for the channel to be relevant
RELEVANCE_SIGNALS = [
    "lifestyle","aesthetic","fashion","style","outfit","ootd","beauty","skincare","makeup",
    "fitness","gym","workout","wellness","health","mindset","motivation","self improvement",
    "travel","adventure","vlog","creator","influencer","content","reels","instagram",
    "entrepreneur","brand","business","personal brand","model","photographer",
    "digital nomad","luxury","hustle","grind","coach","speaker",
]

_BAD_IG_PATHS = {
    'p','explore','stories','reels','accounts','login','signup','direct','tv',
    'about','press','api','static','legal','help','location','hashtag','tags',
    'web','ar','events','music','create','directory','challenge','share','reel',
}

# Targeted searches for aesthetic/active influencers in Western markets
YT_SEARCHES = [
    # Lifestyle / aesthetic
    "aesthetic lifestyle vlog USA 2024 2025",
    "lifestyle influencer USA youtube instagram",
    "aesthetic daily vlog girl USA",
    "luxury lifestyle vlog USA influencer",
    "aesthetic vlog UK lifestyle creator",
    # Fitness / wellness
    "fitness influencer USA youtube channel",
    "gym lifestyle vlog USA aesthetic",
    "wellness lifestyle creator USA youtube",
    "fitness content creator UK instagram youtube",
    "health and fitness influencer USA aesthetic",
    # Fashion / beauty
    "fashion content creator USA youtube instagram",
    "style influencer USA youtube aesthetic",
    "fashion vlog USA creator 2024 2025",
    "beauty influencer USA youtube channel",
    "fashion lifestyle creator UK australia",
    # Travel / adventure
    "travel influencer USA youtube channel",
    "solo travel vlog aesthetic USA",
    "travel lifestyle creator UK aesthetic",
    "digital nomad lifestyle vlog creator",
    "adventure travel vlog USA influencer",
    # Entrepreneur / personal brand
    "entrepreneur lifestyle vlog USA youtube",
    "personal brand creator USA youtube instagram",
    "entrepreneur influencer USA aesthetic youtube",
    "business lifestyle creator USA youtube",
    # Canada / UK / Australia / UAE
    "lifestyle influencer Canada youtube instagram",
    "aesthetic vlog creator Australia instagram",
    "content creator UAE Dubai lifestyle",
    "lifestyle influencer UK aesthetic youtube",
    # Model / creator crossover
    "model content creator USA youtube instagram",
    "instagram influencer youtube channel USA aesthetic",
]


# ── YouTube discovery ─────────────────────────────────────────────────────────

def _parse_number(s):
    s = str(s).replace(",", "").strip().lower()
    try:
        if "million" in s:
            return int(float(s.replace("million", "").strip()) * 1_000_000)
        if "thousand" in s:
            return int(float(s.replace("thousand", "").strip()) * 1_000)
        if s.endswith("m"):
            return int(float(s[:-1]) * 1_000_000)
        if s.endswith("k"):
            return int(float(s[:-1]) * 1_000)
        return int(float(s))
    except:
        return 0


def yt_search_channels(keyword, max_results=20):
    try:
        url = f"https://www.youtube.com/results?search_query={urllib.parse.quote(keyword)}&sp=EgIQAg%253D%253D"
        r = requests.get(url, headers=_BROWSER_HEADERS, timeout=15)
        channel_ids = re.findall(r'"channelId":"([^"]+)"', r.text)
        seen, result = set(), []
        for cid in channel_ids:
            if cid not in seen:
                seen.add(cid)
                result.append(cid)
        return result[:max_results]
    except Exception as e:
        print(f"  [YT search] {e}")
        return []


def get_channel_about(channel_id):
    try:
        payload = {
            "context": {"client": {"clientName": "WEB", "clientVersion": "2.20240101.00.00", "hl": "en", "gl": "US"}},
            "browseId": channel_id,
            "params":   "EgVhYm91dA==",
        }
        r = requests.post(
            "https://www.youtube.com/youtubei/v1/browse",
            params={"key": _YT_KEY},
            json=payload,
            headers={**_BROWSER_HEADERS, "Content-Type": "application/json", "Origin": "https://www.youtube.com"},
            timeout=15,
        )
        data     = r.json()
        data_str = json.dumps(data)

        # Channel name
        name = ""
        try:
            name = data["header"]["pageHeaderRenderer"]["pageTitle"]
        except (KeyError, TypeError):
            m = re.search(r'"pageTitle":"([^"]{2,80})"', data_str)
            if m: name = m.group(1)

        # Subscriber count
        subs_count = 0
        subs_str   = ""
        subs_m = re.search(r'"accessibilityLabel":\s*"([^"]*subscribers)"', data_str)
        if subs_m:
            subs_str   = subs_m.group(1)
            raw        = subs_str.replace(" subscribers", "").replace(",", "").strip()
            subs_count = _parse_number(raw)

        # @handle
        handle_m  = re.search(r'"channelHandleText":\{"simpleText":"([^"]+)"', data_str)
        yt_handle = handle_m.group(1) if handle_m else None

        # Description
        desc_m = re.search(r'"description":\{"simpleText":"([^"]{5,500})"', data_str)
        desc   = desc_m.group(1) if desc_m else ""

        # IG handles from YouTube outbound redirect URLs
        ig_handles = []
        for block in re.findall(r"youtube\.com/redirect[^\"]{0,600}", data_str):
            q_idx = block.find("q=")
            if q_idx == -1: continue
            q_val = block[q_idx + 2:]
            for ch in ["&", "\"", "\\"]:
                pos = q_val.find(ch)
                if pos != -1: q_val = q_val[:pos]
            decoded = urllib.parse.unquote(q_val)
            if "instagram.com" in decoded:
                ig_m = re.search(r"instagram\.com/([a-zA-Z0-9._]{2,30})", decoded)
                if ig_m:
                    h = ig_m.group(1).lower().rstrip(".")
                    if h not in _BAD_IG_PATHS:
                        ig_handles.append(h)

        return {
            "id":         channel_id,
            "name":       name,
            "yt_handle":  yt_handle,
            "subs_count": subs_count,
            "subs_str":   subs_str,
            "desc":       desc[:400],
            "ig":         list(dict.fromkeys(ig_handles)),
        }
    except Exception:
        return {"id": channel_id, "name": "", "yt_handle": None, "subs_count": 0, "subs_str": "", "desc": "", "ig": []}


def is_recently_active(channel_id, months=MAX_INACTIVE_MONTHS):
    """Return True if the channel uploaded at least once in the last `months` months."""
    try:
        url = f"https://www.youtube.com/feeds/videos.xml?channel_id={channel_id}"
        r = requests.get(url, headers=_BROWSER_HEADERS, timeout=10)
        if r.status_code != 200:
            return True  # Can't verify — give benefit of the doubt
        # Grab the first <published> date in the feed (most recent video)
        m = re.search(r"<published>([^<]+)</published>", r.text)
        if not m:
            return True  # No videos listed — new channel or private; keep for Claude to decide
        pub_str = m.group(1).strip()
        # Format: 2024-03-15T18:22:31+00:00
        pub_dt = datetime.fromisoformat(pub_str.replace("Z", "+00:00"))
        cutoff = datetime.now(timezone.utc) - timedelta(days=months * 30)
        return pub_dt >= cutoff
    except Exception:
        return True  # Network error — don't discard on uncertainty


# ── Filters ───────────────────────────────────────────────────────────────────

def is_blocked_region(desc, name):
    text = (desc + " " + name).lower()
    return any(r in text for r in BLOCKED_REGIONS)


def is_blocked_content(desc, name):
    text = (desc + " " + name).lower()
    return any(kw in text for kw in BLOCKED_CONTENT)


def has_relevance_signal(desc, name, yt_handle):
    text = (desc + " " + name + " " + (yt_handle or "")).lower()
    return any(kw in text for kw in RELEVANCE_SIGNALS)


# ── Supabase ──────────────────────────────────────────────────────────────────

def get_existing_db_leads():
    if not SUPABASE_URL or not SUPABASE_KEY:
        return set(), set()
    headers = {"apikey": SUPABASE_KEY, "Authorization": f"Bearer {SUPABASE_KEY}"}
    try:
        r = requests.get(
            f"{SUPABASE_URL}/rest/v1/artists",
            headers=headers,
            params={"select": "instagram,name,platform_id,platform", "limit": 10000},
            timeout=15,
        )
        data = r.json()
        if not isinstance(data, list): return set(), set()
        handles = {a["instagram"].lower() for a in data if a.get("instagram")}
        handles |= {a["platform_id"].lower() for a in data if a.get("platform_id")}
        names   = {a["name"].lower().strip() for a in data if a.get("name")}
        return handles, names
    except:
        return set(), set()


def delete_trash_creator_leads():
    """Delete existing low-quality creator leads (score < 65 or no score) to clean the slate."""
    if not SUPABASE_URL or not SUPABASE_KEY:
        return 0
    headers = {"apikey": SUPABASE_KEY, "Authorization": f"Bearer {SUPABASE_KEY}"}
    try:
        # Fetch IDs of creator leads with score < 65 or null score
        r = requests.get(
            f"{SUPABASE_URL}/rest/v1/artists",
            headers=headers,
            params={"select": "id,score,status", "platform": "eq.creator", "limit": 5000},
            timeout=15,
        )
        records = r.json()
        if not isinstance(records, list): return 0
        # Only delete 'new' status leads (never delete contacted/pitched/signed)
        trash_ids = [
            rec["id"] for rec in records
            if rec.get("status") in ("new", "ignored", None)
            and (rec.get("score") is None or int(rec.get("score") or 0) < 65)
        ]
        if not trash_ids:
            return 0
        del_r = requests.delete(
            f"{SUPABASE_URL}/rest/v1/artists",
            headers=headers,
            params={"id": f"in.({','.join(str(i) for i in trash_ids)})"},
            timeout=15,
        )
        return len(trash_ids) if del_r.status_code in (200, 204) else 0
    except Exception as e:
        print(f"  [Cleanup] {e}")
        return 0


def save_to_supabase(artists, session_id):
    if not SUPABASE_URL or not SUPABASE_KEY or not artists:
        return
    headers = {
        "apikey":        SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}",
        "Content-Type":  "application/json",
        "Prefer":        "return=minimal",
    }
    ok = fail = 0
    for a in artists:
        ig = a.get("ig_handle") or ""
        yt_url = f"https://www.youtube.com/channel/{a['channel_id']}"
        payload = {
            "name":            a["name"],
            "platform":        "creator",
            "platform_id":     a["channel_id"],
            "instagram":       ig or None,
            "followers":       a["subs_count"],
            "listeners":       a["subs_count"],
            "ig_followers":    None,
            "profile_url":     f"https://www.instagram.com/{ig}/" if ig else yt_url,
            "image_url":       "",
            "email":           None,
            "score":           a.get("score") or 0,
            "score_reason":    a.get("score_reason") or "",
            "contact_quality": "none",
            "status":          "new",
            "session_id":      session_id,
            "discovered_at":   datetime.now().isoformat(),
            "notes":           f"YT: {yt_url} | subs: {a['subs_str']}",
        }
        try:
            r = requests.post(f"{SUPABASE_URL}/rest/v1/artists", headers=headers, json=payload, timeout=10)
            if r.status_code in (200, 201):
                ok += 1
            else:
                fail += 1
                if fail == 1:
                    print(f"  [Supabase] HTTP {r.status_code} — {r.text[:120]}")
        except Exception as e:
            fail += 1
            if fail == 1:
                print(f"  [Supabase] {e}")
    print(f"  Synced {ok}/{len(artists)} to Supabase {'OK' if fail == 0 else f'({fail} failed)'}")


# ── Claude scoring ────────────────────────────────────────────────────────────

def score_batch(artists):
    if not CLAUDE_API_KEY or not artists:
        return

    artist_list = "\n".join([
        f"{i+1}. {a['name']} ({a['subs_str']}) — @{a['yt_handle'] or a['channel_id']}"
        + (f" | IG: @{a['ig_handle']}" if a.get('ig_handle') else "")
        + (f"\n   Bio: {a['desc'][:200]}" if a.get('desc') else "")
        for i, a in enumerate(artists)
    ])

    prompt = f"""You are a scout for a premium video editing agency. You're looking for active aesthetic lifestyle/fitness/fashion/travel influencers on YouTube who are solo creators and likely need a professional video editor.

Score HIGH (75+) if:
- Aesthetic visual content: lifestyle, fitness, fashion, travel, beauty, wellness, luxury
- Solo/independent creator (not a media company or brand channel)
- Active and posting regularly in 2024–2025
- Has an Instagram presence (strong signal they're a real influencer)
- Western market: USA, Canada, UK, Australia, UAE
- Would clearly benefit from better video editing

Score LOW (under 40) if:
- Family vlogger / couple vlog / kids content / parenting channel
- South Asian, Pakistani, Indian, Bangladeshi, or any non-Western content
- Gaming, cooking, tech reviews, news, politics, religion
- Inactive or seems to have stopped posting
- Clearly a media company or team (not solo)
- Pure talking-head podcast with no visual production value
- Their content doesn't require video editing skill (slideshows, static, text)

Score MEDIUM (40–74) if niche is lifestyle-adjacent but unclear or mixed signals.

Creators:
{artist_list}

Return ONLY a JSON array — no extra text:
[{{"name": "...", "score": 75, "reason": "one sentence"}}]"""

    try:
        r = requests.post(
            "https://api.anthropic.com/v1/messages",
            headers={"x-api-key": CLAUDE_API_KEY, "anthropic-version": "2023-06-01", "content-type": "application/json"},
            json={"model": "claude-haiku-4-5-20251001", "max_tokens": 1500, "messages": [{"role": "user", "content": prompt}]},
            timeout=30,
        )
        text = r.json()["content"][0]["text"].strip()
        m = re.search(r'\[.*\]', text, re.DOTALL)
        if m:
            scored = json.loads(m.group(0))
            for i, result in enumerate(scored):
                if i < len(artists):
                    artists[i]["score"]        = int(result.get("score", 0))
                    artists[i]["score_reason"] = result.get("reason", "")
    except Exception as e:
        print(f"  [Claude] Scoring error: {e}")


# ── Main ──────────────────────────────────────────────────────────────────────

def run():
    session_id = datetime.now().strftime("creator_%Y%m%d_%H%M")
    print("\n" + "=" * 60)
    print("  RENEGADE RECORDS — Content Creator Discovery Engine v3")
    print("  Source: YouTube search -> channel About page")
    print("  Targets: Aesthetic lifestyle/fitness/fashion/travel influencers")
    print("  Regions: USA, Canada, UK, Australia, UAE only")
    print(f"  Target: {TARGET_LEADS} leads | Subs: {MIN_SUBS:,}-{MAX_SUBS:,} | Score >= {MIN_SCORE}")
    print(f"  Session: {session_id}")
    print("=" * 60)

    # ── Clean up existing trash creator leads ─────────────────────────────────
    print("\n  Cleaning up low-quality existing creator leads...")
    deleted = delete_trash_creator_leads()
    if deleted:
        print(f"  Removed {deleted} low-quality creator leads from DB")
    else:
        print("  No trash leads to remove")

    print("\n  Checking existing leads in Supabase...")
    existing_handles, existing_names = get_existing_db_leads()
    print(f"  Existing leads in DB: {len(existing_handles)}")

    # ── Step 1: YouTube channel search ───────────────────────────────────────
    print(f"\n  Searching YouTube for creator channels ({len(YT_SEARCHES)} queries)...")
    all_channel_ids = []
    seen_channel_ids = set()

    for i, query in enumerate(YT_SEARCHES, 1):
        ids = yt_search_channels(query)
        new = [cid for cid in ids if cid not in seen_channel_ids]
        for cid in new:
            seen_channel_ids.add(cid)
            all_channel_ids.append(cid)
        print(f"  [{i}/{len(YT_SEARCHES)}] '{query[:55]}' -> {len(new)} new channels")
        time.sleep(random.uniform(1.5, 3.0))

    print(f"\n  Total unique YouTube channels: {len(all_channel_ids)}")

    # ── Step 2: Fetch About pages, filter ────────────────────────────────────
    print(f"\n  Fetching channel About pages...")
    candidates = []
    seen_ids   = set(existing_handles)
    skip_subs = skip_content = skip_region = skip_dupe = skip_relevance = skip_inactive = 0

    for i, cid in enumerate(all_channel_ids, 1):
        if cid in seen_ids:
            skip_dupe += 1
            continue

        info = get_channel_about(cid)
        seen_ids.add(cid)

        name       = info["name"] or cid
        subs_count = info["subs_count"]
        desc       = info["desc"]
        ig         = info["ig"][0] if info["ig"] else ""

        if subs_count < MIN_SUBS or subs_count > MAX_SUBS:
            skip_subs += 1
            if i % 20 == 0:
                print(f"  [{i}/{len(all_channel_ids)}] checked {i} — {len(candidates)} candidates")
            time.sleep(0.3)
            continue

        if is_blocked_region(desc, name):
            skip_region += 1
            time.sleep(0.3)
            continue

        if is_blocked_content(desc, name):
            skip_content += 1
            time.sleep(0.3)
            continue

        if not has_relevance_signal(desc, name, info.get("yt_handle")):
            skip_relevance += 1
            time.sleep(0.3)
            continue

        if not is_recently_active(cid):
            skip_inactive += 1
            time.sleep(0.3)
            continue

        if name.lower().strip() in existing_names:
            skip_dupe += 1
            time.sleep(0.3)
            continue

        ig_str = f" | IG: @{ig}" if ig else ""
        print(f"  [{i}/{len(all_channel_ids)}] {name[:40]:40} | {info['subs_str']:20}{ig_str} — PASS")

        candidates.append({
            "channel_id":   cid,
            "name":         name,
            "yt_handle":    info["yt_handle"],
            "subs_count":   subs_count,
            "subs_str":     info["subs_str"],
            "desc":         desc,
            "ig_handle":    ig,
            "score":        0,
            "score_reason": "",
        })

        time.sleep(random.uniform(0.4, 0.8))

        if len(candidates) >= TARGET_LEADS * 3:
            print(f"  Enough candidates ({len(candidates)}) — stopping early")
            break

    print(f"\n  Filter results:")
    print(f"    Channels checked     : {i}")
    print(f"    Subs out of range    : {skip_subs}")
    print(f"    Blocked region       : {skip_region}")
    print(f"    Blocked content type : {skip_content}")
    print(f"    No relevance signal  : {skip_relevance}")
    print(f"    Inactive (>6 months) : {skip_inactive}")
    print(f"    Duplicates           : {skip_dupe}")
    print(f"    PASS                 : {len(candidates)}")

    if not candidates:
        print("\n  No candidates found. Try again — YouTube results rotate.")
        print("\n=== Creator Discovery finished ===")
        return

    candidates.sort(key=lambda a: a["subs_count"])

    # ── Step 3: Claude scoring ────────────────────────────────────────────────
    scoring_ran = False
    if CLAUDE_API_KEY:
        est = (len(candidates) / 20) * 0.03
        print(f"\n  CLAUDE SCORING — {len(candidates)} creators (~${est:.2f})")
        no_prompt = "--no-prompt" in sys.argv
        ans = "yes" if no_prompt else input("  Run scoring? (yes/no): ").strip().lower()
        if ans in ["yes", "y"]:
            scoring_ran = True
            for i in range(0, len(candidates), 20):
                batch = candidates[i:i + 20]
                score_batch(batch)
                qualified_batch = [a for a in batch if (a.get("score") or 0) >= MIN_SCORE]
                if qualified_batch:
                    save_to_supabase(qualified_batch, session_id)
                print(f"  Scored {min(i + 20, len(candidates))}/{len(candidates)}")
                time.sleep(1)
    else:
        print("  No CLAUDE_API_KEY — skipping scoring")

    qualified = sorted(
        [a for a in candidates if (a.get("score") or 0) >= MIN_SCORE],
        key=lambda x: x.get("score", 0), reverse=True,
    )
    if not scoring_ran:
        qualified = candidates
        save_to_supabase(qualified[:TARGET_LEADS], session_id)

    new_leads = qualified[:TARGET_LEADS]

    print(f"\n  Qualified (score >= {MIN_SCORE}): {len(qualified)}")
    if new_leads:
        print(f"\n  {'Score':<6} {'Subscribers':<14} {'Name':<35} {'IG'}")
        print("  " + "-" * 70)
        for a in new_leads[:30]:
            score  = str(a.get("score") or "-")
            ig_str = f"@{a['ig_handle']}" if a.get("ig_handle") else "-"
            print(f"  [{score:>3}]  {a['subs_str']:<14} {a['name']:<35} {ig_str}")

    print(f"\n  {len(new_leads)} creator leads added to dashboard.")
    print("\n" + "=" * 60)
    print(f"  Session {session_id} complete.")
    print("=" * 60 + "\n")


if __name__ == "__main__":
    run()
