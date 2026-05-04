"""
Renegade Records — Content Creator Discovery Engine v1
Finds podcast hosts and reel/content creators who need editors.
Restrictions: 1K–50K followers · USA, Canada, UK, Australia, UAE · no agencies
Run: python content_discovery.py [--no-prompt]
"""
import sys, subprocess
for _pkg in ['requests', 'python-dotenv']:
    try: __import__(_pkg.replace('-', '_').split('.')[0])
    except ImportError: subprocess.check_call([sys.executable, '-m', 'pip', 'install', _pkg], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

import os, json, time, re, requests, io, random, urllib.parse, urllib.request
from datetime import datetime
from dotenv import load_dotenv

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

load_dotenv()

CLAUDE_API_KEY = os.getenv("CLAUDE_API_KEY", "")
SUPABASE_URL   = os.getenv("SUPABASE_URL", "")
SUPABASE_KEY   = os.getenv("SUPABASE_KEY", "")

TARGET_LEADS  = 100
MIN_FOLLOWERS = 1_000
MAX_FOLLOWERS = 50_000
MIN_SCORE     = 60

BLOCKED_REGIONS = [
    "india","indian","pakistan","pakistani","hindi","bollywood","desi","bangladesh","bengali","urdu",
    "karachi","lahore","islamabad","mumbai","delhi","kolkata","bangalore",
    "kenya","ethiopia","tanzania","nigeria","ghana","lagos","nairobi","johannesburg",
    "indonesia","indonesian","philippines","filipino","malaysia","malay",
    "japan","japanese","korea","korean","china","chinese","vietnam","vietnamese",
    "mexico","mexican","colombia","colombian","brazil","brazilian",
]

CONTENT_KEYWORDS = [
    "podcast", "podcaster", "host", "episodes", "content creator",
    "reels", "reel creator", "youtuber", "vlogger", "content",
    "creator", "influencer", "lifestyle", "entrepreneur", "founder",
    "business owner", "personal brand", "digital creator",
]

EXCLUSION_KEYWORDS = [
    "media company", "production house", "agency", "talent agency",
    "management", "pr firm", "marketing agency", "we create content for",
    "our clients", "team of", "studio",
]

_BAD_IG_PATHS = {
    'p', 'explore', 'stories', 'reels', 'accounts', 'login', 'signup',
    'direct', 'tv', 'about', 'press', 'api', 'static', 'legal', 'help',
    'location', 'hashtag', 'tags', 'web', 'ar', 'events', 'music',
    'create', 'directory', 'challenge', 'share', 'reel',
}

_BAD_TW_PATHS = {
    'home', 'search', 'explore', 'i', 'notifications', 'messages',
    'settings', 'hashtag', 'intent', 'login', 'signup', 'about',
    'privacy', 'tos', 'help', 'compose', 'share',
}

DDG_SEARCHES = [
    # Instagram — podcast creators
    'site:instagram.com "podcast" ("new episode" OR "episodes") ("USA" OR "UK" OR "Canada") -"agency"',
    'site:instagram.com "podcaster" ("independent" OR "solo") ("USA" OR "Canada" OR "Australia") -"agency"',
    'site:instagram.com "podcast host" ("entrepreneur" OR "lifestyle" OR "business") ("USA" OR "UK")',
    'site:instagram.com ("starting a podcast" OR "new podcast") ("USA" OR "UK" OR "Canada") 2025',

    # Instagram — reel/content creators
    'site:instagram.com "content creator" ("reels" OR "reel") ("USA" OR "UK" OR "Canada") -"agency"',
    'site:instagram.com "digital creator" ("lifestyle" OR "entrepreneur" OR "fitness") ("USA" OR "UK") -"agency"',
    'site:instagram.com ("posting daily" OR "daily content") ("creator" OR "influencer") ("USA" OR "Canada")',
    'site:instagram.com "new reel" ("content creator" OR "influencer") ("USA" OR "UK" OR "Canada") 2025',
    'site:instagram.com "personal brand" ("content creator" OR "entrepreneur") ("USA" OR "UK" OR "Canada")',
    'site:instagram.com "dm for collabs" ("creator" OR "influencer") ("USA" OR "UK" OR "Canada") -"agency"',

    # Twitter/X — podcast creators
    'site:twitter.com "podcast" ("new episode" OR "episodes") ("USA" OR "UK" OR "Canada") -"agency"',
    'site:twitter.com "podcaster" ("independent" OR "entrepreneur") ("USA" OR "UK" OR "Canada")',
    'site:x.com "podcast host" ("entrepreneur" OR "lifestyle" OR "finance") ("USA" OR "UK")',
    'site:x.com ("starting a podcast" OR "new podcast") ("USA" OR "UK" OR "Canada") 2025',

    # Twitter/X — reel/content creators
    'site:twitter.com "content creator" ("reels" OR "youtube" OR "tiktok") ("USA" OR "UK" OR "Canada") -"agency"',
    'site:twitter.com "digital creator" ("lifestyle" OR "entrepreneur") ("USA" OR "UK" OR "Canada")',
    'site:x.com ("posting daily" OR "daily content") ("creator" OR "influencer") ("USA" OR "UK")',
    'site:x.com "personal brand" ("content creator" OR "influencer") ("USA" OR "UK") 2025',

    # UAE + Australia
    'site:instagram.com ("podcast" OR "content creator") ("Dubai" OR "UAE") -"agency"',
    'site:instagram.com ("content creator" OR "podcaster") ("Australia" OR "Sydney" OR "Melbourne") -"agency"',
]


def ddg_search(query, max_handles=20):
    """DuckDuckGo HTML search — returns list of {handle, platform} dicts."""
    try:
        data = urllib.parse.urlencode({"q": query, "kl": "us-en"}).encode()
        req  = urllib.request.Request(
            "https://html.duckduckgo.com/html/",
            data=data,
            headers={
                "User-Agent":   "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                "Content-Type": "application/x-www-form-urlencoded",
            }
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            html = resp.read().decode("utf-8", errors="ignore")

        results, seen = [], set()

        raw_ig = re.findall(r'instagram\.com/([a-zA-Z0-9._]{2,30})(?:[/?"\s<]|$)', html)
        for h in raw_ig:
            h = h.lower().rstrip('.')
            if h and h not in _BAD_IG_PATHS and h not in seen:
                seen.add(h)
                results.append({"handle": h, "platform": "instagram"})
                if len(results) >= max_handles:
                    break

        raw_tw = re.findall(r'(?:twitter|x)\.com/([a-zA-Z0-9_]{2,30})(?:[/?"\s<]|$)', html)
        for h in raw_tw:
            h = h.lower().rstrip('.')
            if h and h not in _BAD_TW_PATHS and h not in seen:
                seen.add(h)
                results.append({"handle": h, "platform": "twitter"})
                if len(results) >= max_handles:
                    break

        return results
    except Exception as e:
        print(f"  [DDG] {e}")
        return []


_BROWSER_HEADERS = {
    "User-Agent":      "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept":          "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
    "DNT":             "1",
    "Connection":      "keep-alive",
    "Upgrade-Insecure-Requests": "1",
}


def _parse_followers(fstr):
    fstr = fstr.replace(',', '').strip()
    try:
        if fstr.upper().endswith('M'):
            return int(float(fstr[:-1]) * 1_000_000)
        if fstr.upper().endswith('K'):
            return int(float(fstr[:-1]) * 1_000)
        return int(float(fstr))
    except:
        return 0


def _scrape_og(url):
    """Scrape og: meta tags from a public profile page. Returns raw html or None."""
    for attempt in range(2):
        try:
            r = requests.get(url, headers=_BROWSER_HEADERS, timeout=15, allow_redirects=True)
            if r.status_code == 429:
                wait = int(r.headers.get("Retry-After", 45))
                print(f"  [Profile] Rate limited — waiting {min(wait,60)}s")
                time.sleep(min(wait, 60))
                continue
            if r.status_code != 200:
                return None
            if 'login' in r.url:
                return None
            return r.text
        except Exception:
            if attempt == 0:
                time.sleep(3)
    return None


def _extract_og(html, follower_pattern):
    """Extract followers, bio, name, email, image from og: meta tags."""
    def og(prop):
        m = re.search(rf'<meta[^>]+property=["\']og:{prop}["\'][^>]+content=["\']([^"\']+)["\']', html)
        if not m:
            m = re.search(rf'<meta[^>]+content=["\']([^"\']+)["\'][^>]+property=["\']og:{prop}["\']', html)
        return m.group(1) if m else ""

    desc  = og("description")
    title = og("title")
    image = og("image")

    fol_m = re.match(follower_pattern, desc, re.IGNORECASE)
    if not fol_m:
        return None
    followers = _parse_followers(fol_m.group(1))

    bio = ""
    bio_m = re.search(r'\d[\d,]*\s+Posts\s*[-–]\s*(.+)', desc, re.IGNORECASE)
    if bio_m:
        bio = bio_m.group(1).strip()

    name = ""
    nm = re.match(r'^(.+?)\s*[\(@•\|]', title)
    if nm:
        name = nm.group(1).strip()

    email = ""
    em = re.search(r'[\w.+\-]+@[\w\-]+\.[a-zA-Z]{2,}', bio)
    if em:
        email = em.group(0)

    is_private = '"is_private":true' in html or '"isPrivate":true' in html

    return {
        "followers":  followers,
        "bio":        bio,
        "name":       name,
        "email":      email,
        "image_url":  image,
        "is_private": is_private,
    }


def fetch_profile(handle, platform):
    """Fetch public profile data. Returns dict or None."""
    if platform == "instagram":
        html = _scrape_og(f"https://www.instagram.com/{handle}/")
        if not html:
            return None
        data = _extract_og(html, r'([\d,.]+[KMkm]?)\s+Followers')
        if not data or data["followers"] == 0:
            return None
        data["name"] = data["name"] or handle
        return data

    elif platform == "twitter":
        html = _scrape_og(f"https://twitter.com/{handle}")
        if not html:
            return None
        # Twitter og:description: "N Followers, N Following, N Tweets"
        data = _extract_og(html, r'([\d,.]+[KMkm]?)\s+Followers')
        if not data:
            # fallback: some Twitter pages use different format
            m = re.search(r'([\d,.]+[KMkm]?)\s+Followers', html, re.IGNORECASE)
            if not m:
                return None
            followers = _parse_followers(m.group(1))
            data = {"followers": followers, "bio": "", "name": handle, "email": "", "image_url": "", "is_private": False}
        data["name"] = data["name"] or handle
        return data

    return None


def is_content_creator(bio, name, handle):
    text = (bio + " " + name + " " + handle).lower()
    return any(kw in text for kw in CONTENT_KEYWORDS)


def is_excluded(bio, name, handle):
    text = (bio + " " + name + " " + handle).lower()
    return any(kw in text for kw in EXCLUSION_KEYWORDS)


def is_blocked_region(bio, name):
    text = (bio + " " + name).lower()
    return any(r in text for r in BLOCKED_REGIONS)


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
        if not isinstance(data, list):
            return set(), set()
        handles = {a["instagram"].lower() for a in data if a.get("instagram")}
        handles |= {a["platform_id"].lower() for a in data if a.get("platform_id")}
        names   = {a["name"].lower().strip() for a in data if a.get("name")}
        return handles, names
    except:
        return set(), set()


def score_batch(artists):
    if not CLAUDE_API_KEY or not artists:
        return

    artist_list = "\n".join([
        f"{i+1}. @{a['handle']} ({a['platform']}) — {a['name']} — {a['followers']:,} followers\n   Bio: {a['bio'][:200]}"
        for i, a in enumerate(artists)
    ])

    prompt = f"""You are a talent scout for a video editing agency seeking podcast hosts and reel/content creators who likely need a professional editor.

Score HIGH (70+) if: active podcast host or reel/content creator, independent or solo (not an agency or media company), 1K–50K followers, posting regularly, any signals of needing help or looking for collabs, entrepreneur/founder niche (has budget).

Score LOW (under 40) if: big media company, talent agency, has a clear production team, wrong niche (pure text/politics/news/memes), or the account looks like a brand rather than an individual.

Score MEDIUM (40–69) if: possibly a content creator but bio is vague or niche is unclear.

Creators:
{artist_list}

Return ONLY a JSON array:
[{{"name": "...", "score": 75, "reason": "one sentence"}}]"""

    try:
        r = requests.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key":         CLAUDE_API_KEY,
                "anthropic-version": "2023-06-01",
                "content-type":      "application/json",
            },
            json={
                "model":      "claude-haiku-4-5-20251001",
                "max_tokens": 1500,
                "messages":   [{"role": "user", "content": prompt}],
            },
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
        is_ig = a["platform"] == "instagram"
        payload = {
            "name":            a["name"],
            "platform":        "creator",
            "platform_id":     a["handle"],
            "instagram":       a["handle"] if is_ig else None,
            "followers":       a["followers"],
            "listeners":       a["followers"],
            "ig_followers":    a["followers"] if is_ig else None,
            "profile_url":     f"https://www.instagram.com/{a['handle']}/" if is_ig else f"https://twitter.com/{a['handle']}",
            "image_url":       a.get("image_url") or "",
            "email":           a.get("email") or None,
            "score":           a.get("score") or 0,
            "score_reason":    a.get("score_reason") or "",
            "contact_quality": "found" if a.get("email") else "none",
            "status":          "new",
            "session_id":      session_id,
            "discovered_at":   datetime.now().isoformat(),
            "notes":           f"Source: {a['platform']}",
        }
        try:
            r = requests.post(
                f"{SUPABASE_URL}/rest/v1/artists",
                headers=headers, json=payload, timeout=10,
            )
            if r.status_code in (200, 201):
                ok += 1
            else:
                fail += 1
                if fail == 1:
                    print(f"  [Supabase] First error: HTTP {r.status_code} — {r.text[:120]}")
        except Exception as e:
            fail += 1
            if fail == 1:
                print(f"  [Supabase] First error: {e}")
    print(f"  Synced {ok}/{len(artists)} to Supabase {'OK' if fail == 0 else f'({fail} failed)'}")


def run():
    session_id = datetime.now().strftime("creator_%Y%m%d_%H%M")
    print("\n" + "="*60)
    print("  RENEGADE RECORDS — Content Creator Discovery Engine v1")
    print("  Targets: Podcast hosts + Reel/Content creators")
    print("  Regions: USA, Canada, UK, Australia, UAE")
    print(f"  Target: {TARGET_LEADS} new leads | Followers: {MIN_FOLLOWERS:,}–{MAX_FOLLOWERS:,}")
    print(f"  Session: {session_id}")
    print("="*60)

    print("\n  Checking existing leads in Supabase...")
    existing_handles, existing_names = get_existing_db_leads()
    print(f"  Existing leads in DB: {len(existing_handles)}")

    # ── Step 1: Collect handles from DDG searches ────────────────────────────
    all_handles = []
    seen_handles = set(existing_handles)

    print(f"\n  Searching for creator profiles ({len(DDG_SEARCHES)} queries)...")
    for i, query in enumerate(DDG_SEARCHES, 1):
        results = ddg_search(query)
        new_count = 0
        for item in results:
            key = item["handle"]
            if key not in seen_handles:
                seen_handles.add(key)
                all_handles.append(item)
                new_count += 1
        print(f"  [{i}/{len(DDG_SEARCHES)}] {new_count} new handles found")
        time.sleep(random.uniform(12, 20))

    print(f"\n  Total unique new handles: {len(all_handles)}")
    random.shuffle(all_handles)

    # ── Step 2: Verify each profile ─────────────────────────────────────────
    print(f"\n  Verifying profiles...")
    candidates = []
    skip_followers = skip_no_content = skip_excluded = skip_region = skip_private = 0
    fail_count = 0

    for i, item in enumerate(all_handles, 1):
        handle   = item["handle"]
        platform = item["platform"]

        profile = fetch_profile(handle, platform)
        if not profile:
            fail_count += 1
            if fail_count <= 3:
                print(f"  [{i}/{len(all_handles)}] @{handle} ({platform}) — could not fetch")
            time.sleep(1.5)
            continue

        name      = profile["name"]
        bio       = profile["bio"]
        followers = profile["followers"]

        if followers < MIN_FOLLOWERS or followers > MAX_FOLLOWERS:
            skip_followers += 1
            time.sleep(0.4)
            continue

        if not is_content_creator(bio, name, handle):
            skip_no_content += 1
            time.sleep(0.4)
            continue

        if is_excluded(bio, name, handle):
            skip_excluded += 1
            time.sleep(0.4)
            continue

        if is_blocked_region(bio, name):
            skip_region += 1
            time.sleep(0.4)
            continue

        if profile["is_private"] and not profile.get("email"):
            skip_private += 1
            time.sleep(0.4)
            continue

        if name.lower().strip() in existing_names:
            time.sleep(0.4)
            continue

        candidates.append({
            "handle":       handle,
            "platform":     platform,
            "name":         name,
            "bio":          bio,
            "followers":    followers,
            "image_url":    profile.get("image_url", ""),
            "email":        profile.get("email", ""),
            "score":        0,
            "score_reason": "",
        })
        print(f"  [{i}/{len(all_handles)}] @{handle} ({platform}) — {name} — {followers:,} followers — PASS")
        time.sleep(0.8)

        if len(candidates) >= TARGET_LEADS * 3:
            print(f"  Enough candidates ({len(candidates)}) — stopping early")
            break

    print(f"\n  Filter results:")
    print(f"    Checked              : {i} handles")
    print(f"    Could not fetch      : {fail_count}")
    print(f"    Followers out of range: {skip_followers}")
    print(f"    No content signals   : {skip_no_content}")
    print(f"    Excluded (agency etc): {skip_excluded}")
    print(f"    Blocked region       : {skip_region}")
    print(f"    Private (no email)   : {skip_private}")
    print(f"    PASS                 : {len(candidates)}")

    if not candidates:
        print("\n  No candidates found. Try again later — DDG results vary.")
        return

    candidates.sort(key=lambda a: a["followers"])

    # ── Step 3: Claude scoring ───────────────────────────────────────────────
    if CLAUDE_API_KEY:
        est = (len(candidates) / 20) * 0.03
        print(f"\n  CLAUDE SCORING — {len(candidates)} creators (~${est:.2f})")
        no_prompt = "--no-prompt" in sys.argv
        ans = "yes" if no_prompt else input("  Run scoring? (yes/no): ").strip().lower()
        if ans in ["yes", "y"]:
            for i in range(0, len(candidates), 20):
                score_batch(candidates[i:i+20])
                qualified_batch = [a for a in candidates[i:i+20] if (a.get("score") or 0) >= MIN_SCORE]
                if qualified_batch:
                    save_to_supabase(qualified_batch, session_id)
                print(f"  Scored {min(i+20, len(candidates))}/{len(candidates)}")
                time.sleep(1)
    else:
        print("  No CLAUDE_API_KEY — skipping scoring")

    qualified = sorted(
        [a for a in candidates if (a.get("score") or 0) >= MIN_SCORE],
        key=lambda x: x.get("score", 0), reverse=True,
    )
    if not qualified:
        qualified = candidates

    new_leads = qualified[:TARGET_LEADS]

    print(f"\n  Qualified (score >= {MIN_SCORE}): {len(qualified)}")
    print(f"\n  {'Score':<6} {'Platform':<12} {'Handle':<25} {'Followers':<12} {'Name'}")
    print("  " + "─" * 68)
    for a in new_leads[:20]:
        score = a.get("score") or "—"
        print(f"  [{str(score):>3}]  {a['platform']:<12} @{a['handle']:<24} {a['followers']:>8,}     {a['name']}")

    scoring_ran = CLAUDE_API_KEY and "--no-prompt" in sys.argv or (CLAUDE_API_KEY and 'ans' in dir() and ans in ["yes", "y"])
    if not scoring_ran:
        save_to_supabase(new_leads, session_id)

    print(f"\n  {len(new_leads)} creator leads live in dashboard.")
    print("\n" + "="*60)
    print(f"  Session {session_id} complete.")
    print("="*60 + "\n")


if __name__ == "__main__":
    run()
