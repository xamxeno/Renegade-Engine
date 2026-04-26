"""
Renegade Records — Discovery Engine v8
Spotify only · Regions: USA, Canada, UK, Australia, UAE
Runs until TARGET_LEADS new leads found — deduplicates against Supabase
Pass --no-prompt to skip Claude scoring confirmation (used by dashboard API)
"""
import sys, subprocess
for _pkg in ['requests', 'python-dotenv']:
    try: __import__(_pkg.replace('-', '_').split('.')[0])
    except ImportError: subprocess.check_call([sys.executable, '-m', 'pip', 'install', _pkg], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

import os, json, time, re, requests, io
from datetime import datetime
from base64 import b64encode
from dotenv import load_dotenv

# Force UTF-8 output on Windows terminals
if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

load_dotenv()

SPOTIFY_CLIENT_ID     = os.getenv("SPOTIFY_CLIENT_ID", "")
SPOTIFY_CLIENT_SECRET = os.getenv("SPOTIFY_CLIENT_SECRET", "")
CLAUDE_API_KEY        = os.getenv("CLAUDE_API_KEY", "")
SUPABASE_URL          = os.getenv("SUPABASE_URL", "")
SUPABASE_KEY          = os.getenv("SUPABASE_KEY", "")

TARGET_LEADS  = 50          # keep scanning until this many NEW leads saved
MAX_LISTENERS = 100_000     # hard cap — skip immediately if over
MIN_LISTENERS = 1_000       # minimum monthly listeners
MIN_FOLLOWERS = 500         # minimum platform followers
MAX_FOLLOWERS = 100_000     # maximum platform followers
MIN_SCORE     = 60          # minimum Claude score to keep

# ── BLOCKED REGIONS ────────────────────────────────────────────────────────────
BLOCKED_REGIONS = [
    "india","indian","pakistan","pakistani","hindi","bollywood",
    "bhangra","desi","bangladesh","bengali","urdu","karachi","lahore",
    "islamabad","mumbai","delhi","kolkata","rawalpindi","hyderabad",
    "kenya","ethiopia",
    "tanzania","south africa","afrobeats","afropop","amapiano",
    "indonesia","indonesian","philippines","filipino","malaysia","malay",
    "japan","japanese","korea","korean","china","chinese","vietnam","vietnamese",
    "mexico","mexican","colombia","colombian",
    "reggaeton","latin trap","latin pop",
]

BLOCKED_CITIES = [
    "karachi","lahore","islamabad","rawalpindi","faisalabad","multan",
    "mumbai","delhi","kolkata","bangalore","hyderabad","chennai","pune",
    "dhaka","lagos","abuja","accra","nairobi","johannesburg","cape town",
    "jakarta","manila","kuala lumpur","tokyo","beijing","shanghai","seoul",
    "bogota","lima","santiago","buenos aires","sao paulo","mexico city",
]

# ── JUNK ARTIST NAMES ──────────────────────────────────────────────────────────
JUNK_KEYWORDS = [
    "beats","instrumental","lofi","lo-fi","radio","nation","playlist",
    "orchestra","ensemble","foundation","collective","compilation",
    "various","worldwide","beat tape","type beat","records label",
    "urban music","hip hop music","rnb music","soul music",
    "free beat","sample pack","drum kit","loop kit","beat store",
    "music teacher","music school","music lessons","music educator",
    "music coach","music tutor","music academy","music institute",
    "music production school","vocal coach","voice teacher",
    "audio production","sound design","mixing engineer",
    "mastering engineer","music producer","beat maker","beatmaker",
    "music group","music agency","music management","entertainment group",
    "talent agency","booking agency","music publishing",
    "unsigned artists","indie artists","independent artists",
    "podcast","radio show","radio host","cover artist","music blog",
    "music network","music community","sound healing","music therapy",
]

PRODUCER_NAME_PATTERNS = [
    "prod.", "prod by", "prodby", "prod_by", "xproducer", "beatz",
    "tha producer", "the producer", "on the beat", "type beat",
    "producer", "beatmaker", "beat maker",
    "dj ", " dj ", "dj-", "dj_", "deejay", "disc jockey", "turntablist",
]

def is_junk(name):
    n = name.lower()
    if any(kw in n for kw in JUNK_KEYWORDS):
        return True
    if any(p in n for p in PRODUCER_NAME_PATTERNS):
        return True
    if len(name.split()) > 5:
        return True
    if sum(c.isdigit() for c in name) > 3:
        return True
    return False

def is_blocked(genres, bio="", name=""):
    text = " ".join(genres).lower() + " " + bio.lower() + " " + name.lower()
    if any(r in text for r in BLOCKED_REGIONS):
        return True
    if any(c in text for c in BLOCKED_CITIES):
        return True
    return False

# ── SPOTIFY KEYWORD SEARCHES ───────────────────────────────────────────────────
SPOTIFY_KEYWORD_SEARCHES = [
    "independent rnb artist unsigned",
    "self produced rnb singer",
    "indie soul singer unsigned",
    "independent hip hop artist self produced",
    "unsigned neo soul artist",
    "indie trap soul singer",
    "bedroom rnb singer independent",
    "self managed hip hop artist",
    "diy rnb artist no label",
    "underground rnb soul singer",
    "independent rnb artist uk unsigned",
    "indie rnb singer toronto",
    "unsigned soul artist los angeles",
    "independent hip hop artist atlanta",
    "indie rnb artist new york unsigned",
    "unsigned rnb singer canada independent",
    "diy hip hop artist australia",
    "independent soul artist london",
    "alternative rnb indie artist",
    "trap soul unsigned artist",
    "dark rnb indie singer",
    "acoustic soul independent singer",
    "unsigned artist uk rnb 2024",
    "indie hip hop artist usa new",
    "emerging rnb singer unsigned",
    "new rnb artist independent usa",
    "independent trap soul artist 2024",
    "unsigned hip hop artist toronto canada",
    "indie soul singer australia unsigned",
    "underground hip hop artist london uk",
    "unsigned r&b singer usa 2024",
    "indie rnb artist dubai uae",
    "unsigned rapper usa self produced",
    "new soul artist unsigned uk 2024",
    "trap soul singer independent usa",
    "neo soul artist independent australia",
    "unsigned rnb singer chicago independent",
    "indie pop rnb singer canada unsigned",
    "independent afro rnb artist uk",
    "unsigned melodic rapper usa indie",
    "rnb singer songwriter unsigned usa",
    "independent hip hop artist miami",
    "unsigned soul singer houston",
    "indie rnb artist dallas unsigned",
    "unsigned rnb artist phoenix independent",
    "independent rapper seattle unsigned",
    "indie rnb singer birmingham uk",
    "unsigned artist manchester uk rnb",
    "independent rnb singer melbourne australia",
    "unsigned hip hop artist sydney",
    "indie soul artist dubai unsigned",
    "rnb artist abu dhabi independent",
    "unsigned vocalist rnb usa indie",
    "bedroom pop rnb singer unsigned",
    "lo fi rnb singer independent usa",
    "alternative rnb singer unsigned 2024",
    "melodic rap artist independent usa",
    "unsigned singing rapper usa 2024",
    "independent rnb artist no label 2024",
]

# ── PRODUCTION NEED SIGNALS ────────────────────────────────────────────────────
_NEEDS_PRODUCTION_KW = [
    "self.produc","self produc","home studio","bedroom producer",
    "diy music","looking for producer","need a producer","need beats",
    "unsigned","independent artist","indie artist","no label",
    "self.managed","self managed","own label","self.release",
    "demo","mixtape","recording artist","up and coming",
    "just started","new artist","emerging artist",
]
_MANAGED_KW = [
    "booking:","management:","managed by","represented by",
    "booking@","management@","press@","label@","pr contact",
    "warner","universal","sony music","atlantic records",
    "columbia records","interscope","def jam","rca records",
]
_PRODUCER_BIO_KW = [
    "record producer","hip hop producer","hip-hop producer",
    "rap producer","rnb producer","trap producer",
    "producer and artist","artist and producer",
    "beat producer","music producer","executive producer",
    "beats by","prod by","prod.","beatsmith",
]

def detect_needs(artist, bio):
    if not bio:
        return
    b = bio.lower()
    needs_hits    = [kw for kw in _NEEDS_PRODUCTION_KW if kw in b]
    managed_hits  = [kw for kw in _MANAGED_KW          if kw in b]
    producer_hits = [kw for kw in _PRODUCER_BIO_KW      if kw in b]
    if producer_hits:
        artist["needs"] = f"producer: {', '.join(producer_hits[:2])}"
    elif managed_hits:
        artist["needs"] = f"managed/label: {', '.join(managed_hits[:2])}"
    elif needs_hits:
        artist["needs"] = f"indie/DIY: {', '.join(needs_hits[:3])}"

def extract_ig(text):
    if not text: return None
    m = re.search(r'instagram\.com/([A-Za-z0-9_.]{3,30})(?:/|\?|"|\s|$)', text, re.I)
    if m:
        h = m.group(1).rstrip('/')
        if h.lower() not in {'p','reel','reels','stories','explore','accounts'}:
            return h
    return None

def make_artist(name, platform, platform_id, followers, listeners, genres, profile_url, image_url):
    return {
        "name": name, "platform": platform, "platform_id": platform_id,
        "followers": followers, "listeners": listeners,
        "genres": genres, "profile_url": profile_url, "image_url": image_url,
        "instagram": None, "email": None, "facebook": None, "phone": None,
        "ig_followers": None, "contact_quality": "none",
        "needs": None, "score": None, "score_reason": None, "status": "new",
    }

# ── SPOTIFY AUTH ───────────────────────────────────────────────────────────────
_token = None
_token_exp = 0

def get_token():
    global _token, _token_exp
    if _token and time.time() < _token_exp:
        return _token
    creds = b64encode(f"{SPOTIFY_CLIENT_ID}:{SPOTIFY_CLIENT_SECRET}".encode()).decode()
    try:
        r = requests.post("https://accounts.spotify.com/api/token",
            headers={"Authorization": f"Basic {creds}"},
            data={"grant_type": "client_credentials"}, timeout=10)
        d = r.json()
        if "error" in d:
            print(f"  [Spotify] Auth error: {d.get('error_description', d)}")
            return None
        _token     = d.get("access_token")
        _token_exp = time.time() + d.get("expires_in", 3600) - 60
        return _token
    except Exception as e:
        print(f"  [Spotify] Token request failed: {e}")
        return None

def sp(endpoint, params=None):
    token = get_token()
    if not token:
        return {}
    try:
        r = requests.get(
            f"https://api.spotify.com/v1/{endpoint}",
            headers={"Authorization": f"Bearer {token}"},
            params=params or {}, timeout=12)
        if r.status_code != 200:
            return {}
        return r.json()
    except:
        return {}

SP_PAGE_HEADERS = {"User-Agent": "Twitterbot/1.0"}

def spotify_monthly_listeners(artist_id):
    """Scrape Spotify artist page for actual monthly listener count."""
    if not artist_id:
        return None
    for attempt in range(3):
        try:
            r = requests.get(
                f"https://open.spotify.com/artist/{artist_id}",
                headers=SP_PAGE_HEADERS, timeout=15)
            if r.status_code == 429:
                time.sleep(5 * (attempt + 1))
                continue
            if r.status_code != 200:
                break
            m = re.search(r'([\d,.]+\s*[KkMmBb]?)\s+monthly\s+listener', r.text, re.I)
            if m:
                raw = m.group(1).strip().upper().replace(',','').replace(' ','')
                if 'K' in raw:   return int(float(raw.replace('K','')) * 1_000)
                elif 'M' in raw: return int(float(raw.replace('M','')) * 1_000_000)
                else:            return int(raw.replace('.',''))
        except:
            pass
        time.sleep(2)
    return None

# ── SPOTIFY SEARCH ─────────────────────────────────────────────────────────────
def spotify_keyword_search(query, pages=2):
    """Search Spotify by keyword. Uses Spotify monthly listener scrape — no Last.fm."""
    artists = []
    seen_ids = set()
    for page in range(pages):
        data = sp("search", {
            "q": query, "type": "artist",
            "limit": 10, "offset": page * 10, "market": "US"
        })
        items = data.get("artists", {}).get("items", [])
        if not items:
            break
        for item in items:
            name = item.get("name", "").strip()
            if not name or is_junk(name):
                continue
            aid = item.get("id", "")
            if aid in seen_ids:
                continue
            seen_ids.add(aid)

            sp_followers = item.get("followers", {}).get("total") or 0
            sp_popularity = item.get("popularity") or 0
            if sp_followers > MAX_FOLLOWERS or sp_popularity > 65:
                continue

            genres = item.get("genres", [])
            if is_blocked(genres, name=name):
                continue

            profile_url = item.get("external_urls", {}).get("spotify", "")
            image_url   = item["images"][0]["url"] if item.get("images") else ""

            listeners = spotify_monthly_listeners(aid)
            if listeners is None:
                # Fallback to followers if scrape fails — only if followers in range
                if sp_followers >= MIN_FOLLOWERS:
                    listeners = sp_followers
                else:
                    time.sleep(0.1)
                    continue
            if listeners > MAX_LISTENERS or listeners < MIN_LISTENERS:
                time.sleep(0.1)
                continue

            artist = make_artist(name, "spotify", aid,
                                 followers=sp_followers, listeners=listeners,
                                 genres=genres[:5], profile_url=profile_url,
                                 image_url=image_url)
            artists.append(artist)
            time.sleep(0.2)
        time.sleep(0.3)
    return artists

# ── SUPABASE DEDUPLICATION ─────────────────────────────────────────────────────
def get_existing_db_leads():
    """Fetch all platform_ids and names already in Supabase to prevent duplicates."""
    if not SUPABASE_URL or not SUPABASE_KEY:
        return set(), set()
    headers = {
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}",
    }
    try:
        r = requests.get(
            f"{SUPABASE_URL}/rest/v1/artists",
            headers=headers,
            params={"select": "platform_id,name", "limit": 10000},
            timeout=15)
        data = r.json()
        if not isinstance(data, list):
            return set(), set()
        ids   = {a["platform_id"] for a in data if a.get("platform_id")}
        names = {a["name"].lower().strip() for a in data if a.get("name")}
        return ids, names
    except:
        return set(), set()

# ── INSTAGRAM INLINE SCAN ──────────────────────────────────────────────────────
_resolve_fn = None  # loaded lazily on first use to avoid module-level side effects

def _load_resolve():
    global _resolve_fn
    if _resolve_fn is not None:
        return True
    try:
        from resolve import resolve as fn
        _resolve_fn = fn
        return True
    except ImportError:
        return False

def scan_instagram(artist):
    """
    Run resolve.py on this artist inline during discovery.
    Sets contact_quality = 'found' or 'contactless'.
    Never passes stored --ig — always fresh search.

    High IG followers + low engagement = potentially buying followers = still unsigned.
    We do NOT skip based on ig_followers count — just note it for manual review.
    """
    if not _load_resolve():
        artist["contact_quality"] = "none"
        return

    try:
        result = _resolve_fn(
            artist["name"],
            platform=artist.get("platform", ""),
            profile_url=artist.get("profile_url", ""),
            # Never pass existing_ig — always fresh
        )

        ig           = result.get("instagram")
        ig_followers = result.get("ig_followers") or 0

        if ig:
            artist["instagram"]    = ig
            artist["ig_followers"] = ig_followers
            artist["contact_quality"] = "found"

            # High followers + potentially low engagement = still a potential lead
            # Don't skip — just flag in needs for manual review
            if ig_followers > 50_000:
                note = f"high_ig:{ig_followers:,} — verify engagement"
                artist["needs"] = (artist.get("needs") or "") + f" | {note}"

            print(f"    IG: @{ig} ({ig_followers:,} followers)")
        else:
            artist["contact_quality"] = "contactless"
            print(f"    No IG found — contactless")

        # Capture email if found
        if result.get("email"):
            artist["email"] = result["email"]

        # Update listeners if resolve found a more accurate count
        if result.get("listeners") and result["listeners"] > 0:
            artist["listeners"] = result["listeners"]

    except Exception as e:
        print(f"    IG scan error: {e}")
        artist["contact_quality"] = "contactless"

# ── CLAUDE SCORING ─────────────────────────────────────────────────────────────
def score_batch(artists):
    if not CLAUDE_API_KEY:
        for a in artists:
            a["score"] = 50
            a["score_reason"] = "No Claude API key"
        return artists

    batch = [{
        "index":         i,
        "name":          a["name"],
        "platform":      a["platform"],
        "listeners":     a.get("listeners") or a.get("followers", 0),
        "genres":        a.get("genres", [])[:5],
        "has_instagram": bool(a.get("instagram")),
        "ig_followers":  a.get("ig_followers") or 0,
        "needs":         a.get("needs") or "",
        "contact_quality": a.get("contact_quality", "none"),
    } for i, a in enumerate(artists)]

    prompt = f"""You are a lead-scoring analyst for Renegade Records — a recording studio (mixing, mastering, beat production, artist development) targeting INDEPENDENT artists who genuinely need professional help RIGHT NOW.

Sweet-spot client: solo performer, unsigned/self-managed, 1k–15k monthly listeners, R&B / Hip-Hop / Neo Soul / Trap Soul genre, US/Canada/UK/Australia/UAE, zero label backing, contactable directly.

SCORING RULES:
90-100  PERFECT: 1k–10k listeners + R&B/Hip-Hop/Neo Soul/Trap Soul + indie/DIY signals + no management
80-89   STRONG: 10k–20k listeners OR 1k–10k with neutral needs, genre matches
70-79   GOOD: 20k–35k listeners, genre matches, no management flags
60-69   BORDERLINE: good genre + under 20k but some flag (empty needs, minimal data)
0-59    DO NOT USE

HARD ZERO:
- Producer, beatmaker, DJ, audio engineer (even if they also perform)
- Radio station, playlist, compilation, orchestra, collective
- Genres outside target: reggaeton, afrobeats, K-pop, Bollywood, country, rock, EDM, house, jazz, classical
- Listeners above 35k
- needs contains: producer:, managed by, booking:, warner, universal, sony, atlantic, columbia

NOTE: high ig_followers with low engagement suggests bought followers — this can mean the artist is still unsigned and reachable. Do not penalize for high ig_followers alone.

Return ONLY valid JSON array:
[{{"index": 0, "score": 82, "reason": "One sentence citing listeners + genre + needs", "is_solo_artist": true}}]

Artists:
{json.dumps(batch)}"""

    try:
        r = requests.post("https://api.anthropic.com/v1/messages",
            headers={"x-api-key": CLAUDE_API_KEY,
                     "anthropic-version": "2023-06-01",
                     "content-type": "application/json"},
            json={"model": "claude-haiku-4-5-20251001", "max_tokens": 2000,
                  "messages": [{"role": "user", "content": prompt}]}, timeout=40)
        raw = r.json()["content"][0]["text"].strip()
        raw = re.sub(r"```json?\n?", "", raw).replace("```","").strip()
        for s in json.loads(raw):
            idx = s.get("index", -1)
            if 0 <= idx < len(artists):
                artists[idx]["score"]        = s.get("score", 0)
                artists[idx]["score_reason"] = s.get("reason", "")
                if not s.get("is_solo_artist", True):
                    artists[idx]["score"] = 0
    except Exception as e:
        print(f"  Scoring error: {e}")
        for a in artists:
            if a["score"] is None:
                a["score"] = 40
    return artists

# ── SAVE TO SUPABASE ───────────────────────────────────────────────────────────
def save(artists, session_id=None):
    ts       = session_id or datetime.now().strftime("%Y%m%d_%H%M")
    filename = f"leads_{ts}.json"
    with open(filename, "w", encoding="utf-8") as f:
        json.dump(artists, f, indent=2, ensure_ascii=False)
    print(f"\n  Saved -> {filename}")

    if not SUPABASE_URL or not SUPABASE_KEY:
        print("  [Supabase] No credentials — saved locally only")
        return filename

    headers = {
        "apikey": SUPABASE_KEY, "Authorization": f"Bearer {SUPABASE_KEY}",
        "Content-Type": "application/json",
        "Prefer": "resolution=ignore-duplicates,return=minimal"
    }
    ok = fail = 0
    first_error = None
    _session_col_missing = False

    for a in artists:
        payload = {
            "name":            a["name"],
            "platform":        a["platform"],
            "platform_id":     a.get("platform_id") or a["name"],
            "followers":       a.get("followers", 0),
            "listeners":       a.get("listeners") or a.get("followers", 0),
            "genres":          json.dumps(a.get("genres", [])),
            "profile_url":     a.get("profile_url", ""),
            "image_url":       a.get("image_url", ""),
            "instagram":       a.get("instagram"),
            "facebook":        a.get("facebook"),
            "phone":           a.get("phone"),
            "email":           a.get("email"),
            "ig_followers":    a.get("ig_followers"),
            "contact_quality": a.get("contact_quality", "none"),
            "needs":           a.get("needs"),
            "score":           a.get("score", 0),
            "score_reason":    a.get("score_reason", ""),
            "status":          "new",
            "discovered_at":   datetime.now().isoformat(),
        }
        if not _session_col_missing:
            payload["session_id"] = ts

        try:
            res = requests.post(f"{SUPABASE_URL}/rest/v1/artists",
                                headers=headers, json=payload, timeout=10)
            if res.status_code in (200, 201):
                ok += 1
            elif "session_id" in res.text and res.status_code in (400, 422):
                _session_col_missing = True
                payload.pop("session_id", None)
                res2 = requests.post(f"{SUPABASE_URL}/rest/v1/artists",
                                     headers=headers, json=payload, timeout=10)
                if res2.status_code in (200, 201):
                    ok += 1
                    if first_error is None:
                        first_error = "MISSING COLUMN: ALTER TABLE artists ADD COLUMN IF NOT EXISTS session_id text;"
                else:
                    fail += 1
            else:
                fail += 1
                if first_error is None:
                    first_error = f"HTTP {res.status_code}: {res.text[:200]}"
        except Exception as e:
            fail += 1
            if first_error is None:
                first_error = str(e)

    if first_error:
        print(f"  [Supabase] First error -> {first_error}")
    print(f"  Synced {ok}/{len(artists)} to Supabase {'OK' if fail == 0 else f'({fail} failed)'}")
    return filename

# ── MAIN ───────────────────────────────────────────────────────────────────────
def run():
    session_id = datetime.now().strftime("%Y%m%d_%H%M")
    print("\n" + "="*60)
    print("  RENEGADE RECORDS — Discovery Engine v8")
    print("  Spotify Only | Regions: USA, Canada, UK, Australia, UAE")
    print(f"  Target: {TARGET_LEADS} new leads | Max listeners: {MAX_LISTENERS:,}")
    print(f"  Session: {session_id}")
    print("="*60)

    # ── Load existing DB leads for deduplication ──────────────────────────────
    print("\n  Checking existing leads in Supabase...")
    existing_ids, existing_names = get_existing_db_leads()
    print(f"  Existing leads in DB: {len(existing_ids)}")

    # ── Gather all candidates ─────────────────────────────────────────────────
    all_candidates = []
    seen_in_session = set()

    def add(artists_list):
        for a in artists_list:
            pid  = a.get("platform_id", "")
            name = a["name"].lower().strip()
            # Skip if already in Supabase
            if pid in existing_ids or name in existing_names:
                continue
            # Skip if already seen this session
            if pid in seen_in_session or name in seen_in_session:
                continue
            seen_in_session.add(pid)
            seen_in_session.add(name)
            all_candidates.append(a)

    print("\n[1/1] Spotify...")
    if SPOTIFY_CLIENT_ID and SPOTIFY_CLIENT_SECRET:
        for i, query in enumerate(SPOTIFY_KEYWORD_SEARCHES, 1):
            found = spotify_keyword_search(query)
            if found:
                print(f"  [{i}/{len(SPOTIFY_KEYWORD_SEARCHES)}] '{query}' -> {len(found)} artists")
            add(found)
            time.sleep(0.3)
        print(f"  Spotify candidates so far: {len(all_candidates)}")
    else:
        print("  SKIPPED — add SPOTIFY_CLIENT_ID + SPOTIFY_CLIENT_SECRET to .env")

    # Sort lowest listeners first — most reachable/hungry artists first
    all_candidates.sort(key=lambda a: a.get("listeners") or a.get("followers") or 0)

    print(f"\n{'='*60}")
    print(f"  Total new candidates (not in DB): {len(all_candidates)}")
    print(f"  Now scanning Instagram for each — stops at {TARGET_LEADS} saves")
    print(f"{'='*60}\n")

    if not all_candidates:
        print("  No new candidates found. All artists already in DB or none passed filters.")
        return

    # ── Instagram scan loop — runs until TARGET_LEADS saved ──────────────────
    new_leads = []

    for i, artist in enumerate(all_candidates):
        if len(new_leads) >= TARGET_LEADS:
            break

        listeners = artist.get("listeners") or artist.get("followers") or 0

        # Hard cap — skip immediately, don't even scan IG
        if listeners > MAX_LISTENERS:
            print(f"  SKIP {artist['name']}: {listeners:,} listeners (over {MAX_LISTENERS:,} cap)")
            continue

        print(f"  [{i+1}/{len(all_candidates)}] {artist['name']} — {listeners:,} listeners")
        print(f"    Scanning Instagram...")

        scan_instagram(artist)

        status = "OK IG found" if artist.get("instagram") else "- contactless"
        print(f"    {status} — Lead #{len(new_leads)+1}/{TARGET_LEADS} saved")
        new_leads.append(artist)
        time.sleep(0.5)

    # ── Summary ───────────────────────────────────────────────────────────────
    found_ig    = sum(1 for a in new_leads if a.get("instagram"))
    contactless = sum(1 for a in new_leads if not a.get("instagram"))

    print(f"\n{'='*60}")
    print(f"  SCAN COMPLETE")
    print(f"  New leads saved  : {len(new_leads)}")
    print(f"  Instagram found  : {found_ig}")
    print(f"  Contactless      : {contactless}")
    print(f"{'='*60}")

    if not new_leads:
        print("  No new leads found.")
        return

    # ── Save unscored leads to dashboard now ──────────────────────────────────
    print(f"\n  Saving {len(new_leads)} leads to dashboard (unscored)...")
    save(new_leads, session_id)
    print(f"  Leads are live. Open New Search tab in dashboard.")

    # ── Claude scoring ────────────────────────────────────────────────────────
    print(f"\n{'='*60}")
    print(f"  CLAUDE AI SCORING")
    est = (len(new_leads) / 20) * 0.06
    print(f"  Artists to score : {len(new_leads)}")
    print(f"  Estimated cost   : ~${est:.2f}")
    print(f"{'='*60}")

    no_prompt = "--no-prompt" in sys.argv
    ans = "yes" if no_prompt else input("\n  Run Claude AI scoring now? (yes/no): ").strip().lower()
    if ans in ["yes", "y"]:
        print(f"\n  Scoring in batches of 20...")
        for i in range(0, len(new_leads), 20):
            score_batch(new_leads[i:i+20])
            print(f"  Scored {min(i+20, len(new_leads))}/{len(new_leads)}")
            time.sleep(1)

        def _passes_hard_filter(a):
            needs = (a.get("needs") or "").lower()
            genres = a.get("genres") or []
            if is_blocked(genres):
                return False
            label_kw = ["managed by","booking:","management:","booking@",
                        "warner","universal","sony","atlantic","columbia","interscope","def jam","rca"]
            return not any(kw in needs for kw in label_kw)

        qualified = sorted(
            [a for a in new_leads if (a.get("score") or 0) >= MIN_SCORE and _passes_hard_filter(a)],
            key=lambda x: x.get("score", 0), reverse=True
        )

        print(f"\n  Qualified (score >= {MIN_SCORE}): {len(qualified)}")
        print(f"\n  TOP LEADS")
        print(f"  {'Score':<7} {'Name':<28} {'IG':<22} {'Listeners':<12} {'Genres'}")
        print("  " + "─"*75)
        for a in qualified[:20]:
            ig    = f"@{a['instagram']}" if a.get("instagram") else "—"
            genre = ", ".join(a.get("genres", [])[:2]) or "—"
            print(f"  [{a['score']:>3}]  {a['name']:<28} {ig:<22} {str(a.get('listeners',0)):<12} {genre}")

        print(f"\n  Updating dashboard with scores...")
        save(qualified, session_id)
        print(f"  Done — {len(qualified)} qualified leads live in dashboard.")
    else:
        print("  Skipped scoring. Leads are live unscored.")

    print("\n" + "="*60)
    print(f"  Session {session_id} complete.")
    print("="*60 + "\n")

if __name__ == "__main__":
    run()
