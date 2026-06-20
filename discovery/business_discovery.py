"""
Renegade Records — Business Owner Discovery Engine v1
Finds small business owners on Instagram who have LinkedIn in their bio.
Targets: restaurants, cafes, gyms, retail, gas stations, institutes, farmhouses
Regions: USA, Canada, UK, Australia, UAE/Dubai
Run: python business_discovery.py [--no-prompt]
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

SUPABASE_URL = os.getenv("SUPABASE_URL", "")
SUPABASE_KEY = os.getenv("SUPABASE_KEY", "")

TARGET_LEADS  = 50
MIN_FOLLOWERS = 500
MAX_FOLLOWERS = 500_000

# Regions to block (not our target markets)
BLOCKED_REGIONS = [
    "india","indian","pakistan","pakistani","hindi","bangladesh","bengali",
    "karachi","lahore","islamabad","mumbai","delhi","kolkata","bangalore",
    "kenya","ethiopia","tanzania","nigeria","ghana","lagos","nairobi",
    "indonesia","philippines","malaysia","vietnam",
    "japan","japanese","korea","korean","china","chinese",
    "mexico","mexican","colombia","colombian","brazil","brazilian",
]

OWNER_KEYWORDS = [
    "owner", "founder", "co-founder", "ceo", "proprietor",
    "entrepreneur", "established", "est.", "est ", "my business",
    "my restaurant", "my cafe", "my gym", "my shop", "my store",
]

LINKEDIN_SIGNALS = [
    "linkedin.com/", "linkedin.com", "linked.in/", "linkedin:", "linkedin -",
    "linkedin |", "/ linkedin", "| linkedin", "my linkedin",
]

# Instagram reserved paths — not user profiles
_BAD_IG_PATHS = {
    'p', 'explore', 'stories', 'reels', 'accounts', 'login', 'signup',
    'direct', 'tv', 'about', 'press', 'api', 'static', 'legal', 'help',
    'location', 'hashtag', 'tags', 'web', 'ar', 'events', 'music',
    'create', 'directory', 'challenge', 'share', 'reel',
}

# DuckDuckGo searches — business owner profiles by type + region + linkedin signal
DDG_SEARCHES = [
    # Restaurant / cafe owners
    'site:instagram.com "restaurant owner" ("USA" OR "United States") "linkedin"',
    'site:instagram.com "restaurant owner" ("UK" OR "United Kingdom" OR "London") "linkedin"',
    'site:instagram.com "restaurant owner" ("Canada" OR "Toronto" OR "Vancouver") "linkedin"',
    'site:instagram.com "restaurant owner" ("Australia" OR "Sydney" OR "Melbourne") "linkedin"',
    'site:instagram.com "restaurant owner" ("Dubai" OR "UAE" OR "Abu Dhabi") "linkedin"',
    'site:instagram.com "cafe owner" ("USA" OR "UK" OR "Canada" OR "Australia") "linkedin"',
    'site:instagram.com "coffee shop owner" ("USA" OR "UK" OR "Canada") "linkedin"',

    # Gym / fitness studio owners
    'site:instagram.com "gym owner" ("USA" OR "United States") "linkedin"',
    'site:instagram.com "gym owner" ("UK" OR "Canada" OR "Australia" OR "Dubai") "linkedin"',
    'site:instagram.com "fitness studio owner" ("USA" OR "UK" OR "Canada") "linkedin"',
    'site:instagram.com "crossfit owner" OR "yoga studio owner" ("USA" OR "UK") "linkedin"',

    # Retail / boutique owners
    'site:instagram.com "boutique owner" ("USA" OR "United States") "linkedin"',
    'site:instagram.com "boutique owner" ("UK" OR "Canada" OR "Australia") "linkedin"',
    'site:instagram.com "retail store owner" ("USA" OR "UK" OR "Canada") "linkedin"',
    'site:instagram.com "shop owner" ("USA" OR "United States") "linkedin" "founder"',
    'site:instagram.com "store owner" ("UK" OR "United Kingdom") "linkedin" "founder"',

    # Gas station / fuel / service station
    'site:instagram.com "gas station owner" ("USA" OR "United States") "linkedin"',
    'site:instagram.com "petrol station owner" ("UK" OR "Australia") "linkedin"',
    'site:instagram.com "fuel station owner" ("UAE" OR "Dubai" OR "Canada") "linkedin"',

    # Institute / academy / school
    'site:instagram.com "academy founder" ("USA" OR "UK" OR "Canada") "linkedin"',
    'site:instagram.com "institute founder" ("USA" OR "UK" OR "Australia") "linkedin"',
    'site:instagram.com "school owner" ("USA" OR "UK" OR "Canada") "linkedin"',
    'site:instagram.com "tutoring center owner" ("USA" OR "Canada") "linkedin"',

    # Farmhouse / ranch / agri-business
    'site:instagram.com "farmhouse owner" ("USA" OR "Canada" OR "Australia") "linkedin"',
    'site:instagram.com "farm owner" ("USA" OR "United States") "linkedin"',
    'site:instagram.com "ranch owner" ("USA" OR "Canada" OR "Australia") "linkedin"',

    # General small business owner
    'site:instagram.com "small business owner" ("USA" OR "United States") "linkedin"',
    'site:instagram.com "small business owner" ("UK" OR "Canada" OR "Australia") "linkedin"',
    'site:instagram.com "entrepreneur" "founder" ("USA" OR "United States") "linkedin" -"crypto" -"nft"',
    'site:instagram.com "entrepreneur" "founder" ("UK" OR "Canada" OR "Australia") "linkedin" -"crypto"',

    # UAE/Dubai market specifically
    'site:instagram.com "business owner" ("Dubai" OR "UAE" OR "Abu Dhabi") "linkedin"',
    'site:instagram.com "entrepreneur" ("Dubai" OR "UAE") "founder" "linkedin"',
    'site:instagram.com "restaurant" OR "cafe" ("Dubai" OR "UAE") "owner" "linkedin"',
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
}

def _parse_ig_followers(fstr):
    fstr = fstr.replace(',', '').strip()
    try:
        if fstr.upper().endswith('M'): return int(float(fstr[:-1]) * 1_000_000)
        if fstr.upper().endswith('K'): return int(float(fstr[:-1]) * 1_000)
        return int(float(fstr))
    except:
        return 0


def fetch_ig_profile(handle):
    """Fetch Instagram public profile page and parse og: meta tags."""
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
            if 'login' in r.url or 'accounts/login' in html[:500]:
                return None

            desc_m = re.search(r'<meta[^>]+property=["\']og:description["\'][^>]+content=["\']([^"\']+)["\']', html)
            if not desc_m:
                desc_m = re.search(r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+property=["\']og:description["\']', html)
            if not desc_m:
                return None
            desc = desc_m.group(1)

            fol_m = re.match(r'([\d,.]+[KMkm]?)\s+Followers', desc, re.IGNORECASE)
            if not fol_m:
                return None
            followers = _parse_ig_followers(fol_m.group(1))

            bio = ""
            bio_m = re.search(r'\d[\d,]*\s+Posts\s*[-–]\s*(.+)', desc, re.IGNORECASE)
            if bio_m:
                bio = bio_m.group(1).strip()

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


def has_linkedin(bio):
    """Returns True if any LinkedIn signal found in bio."""
    bio_lower = bio.lower()
    return any(sig in bio_lower for sig in LINKEDIN_SIGNALS)


def has_owner_signal(bio, name, handle):
    """Returns True if the profile looks like a business owner."""
    text = (bio + " " + name + " " + handle).lower()
    return any(kw in text for kw in OWNER_KEYWORDS)


def is_blocked_region(bio, name):
    text = (bio + " " + name).lower()
    return any(r in text for r in BLOCKED_REGIONS)


def detect_business_type(bio, name, handle):
    """Detect what type of business this owner runs."""
    text = (bio + " " + name + " " + handle).lower()
    if any(k in text for k in ["restaurant", "food", "dining", "cuisine", "eatery", "diner"]):
        return "restaurant"
    if any(k in text for k in ["cafe", "coffee", "bakery", "pastry", "brunch"]):
        return "cafe"
    if any(k in text for k in ["gym", "fitness", "crossfit", "yoga", "pilates", "workout", "wellness", "health club"]):
        return "gym"
    if any(k in text for k in ["boutique", "fashion", "clothing", "apparel", "shoes", "jewel"]):
        return "retail"
    if any(k in text for k in ["retail", "shop", "store", "merchandise"]):
        return "retail"
    if any(k in text for k in ["gas station", "petrol", "fuel", "service station"]):
        return "gas station"
    if any(k in text for k in ["school", "academy", "institute", "college", "tutoring", "education", "training center"]):
        return "institute"
    if any(k in text for k in ["farm", "ranch", "farmhouse", "agri", "orchard", "vineyard"]):
        return "farmhouse"
    if any(k in text for k in ["salon", "barber", "spa", "beauty", "nail"]):
        return "beauty"
    if any(k in text for k in ["hotel", "motel", "airbnb", "hostel", "resort", "lodge"]):
        return "hospitality"
    return "business"


def get_existing_db_leads():
    """Fetch existing business platform_ids to avoid duplicates."""
    if not SUPABASE_URL or not SUPABASE_KEY:
        return set(), set()
    headers = {"apikey": SUPABASE_KEY, "Authorization": f"Bearer {SUPABASE_KEY}"}
    try:
        r = requests.get(
            f"{SUPABASE_URL}/rest/v1/artists",
            headers=headers,
            params={"select": "instagram,platform_id", "platform": "eq.business", "limit": 10000},
            timeout=15,
        )
        data = r.json()
        if not isinstance(data, list):
            return set(), set()
        handles = {a["instagram"].lower() for a in data if a.get("instagram")}
        handles |= {a["platform_id"].lower() for a in data if a.get("platform_id")}
        return handles, set()
    except:
        return set(), set()


def save_to_supabase(leads, session_id):
    """Save business owner leads to Supabase."""
    if not SUPABASE_URL or not SUPABASE_KEY or not leads:
        print("  [Supabase] No credentials — not synced")
        return
    headers = {
        "apikey":        SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}",
        "Content-Type":  "application/json",
        "Prefer":        "resolution=ignore-duplicates,return=minimal",
    }
    ok = fail = 0
    for a in leads:
        payload = {
            "name":            a["name"],
            "platform":        "business",
            "platform_id":     a["handle"],
            "instagram":       a["handle"],
            "followers":       a["followers"],
            "listeners":       a["followers"],
            "ig_followers":    a["followers"],
            "profile_url":     f"https://www.instagram.com/{a['handle']}/",
            "image_url":       a.get("image_url") or "",
            "email":           a.get("email") or None,
            "needs":           a.get("business_type", "business"),
            "score":           0,
            "score_reason":    "Business owner with LinkedIn in bio",
            "contact_quality": "found" if a.get("email") else "none",
            "status":          "new",
            "session_id":      session_id,
            "discovered_at":   datetime.now().isoformat(),
        }
        try:
            r = requests.post(
                f"{SUPABASE_URL}/rest/v1/artists?on_conflict=platform%2Cplatform_id",
                headers=headers, json=payload, timeout=10,
            )
            if r.status_code in (200, 201, 204):
                ok += 1
            else:
                fail += 1
                if fail == 1:
                    print(f"  [Supabase] First error: HTTP {r.status_code} — {r.text[:120]}")
        except Exception as e:
            fail += 1
            if fail == 1:
                print(f"  [Supabase] First error: {e}")
    print(f"  Synced {ok}/{len(leads)} to Supabase {'OK' if fail == 0 else f'({fail} failed)'}")


def run():
    session_id = datetime.now().strftime("biz_%Y%m%d_%H%M")
    print("\n" + "="*60)
    print("  RENEGADE RECORDS — Business Owner Discovery Engine v1")
    print("  Targets: restaurants, cafes, gyms, retail, gas stations,")
    print("           institutes, farmhouses — LinkedIn in bio only")
    print("  Regions: USA, Canada, UK, Australia, UAE/Dubai")
    print(f"  Target: {TARGET_LEADS} leads | Session: {session_id}")
    print("="*60)

    print("\n  Checking existing leads in Supabase...")
    existing_handles, _ = get_existing_db_leads()
    print(f"  Existing business leads in DB: {len(existing_handles)}")

    # ── Step 1: Collect IG handles from DDG searches ────────────────────────
    all_handles = []
    seen_handles = set(existing_handles)

    print(f"\n  Searching Instagram for business owner profiles ({len(DDG_SEARCHES)} queries)...")
    for i, query in enumerate(DDG_SEARCHES, 1):
        handles = ddg_search(query)
        new_count = 0
        for h in handles:
            if h not in seen_handles:
                seen_handles.add(h)
                all_handles.append(h)
                new_count += 1
        print(f"  [{i}/{len(DDG_SEARCHES)}] {new_count} new handles")
        time.sleep(random.uniform(10, 18))

    print(f"\n  Total unique new handles: {len(all_handles)}")
    random.shuffle(all_handles)

    # ── Step 2: Verify each handle ──────────────────────────────────────────
    print(f"\n  Verifying profiles (checking LinkedIn + owner signals)...")
    leads = []
    skip_followers = skip_no_linkedin = skip_no_owner = skip_region = skip_private = 0

    for i, handle in enumerate(all_handles, 1):
        if len(leads) >= TARGET_LEADS:
            print(f"  Target of {TARGET_LEADS} leads reached — stopping")
            break

        profile = fetch_ig_profile(handle)
        if not profile:
            time.sleep(1.5)
            continue

        name      = profile["name"]
        bio       = profile["bio"]
        followers = profile["followers"]

        if followers < MIN_FOLLOWERS or followers > MAX_FOLLOWERS:
            skip_followers += 1
            time.sleep(0.4)
            continue

        if is_blocked_region(bio, name):
            skip_region += 1
            time.sleep(0.4)
            continue

        if not has_linkedin(bio):
            skip_no_linkedin += 1
            time.sleep(0.4)
            continue

        if not has_owner_signal(bio, name, handle):
            skip_no_owner += 1
            time.sleep(0.4)
            continue

        if profile["is_private"] and not profile.get("email"):
            skip_private += 1
            time.sleep(0.4)
            continue

        btype = detect_business_type(bio, name, handle)
        leads.append({
            "handle":        handle,
            "name":          name,
            "bio":           bio,
            "followers":     followers,
            "image_url":     profile.get("image_url", ""),
            "email":         profile.get("email", ""),
            "business_type": btype,
        })
        print(f"  [{i}/{len(all_handles)}] @{handle} — {name} — {followers:,} — {btype} — SAVED ({len(leads)}/{TARGET_LEADS})")
        time.sleep(0.8)

    print(f"\n  Filter results:")
    print(f"    Checked               : {min(i, len(all_handles))}")
    print(f"    Followers out of range: {skip_followers}")
    print(f"    Blocked region        : {skip_region}")
    print(f"    No LinkedIn in bio    : {skip_no_linkedin}")
    print(f"    No owner signals      : {skip_no_owner}")
    print(f"    Private (no email)    : {skip_private}")
    print(f"    SAVED                 : {len(leads)}")

    if not leads:
        print("\n  No business owner leads found. DDG results vary — try again.")
        print("\n" + "="*60)
        print(f"  Session {session_id} complete.")
        print("="*60 + "\n")
        return

    # ── Step 3: Save ────────────────────────────────────────────────────────
    print(f"\n  {'Handle':<25} {'Followers':<12} {'Type':<14} {'Name'}")
    print("  " + "─"*65)
    for a in leads[:20]:
        print(f"  @{a['handle']:<24} {a['followers']:>8,}    {a['business_type']:<14} {a['name']}")

    save_to_supabase(leads, session_id)

    print(f"\n  {len(leads)} business owner leads live in dashboard.")
    print("\n" + "="*60)
    print(f"  Session {session_id} complete.")
    print("="*60 + "\n")


if __name__ == "__main__":
    run()
