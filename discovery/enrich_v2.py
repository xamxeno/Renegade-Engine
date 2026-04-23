import sys, io
if __name__ == "__main__" or "--json" in sys.argv:
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

"""
Renegade Records -- Enrichment Engine v2  (PLAIN REQUESTS REWRITE)

Root cause of all previous failures:
  Selenium/headless Chrome is detected by Spotify and served a stripped page
  with no social links. Claude's own web_fetch tool uses a plain HTTP GET
  (no JS engine) and receives the full SSR HTML including Instagram links.

Solution: replicate Claude's fetch exactly — plain requests.get() with
crawler-style Accept headers. No Selenium. No Playwright. No browser at all.

Pipeline:
  1. Plain HTTP GET of Spotify artist page  (same method Claude uses)
  2. Parse all external links + bio + listeners from the HTML
  3. Follow Linktree/Beacons/bio.link one level deep
  4. Scrape artist website if found
  5. Instagram verification (soft-pass if blocked)
  6. DuckDuckGo search fallback
  7. Claude AI fallback
"""

import re, json, time, random, os, argparse, asyncio
import requests
from bs4 import BeautifulSoup
from urllib.parse import quote_plus, urljoin, urlparse
from dotenv import load_dotenv

load_dotenv()

CLAUDE_API_KEY = os.getenv("CLAUDE_API_KEY", "")
LASTFM_API_KEY = os.getenv("LASTFM_API_KEY", "156d007301853d76f0d41665092f879a")

_JSON_MODE = False

def log(*args):
    msg = " ".join(str(a) for a in args)
    if _JSON_MODE:
        print(msg, file=sys.stderr, flush=True)
    else:
        print(msg, flush=True)

# ── PATTERNS ──────────────────────────────────────────────────────────────────

IG_RE     = re.compile(r'(?:instagram\.com/|@)([A-Za-z0-9](?:[A-Za-z0-9_.]{0,28}[A-Za-z0-9])?)/?(?:\?[^\s"\'<>]*)?', re.I)
EMAIL_RE  = re.compile(r'[a-zA-Z0-9+_.%\-]+@[a-zA-Z0-9\-]+\.[a-zA-Z]{2,}')
TIKTOK_RE = re.compile(r'tiktok\.com/@([A-Za-z0-9_.]{1,40})/?', re.I)

BAD_IG = {
    'p','reel','reels','stories','explore','accounts','about','help',
    'legal','privacy','safety','directory','music','search','instagram',
    'facebook','twitter','youtube','spotify','tiktok','soundcloud',
    'login','signup','challenge','graphql','api','web','www',
    'keyframes','media','import','charset','supports','style','styles',
    'script','scripts','undefined','null','none','true','false',
    'share','sharer','photo','photos','video','videos','live',
    'spotifyus','spotifyuk','spotifynews','spotifyloud','spotifyforartists','spotifycharts',
    'popular','trending','featured','official','verified',
    'artist','artists','musician','musicians',
    'follow','followers','following','likes','posts',
    'new','latest','top','best','more','view','views',
    'home','feed','tag','tags','location','embed','cdn','static',
    'profile','profiles','page','pages','site','sites',
    'link','links','url','redirect','click','download','app','store',
    'contact','email','mail','newsletter','subscribe',
    'press','news','blog','post','article',
    'stream','streaming','listen','play','player',
    'tour','tickets','merch','shop','buy','get',
    'here','this','that','with','from','your','their',
    'have','been','will','would','could','should',
}

SPOTIFY_OWNED = {
    'spotify','spotifyus','spotifyuk','spotifynews',
    'spotifyloud','spotifyforartists','spotifycharts',
}

def clean_ig(handle):
    if not handle: return None
    h = handle.strip().lstrip('@').split('?')[0].rstrip('/')
    h = h.rstrip('.,;:!?')  # trailing punctuation is never part of a valid handle
    h = h.lstrip('.')       # IG handles can't start with a period
    if len(h) < 2 or len(h) > 30: return None
    if h.lower() in BAD_IG: return None
    if h.lower() in SPOTIFY_OWNED: return None
    if not re.match(r'^[A-Za-z0-9._]+$', h): return None
    return h

def extract_ig(text):
    for m in IG_RE.finditer(text):
        h = clean_ig(m.group(1))
        if h: return h
    return None

# Text-pattern extractor — handles bio lines like:
#   "Instagram - Selfmadedully"   (SoundCloud style)
#   "IG: selfmadedully"
#   "@selfmadedully"
#   "instagram.com/selfmadedully" already handled by IG_RE above
TEXT_IG_RE = re.compile(
    r'(?:'
    r'instagram\s*[-:@]\s*'      # "Instagram - " or "Instagram: " or "Instagram @ "
    r'|(?<!\w)@'                  # bare @handle (not inside a word)
    r'|ig\s*[-:@]\s*'             # "IG: " / "IG - "
    r')'
    r'([A-Za-z0-9][A-Za-z0-9_.]{1,28}[A-Za-z0-9])',
    re.I
)

def extract_ig_from_text(text):
    """Extract IG handle from bio-style text like 'Instagram - Handle' or 'IG: handle'."""
    if not text:
        return None
    # Try URL format first
    h = extract_ig(text)
    if h:
        return h
    # Try text format
    for m in TEXT_IG_RE.finditer(text):
        h = clean_ig(m.group(1))
        if h:
            return h
    return None

def extract_email(text):
    for e in EMAIL_RE.findall(text):
        if not any(j in e.lower() for j in ['noreply','example.','sentry.','spotify.','apple.','google.']):
            return e
    return None

def extract_tiktok(text):
    m = TIKTOK_RE.search(text)
    return m.group(1) if m else None

# ── HTTP FETCH ────────────────────────────────────────────────────────────────
# Try multiple User-Agent strings — Spotify responds differently to each.
# Claude's internal fetch tool gets the full SSR page; we replicate that here
# by cycling through UAs until we get a full response (>50k chars).

UA_LIST = [
    # Claude-style crawler UA (worked in Claude's own fetch)
    "Mozilla/5.0 (compatible; ClaudeBot/1.0; +https://www.anthropic.com)",
    # Standard Chrome on Windows
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    # Safari on Mac
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_4) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4 Safari/605.1.15",
    # Googlebot
    "Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)",
    # curl-style (very simple, sometimes bypasses JS-detection)
    "curl/8.5.0",
]

def fetch(url, timeout=15):
    """Try multiple UAs until we get a substantial response."""
    for ua in UA_LIST:
        try:
            headers = {
                "User-Agent": ua,
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "en-US,en;q=0.9",
                "Accept-Encoding": "gzip, deflate",
                "Cache-Control": "no-cache",
            }
            r = requests.get(url, headers=headers, timeout=timeout, allow_redirects=True)
            if r.status_code == 200 and len(r.text) > 20000:
                log(f"  fetch OK ({len(r.text):,} chars) UA={ua[:40]}")
                return r.text
            elif r.status_code == 200:
                log(f"  fetch thin ({len(r.text):,} chars) UA={ua[:40]} — trying next")
        except Exception as e:
            log(f"  fetch error ({ua[:30]}): {e}")
    # Return whatever we got last even if thin
    try:
        r = requests.get(url, headers={"User-Agent": UA_LIST[1]}, timeout=timeout)
        if r.status_code == 200:
            return r.text
    except: pass
    return None


def fetch_spotify_via_api(artist_id):
    """
    Get track names + basic artist data via Spotify's anonymous token API.
    """
    result = {"top_tracks": [], "monthly_listeners": None, "name": ""}
    try:
        log(f"  [v2] API: fetching anonymous token...")
        token_r = requests.get(
            "https://open.spotify.com/get_access_token?reason=transport&productType=web_player",
            headers={"User-Agent": UA_LIST[1], "Referer": "https://open.spotify.com/"},
            timeout=10
        )
        log(f"  [v2] API: token status={token_r.status_code}")
        if token_r.status_code != 200:
            log(f"  [v2] API: token fetch failed: {token_r.text[:100]}")
            return result
        token = token_r.json().get("accessToken", "")
        log(f"  [v2] API: token={'OK len='+str(len(token)) if token else 'EMPTY'}")
        if not token:
            return result

        auth = {"Authorization": f"Bearer {token}"}

        ar = requests.get(f"https://api.spotify.com/v1/artists/{artist_id}", headers=auth, timeout=10)
        log(f"  [v2] API: artist endpoint status={ar.status_code}")
        if ar.status_code == 200:
            result["name"] = ar.json().get("name", "")

        tr = requests.get(
            f"https://api.spotify.com/v1/artists/{artist_id}/top-tracks?market=US",
            headers=auth, timeout=10
        )
        log(f"  [v2] API: top-tracks status={tr.status_code}")
        if tr.status_code == 200:
            result["top_tracks"] = [t["name"] for t in tr.json().get("tracks", [])[:5]]
        else:
            log(f"  [v2] API: top-tracks error: {tr.text[:100]}")

        log(f"  [v2] API result: name='{result['name']}' tracks={result['top_tracks']}")
    except Exception as e:
        log(f"  [v2] Spotify API error: {e}")
    return result


# ── STEP 1: SPOTIFY PAGE — plain HTTP fetch ────────────────────────────────────

def scrape_spotify_page(profile_url):
    """
    Fetch the Spotify artist page with a plain HTTP GET — no browser needed.
    Falls back to Spotify's anonymous token API to get track names when the
    HTML page returns a thin/bot-detected shell.
    Returns: { links, bio, monthly_listeners, followers, top_tracks }
    """
    result = {"links": [], "bio": "", "monthly_listeners": None, "followers": None, "top_tracks": []}

    # Extract artist ID upfront for API fallback
    artist_id = ""
    m_id = re.search(r'/artist/([A-Za-z0-9]+)', profile_url)
    if m_id:
        artist_id = m_id.group(1)

    log(f"  [v2] Fetching Spotify page (plain HTTP — no browser)...")
    html = fetch(profile_url)
    if not html:
        log(f"  [v2] Spotify page fetch failed — check network")
        # Still try API for track names
        if artist_id:
            api_data = fetch_spotify_via_api(artist_id)
            result["top_tracks"] = api_data["top_tracks"]
        return result

    has_ig = 'instagram' in html.lower()
    page_size = len(html)
    log(f"  [v2] Got {page_size:,} chars — instagram in source: {has_ig}")

    soup = BeautifulSoup(html, "html.parser")

    # ── Top track names — extract BEFORE link filtering (track links are spotify.com) ──
    tracks = []
    for a in soup.find_all("a", href=True):
        if "/track/" in a["href"]:
            title = a.get_text(strip=True)
            # Filter out junk: numbers only, too short, duplicates
            if title and len(title) > 1 and not title.isdigit() and title not in tracks:
                tracks.append(title)
    result["top_tracks"] = tracks[:5]
    log(f"  [v2] Tracks from HTML: {result['top_tracks']}")

    # If still no tracks (curl page may use JS rendering for track list),
    # fall back to Spotify API which always returns them
    if not result["top_tracks"] and artist_id:
        log(f"  [v2] No tracks in HTML — fetching via Spotify API...")
        api_data = fetch_spotify_via_api(artist_id)
        result["top_tracks"] = api_data["top_tracks"]

    # ── Extract all external links ─────────────────────────────────────────────
    SKIP_DOMAINS = ['spotify.com','spotifycdn.com','scdn.co','onetrust.com',
                    'spotifyforartists.com','spotify.design']
    seen = set()
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if not href.startswith("http"): continue
        if any(s in href for s in SKIP_DOMAINS): continue
        if href not in seen:
            seen.add(href)
            result["links"].append(href)

    # Remove Spotify's own social accounts (appear in footer of every page)
    result["links"] = [
        l for l in result["links"]
        if not any(f"instagram.com/{h}" in l.lower() for h in SPOTIFY_OWNED)
        and "facebook.com/Spotify" not in l
        and "twitter.com/spotify" not in l.lower()
    ]

    # ── Bio text ───────────────────────────────────────────────────────────────
    bio = ""
    full_text = soup.get_text(separator="\n")
    m = re.search(r'About\n+(.+?)(?:\n{2,}|\d+ monthly|\d+ [Ff]ollower)', full_text, re.S)
    if m:
        bio = m.group(1).strip()[:600]
    result["bio"] = bio

    # ── Monthly listeners ──────────────────────────────────────────────────────
    m2 = re.search(r'([\d,]+)\s+monthly\s+listener', html, re.I)
    if m2:
        result["monthly_listeners"] = int(m2.group(1).replace(',', ''))

    # ── Followers ─────────────────────────────────────────────────────────────
    m3 = re.search(r'([\d,]+)\s+[Ff]ollower', html)
    if m3:
        result["followers"] = int(m3.group(1).replace(',', ''))

    log(f"  [v2] Spotify: {len(result['links'])} external links | "
        f"bio={bool(result['bio'])} | listeners={result['monthly_listeners']} | "
        f"followers={result['followers']} | tracks={result['top_tracks']}")
    for l in result["links"]:
        log(f"  [v2] Link found: {l}")

    return result

# ── STEP 2: CHAIN FOLLOW ──────────────────────────────────────────────────────

AGGREGATE_DOMAINS = ['linktr.ee','beacons.ai','bio.link','lnk.to','ffm.to','hypeddit.com','sndn.link']

def is_aggregate(url):
    try: return any(d in urlparse(url).netloc for d in AGGREGATE_DOMAINS)
    except: return False

def follow_link(url):
    html = fetch(url)
    if not html: return None, None
    return extract_ig(html), extract_email(html)

def scrape_website(url):
    ig, email = follow_link(url)
    if not email:
        _, email2 = follow_link(urljoin(url, "/contact"))
        if email2: email = email2
    return ig, email

# ── STEP 3: INSTAGRAM VERIFICATION ────────────────────────────────────────────

IG_API_HEADERS = {
    "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15",
    "x-ig-app-id": "936619743392459",
    "Accept": "*/*",
    "Accept-Language": "en-US,en;q=0.9",
    "Origin": "https://www.instagram.com",
    "Referer": "https://www.instagram.com/",
}

def verify_instagram(handle):
    """
    Soft-pass on 401/403/429 — don't silently drop handles just because
    Instagram is blocking the verification request.
    Only return None on a definitive 404 (handle does not exist).
    """
    if not handle: return None
    try:
        r = requests.get(
            f"https://i.instagram.com/api/v1/users/web_profile_info/?username={handle}",
            headers=IG_API_HEADERS, timeout=12)
        if r.status_code == 200:
            d = r.json().get("data", {}).get("user", {})
            if d:
                return {"found": True,
                        "followers": d.get("edge_followed_by", {}).get("count"),
                        "bio": d.get("biography", ""),
                        "verified": d.get("is_verified", False)}
        elif r.status_code == 404:
            return None
        elif r.status_code in (401, 403, 429):
            log(f"  [v2] IG API blocked ({r.status_code}) — soft pass @{handle}")
            return {"found": True, "followers": None, "bio": "", "soft_pass": True}
    except: pass

    try:
        r2 = requests.get(f"https://www.instagram.com/{handle}/",
            headers={"User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X)"},
            timeout=10, allow_redirects=True)
        if r2.status_code == 200 and handle.lower() in r2.text.lower():
            m = re.search(r'"edge_followed_by":\{"count":(\d+)\}', r2.text)
            return {"found": True, "followers": int(m.group(1)) if m else None, "bio": ""}
        elif r2.status_code == 404:
            return None
        elif r2.status_code in (401, 403, 429):
            return {"found": True, "followers": None, "bio": "", "soft_pass": True}
    except: pass

    log(f"  [v2] IG unverifiable — soft pass @{handle}")
    return {"found": True, "followers": None, "bio": "", "soft_pass": True}

# ── STEP 4: DUCKDUCKGO FALLBACK ───────────────────────────────────────────────

DDG_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept": "text/html,*/*",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://duckduckgo.com/",
}

GENERIC_WORDS = {
    'popular','trending','featured','official','verified','music','artist',
    'follow','followers','profile','new','latest','top','best','more','view',
    'home','link','click','download','app','stream','listen','tour','tickets',
    'merch','shop','contact','press','here','this','that','with','from',
}

def ddg_search(query):
    try:
        r = requests.get(f"https://html.duckduckgo.com/html/?q={quote_plus(query)}",
                         headers=DDG_HEADERS, timeout=12)
        return r.text if r.status_code == 200 else None
    except: return None

def confirm_ig_is_artist(handle, artist_name, top_tracks, spotify_url=""):
    """
    Fetch the Instagram profile page and confirm it belongs to this artist
    by checking for: artist name, track titles, or Spotify URL in the bio/content.
    Returns True if confirmed, False if it's a different person, None if unverifiable.
    """
    try:
        r = requests.get(
            f"https://www.instagram.com/{handle}/",
            headers={"User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15"},
            timeout=10, allow_redirects=True
        )
        if r.status_code == 404:
            return False
        if r.status_code != 200:
            return None  # Can't confirm, but don't reject

        page = r.text.lower()
        name_lower = artist_name.lower()

        # Check for artist name in page
        if name_lower in page:
            log(f"  [v2] Confirmed: artist name '{artist_name}' in IG page")
            return True

        # Check for any known track title
        for track in top_tracks:
            if len(track) > 4 and track.lower() in page:
                log(f"  [v2] Confirmed: track '{track}' in IG page")
                return True

        # Check for spotify.com link in page
        if "spotify.com" in page:
            log(f"  [v2] Confirmed: Spotify link in IG page")
            return True

        # Check for artist ID specifically
        artist_id = ""
        m = re.search(r'/artist/([A-Za-z0-9]+)', spotify_url)
        if m:
            artist_id = m.group(1).lower()
            if artist_id in page:
                log(f"  [v2] Confirmed: Spotify artist ID in IG page")
                return True

        log(f"  [v2] Could not confirm @{handle} belongs to '{artist_name}'")
        return None  # Unverifiable — not enough info either way

    except Exception as e:
        log(f"  [v2] IG confirm error: {e}")
        return None


def search_for_instagram(name, spotify_url="", top_tracks=None, genres=None):
    """
    Build targeted DDG queries. Each candidate is cross-checked against
    the actual IG profile to confirm it's the right artist.
    """
    log(f"  [v2] DDG: searching for '{name}' instagram")
    combined = ""
    artist_id = ""
    if spotify_url:
        m = re.search(r'/artist/([A-Za-z0-9]+)', spotify_url)
        if m: artist_id = m.group(1)

    top_tracks = top_tracks or []
    track_hint = f'"{top_tracks[0]}"' if top_tracks else ""
    genre_hint = genres[0] if genres else "rapper"

    queries = [q for q in [
        f'spotify artist {artist_id} instagram' if artist_id else None,
        f'"{name}" {track_hint} instagram' if track_hint else None,
        f'"{name}" {genre_hint} instagram',
        f'site:instagram.com "{name}" rapper',
        f'site:instagram.com "{name}" music',
        f'"{name}" spotify instagram',
        f'site:soundcloud.com "{name}" instagram',   # NEW: SoundCloud bio often lists IG
    ] if q]

    # Build name tokens for fuzzy matching (split on space/underscore)
    name_lower = name.lower().replace(' ', '').replace('_', '')
    name_tokens = set(re.split(r'[\s_]+', name.lower()))  # e.g. {"selfmade", "dully"}
    rejected = set()

    for query in queries:
        log(f"  [v2] DDG: {query}")
        html = ddg_search(query)
        if not html:
            log(f"  [v2] DDG: no response")
            time.sleep(random.uniform(1.0, 2.0))
            continue
        if html:
            combined += html[:2000]
            candidates = []
            for m_ig in IG_RE.finditer(html):
                h = clean_ig(m_ig.group(1))
                if h and h.lower() not in GENERIC_WORDS and h not in candidates and h not in rejected:
                    candidates.append(h)
            log(f"  [v2] DDG: {len(candidates)} raw candidates: {candidates[:5]}")

            for h in candidates:
                h_lower = h.lower().replace('_', '').replace('.', '')
                # Token match: accept if handle contains ANY name token (e.g. "dully" in "selfmadedully")
                token_hit = any(tok in h_lower for tok in name_tokens if len(tok) >= 3)
                full_hit = name_lower in h_lower or h_lower in name_lower
                if not full_hit and not token_hit:
                    overlap = len(set(name_lower) & set(h_lower))
                    if overlap < max(2, len(name_lower) * 0.35):  # lowered from 0.5 → 0.35
                        continue

                log(f"  [v2] Candidate @{h} — confirming identity...")
                confirmed = confirm_ig_is_artist(h, name, top_tracks, spotify_url)
                if confirmed is True:
                    log(f"  [v2] Confirmed: @{h}")
                    return h, combined
                elif confirmed is False:
                    log(f"  [v2] Rejected (wrong person): @{h}")
                    rejected.add(h)
                else:
                    log(f"  [v2] Unverifiable but name matched — accepting @{h}")
                    return h, combined

            # Loose fallback: if name filter rejected everything, try ALL
            # candidates through the identity confirmer (no name-match required)
            if candidates:
                log(f"  [v2] No name-matched candidates — trying loose confirm on: {candidates[:3]}")
                for h in candidates[:4]:
                    if h in rejected: continue
                    confirmed = confirm_ig_is_artist(h, name, top_tracks, spotify_url)
                    if confirmed is True:
                        log(f"  [v2] Loose confirmed: @{h}")
                        return h, combined
                    elif confirmed is False:
                        rejected.add(h)

        time.sleep(random.uniform(1.0, 2.0))

    return None, combined

# ── LAST.FM ───────────────────────────────────────────────────────────────────

def get_lastfm_bio(name):
    try:
        r = requests.get("https://ws.audioscrobbler.com/2.0/", params={
            "method": "artist.getinfo", "artist": name,
            "api_key": LASTFM_API_KEY, "format": "json", "autocorrect": 1
        }, timeout=8)
        return r.json().get("artist", {}).get("bio", {}).get("summary", "") or ""
    except: return ""

# ── SOUNDCLOUD SCRAPING ───────────────────────────────────────────────────────

_SC_CLIENT_ID_CACHE = {"id": None}

def _get_soundcloud_client_id():
    """Extract SoundCloud client_id from their homepage JS bundle (cached)."""
    if _SC_CLIENT_ID_CACHE["id"]:
        return _SC_CLIENT_ID_CACHE["id"]
    try:
        r = requests.get("https://soundcloud.com/", headers={"User-Agent": UA_LIST[1]}, timeout=10)
        # Find script URLs in the page
        script_urls = re.findall(r'src="(https://a-v2\.sndcdn\.com/assets/[^"]+\.js)"', r.text)
        for script_url in script_urls[:4]:
            sr = requests.get(script_url, headers={"User-Agent": UA_LIST[1]}, timeout=8)
            m = re.search(r'client_id\s*:\s*"([A-Za-z0-9]{32})"', sr.text)
            if m:
                _SC_CLIENT_ID_CACHE["id"] = m.group(1)
                log(f"  [v2] SoundCloud client_id extracted: {m.group(1)[:8]}...")
                return m.group(1)
    except Exception as e:
        log(f"  [v2] SoundCloud client_id extraction failed: {e}")
    return None


def scrape_soundcloud(name):
    """
    Find artist on SoundCloud via DDG, then scrape their profile page.
    SoundCloud profiles expose social links (Instagram, etc.) directly in HTML.
    Returns: (ig_handle, email) or (None, None)
    """
    log(f"  [v2] SoundCloud: searching for '{name}'...")

    # Step 1: Find their SoundCloud URL via DDG
    sc_url = None
    query = f'site:soundcloud.com "{name}"'
    html = ddg_search(query)
    if html:
        # Look for soundcloud.com profile URLs in results
        sc_matches = re.findall(r'https?://soundcloud\.com/([a-zA-Z0-9_-]+)(?:/[^\s"\'<>]*)?', html)
        # Filter out non-profile pages
        skip_sc = {'you','pages','stations','discover','stream','explore','jobs','go'}
        for slug in sc_matches:
            if slug.lower() not in skip_sc and len(slug) > 2:
                sc_url = f"https://soundcloud.com/{slug}"
                log(f"  [v2] SoundCloud candidate: {sc_url}")
                break

    if not sc_url:
        # Try SoundCloud v2 search API (no auth required, returns JSON)
        # Extract client_id dynamically from SoundCloud homepage
        sc_client_id = _get_soundcloud_client_id()
        if sc_client_id:
            try:
                api_r = requests.get(
                    "https://api-v2.soundcloud.com/search/users",
                    params={"q": name, "client_id": sc_client_id, "limit": 3},
                    headers={"User-Agent": UA_LIST[1]},
                    timeout=10
                )
                if api_r.status_code == 200:
                    users = api_r.json().get("collection", [])
                    for u in users:
                        uname = u.get("username", "")
                        permalink = u.get("permalink", "")
                        # Match on username similarity
                        if any(w.lower() in uname.lower() for w in name.split()):
                            sc_url = f"https://soundcloud.com/{permalink}"
                            log(f"  [v2] SoundCloud API found: {sc_url} ({uname})")
                            break
            except Exception as e:
                log(f"  [v2] SoundCloud API search error: {e}")

    if not sc_url:
        # Direct slug guesses as last resort
        for guess in [name.lower().replace(' ', ''), name.lower().replace(' ', '-')]:
            candidate = f"https://soundcloud.com/{guess}"
            try:
                r = requests.get(candidate, headers={"User-Agent": UA_LIST[1]},
                                  timeout=8, allow_redirects=True)
                if r.status_code == 200 and len(r.text) > 5000:
                    sc_url = candidate
                    log(f"  [v2] SoundCloud direct hit: {sc_url}")
                    break
            except: pass

    if not sc_url:
        log(f"  [v2] SoundCloud: no profile found")
        return None, None

    # Step 2: Scrape the SoundCloud profile
    sc_html = fetch(sc_url)
    if not sc_html:
        log(f"  [v2] SoundCloud: fetch failed for {sc_url}")
        return None, None

    ig    = extract_ig(sc_html)      # URL format: instagram.com/handle
    email = extract_email(sc_html)

    # SoundCloud stores social links in window.__sc_hydration JSON.
    # Artists often write "Instagram - Handle" in their description (plain text,
    # not a URL) — extract_ig misses this, extract_ig_from_text catches it.
    if not ig:
        hydration_match = re.search(r'window\.__sc_hydration\s*=\s*(\[.+?\]);', sc_html, re.S)
        if hydration_match:
            try:
                hydration = json.loads(hydration_match.group(1))
                for item in hydration:
                    if not isinstance(item, dict): continue
                    if item.get("hydratable") != "user": continue
                    user = item.get("data", {})

                    # 1. Check links array (URL format)
                    for link in (user.get("links") or []):
                        url = link.get("url", "") or link.get("value", "")
                        ig = ig or extract_ig(url)

                    # 2. Check description (text format: "Instagram - Handle")
                    desc = user.get("description", "") or ""
                    ig = ig or extract_ig_from_text(desc)

                    # 3. Email from description
                    if not email:
                        email = extract_email(desc)

                    if ig:
                        log(f"  [v2] SoundCloud hydration: description='{desc[:80]}'")
                        break
            except Exception as e:
                log(f"  [v2] SoundCloud hydration error: {e}")

    if ig:
        log(f"  [v2] SoundCloud: found IG @{ig}")
    else:
        log(f"  [v2] SoundCloud: no IG found on profile page")

    return ig, email

# ── CLAUDE WITH WEB SEARCH ────────────────────────────────────────────────────
#
# Anthropic's web_search_20250305 is a SERVER-SIDE tool — one API call handles
# everything. Claude searches, gets results, and returns the text answer all in
# the same response. No multi-turn needed. Do NOT inject tool_results manually.
#
# This is now the PRIMARY fallback (step 2), not a last resort.

_CLAUDE_SKIP = {
    "UNKNOWN","I","THE","SORRY","NOT","NO","A","AN","IS","ARE",
    "FOUND","COULD","UNABLE","CANNOT","HERE","THIS","THEIR","ITS",
    "THEIR","THEY","HIS","HER","YOUR","OUR","MY","WE","IT","ON",
    "IN","OF","TO","FOR","WITH","FROM","AT","BY","AS","OR","AND",
}

def _parse_handle_from_claude_text(raw):
    """Extract IG handle from Claude's full text response.

    Strategy:
      1. instagram.com/handle URL in text — most precise, always trusted
      2. Phrase patterns: 'handle is X', 'username: X', '@X'
      3. Short response only (≤3 words) — if Claude followed instructions and
         gave just the bare handle, accept the last non-skip word.
         Do NOT word-scan long sentences — that picks up random English words
         like 'platforms', 'music', 'artist' as fake handles.
    """
    if not raw:
        return None
    # 1. instagram.com/handle URL
    h = extract_ig(raw)
    if h:
        return h
    # 2. Phrase patterns
    for pat in [
        r'(?:handle|username|account|instagram)\s*(?:is|:)\s*@?([A-Za-z0-9][A-Za-z0-9_.]{1,28}[A-Za-z0-9])',
        r'@([A-Za-z0-9][A-Za-z0-9_.]{1,28}[A-Za-z0-9])',
    ]:
        m = re.search(pat, raw, re.I)
        if m:
            h = clean_ig(m.group(1))
            if h:
                return h
    # 3. Short response only — Claude gave the bare handle as instructed
    words = raw.replace('\n', ' ').split()
    if len(words) <= 3:
        for word in reversed(words):
            candidate = word.strip('.,;:!?@"\'()')
            if not candidate or candidate.upper() in _CLAUDE_SKIP:
                continue
            h = clean_ig(candidate)
            if h and len(h) >= 3:
                return h
    return None


def claude_find_instagram(name, bio="", platform_url="", search_context=""):
    if not CLAUDE_API_KEY:
        log("  [v2] No CLAUDE_API_KEY — skipping Claude step")
        return None

    context_parts = []
    if bio:            context_parts.append(f"Spotify bio: {bio[:400]}")
    if search_context: context_parts.append(f"Search context: {search_context[:800]}")
    context = ("\n".join(context_parts) + "\n") if context_parts else ""

    prompt = (
        f"Find the Instagram handle for music artist \"{name}\" on Spotify.\n"
        f"Spotify URL: {platform_url}\n"
        f"{context}"
        f"Search their name on the web, check SoundCloud, Linktree, and any music blogs.\n"
        f"Reply with exactly one word — the Instagram username only (no @ symbol, no URL, no explanation).\n"
        f"If not found after searching, reply: UNKNOWN"
    )

    headers = {
        "x-api-key":         CLAUDE_API_KEY,
        "anthropic-version": "2023-06-01",
        "anthropic-beta":    "web-search-2025-03-05",
        "content-type":      "application/json",
    }

    # ── Attempt 1: with web_search tool ──────────────────────────────────────
    try:
        r = requests.post(
            "https://api.anthropic.com/v1/messages",
            headers=headers,
            json={
                "model":      "claude-haiku-4-5-20251001",
                "max_tokens": 150,
                "tools":      [{"type": "web_search_20250305", "name": "web_search"}],
                "messages":   [{"role": "user", "content": prompt}],
            },
            timeout=60,
        )
        log(f"  [v2] Claude+search status: {r.status_code}")

        if r.status_code == 200:
            data = r.json()
            log(f"  [v2] stop_reason={data.get('stop_reason')} blocks={[b.get('type') for b in data.get('content',[])]}")
            # Walk ALL content blocks — text answer may come after tool_use/tool_result blocks
            for block in data.get("content", []):
                if block.get("type") == "text":
                    raw = block["text"].strip()
                    log(f"  [v2] Claude answer raw: {raw[:120]!r}")
                    if raw.upper().startswith("UNKNOWN"):
                        break
                    h = _parse_handle_from_claude_text(raw)
                    if h:
                        log(f"  [v2] Claude handle extracted: {h!r}")
                        return h
            log("  [v2] Claude+search returned no usable handle")

        elif r.status_code in (400, 404):
            log(f"  [v2] web_search tool not available ({r.status_code}) — falling back to plain")
        else:
            log(f"  [v2] Claude+search error {r.status_code}: {r.text[:120]}")

    except Exception as e:
        log(f"  [v2] Claude+search exception: {e}")

    # ── Attempt 2: plain Claude, no tools (works on all tiers) ───────────────
    try:
        r2 = requests.post(
            "https://api.anthropic.com/v1/messages",
            headers={k: v for k, v in headers.items() if k != "anthropic-beta"},
            json={
                "model":      "claude-haiku-4-5-20251001",
                "max_tokens": 30,
                "messages":   [{"role": "user", "content": prompt}],
            },
            timeout=20,
        )
        log(f"  [v2] Claude plain status: {r2.status_code}")
        if r2.status_code == 200:
            raw = r2.json().get("content", [{}])[0].get("text", "").strip()
            log(f"  [v2] Claude plain answer raw: {raw[:120]!r}")
            if raw and not raw.upper().startswith("UNKNOWN"):
                h = _parse_handle_from_claude_text(raw)
                if h:
                    log(f"  [v2] Claude plain handle extracted: {h!r}")
                    return h
    except Exception as e:
        log(f"  [v2] Claude plain exception: {e}")

    return None

# ── MAIN ──────────────────────────────────────────────────────────────────────

async def resolve_async(name, platform="spotify", profile_url="", ig_hint=None):
    result = {
        "instagram": None, "tiktok": None, "email": None,
        "ig_followers": None, "skip": False, "skip_reason": None, "sources": [],
    }

    log(f"\n[v2] Enriching: {name}")
    log(f"  Platform: {platform} | URL: {profile_url or 'none'}")

    # Slug used throughout to detect handles that are just the artist's name
    name_slug = re.sub(r'[\s_.\-]+', '', name).lower()

    # ── Step 1: Spotify plain HTTP fetch ──────────────────────────────────────
    spotify = {"links": [], "bio": "", "monthly_listeners": None, "followers": None}
    if profile_url and "spotify.com" in profile_url:
        spotify = scrape_spotify_page(profile_url)

    bio = spotify.get("bio", "")
    top_tracks = spotify.get("top_tracks", [])
    found_ig = found_email = found_tiktok = website_url = None

    # ── Step 2: Claude with web search — run FIRST, most accurate source ──────
    # Claude receives the Spotify URL and searches the web directly. It finds
    # the correct handle far more reliably than scraping Spotify page links,
    # which can contain unrelated @handles (e.g. "@Manic" when handle is "@manic_mc").
    if CLAUDE_API_KEY and profile_url:
        log(f"  [v2] Running Claude web search first (most reliable)...")
        found_ig = claude_find_instagram(name, bio, profile_url)
        if found_ig:
            result["sources"].append("claude_websearch")
            log(f"  [v2] IG from Claude web search: @{found_ig}")

    # ── Spotify page links — only use if Claude found nothing, AND verify identity ──
    # Spotify pages sometimes contain wrong/unrelated IG handles (another artist
    # with the same name, an old handle, etc.). Always confirm before trusting.
    if not found_ig:
        for link in spotify.get("links", []):
            ig_m = IG_RE.search(link)
            ig = clean_ig(ig_m.group(1)) if ig_m else None
            if ig and not found_ig:
                log(f"  [v2] Spotify page candidate: @{ig} — confirming identity...")
                confirmed = confirm_ig_is_artist(ig, name, top_tracks, profile_url)
                if confirmed is not False:  # True or None (unverifiable) = accept
                    found_ig = ig
                    result["sources"].append("spotify_page")
                    log(f"  [v2] IG from Spotify page link (confirmed={confirmed}): @{ig}")
                else:
                    log(f"  [v2] Rejected Spotify page handle @{ig} — wrong artist")

            tk = TIKTOK_RE.search(link)
            if tk and not found_tiktok:
                found_tiktok = tk.group(1)

            if is_aggregate(link) and not found_ig:
                log(f"  [v2] Following aggregate: {link[:60]}")
                agg_ig, agg_email = follow_link(link)
                if agg_ig:
                    found_ig = agg_ig
                    result["sources"].append("linktree")
                    log(f"  [v2] IG from aggregate: @{agg_ig}")
                if agg_email and not found_email:
                    found_email = agg_email

            if not found_ig and not is_aggregate(link) and "instagram" not in link:
                parsed = urlparse(link)
                skip_netloc = ['facebook.','twitter.','x.com','youtube.','tiktok.',
                               'soundcloud.','spotify.','apple.','google.','linkfire.']
                if parsed.netloc and not any(d in parsed.netloc for d in skip_netloc):
                    if not website_url:
                        website_url = link

    if website_url and not found_ig:
        log(f"  [v2] Scraping artist website: {website_url[:60]}")
        ws_ig, ws_email = scrape_website(website_url)
        if ws_ig:
            found_ig = ws_ig
            result["sources"].append("artist_website")
            log(f"  [v2] IG from website: @{ws_ig}")
        if ws_email and not found_email:
            found_email = ws_email

    if not found_ig and bio:
        bio_ig = extract_ig(bio)
        if bio_ig:
            found_ig = bio_ig
            result["sources"].append("spotify_bio")
            log(f"  [v2] IG from bio text: @{bio_ig}")

    # Last.fm (kept for email + bio enrichment even if IG already found)
    if not found_ig or not found_email:
        log(f"  [v2] Checking Last.fm...")
        lfm = get_lastfm_bio(name)
        if lfm:
            if not found_ig:
                lfm_ig = extract_ig(lfm)
                if lfm_ig:
                    found_ig = lfm_ig
                    result["sources"].append("lastfm")
                    log(f"  [v2] IG from Last.fm: @{lfm_ig}")
            if not found_email:
                found_email = extract_email(lfm)

    # SoundCloud (when accessible)
    if not found_ig:
        sc_ig, sc_email = scrape_soundcloud(name)
        if sc_ig:
            found_ig = sc_ig
            result["sources"].append("soundcloud")
            log(f"  [v2] IG from SoundCloud: @{sc_ig}")
        if sc_email and not found_email:
            found_email = sc_email

    # ── Step 3: Verify ────────────────────────────────────────────────────────
    if found_ig:
        # Extra guard: if the handle is just the artist's name (e.g. "Manic" for
        # artist "Manic"), it's often wrong — the real handle usually has a suffix
        # like manic_mc. Require a hard identity confirmation in this case.
        handle_slug = re.sub(r'[\s_.\-]+', '', found_ig).lower()
        handle_is_just_name = (handle_slug == name_slug)
        if handle_is_just_name:
            log(f"  [v2] Handle @{found_ig} == artist name — running strict identity check")
            confirmed = confirm_ig_is_artist(found_ig, name, top_tracks, profile_url)
            if confirmed is not True:
                log(f"  [v2] Rejected @{found_ig} — handle matches artist name, retrying Claude with hint")
                found_ig = None
                # Claude returned the bare name (e.g. "Manic") — common mistake.
                # Retry with an explicit hint that the real handle is different.
                if CLAUDE_API_KEY:
                    hint_prompt_extra = (
                        f"IMPORTANT: Their Instagram handle is NOT just \"{name}\". "
                        f"It likely has underscores, numbers, or extra words (e.g. {name.lower().replace(' ','_')}_music, "
                        f"{name.lower().replace(' ','')}official, {name.lower().replace(' ','_')}mc, etc.). "
                        f"Search carefully and find the ACTUAL username, not just the artist's name."
                    )
                    retry_ig = claude_find_instagram(name, bio, profile_url, hint_prompt_extra)
                    if retry_ig:
                        retry_slug = re.sub(r'[\s_.\-]+', '', retry_ig).lower()
                        if retry_slug != name_slug:  # only accept if it's different from the name
                            found_ig = retry_ig
                            result["sources"].append("claude_websearch_retry")
                            log(f"  [v2] Claude retry found different handle: @{retry_ig}")

    if found_ig:
        log(f"  [v2] Verifying: @{found_ig}")
        ig_data = verify_instagram(found_ig)
        if ig_data and ig_data.get("found"):
            result["instagram"] = found_ig
            result["ig_followers"] = ig_data.get("followers")
            producer_flags = ["producer","beat maker","beatmaker","mixing engineer",
                              "mastering","music producer","sound engineer"]
            if any(f in (ig_data.get("bio","")).lower() for f in producer_flags):
                result["skip"] = True
                result["skip_reason"] = "IG bio identifies as producer"
        else:
            log(f"  [v2] IG not verified: @{found_ig}")
            found_ig = None

    # ── Step 4: Claude with web search (runs BEFORE DDG — more reliable) ────────
    # Claude+web_search is the single most reliable fallback when scraping fails.
    # DDG's HTML endpoint is frequently blocked; Claude's search API is not.
    if not result.get("instagram") and CLAUDE_API_KEY:
        log(f"  [v2] Trying Claude with web search...")
        claude_ig = claude_find_instagram(name, bio, profile_url, "")
        if claude_ig:
            # Reject if handle == artist name without hard confirmation
            c_slug = re.sub(r'[\s_.\-]+', '', claude_ig).lower()
            if c_slug == name_slug:
                confirmed = confirm_ig_is_artist(claude_ig, name, top_tracks, profile_url)
                if confirmed is not True:
                    log(f"  [v2] Step4 Claude: rejected @{claude_ig} — name-match but not confirmed, skipping")
                    claude_ig = None
        if claude_ig:
            ig_data = verify_instagram(claude_ig)
            if ig_data and ig_data.get("found"):
                result["instagram"] = claude_ig
                result["ig_followers"] = ig_data.get("followers")
                result["sources"].append("claude_websearch")
                log(f"  [v2] Claude+search IG accepted: @{claude_ig}")

    # ── Step 5: DDG fallback (kept as extra net) ──────────────────────────────
    ddg_context = ""
    if not result.get("instagram"):
        time.sleep(random.uniform(1.5, 3.0))
        log(f"  [v2] Top tracks for DDG disambiguation: {top_tracks}")
        ddg_ig, ddg_context = search_for_instagram(name, profile_url, top_tracks=top_tracks)
        if ddg_ig:
            ig_data = verify_instagram(ddg_ig)
            if ig_data and ig_data.get("found"):
                result["instagram"] = ddg_ig
                result["ig_followers"] = ig_data.get("followers")
                result["sources"].append("duckduckgo")
                log(f"  [v2] DDG IG accepted: @{ddg_ig}")

    # ── Step 6: Claude plain fallback (if DDG found context but web_search failed) ──
    if not result.get("instagram") and CLAUDE_API_KEY and ddg_context:
        log(f"  [v2] Trying Claude with DDG context...")
        claude_ig2 = claude_find_instagram(name, bio, profile_url, ddg_context)
        if claude_ig2:
            ig_data = verify_instagram(claude_ig2)
            if ig_data and ig_data.get("found"):
                result["instagram"] = claude_ig2
                result["ig_followers"] = ig_data.get("followers")
                result["sources"].append("claude_ai")
                log(f"  [v2] Claude+DDGctx IG accepted: @{claude_ig2}")

    result["tiktok"] = found_tiktok
    result["email"] = found_email

    if result.get("instagram"):
        f = f"{result['ig_followers']:,}" if result.get("ig_followers") else "unknown followers"
        log(f"\n  RESULT: @{result['instagram']} | {f} | sources: {result['sources']}")
    else:
        log(f"\n  RESULT: not found after all steps")

    return result


def resolve(name, platform="spotify", profile_url="", ig_hint=None):
    return asyncio.run(resolve_async(name, platform, profile_url, ig_hint))


# ── CLI ────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Renegade Enrichment Engine v2")
    parser.add_argument("--name",        required=True)
    parser.add_argument("--platform",    default="spotify")
    parser.add_argument("--profile-url", default="")
    parser.add_argument("--json",        action="store_true")
    args = parser.parse_args()

    _JSON_MODE = args.json
    result = resolve(args.name, args.platform, args.profile_url or "")

    if args.json:
        print(json.dumps(result), flush=True)
    else:
        print("\n--- Final Result ---")
        print(f"  Instagram  : @{result['instagram']}" if result['instagram'] else "  Instagram  : not found")
        print(f"  IG followers: {result['ig_followers']:,}" if result.get('ig_followers') else "  IG followers: unknown")
        print(f"  TikTok     : @{result['tiktok']}" if result.get('tiktok') else "  TikTok     : not found")
        print(f"  Email      : {result['email']}" if result.get('email') else "  Email      : not found")
        print(f"  Sources    : {', '.join(result['sources']) or 'none'}")
        if result.get('skip'):
            print(f"  FLAG       : {result['skip_reason']}")
