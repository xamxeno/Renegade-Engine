"""
Renegade Records — Business Owner Discovery Engine v2
Target: Business owners who would want online CCTV / remote surveillance.
High-security-need businesses: gas stations, retail, warehouses, car dealers,
pharmacies, parking lots, nightclubs, hotels, construction, convenience stores.
Regions: USA, Canada, UK, Australia, UAE/Dubai
Filters: LinkedIn in bio + owner signal + target business type
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

TEST_MODE     = "--test" in sys.argv
TARGET_LEADS  = 5 if TEST_MODE else 50
MIN_FOLLOWERS = 300
MAX_FOLLOWERS = 500_000

# Regions to block
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
    "director", "managing director", "md ", "operations",
]

LINKEDIN_SIGNALS = [
    "linkedin.com/in/", "linkedin.com/", "linked.in/", "linkedin:",
    "linkedin -", "linkedin |", "/ linkedin", "| linkedin",
]

# Business types that NEED security/CCTV surveillance
# These keywords must appear in bio/name to confirm they're the right target
SECURITY_NEED_KEYWORDS = [
    # Fuel / gas
    "gas station", "petrol station", "fuel station", "service station", "filling station",
    "petrol", "fuel", "bp station", "shell station", "exxon", "chevron", "sunoco",
    # Retail / shop
    "retail", "store owner", "shop owner", "boutique", "merchandise", "clothing store",
    "fashion store", "shoe store", "hardware store", "electronics store", "convenience store",
    "corner store", "off licence", "liquor store", "off-license", "supermarket",
    # Auto
    "car dealership", "auto dealer", "car dealer", "used cars", "car lot", "auto sales",
    "auto repair", "body shop", "mechanic shop", "tire shop", "auto parts",
    # Warehouse / storage
    "warehouse", "storage facility", "self storage", "self-storage", "storage unit",
    "logistics", "distribution center", "fulfillment", "depot",
    # Parking
    "parking lot", "parking garage", "car park", "parking facility",
    # Nightlife
    "nightclub", "club owner", "bar owner", "lounge owner", "pub owner",
    "strip club", "venue owner",
    # Hotel / hospitality
    "hotel owner", "motel owner", "hotel manager", "hospitality",
    "airbnb host", "property manager", "property management",
    # Construction / contracting
    "construction", "contractor", "general contractor", "building company",
    "construction company", "site manager",
    # Pharmacy / medical
    "pharmacy", "pharmacist", "chemist shop", "drugstore",
    # Jewelry
    "jeweler", "jewellery", "jewelry store", "gold shop",
    # Restaurant at night / bar
    "restaurant owner", "cafe owner", "coffee shop", "food business",
    # Office / commercial property
    "office building", "commercial property", "landlord", "real estate",
    "property investor", "property developer",
    # School / childcare
    "school owner", "daycare owner", "nursery owner", "childcare",
    # Bank-adjacent
    "atm", "money exchange", "currency exchange", "pawn shop",
]

# Instagram reserved paths — not user profiles
_BAD_IG_PATHS = {
    'p', 'explore', 'stories', 'reels', 'accounts', 'login', 'signup',
    'direct', 'tv', 'about', 'press', 'api', 'static', 'legal', 'help',
    'location', 'hashtag', 'tags', 'web', 'ar', 'events', 'music',
    'create', 'directory', 'challenge', 'share', 'reel',
}

# DuckDuckGo searches — CCTV-relevant business owners
# IMPORTANT: DDG only indexes og:title (display name + handle) and a short og:description
# snippet from Instagram pages — it does NOT index bio text.
# Strategy: NO quoted exact phrases (too restrictive). Use unquoted keywords that would
# appear in the username/display-name, PLUS inurl: to match handles directly.
DDG_SEARCHES = [
    # Gas station / fuel — handle-based
    'site:instagram.com inurl:gasstation owner ceo founder',
    'site:instagram.com inurl:petrolstation owner founder',
    'site:instagram.com inurl:fuelstation owner entrepreneur',
    'site:instagram.com gasstation owner ceo founder USA',
    'site:instagram.com petrolstation owner founder UK',

    # Convenience / liquor store
    'site:instagram.com inurl:liquorstore owner founder',
    'site:instagram.com inurl:conveniencestore owner ceo',
    'site:instagram.com liquorstore owner entrepreneur USA',
    'site:instagram.com cornerstore owner founder USA',

    # Retail / boutique
    'site:instagram.com inurl:boutique owner ceo founder',
    'site:instagram.com inurl:retailstore owner founder',
    'site:instagram.com boutique owner ceo entrepreneur USA',
    'site:instagram.com shopowner entrepreneur founder USA',

    # Car dealer / auto
    'site:instagram.com inurl:cardealer owner founder',
    'site:instagram.com inurl:autosales owner entrepreneur',
    'site:instagram.com inurl:usedcars owner founder',
    'site:instagram.com cardealer owner founder USA',
    'site:instagram.com autorepair owner founder USA',

    # Warehouse / storage / logistics
    'site:instagram.com inurl:warehouse owner founder',
    'site:instagram.com inurl:selfstorage owner ceo',
    'site:instagram.com warehouse owner founder USA',
    'site:instagram.com selfstorage owner entrepreneur USA',

    # Nightclub / bar / venue
    'site:instagram.com inurl:nightclub owner founder',
    'site:instagram.com inurl:barowner founder entrepreneur',
    'site:instagram.com nightclub owner founder USA',
    'site:instagram.com nightclub owner founder UK',
    'site:instagram.com lounge owner founder Dubai entrepreneur',

    # Hotel / property management
    'site:instagram.com inurl:hotel owner founder',
    'site:instagram.com hotel owner founder entrepreneur USA',
    'site:instagram.com propertymanager owner founder USA',
    'site:instagram.com inurl:propertymanagement owner ceo',

    # Construction / contracting
    'site:instagram.com inurl:contractor owner founder',
    'site:instagram.com inurl:construction owner ceo',
    'site:instagram.com contractor owner founder USA entrepreneur',

    # Pharmacy / jewelry
    'site:instagram.com inurl:pharmacy owner founder',
    'site:instagram.com inurl:jewelry owner founder',
    'site:instagram.com jewelry owner founder USA entrepreneur',
    'site:instagram.com jeweler owner entrepreneur UK',

    # UAE / Dubai market
    'site:instagram.com businessowner founder entrepreneur Dubai',
    'site:instagram.com storeowner entrepreneur UAE Dubai',

    # General — CCTV / security owner signals
    'site:instagram.com cctv security owner entrepreneur business',
    'site:instagram.com inurl:security owner founder entrepreneur',
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
    """True if LinkedIn is referenced in bio."""
    bio_lower = bio.lower()
    return any(sig in bio_lower for sig in LINKEDIN_SIGNALS)


def has_owner_signal(bio, name, handle):
    """True if bio/name suggests this person is an owner or founder."""
    text = (bio + " " + name + " " + handle).lower()
    return any(kw in text for kw in OWNER_KEYWORDS)


def has_security_relevant_business(bio, name, handle):
    """True if they run a type of business that genuinely needs CCTV/remote surveillance."""
    text = (bio + " " + name + " " + handle).lower()
    return any(kw in text for kw in SECURITY_NEED_KEYWORDS)


def is_blocked_region(bio, name):
    text = (bio + " " + name).lower()
    return any(r in text for r in BLOCKED_REGIONS)


def detect_business_type(bio, name, handle):
    """Map the profile to the most specific CCTV-relevant business category."""
    text = (bio + " " + name + " " + handle).lower()
    if any(k in text for k in ["gas station", "petrol station", "fuel station", "filling station", "petrol", "fuel"]):
        return "gas station"
    if any(k in text for k in ["nightclub", "night club", "club owner", "bar owner", "lounge owner", "pub owner", "venue owner"]):
        return "nightclub/bar"
    if any(k in text for k in ["car dealership", "auto dealer", "car dealer", "used car", "car lot", "auto sales"]):
        return "car dealership"
    if any(k in text for k in ["auto repair", "body shop", "mechanic shop", "tire shop"]):
        return "auto repair"
    if any(k in text for k in ["warehouse", "storage facility", "self storage", "self-storage", "storage unit"]):
        return "warehouse/storage"
    if any(k in text for k in ["parking lot", "parking garage", "car park", "parking facility"]):
        return "parking"
    if any(k in text for k in ["hotel owner", "motel owner", "hotel manager", "hotel"]):
        return "hotel"
    if any(k in text for k in ["construction", "general contractor", "contractor", "building company"]):
        return "construction"
    if any(k in text for k in ["pharmacy", "pharmacist", "chemist", "drugstore"]):
        return "pharmacy"
    if any(k in text for k in ["jewel", "jewelry", "jewellery", "gold shop"]):
        return "jewelry store"
    if any(k in text for k in ["liquor store", "off licence", "off-license", "bottle shop"]):
        return "liquor store"
    if any(k in text for k in ["convenience store", "corner store", "supermarket"]):
        return "convenience store"
    if any(k in text for k in ["property manager", "property management", "landlord", "property investor", "airbnb"]):
        return "property/real estate"
    if any(k in text for k in ["retail", "boutique", "clothing store", "fashion store", "hardware"]):
        return "retail"
    if any(k in text for k in ["logistics", "distribution", "fulfillment", "depot"]):
        return "logistics"
    if any(k in text for k in ["restaurant", "dining", "eatery", "food business"]):
        return "restaurant"
    if any(k in text for k in ["cafe", "coffee shop", "bakery"]):
        return "cafe"
    return "business"


def get_existing_db_leads():
    """Fetch existing business platform_ids to avoid duplicates."""
    if not SUPABASE_URL or not SUPABASE_KEY:
        return set()
    headers = {"apikey": SUPABASE_KEY, "Authorization": f"Bearer {SUPABASE_KEY}"}
    try:
        r = requests.get(
            f"{SUPABASE_URL}/rest/v1/artists",
            headers=headers,
            params={"select": "platform_id", "platform": "eq.business", "limit": 10000},
            timeout=15,
        )
        data = r.json()
        if not isinstance(data, list):
            return set()
        return {a["platform_id"].lower() for a in data if a.get("platform_id")}
    except:
        return set()


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
            "score_reason":    "Business owner with LinkedIn — CCTV/security prospect",
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
    print("  RENEGADE — Business Owner Discovery (CCTV/Security) v2")
    print("  Targets: gas stations, retail, car dealers, warehouses,")
    print("           nightclubs, hotels, parking, pharmacies, jewelry")
    print("  Filter:  LinkedIn in bio + owner signal + security business")
    print("  Regions: USA, Canada, UK, Australia, UAE/Dubai")
    if TEST_MODE:
        print("  MODE:    TEST (5 leads, relaxed filters, verbose output)")
    print(f"  Target:  {TARGET_LEADS} leads | Session: {session_id}")
    print("="*60)

    print("\n  Checking existing leads in Supabase...")
    existing_handles = get_existing_db_leads()
    print(f"  Existing business leads in DB: {len(existing_handles)}")

    # ── Step 1: Collect IG handles from DDG searches ────────────────────────
    all_handles = []
    seen_handles = set(existing_handles)

    queries = DDG_SEARCHES[:15] if TEST_MODE else DDG_SEARCHES
    print(f"\n  Searching Instagram ({len(queries)} queries)...")
    for i, query in enumerate(queries, 1):
        handles = ddg_search(query)
        new_count = 0
        for h in handles:
            if h not in seen_handles:
                seen_handles.add(h)
                all_handles.append(h)
                new_count += 1
        if TEST_MODE:
            print(f"  [{i}/{len(queries)}] {new_count} new handles  ← {query[:70]}")
        else:
            print(f"  [{i}/{len(queries)}] {new_count} new handles")
        time.sleep(random.uniform(6, 12) if TEST_MODE else random.uniform(10, 18))

    print(f"\n  Total unique handles to verify: {len(all_handles)}")
    if TEST_MODE and all_handles:
        print(f"  Handles found: {', '.join('@'+h for h in all_handles[:30])}")
    random.shuffle(all_handles)

    # ── Step 2: Verify each handle ──────────────────────────────────────────
    print(f"\n  Verifying profiles...")
    leads = []
    skip_followers = skip_no_linkedin = skip_no_owner = skip_no_biz = skip_region = skip_private = skip_no_profile = 0
    checked = 0

    for handle in all_handles:
        if len(leads) >= TARGET_LEADS:
            print(f"  Target of {TARGET_LEADS} leads reached — stopping")
            break

        checked += 1
        profile = fetch_ig_profile(handle)
        if not profile:
            skip_no_profile += 1
            if TEST_MODE:
                print(f"  @{handle} → SKIP: no profile (private/404/rate-limited)")
            time.sleep(1.5)
            continue

        name      = profile["name"]
        bio       = profile["bio"]
        followers = profile["followers"]

        if followers < MIN_FOLLOWERS or followers > MAX_FOLLOWERS:
            skip_followers += 1
            if TEST_MODE:
                print(f"  @{handle} → SKIP: followers={followers:,} (range {MIN_FOLLOWERS:,}–{MAX_FOLLOWERS:,})")
            time.sleep(0.4)
            continue

        if is_blocked_region(bio, name):
            skip_region += 1
            if TEST_MODE:
                print(f"  @{handle} → SKIP: blocked region — bio='{bio[:60]}'")
            time.sleep(0.4)
            continue

        if not has_linkedin(bio):
            skip_no_linkedin += 1
            if TEST_MODE:
                print(f"  @{handle} → SKIP: no LinkedIn in bio — bio='{bio[:80]}'")
            time.sleep(0.4)
            continue

        if not has_owner_signal(bio, name, handle):
            skip_no_owner += 1
            if TEST_MODE:
                print(f"  @{handle} → SKIP: no owner signal — bio='{bio[:80]}'")
            time.sleep(0.4)
            continue

        # In TEST MODE: skip the business-type filter so we can see what passes LinkedIn+owner
        if not TEST_MODE and not has_security_relevant_business(bio, name, handle):
            skip_no_biz += 1
            time.sleep(0.4)
            continue
        if TEST_MODE and not has_security_relevant_business(bio, name, handle):
            skip_no_biz += 1
            print(f"  @{handle} → PASS (biz filter relaxed in test): {followers:,} followers — bio='{bio[:80]}'")
            # Still save in test mode even without biz match
        else:
            if TEST_MODE:
                print(f"  @{handle} → PASS: {followers:,} followers — bio='{bio[:80]}'")

        if profile["is_private"] and not profile.get("email"):
            skip_private += 1
            if TEST_MODE:
                print(f"  @{handle} → SKIP: private account, no email")
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
        print(f"  @{handle} — {name} — {followers:,} — {btype} — SAVED ({len(leads)}/{TARGET_LEADS})")
        time.sleep(0.8)

    print(f"\n  Filter results:")
    print(f"    Checked                   : {checked}")
    print(f"    No profile (404/private)  : {skip_no_profile}")
    print(f"    Followers out of range    : {skip_followers}")
    print(f"    Blocked region            : {skip_region}")
    print(f"    No LinkedIn in bio        : {skip_no_linkedin}")
    print(f"    No owner signal           : {skip_no_owner}")
    if not TEST_MODE:
        print(f"    Wrong business type       : {skip_no_biz}")
    else:
        print(f"    Wrong business type (info): {skip_no_biz} (filter relaxed in test mode)")
    print(f"    Private (no email)        : {skip_private}")
    print(f"    SAVED                     : {len(leads)}")

    if not leads:
        print("\n  No leads found. DDG results vary — try again in a few hours.")
        print("\n" + "="*60)
        print(f"  Session {session_id} complete.")
        print("="*60 + "\n")
        return  # "finished" is printed by __main__ after run() returns

    print(f"\n  {'Handle':<24} {'Followers':<11} {'Type':<20} {'Name'}")
    print("  " + "─"*70)
    for a in leads[:25]:
        print(f"  @{a['handle']:<23} {a['followers']:>8,}   {a['business_type']:<20} {a['name']}")

    save_to_supabase(leads, session_id)

    print(f"\n  {len(leads)} business owner leads live in dashboard.")
    print("\n" + "="*60)
    print(f"  Session {session_id} complete.")
    print("="*60 + "\n")


if __name__ == "__main__":
    run()
    print("=== Business Discovery finished ===")
