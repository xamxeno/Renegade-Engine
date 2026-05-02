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

import os, json, time, re, requests, io, random
from datetime import datetime
from base64 import b64encode
from dotenv import load_dotenv

KEYWORD_STATS_FILE = os.path.join(os.path.dirname(__file__), "keyword_stats.json")

def load_keyword_stats():
    try:
        with open(KEYWORD_STATS_FILE, "r") as f:
            return json.load(f)
    except:
        return {}

def save_keyword_stats(stats):
    try:
        with open(KEYWORD_STATS_FILE, "w") as f:
            json.dump(stats, f, indent=2)
    except:
        pass

def weighted_shuffle(keywords, stats):
    """Shuffle keywords but bias toward ones that historically find more artists."""
    def weight(kw):
        s = stats.get(kw, {})
        runs = s.get("runs", 0)
        hits = s.get("hits", 0)
        # New keywords get a neutral weight of 1.0
        if runs == 0:
            return 1.0
        avg = hits / runs
        # Score 0–3: low performers get 0.3, high performers get 3.0
        return max(0.3, min(3.0, 0.5 + avg * 1.5))

    weights = [weight(kw) for kw in keywords]
    # Weighted random sort — shuffle with probability proportional to weight
    paired = list(zip(weights, keywords))
    random.shuffle(paired)
    paired.sort(key=lambda x: x[0] + random.random() * 0.5, reverse=True)
    return [kw for _, kw in paired]

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
    # Generic/placeholder names that Spotify returns from keyword searches
    "unsigned","untitled","unspecified","unknown","unnamed","no name",
    "contactless","n/a","tbd","tba","placeholder","test","demo",
    "artist","rapper","singer","vocalist","musician","performer",
    "independent","indie artist","new artist","emerging artist",
    "upcoming artist","rising artist","unsigned artist",
]

# Exact-match junk — name must equal one of these (case-insensitive)
JUNK_EXACT = {
    "prod","prods","production","productions","beats","beat","music",
    "untitled","unnamed","unknown","n/a","tba","tbd","demo","test",
    "artist","rapper","singer","musician","vocalist","performer",
    "unsigned","unspecified","insignificant","anonymous",
    "rnb","r&b","hiphop","hip hop","soul","trap","pop","indie","alternative",
}

PRODUCER_NAME_PATTERNS = [
    "prod.", "prod by", "prodby", "prod_by", "produced by", "producedby", "xproducer", "beatz",
    "tha producer", "the producer", "on the beat", "type beat",
    "producer", "beatmaker", "beat maker",
    "dj-", "dj_", "deejay", "disc jockey", "turntablist",
]

# Handles that are clearly generic/wrong — reject even if resolve returns them
GENERIC_IG_HANDLES = {
    "rnb","rb","hiphop","hiphopmusic","rnbmusic","soulmusic","trapmusic",
    "music","rap","soul","trap","pop","indie","alternative","rock","jazz",
    "unsigned","unsigned_","independentartist","newartist","emergingartist",
    "artist","singer","rapper","vocalist","musician","performer",
    "soulsister","jksoul","rnbstylerz","rnbdjs","alternativerockmusic",
}

# Genre-description names that look like category pages, not real artists
_GENRE_NAME_RE = re.compile(
    r'^(r&b|r\'n\'b|rnb|hip.?hop|soul|trap|pop|indie|alternative|rock|jazz|'
    r'electronic|edm|house|techno|lo.?fi|neo.?soul|afro|drill|grime|uk rap)'
    r'(\s*[&+x]\s*(rock|pop|soul|hip.?hop|rnb|rap|trap|edm|house))?'
    r'(\s+(music|sounds?|vibes?|nation|stylez?|stylerz|boyz|girlz|gang|'
    r'crew|squad|family|collective|refreshed|reloaded|remixed|session))?$',
    re.I
)

def is_junk(name):
    n = name.lower().strip()
    if n in JUNK_EXACT:
        return True
    if any(kw in n for kw in JUNK_KEYWORDS):
        return True
    if any(p in n for p in PRODUCER_NAME_PATTERNS):
        return True
    # Word-boundary DJ check — catches "dj", "djs", "rnb djs", "dj frank"
    if re.search(r'\bdjs?\b', n):
        return True
    # Name looks like a genre category/description page, or genre word + suffix
    if re.match(r'^(rnb|r&b|hiphop|hip hop|soul|trap|rap|pop)(stylerz?|stylez?|boyz?|girlz?|nation|squad|gang|family|crew|vibes?|music|sounds?)?$', n):
        return True
    if _GENRE_NAME_RE.match(n):
        return True
    # Name contains "&" between genre words (e.g. "Alternative & Rock")
    if re.search(r'\b(rock|pop|soul|rnb|rap|trap|jazz|indie)\s*&\s*(rock|pop|soul|rnb|rap|trap|jazz|indie)\b', n):
        return True
    if len(name.split()) > 5:
        return True
    if sum(c.isdigit() for c in name) > 3:
        return True
    # All-caps names 6+ chars are usually labels/playlists, not artists
    letters = [c for c in name if c.isalpha()]
    if len(letters) >= 6 and all(c.isupper() for c in letters):
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
# Keep queries SHORT (2-4 words) — Spotify search is NAME-based not descriptor-based.
# Longer phrases like "dark rnb vocals smooth" return 0 results.
# Avoid standalone words that ARE artist names: "unsigned", "independent", "artist",
# "singer", "rapper" — the junk filters now handle any that slip through.
SPOTIFY_KEYWORD_SEARCHES = [
    # ── Genre/style terms (short — Spotify indexes these) ────────────────────
    "trap soul",
    "neo soul",
    "dark rnb",
    "alternative rnb",
    "melodic rap",
    "bedroom pop rnb",
    "lo fi rnb",
    "bedroom rnb",
    "trap rnb",
    "conscious rap",
    "afro soul uk",
    "melodic drill",
    "sad rnb",
    "slow jam rnb",
    "acoustic soul",
    "rnb pop",
    "soul rap",
    "underground rnb",
    "underground hip hop",
    "street soul",
    # ── USA cities + genre ───────────────────────────────────────────────────
    "atlanta trap soul",
    "atlanta rnb",
    "new york melodic rap",
    "new york rnb",
    "los angeles rnb",
    "chicago soul rap",
    "houston rap",
    "miami rnb",
    "detroit soul",
    "memphis rap",
    "charlotte rnb",
    "philadelphia rap",
    "dallas rnb",
    "seattle rnb",
    "dc rap rnb",
    "nashville rnb",
    "new orleans soul",
    "baltimore rap",
    "st louis rap",
    "compton rap",
    "brooklyn rap",
    "bronx hip hop",
    # ── Canada ───────────────────────────────────────────────────────────────
    "toronto rnb",
    "toronto trap",
    "toronto melodic rap",
    "montreal rnb",
    "vancouver rap",
    # ── UK ───────────────────────────────────────────────────────────────────
    "london rnb",
    "london drill",
    "birmingham uk rnb",
    "manchester rap",
    "leeds rap",
    "bristol rnb",
    "uk afrobeats rnb",
    "uk trap soul",
    "uk neo soul",
    # ── Australia ────────────────────────────────────────────────────────────
    "sydney rnb",
    "melbourne rap",
    "brisbane hip hop",
    "australia trap soul",
    # ── UAE ──────────────────────────────────────────────────────────────────
    "dubai rnb",
    "dubai rap",
    # ── Additional style/vibe searches ───────────────────────────────────────
    "self produced rnb",
    "diy hip hop",
    "bedroom soul",
    "acoustic rnb",
    "guitar rnb",
    "piano rnb",
    "emotional rap",
    "pain rap",
    "heartbreak rnb",
    "late night rnb",
    "chill rnb",
    "smooth soul rap",
    "gritty rap street",
    "melodic trap",
    "autotune trap rnb",
    "gospel rap",
    "drill rnb",
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
def spotify_keyword_search(query, pages=4):
    """Search Spotify by keyword. Uses Spotify monthly listener scrape — no Last.fm."""
    artists = []
    seen_ids = set()
    raw_count = skip_junk = skip_pop = skip_region = skip_listeners = 0
    for page in range(pages):
        data = sp("search", {
            "q": query, "type": "artist",
            "limit": 10, "offset": page * 10, "market": "US"
        })
        items = data.get("artists", {}).get("items", [])
        if not items:
            break
        raw_count += len(items)
        for item in items:
            name = item.get("name", "").strip()
            if not name or is_junk(name):
                skip_junk += 1
                continue
            aid = item.get("id", "")
            if aid in seen_ids:
                continue
            seen_ids.add(aid)

            sp_followers = item.get("followers", {}).get("total") or 0
            sp_popularity = item.get("popularity") or 0
            if sp_followers > MAX_FOLLOWERS or sp_popularity > 65:
                skip_pop += 1
                continue

            genres = item.get("genres", [])
            if is_blocked(genres, name=name):
                skip_region += 1
                continue

            profile_url = item.get("external_urls", {}).get("spotify", "")
            image_url   = item["images"][0]["url"] if item.get("images") else ""

            listeners = spotify_monthly_listeners(aid)
            if listeners is None:
                # Scrape failed — estimate from followers or accept with floor estimate
                # Small artists often have very few followers but real listeners
                if sp_followers >= MIN_FOLLOWERS:
                    listeners = sp_followers
                elif sp_followers > 0:
                    # Accept with rough estimate — Claude scoring will filter low-quality
                    listeners = max(sp_followers * 8, MIN_LISTENERS)
                else:
                    # Zero followers AND scrape failed — genuinely unknown, skip
                    skip_listeners += 1
                    continue
            if listeners > MAX_LISTENERS or listeners < MIN_LISTENERS:
                skip_listeners += 1
                continue

            artist = make_artist(name, "spotify", aid,
                                 followers=sp_followers, listeners=listeners,
                                 genres=genres[:5], profile_url=profile_url,
                                 image_url=image_url)
            artists.append(artist)
            time.sleep(0.2)
        time.sleep(0.3)

    if raw_count > 0:
        print(f"    '{query}': {raw_count} raw → -{skip_junk} junk, -{skip_pop} popular, -{skip_region} region, -{skip_listeners} listeners → {len(artists)} pass")
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

        if ig and ig.lower() not in GENERIC_IG_HANDLES and ig_followers > 0:
            artist["instagram"]    = ig
            artist["ig_followers"] = ig_followers
            artist["contact_quality"] = "found"
            print(f"    IG: @{ig} ({ig_followers:,} followers)")
        else:
            if ig and (ig.lower() in GENERIC_IG_HANDLES or ig_followers == 0):
                print(f"    IG rejected: @{ig} (generic handle or 0 followers)")
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
        kw_stats = load_keyword_stats()
        ordered_queries = weighted_shuffle(SPOTIFY_KEYWORD_SEARCHES, kw_stats)
        for i, query in enumerate(ordered_queries, 1):
            before = len(all_candidates)
            found = spotify_keyword_search(query)
            add(found)
            after = len(all_candidates)
            new_hits = after - before
            # Track performance
            s = kw_stats.setdefault(query, {"runs": 0, "hits": 0})
            s["runs"] += 1
            s["hits"] += new_hits
            print(f"  [{i}/{len(ordered_queries)}] '{query}' -> {new_hits} new (total: {len(all_candidates)})")
            time.sleep(0.3)
            # Stop searching once we have enough candidates
            if len(all_candidates) >= TARGET_LEADS * 3:
                print(f"  Enough candidates ({len(all_candidates)}) — skipping remaining keywords")
                break
        save_keyword_stats(kw_stats)
        print(f"  Spotify candidates: {len(all_candidates)}")
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

    # ── Take up to TARGET_LEADS * 5 candidates for scoring pool ──────────────
    pool = []
    for artist in all_candidates:
        if len(pool) >= TARGET_LEADS * 5:
            break
        listeners = artist.get("listeners") or artist.get("followers") or 0
        if listeners > MAX_LISTENERS:
            continue
        artist["contact_quality"] = "none"
        pool.append(artist)

    print(f"\n{'='*60}")
    print(f"  {len(pool)} candidates ready for scoring")
    print(f"{'='*60}")

    # ── Claude scoring BEFORE save — fixes null scores in Supabase ───────────
    def _passes_hard_filter(a):
        needs = (a.get("needs") or "").lower()
        genres = a.get("genres") or []
        if is_blocked(genres):
            return False
        label_kw = ["managed by","booking:","management:","booking@",
                    "warner","universal","sony","atlantic","columbia","interscope","def jam","rca"]
        return not any(kw in needs for kw in label_kw)

    no_prompt = "--no-prompt" in sys.argv
    if CLAUDE_API_KEY:
        est = (len(pool) / 20) * 0.06
        print(f"\n  CLAUDE AI SCORING — {len(pool)} artists (~${est:.2f})")
        ans = "yes" if no_prompt else input("  Run scoring? (yes/no): ").strip().lower()
        if ans in ["yes", "y"]:
            for i in range(0, len(pool), 20):
                score_batch(pool[i:i+20])
                print(f"  Scored {min(i+20, len(pool))}/{len(pool)}")
                time.sleep(1)
        else:
            print("  Skipped. All candidates will be saved unscored.")
    else:
        print("  No CLAUDE_API_KEY — skipping scoring")

    # ── Filter to qualified leads ─────────────────────────────────────────────
    qualified = sorted(
        [a for a in pool if (a.get("score") or 0) >= MIN_SCORE and _passes_hard_filter(a)],
        key=lambda x: x.get("score", 0), reverse=True
    )
    # If scoring was skipped, take top TARGET_LEADS by listeners
    if not qualified:
        qualified = [a for a in pool if _passes_hard_filter(a)][:TARGET_LEADS]

    new_leads = qualified[:TARGET_LEADS]

    print(f"\n  Qualified (score >= {MIN_SCORE}): {len(qualified)}")
    print(f"  Saving top {len(new_leads)} to dashboard\n")
    print(f"  {'Score':<6} {'Name':<28} {'Listeners':<12} {'Genres'}")
    print("  " + "─"*65)
    for a in new_leads[:20]:
        genre = ", ".join(a.get("genres", [])[:2]) or "—"
        score = a.get("score") or "—"
        print(f"  [{str(score):>3}]  {a['name']:<28} {str(a.get('listeners',0)):<12} {genre}")

    if not new_leads:
        print("  No qualified leads — try adjusting MIN_SCORE or adding new keywords.")
        return

    # ── Save — scores already set, so Supabase gets full data ────────────────
    save(new_leads, session_id)
    print(f"\n  {len(new_leads)} leads live. Enrichment worker will find Instagrams.")
    print("\n" + "="*60)
    print(f"  Session {session_id} complete.")
    print("="*60 + "\n")

if __name__ == "__main__":
    run()
