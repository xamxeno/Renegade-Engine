"""
Renegade Records — Instagram Discovery Engine v1
Finds unsigned music artists directly from Instagram via web search.
Restrictions: 1K–100K followers · USA, Canada, UK, Australia, UAE · no producers/DJs
Run: python insta_discovery.py [--no-prompt]
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

TARGET_LEADS  = 50
MIN_FOLLOWERS = 1_000
MAX_FOLLOWERS = 100_000
MIN_SCORE     = 60

BLOCKED_REGIONS = [
    "india","indian","pakistan","pakistani","hindi","bollywood","desi","bangladesh","bengali","urdu",
    "karachi","lahore","islamabad","mumbai","delhi","kolkata","bangalore",
    "kenya","ethiopia","tanzania","nigeria","ghana","lagos","nairobi","johannesburg",
    "indonesia","indonesian","philippines","filipino","malaysia","malay",
    "japan","japanese","korea","korean","china","chinese","vietnam","vietnamese",
    "mexico","mexican","colombia","colombian","brazil","brazilian",
    "reggaeton","latin trap","latin pop",
]

PRODUCER_KEYWORDS = [
    "music producer", "beat maker", "beatmaker", "mixing engineer", "mastering engineer",
    "sound engineer", "audio engineer", "beats for sale", "beat store", "type beats",
    "free beat", "sample pack", "produced by", "prod by",
]

MUSIC_KEYWORDS = [
    "singer", "rapper", "artist", "vocalist", "songwriter",
    "r&b", "rnb", "hip hop", "hiphop", "rap", "trap", "soul",
    "neo soul", "melodic", "indie", "new music", "new single",
    "out now", "music video", "unsigned", "independent artist",
    "streaming", "spotify", "apple music", "soundcloud",
    "booking", "for features", "dms open", "musician",
]

# Instagram path segments that are NOT user profiles
_BAD_IG_PATHS = {
    'p', 'explore', 'stories', 'reels', 'accounts', 'login', 'signup',
    'direct', 'tv', 'about', 'press', 'api', 'static', 'legal', 'help',
    'location', 'hashtag', 'tags', 'web', 'ar', 'events', 'music',
    'create', 'directory', 'challenge', 'share', 'reel',
}

# DuckDuckGo queries — Google-style boolean syntax for precision targeting
DDG_SEARCHES = [
    # Underground/independent rappers by region
    'site:instagram.com "underground rapper" ("USA" OR "United States") -"producer" -"engineer"',
    'site:instagram.com "underground rapper" ("UK" OR "United Kingdom" OR "London") -"producer"',
    'site:instagram.com "underground rapper" ("Canada" OR "Toronto" OR "Montreal") -"producer"',
    'site:instagram.com "underground rapper" ("Australia" OR "Sydney" OR "Melbourne") -"producer"',

    # R&B/soul singers unsigned
    'site:instagram.com "independent artist" ("r&b" OR "rnb") ("USA" OR "United States") -"producer" -"dj"',
    'site:instagram.com "unsigned" ("r&b singer" OR "rnb singer") ("UK" OR "Canada" OR "Australia")',
    'site:instagram.com "neo soul" ("independent" OR "unsigned") ("USA" OR "UK") -"producer" -"engineer"',
    'site:instagram.com "trap soul" ("independent artist" OR "unsigned artist") -"producer" -"beatmaker"',

    # Active release signals
    'site:instagram.com "new single out now" ("rapper" OR "singer") ("USA" OR "UK" OR "Canada") -"producer"',
    'site:instagram.com "out now on all platforms" ("rapper" OR "singer" OR "artist") -"producer" -"dj"',
    'site:instagram.com "streaming everywhere" ("independent" OR "unsigned") ("rapper" OR "singer")',
    'site:instagram.com "music video out" ("independent artist" OR "unsigned artist") -"producer"',

    # DM/booking open signals (high outreach potential)
    'site:instagram.com "dms open" ("rapper" OR "singer" OR "artist") ("USA" OR "UK" OR "Canada") -"producer"',
    'site:instagram.com "for bookings" ("r&b" OR "rap" OR "rnb") ("USA" OR "UK" OR "Canada") -"producer"',
    'site:instagram.com "booking email" ("rapper" OR "singer") ("independent" OR "unsigned") -"producer"',

    # Genre-specific
    'site:instagram.com "melodic rapper" ("independent" OR "unsigned") ("USA" OR "UK" OR "Canada" OR "Australia")',
    'site:instagram.com "singer songwriter" ("independent" OR "unsigned") ("r&b" OR "rnb" OR "soul") -"producer"',
    'site:instagram.com "vocalist" ("independent artist" OR "unsigned artist") ("USA" OR "UK" OR "Canada")',

    # UAE/Dubai market
    'site:instagram.com ("rapper" OR "r&b singer") ("Dubai" OR "UAE" OR "Abu Dhabi") "independent" -"producer"',

    # Fresh 2025 signal
    'site:instagram.com "independent artist" ("rap" OR "r&b" OR "rnb") "2025" ("USA" OR "UK" OR "Canada") -"producer" -"dj"',
]


def ddg_search(query, max_handles=20):
    """DuckDuckGo HTML search — returns Instagram handles from results."""
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

        raw = re.findall(r'instagram\.com/([a-zA-Z0-9._]{2,30})(?:[/?"\s<]|$)', html)
        handles, seen = [], set()
        for h in raw:
            h = h.lower().rstrip('.')
            if h and h not in _BAD_IG_PATHS and h not in seen:
                seen.add(h)
                handles.append(h)
                if len(handles) >= max_handles:
                    break
        return handles
    except Exception as e:
        print(f"  [DDG] {e}")
        return []


_IG_PAGE_HEADERS = {
    "User-Agent":      "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept":          "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
    "DNT":             "1",
    "Connection":      "keep-alive",
    "Upgrade-Insecure-Requests": "1",
    "Sec-Fetch-Dest":  "document",
    "Sec-Fetch-Mode":  "navigate",
    "Sec-Fetch-Site":  "none",
    "Sec-Fetch-User":  "?1",
}

def _parse_ig_followers(fstr):
    """Parse '12.5K', '1,234', '2M' etc. → int."""
    fstr = fstr.replace(',', '').strip()
    try:
        if fstr.upper().endswith('M'):
            return int(float(fstr[:-1]) * 1_000_000)
        if fstr.upper().endswith('K'):
            return int(float(fstr[:-1]) * 1_000)
        return int(float(fstr))
    except:
        return 0


def fetch_ig_profile(handle):
    """Fetch Instagram profile by scraping public profile page og: meta tags."""
    for attempt in range(2):
        try:
            r = requests.get(
                f"https://www.instagram.com/{handle}/",
                headers=_IG_PAGE_HEADERS,
                timeout=15,
                allow_redirects=True,
            )
            if r.status_code == 429:
                wait = int(r.headers.get("Retry-After", 45))
                print(f"  [IG] Rate limited — waiting {min(wait,60)}s")
                time.sleep(min(wait, 60))
                continue
            if r.status_code != 200:
                return None

            html = r.text

            # Check for login redirect (Instagram blocks bots)
            if 'login' in r.url or 'accounts/login' in html[:500]:
                return None

            # og:description — "12.5K Followers, 234 Following, 52 Posts - Bio text"
            desc_m = re.search(r'<meta[^>]+property=["\']og:description["\'][^>]+content=["\']([^"\']+)["\']', html)
            if not desc_m:
                desc_m = re.search(r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+property=["\']og:description["\']', html)
            if not desc_m:
                return None
            desc = desc_m.group(1)

            # Parse follower count
            fol_m = re.match(r'([\d,.]+[KMkm]?)\s+Followers', desc, re.IGNORECASE)
            if not fol_m:
                return None
            followers = _parse_ig_followers(fol_m.group(1))

            # Extract bio (text after "N Posts - ")
            bio = ""
            bio_m = re.search(r'\d[\d,]*\s+Posts\s*[-–]\s*(.+)', desc, re.IGNORECASE)
            if bio_m:
                bio = bio_m.group(1).strip()

            # og:title — "Name (@handle) • Instagram..."
            name = handle
            title_m = re.search(r'<meta[^>]+property=["\']og:title["\'][^>]+content=["\']([^"\']+)["\']', html)
            if not title_m:
                title_m = re.search(r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+property=["\']og:title["\']', html)
            if title_m:
                nm = re.match(r'^(.+?)\s*[\(@•]', title_m.group(1))
                if nm:
                    name = nm.group(1).strip()

            is_private = '"is_private":true' in html or '"isPrivate":true' in html

            email = ""
            em = re.search(r'[\w.+\-]+@[\w\-]+\.[a-zA-Z]{2,}', bio)
            if em:
                email = em.group(0)

            img = ""
            img_m = re.search(r'<meta[^>]+property=["\']og:image["\'][^>]+content=["\']([^"\']+)["\']', html)
            if not img_m:
                img_m = re.search(r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+property=["\']og:image["\']', html)
            if img_m:
                img = img_m.group(1)

            return {
                "name":       name,
                "bio":        bio,
                "followers":  followers,
                "is_private": is_private,
                "image_url":  img,
                "email":      email,
            }
        except Exception:
            if attempt == 0:
                time.sleep(3)
    return None


def is_music_artist(bio, name, handle):
    text = (bio + " " + name + " " + handle).lower()
    return any(kw in text for kw in MUSIC_KEYWORDS)


def is_producer(bio, name, handle):
    text = (bio + " " + name + " " + handle).lower()
    if re.search(r'\bdjs?\b', text):
        return True
    return any(kw in text for kw in PRODUCER_KEYWORDS)


def is_blocked_region(bio, name):
    text = (bio + " " + name).lower()
    return any(r in text for r in BLOCKED_REGIONS)


def get_existing_db_leads():
    """Fetch all existing handles/names from Supabase to avoid duplicates."""
    if not SUPABASE_URL or not SUPABASE_KEY:
        return set(), set()
    headers = {"apikey": SUPABASE_KEY, "Authorization": f"Bearer {SUPABASE_KEY}"}
    try:
        r = requests.get(
            f"{SUPABASE_URL}/rest/v1/artists",
            headers=headers,
            params={"select": "instagram,name,platform_id", "limit": 10000},
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
    """Score a batch of Instagram artists with Claude Haiku."""
    if not CLAUDE_API_KEY or not artists:
        return

    artist_list = "\n".join([
        f"{i+1}. @{a['handle']} — {a['name']} — {a['followers']:,} followers\n   Bio: {a['bio'][:200]}"
        for i, a in enumerate(artists)
    ])

    prompt = f"""You are an A&R scout at a hip-hop/R&B record label looking for unsigned artists to reach out to.

Rate each Instagram artist 0-100 for signing/outreach potential. Be discriminating.

Score HIGH (70+) if: real music artist (singer/rapper/songwriter), R&B/hip-hop/trap/soul/neo-soul genres, unsigned/independent signals, actively releasing music, DMs open or booking email visible.

Score LOW (under 40) if: producer/beatmaker/DJ, clearly managed/signed, fan page, label account, venue/event, wrong genre, or the account looks commercial/brand-level.

Score MEDIUM (40-69) if: possibly an artist but bio is vague, right vibes but unclear if unsigned.

Artists:
{artist_list}

Return ONLY a JSON array:
[{{"name": "...", "score": 75, "reason": "one sentence"}}]"""

    try:
        r = requests.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key":          CLAUDE_API_KEY,
                "anthropic-version":  "2023-06-01",
                "content-type":       "application/json",
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
    """Save Instagram artists to Supabase."""
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
        payload = {
            "name":            a["name"],
            "platform":        "instagram",
            "platform_id":     a["handle"],
            "instagram":       a["handle"],
            "followers":       a["followers"],
            "listeners":       a["followers"],
            "ig_followers":    a["followers"],
            "profile_url":     f"https://www.instagram.com/{a['handle']}/",
            "image_url":       a.get("image_url") or "",
            "email":           a.get("email") or None,
            "score":           a.get("score") or 0,
            "score_reason":    a.get("score_reason") or "",
            "contact_quality": "found" if a.get("email") else "none",
            "status":          "new",
            "session_id":      session_id,
            "discovered_at":   datetime.now().isoformat(),
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
    session_id = datetime.now().strftime("ig_%Y%m%d_%H%M")
    print("\n" + "="*60)
    print("  RENEGADE RECORDS — Instagram Discovery Engine v1")
    print("  Regions: USA, Canada, UK, Australia, UAE")
    print(f"  Target: {TARGET_LEADS} new leads | Followers: {MIN_FOLLOWERS:,}–{MAX_FOLLOWERS:,}")
    print(f"  Session: {session_id}")
    print("="*60)

    print("\n  Checking existing leads in Supabase...")
    existing_handles, existing_names = get_existing_db_leads()
    print(f"  Existing leads in DB: {len(existing_handles)}")

    # ── Step 1: Collect IG handles from DDG searches ────────────────────────
    all_handles = []
    seen_handles = set(existing_handles)

    print(f"\n  Searching for Instagram artist profiles ({len(DDG_SEARCHES)} queries)...")
    for i, query in enumerate(DDG_SEARCHES, 1):
        handles = ddg_search(query)
        new_count = 0
        for h in handles:
            if h not in seen_handles:
                seen_handles.add(h)
                all_handles.append(h)
                new_count += 1
        print(f"  [{i}/{len(DDG_SEARCHES)}] {new_count} new handles found")
        time.sleep(random.uniform(12, 20))  # DDG rate limit buffer

    print(f"\n  Total unique new handles: {len(all_handles)}")
    random.shuffle(all_handles)

    # ── Step 2: Verify each handle (followers, bio, region) ─────────────────
    print(f"\n  Verifying profiles...")
    candidates = []
    skip_followers = skip_no_music = skip_producer = skip_region = skip_private = 0

    fail_count = 0
    for i, handle in enumerate(all_handles, 1):
        profile = fetch_ig_profile(handle)
        if not profile:
            fail_count += 1
            if fail_count <= 3:
                print(f"  [{i}/{len(all_handles)}] @{handle} — could not fetch (login wall or blocked)")
            time.sleep(1.5)
            continue

        name      = profile["name"]
        bio       = profile["bio"]
        followers = profile["followers"]

        if followers < MIN_FOLLOWERS or followers > MAX_FOLLOWERS:
            skip_followers += 1
            time.sleep(0.4)
            continue

        if not is_music_artist(bio, name, handle):
            skip_no_music += 1
            time.sleep(0.4)
            continue

        if is_producer(bio, name, handle):
            skip_producer += 1
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
            "name":         name,
            "bio":          bio,
            "followers":    followers,
            "image_url":    profile.get("image_url", ""),
            "email":        profile.get("email", ""),
            "score":        0,
            "score_reason": "",
        })
        print(f"  [{i}/{len(all_handles)}] @{handle} — {name} — {followers:,} followers — PASS")
        time.sleep(0.8)

        if len(candidates) >= TARGET_LEADS * 3:
            print(f"  Enough candidates ({len(candidates)}) — stopping early")
            break
    else:
        time.sleep(0.4)

    print(f"\n  Filter results:")
    print(f"    Checked : {i} handles")
    print(f"    Followers out of range : {skip_followers}")
    print(f"    No music signals       : {skip_no_music}")
    print(f"    Producer/DJ            : {skip_producer}")
    print(f"    Blocked region         : {skip_region}")
    print(f"    Private (no email)     : {skip_private}")
    print(f"    PASS                   : {len(candidates)}")

    if not candidates:
        print("\n  No candidates found. Try again later — DDG results vary.")
        return

    candidates.sort(key=lambda a: a["followers"])

    # ── Step 3: Claude scoring ───────────────────────────────────────────────
    if CLAUDE_API_KEY:
        est = (len(candidates) / 20) * 0.03
        print(f"\n  CLAUDE SCORING — {len(candidates)} artists (~${est:.2f})")
        no_prompt = "--no-prompt" in sys.argv
        ans = "yes" if no_prompt else input("  Run scoring? (yes/no): ").strip().lower()
        if ans in ["yes", "y"]:
            for i in range(0, len(candidates), 20):
                score_batch(candidates[i:i+20])
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
    print(f"  Saving top {len(new_leads)} leads\n")
    print(f"  {'Score':<6} {'Handle':<25} {'Followers':<12} {'Name'}")
    print("  " + "─" * 60)
    for a in new_leads[:20]:
        score = a.get("score") or "—"
        print(f"  [{str(score):>3}]  @{a['handle']:<24} {a['followers']:>8,}     {a['name']}")

    # ── Step 4: Save ─────────────────────────────────────────────────────────
    save_to_supabase(new_leads, session_id)

    print(f"\n  {len(new_leads)} Instagram leads live in dashboard.")
    print("\n" + "="*60)
    print(f"  Session {session_id} complete.")
    print("="*60 + "\n")


if __name__ == "__main__":
    run()
