"""
Renegade Records — Enrichment Engine v3
No Claude API. Pipeline:
  1. Spotify page scrape → direct IG links + aggregate/linktree follow
  2. Artist website scrape
  3. SoundCloud scrape
  4. SerpAPI search
  5. DuckDuckGo fallback
  6. Soft-pass IG verification
"""

import sys, re, json, time, random, os, argparse
import urllib.request, urllib.parse, urllib.error

try:
    import requests
except ImportError:
    import subprocess
    subprocess.check_call([sys.executable, '-m', 'pip', 'install', 'requests'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    import requests

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

SERPAPI_KEY = os.getenv("SERPAPI_KEY", "")

_JSON_MODE = False

def log(*args):
    if _JSON_MODE:
        print(" ".join(str(a) for a in args), file=sys.stderr, flush=True)
    else:
        print(" ".join(str(a) for a in args), flush=True)

# ── PATTERNS ──────────────────────────────────────────────────────────────────

IG_RE    = re.compile(r'(?:instagram\.com/|@)([A-Za-z0-9](?:[A-Za-z0-9_.]{0,28}[A-Za-z0-9])?)/?(?:\?[^\s"\'<>]*)?', re.I)
EMAIL_RE = re.compile(r'[a-zA-Z0-9+_.%\-]+@[a-zA-Z0-9\-]+\.[a-zA-Z]{2,}')

BAD_IG = {
    'p','reel','reels','stories','explore','accounts','about','help','legal','privacy',
    'safety','directory','music','search','instagram','facebook','twitter','youtube',
    'spotify','tiktok','soundcloud','login','signup','challenge','graphql','api','web',
    'www','undefined','null','none','true','false','share','photo','photos','video',
    'videos','live','spotifyus','spotifyuk','spotifynews','spotifyloud',
    'spotifyforartists','spotifycharts','popular','trending','featured','official',
    'verified','artist','artists','musician','musicians','follow','followers',
    'following','likes','posts','new','latest','top','best','more','view','views',
    'home','feed','tag','tags','location','embed','cdn','static','profile','profiles',
    'page','pages','site','sites','link','links','url','redirect','click','download',
    'app','store','contact','email','mail','newsletter','subscribe','press','news',
    'blog','stream','streaming','listen','play','player','tour','tickets','merch',
    'shop','buy','get',
}

SPOTIFY_OWNED = {'spotify','spotifyus','spotifyuk','spotifynews','spotifyloud','spotifyforartists','spotifycharts'}
AGGREGATE_DOMAINS = ['linktr.ee','beacons.ai','bio.link','lnk.to','ffm.to','hypeddit.com','sndn.link']

def clean_ig(handle):
    if not handle: return None
    h = handle.strip().lstrip('@').split('?')[0].rstrip('/').rstrip('.,;:!?').lstrip('.')
    if len(h) < 2 or len(h) > 30: return None
    if h.lower() in BAD_IG or h.lower() in SPOTIFY_OWNED: return None
    if not re.match(r'^[A-Za-z0-9._]+$', h): return None
    return h

def extract_ig(text):
    for m in IG_RE.finditer(text):
        h = clean_ig(m.group(1))
        if h: return h
    return None

def extract_email(text):
    for e in EMAIL_RE.findall(text):
        if not any(j in e.lower() for j in ['noreply','example.','sentry.','spotify.','apple.','google.']):
            return e
    return None

def is_aggregate(url):
    return any(d in url for d in AGGREGATE_DOMAINS)

# ── HTTP FETCH ────────────────────────────────────────────────────────────────

UA_LIST = [
    "Mozilla/5.0 (compatible; ClaudeBot/1.0; +https://www.anthropic.com)",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_4) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4 Safari/605.1.15",
    "curl/8.5.0",
]

def fetch(url, timeout=15):
    for ua in UA_LIST:
        try:
            r = requests.get(url, headers={
                "User-Agent": ua,
                "Accept": "text/html,application/xhtml+xml,*/*;q=0.8",
                "Accept-Language": "en-US,en;q=0.9",
                "Cache-Control": "no-cache",
            }, timeout=timeout, allow_redirects=True)
            if r.status_code == 200 and len(r.text) > 10000:
                return r.text
        except: pass
    return None

# ── STEP 1: SPOTIFY PAGE ──────────────────────────────────────────────────────

def scrape_spotify_page(profile_url):
    result = {"links": [], "bio": "", "top_tracks": []}
    log(f"  [v3] Fetching Spotify page...")
    html = fetch(profile_url)
    if not html:
        log("  [v3] Spotify fetch failed")
        return result

    # External links
    SKIP = ['spotify.com','spotifycdn.com','scdn.co','onetrust.com']
    seen = set()
    for m in re.finditer(r'href="(https?://[^"]+)"', html):
        href = m.group(1)
        if any(s in href for s in SKIP): continue
        if href not in seen:
            seen.add(href)
            result["links"].append(href)

    # Filter Spotify's own social accounts
    result["links"] = [l for l in result["links"]
        if not any(f"instagram.com/{h}" in l.lower() for h in SPOTIFY_OWNED)]

    # Bio
    m = re.search(r'"biography"\s*:\s*"((?:[^"\\]|\\.)*)"', html)
    if m: result["bio"] = m.group(1).replace('\\n', ' ')[:600]

    # Track names
    for tm in re.finditer(r'"name"\s*:\s*"([^"]{3,80})"', html):
        t = tm.group(1)
        if t not in result["top_tracks"] and not t.startswith('http'):
            result["top_tracks"].append(t)
            if len(result["top_tracks"]) >= 5: break

    log(f"  [v3] Spotify: {len(result['links'])} links | bio={bool(result['bio'])}")
    return result

# ── IG IDENTITY CONFIRM ───────────────────────────────────────────────────────

def confirm_ig_is_artist(handle, artist_name, top_tracks=None, spotify_url=""):
    try:
        r = requests.get(f"https://www.instagram.com/{handle}/",
            headers={"User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15"},
            timeout=10, allow_redirects=True)
        if r.status_code == 404: return False
        if r.status_code != 200: return None
        page = r.text.lower()
        if artist_name.lower() in page: return True
        for track in (top_tracks or []):
            if len(track) > 4 and track.lower() in page: return True
        if "spotify.com" in page: return True
        return None
    except: return None

# ── IG SOFT VERIFY ────────────────────────────────────────────────────────────

def verify_instagram(handle):
    if not handle: return None
    try:
        r = requests.get(f"https://i.instagram.com/api/v1/users/web_profile_info/?username={handle}",
            headers={
                "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15",
                "x-ig-app-id": "936619743392459",
            }, timeout=12)
        if r.status_code == 200:
            d = r.json().get("data", {}).get("user", {})
            if d:
                return {"found": True, "followers": d.get("edge_followed_by", {}).get("count"), "bio": d.get("biography", "")}
        elif r.status_code == 404: return None
        elif r.status_code in (401, 403, 429):
            return {"found": True, "followers": None, "bio": "", "soft_pass": True}
    except: pass
    # Soft-pass — don't reject handles just because IG blocks the check
    return {"found": True, "followers": None, "bio": "", "soft_pass": True}

# ── SERPAPI SEARCH ────────────────────────────────────────────────────────────

def serp_find_instagram(artist_name):
    if not SERPAPI_KEY: return None
    try:
        r = requests.get("https://serpapi.com/search", params={
            "engine": "google",
            "q": f"{artist_name} site:instagram.com",
            "api_key": SERPAPI_KEY,
            "num": 5
        }, timeout=15)
        data = r.json()
        if "error" in data:
            log(f"  [v3] SerpAPI: {data['error']}")
            return None
        for item in data.get("organic_results", []):
            m = re.search(r'instagram\.com/([A-Za-z0-9_.]+)', item.get("link", ""))
            if m:
                handle = clean_ig(m.group(1))
                if handle:
                    log(f"  [v3] SerpAPI found: @{handle}")
                    return handle
    except Exception as e:
        log(f"  [v3] SerpAPI error: {e}")
    return None

# ── DUCKDUCKGO FALLBACK ───────────────────────────────────────────────────────

def ddg_find_instagram(name, spotify_url="", top_tracks=None):
    log(f"  [v3] DDG: searching for '{name}'")
    artist_id = ""
    m = re.search(r'/artist/([A-Za-z0-9]+)', spotify_url)
    if m: artist_id = m.group(1)

    queries = [q for q in [
        f'spotify artist {artist_id} instagram' if artist_id else None,
        f'"{name}" instagram musician',
        f'site:instagram.com "{name}" music',
    ] if q]

    name_tokens = set(re.split(r'[\s_]+', name.lower()))

    for query in queries:
        try:
            r = requests.get(f"https://html.duckduckgo.com/html/?q={urllib.parse.quote_plus(query)}",
                headers={"User-Agent": UA_LIST[1], "Accept": "text/html"}, timeout=12)
            html = r.text if r.status_code == 200 else ""
        except: html = ""

        if not html:
            time.sleep(1)
            continue

        for m_ig in IG_RE.finditer(html):
            h = clean_ig(m_ig.group(1))
            if not h: continue
            h_lower = h.lower().replace('_','').replace('.','')
            token_hit = any(tok in h_lower for tok in name_tokens if len(tok) >= 3)
            if token_hit:
                confirmed = confirm_ig_is_artist(h, name, top_tracks or [], spotify_url)
                if confirmed is not False:
                    log(f"  [v3] DDG found: @{h}")
                    return h

        time.sleep(random.uniform(1.0, 2.0))
    return None

# ── SOUNDCLOUD ────────────────────────────────────────────────────────────────

def scrape_soundcloud(name):
    log(f"  [v3] SoundCloud: searching for '{name}'")
    try:
        r = requests.get(f"https://html.duckduckgo.com/html/?q={urllib.parse.quote_plus('site:soundcloud.com ' + name)}",
            headers={"User-Agent": UA_LIST[1], "Accept": "text/html"}, timeout=12)
        html = r.text if r.status_code == 200 else ""
    except: return None, None

    skip_sc = {'you','pages','stations','discover','stream','explore','jobs','go'}
    sc_url = None
    for slug in re.findall(r'soundcloud\.com/([a-zA-Z0-9_-]+)', html):
        if slug.lower() not in skip_sc and len(slug) > 2:
            sc_url = f"https://soundcloud.com/{slug}"
            break

    if not sc_url: return None, None
    sc_html = fetch(sc_url)
    if not sc_html: return None, None

    ig = extract_ig(sc_html)
    email = extract_email(sc_html)

    if not ig:
        m = re.search(r'window\.__sc_hydration\s*=\s*(\[.+?\]);', sc_html, re.S)
        if m:
            try:
                for item in json.loads(m.group(1)):
                    if not isinstance(item, dict) or item.get("hydratable") != "user": continue
                    user = item.get("data", {})
                    for link in (user.get("links") or []):
                        ig = ig or extract_ig(link.get("url","") or link.get("value",""))
                    desc = user.get("description","") or ""
                    if not ig:
                        tm = re.search(r'(?:instagram\s*[-:@]\s*|ig\s*[-:@]\s*|(?<!\w)@)([A-Za-z0-9][A-Za-z0-9_.]{1,28}[A-Za-z0-9])', desc, re.I)
                        if tm: ig = clean_ig(tm.group(1))
                    if not email: email = extract_email(desc)
                    if ig: break
            except: pass

    if ig: log(f"  [v3] SoundCloud: @{ig}")
    return ig, email

# ── MAIN RESOLVE ──────────────────────────────────────────────────────────────

def resolve(name, platform="spotify", profile_url=""):
    result = {"instagram": None, "email": None, "ig_followers": None,
              "skip": False, "skip_reason": None, "sources": []}

    log(f"\n[v3] Enriching: {name}")

    spotify = {"links": [], "bio": "", "top_tracks": []}
    if profile_url and "spotify.com" in profile_url:
        spotify = scrape_spotify_page(profile_url)

    top_tracks = spotify.get("top_tracks", [])
    found_ig = found_email = website_url = None

    # Step 1: Spotify page links
    skip_netloc = ['facebook.','twitter.','x.com','youtube.','tiktok.','soundcloud.','spotify.','apple.','google.','linkfire.']
    for link in spotify.get("links", []):
        m = IG_RE.search(link)
        ig = clean_ig(m.group(1)) if m else None
        if ig and not found_ig:
            confirmed = confirm_ig_is_artist(ig, name, top_tracks, profile_url)
            if confirmed is not False:
                found_ig = ig
                result["sources"].append("spotify_page")
                log(f"  [v3] IG from Spotify page: @{ig}")

        if is_aggregate(link) and not found_ig:
            log(f"  [v3] Following {link[:50]}")
            try:
                r = requests.get(link, headers={"User-Agent": UA_LIST[0]}, timeout=12, allow_redirects=True)
                agg_ig = extract_ig(r.text)
                agg_email = extract_email(r.text)
                if agg_ig: found_ig = agg_ig; result["sources"].append("linktree")
                if agg_email and not found_email: found_email = agg_email
            except: pass

        if not found_ig and not is_aggregate(link) and "instagram" not in link:
            parsed = urllib.parse.urlparse(link)
            if parsed.netloc and not any(d in parsed.netloc for d in skip_netloc):
                if not website_url: website_url = link

    # Step 2: Artist website
    if website_url and not found_ig:
        log(f"  [v3] Scraping website: {website_url[:60]}")
        try:
            r = requests.get(website_url, headers={"User-Agent": UA_LIST[1]}, timeout=12, allow_redirects=True)
            ws_ig = extract_ig(r.text)
            ws_email = extract_email(r.text)
            if ws_ig: found_ig = ws_ig; result["sources"].append("artist_website")
            if ws_email and not found_email: found_email = ws_email
        except: pass

    # Step 3: Bio text
    if not found_ig and spotify.get("bio"):
        bio_ig = extract_ig(spotify["bio"])
        if bio_ig:
            found_ig = bio_ig
            result["sources"].append("spotify_bio")
            log(f"  [v3] IG from bio: @{bio_ig}")

    # Step 4: SoundCloud
    if not found_ig:
        sc_ig, sc_email = scrape_soundcloud(name)
        if sc_ig: found_ig = sc_ig; result["sources"].append("soundcloud")
        if sc_email and not found_email: found_email = sc_email

    # Step 5: SerpAPI
    if not found_ig:
        found_ig = serp_find_instagram(name)
        if found_ig: result["sources"].append("serpapi")

    # Step 6: DDG fallback
    if not found_ig:
        found_ig = ddg_find_instagram(name, profile_url, top_tracks)
        if found_ig: result["sources"].append("duckduckgo")

    # Step 7: Verify
    if found_ig:
        ig_data = verify_instagram(found_ig)
        if ig_data and ig_data.get("found"):
            result["instagram"] = found_ig
            result["ig_followers"] = ig_data.get("followers")
            producer_flags = ["producer","beat maker","beatmaker","mixing engineer","mastering","music producer"]
            if any(f in (ig_data.get("bio","")).lower() for f in producer_flags):
                result["skip"] = True
                result["skip_reason"] = "IG bio identifies as producer"
        else:
            log(f"  [v3] IG not verified: @{found_ig}")

    result["email"] = found_email

    if result.get("instagram"):
        f = f"{result['ig_followers']:,}" if result.get("ig_followers") else "unknown followers"
        log(f"\n  RESULT: @{result['instagram']} | {f} | sources: {result['sources']}")
    else:
        log(f"\n  RESULT: not found")

    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Renegade Enrichment Engine v3")
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
        print(f"  Instagram   : @{result['instagram']}" if result['instagram'] else "  Instagram   : not found")
        print(f"  IG followers: {result['ig_followers']:,}" if result.get('ig_followers') else "  IG followers: unknown")
        print(f"  Email       : {result['email']}" if result.get('email') else "  Email       : not found")
        print(f"  Sources     : {', '.join(result['sources']) or 'none'}")
        if result.get('skip'):
            print(f"  FLAG        : {result['skip_reason']}")
