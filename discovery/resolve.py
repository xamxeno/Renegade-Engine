import sys, io
if __name__ == "__main__" or "--json" in sys.argv:
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

"""
Renegade Records — Contact Resolution Engine v2
Sources (in priority order):
1. MusicBrainz   — structured social links (Instagram, Facebook, Twitter, website)
2. Last.fm bio   — artist bio with possible IG/email mentions
3. Official site — scrape homepage + /contact for email
4. Instagram API — fetch bio/followers via i.instagram.com internal API
5. DuckDuckGo    — HTML search fallback
6. Google        — HTML search fallback (may be JS-only)
"""

import re, time, json, requests
from urllib.parse import quote_plus, urljoin, unquote
from concurrent.futures import ThreadPoolExecutor, as_completed

# ── GLOBAL MODE (set by CLI before resolve() is called) ───────────────────────
_JSON_MODE = False

# When True: skip email / phone / Facebook / website — Instagram only.
# Flip to False later once IG bugs are resolved.
IG_ONLY = True

def log(*args):
    """Route debug output to stderr in --json mode so stdout is clean JSON only."""
    msg = " ".join(str(a) for a in args)
    if _JSON_MODE:
        print(msg, file=sys.stderr, flush=True)
    else:
        print(msg, flush=True)

# ── HEADERS ───────────────────────────────────────────────────────────────────
HEADERS_CHROME = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
    "DNT": "1",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
    "Cache-Control": "max-age=0",
}

HEADERS_MOBILE = {
    "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}

HEADERS_IG_API = {
    "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1",
    "x-ig-app-id": "936619743392459",
    "Accept": "*/*",
    "Accept-Language": "en-US,en;q=0.9",
    "Origin": "https://www.instagram.com",
    "Referer": "https://www.instagram.com/",
}

# Google consent cookie bypass (avoids consent-gate redirect)
HEADERS_GOOGLE = {
    **HEADERS_CHROME,
    "Referer": "https://www.google.com/",
    "Cookie": "CONSENT=YES+cb.20240101-07-p0.en+FX+410; SOCS=CAESEwgDEgk0ODE3Nzk3MjQaAmVuIAEaBgiA_LyoBg",
}

BAD_IG_HANDLES = {
    # Instagram reserved paths
    'p','reel','reels','stories','explore','accounts','about','help',
    'legal','privacy','safety','directory','music','search','instagram',
    'facebook','twitter','youtube','spotify','tiktok','soundcloud',
    'login','signup','challenge','graphql','api','web','www',
    # CSS at-rules
    'keyframes','media','import','charset','supports','namespace',
    'font','fontface','page','viewport','layer','property','scope',
    # Programming / markup tokens
    'style','styles','script','scripts','function','class','return',
    'undefined','null','true','false','var','let','const','type',
    'each','mixin','include','extend','use','forward',
    # Common English words that appear after @ in web pages (false positives)
    'popular','trending','official','verified','real','the','and','but','for',
    'top','best','new','now','all','your','our','this','that','with','from',
    'more','most','how','why','what','who','when','which','into','over',
    'music','artist','singer','rapper','brand','page','post','share','link',
    'home','news','blog','shop','store','info','contact','support','team',
    'follow','following','followers','likes','comments','views','subscribe',
    'download','stream','listen','watch','click','here','there','where',
    'username','handle','profile','account','user','name','email','phone',
    'booking','management','press','media','label','record','studio',
    'mention','tagged','featured','sponsored','ad','ads','promoted',
    'everyone','someone','anyone','nobody','people','person','world',
    'today','tomorrow','yesterday','week','month','year','time','date',
    # Single letters and very short tokens
    'a','b','c','d','e','f','g','h','i','j','k','l','m',
    'n','o','q','r','s','t','u','v','w','x','y','z',
}

# ── EXTRACTION HELPERS ────────────────────────────────────────────────────────

def extract_ig(text):
    if not text: return None
    patterns = [
        r'instagram\.com/([A-Za-z0-9_.]{3,30})(?:/|\?|"|\s|\'|\\|$)',
        r'(?:^|[\s,;|•·\(])@([A-Za-z0-9_.]{3,30})(?:\s|$|\)|,|\.)',
        r'ig[:\s]+@?([A-Za-z0-9_.]{3,30})',
        r'insta[:\s]+@?([A-Za-z0-9_.]{3,30})',
    ]
    for p in patterns:
        for m in re.finditer(p, text, re.I | re.M):
            h = m.group(1).strip().rstrip('/.,;)')
            if (h.lower() not in BAD_IG_HANDLES
                    and len(h) >= 3
                    and not h.startswith('.')):
                return h
    return None

def extract_facebook(text):
    if not text: return None
    bad = {'sharer','share','login','help','events','dialog','permalink',
           'hashtag','watch','photo','video','groups','story','stories',
           'ads','pages','pg','profile','home'}
    for m in re.finditer(
        r'(?:facebook|fb)\.com/([A-Za-z0-9_.]{3,60})(?:/|\?|"|\s|\'|\\|$)',
        text, re.I
    ):
        h = m.group(1).rstrip('/.,;)')
        if not any(b in h.lower() for b in bad) and len(h) >= 3:
            return f"facebook.com/{h}"
    return None

def extract_phone(text):
    if not text: return None
    m = re.search(
        r'(\+1[\s\-.]?\(?\d{3}\)?[\s\-.]?\d{3}[\s\-.]?\d{4}'
        r'|\+44[\s\-.]?\(?\d{1,4}\)?[\s\-.]?\d{3,4}[\s\-.]?\d{4}'
        r'|\+61[\s\-.]?\(?\d{1}\)?[\s\-.]?\d{4}[\s\-.]?\d{4}'
        r'|\+971[\s\-.]?\d{2}[\s\-.]?\d{3}[\s\-.]?\d{4})',
        text
    )
    return m.group(0).strip() if m else None

def extract_email(text):
    if not text: return None
    m = re.search(
        r'[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}', text)
    if m:
        em = m.group(0).lower()
        skip = ['example','placeholder','domain','sentry','noreply',
                'no-reply','support@last','info@last','privacy@','legal@',
                '@sentry','@example','wixpress','squarespace','wordpress',
                'schema.org']
        if not any(s in em for s in skip):
            return em
    return None

def extract_links(text):
    return re.findall(r'https?://[^\s\)\]\>\<\"\',]+', text)

def _extract_ig_from_url(url_str):
    m = re.search(r'instagram\.com/([A-Za-z0-9_.]{3,30})', url_str, re.I)
    if m:
        h = m.group(1).rstrip('/.,;)')
        if h.lower() not in BAD_IG_HANDLES and len(h) >= 3:
            return h
    return None

def _extract_fb_from_url(url_str):
    return extract_facebook(url_str)

# ── FETCH HELPERS ─────────────────────────────────────────────────────────────

def fetch(url, headers=None, timeout=12):
    try:
        r = requests.get(
            url,
            headers=headers or HEADERS_CHROME,
            timeout=timeout,
            allow_redirects=True,
        )
        return r.text
    except Exception:
        return ""

# ── MUSICBRAINZ (PRIMARY SOURCE) ──────────────────────────────────────────────
# Free, no API key needed. Has structured social links for most known artists.
# Rate limit: 1 req/sec — we add 1.1s sleep between calls.

MB_HEADERS = {
    "User-Agent": "RenegadeEngine/2.0 (renegaderecordsusa@gmail.com)",
    "Accept": "application/json",
}

# MusicBrainz relationship type → what it means
MB_SOCIAL_TYPES = {
    "social network",
    "official homepage",
    "free streaming",
    "streaming",
    "lyrics",
    "other databases",
    "purchase for download",
}

def _get_spotify_monthly_listeners(artist_id):
    """
    Get Spotify monthly listeners via the OG/SEO page Spotify serves to social crawlers.
    Uses Twitterbot User-Agent — Spotify responds with og:description containing
    'Artist · 15K monthly listeners.' which we parse into an integer.
    Returns int or None on failure.
    """
    if not artist_id:
        return None
    _headers = {"User-Agent": "Twitterbot/1.0"}
    for _attempt in range(3):
        try:
            _r = requests.get(
                f"https://open.spotify.com/artist/{artist_id}",
                headers=_headers, timeout=15
            )
            if _r.status_code == 429:
                time.sleep(5 * (_attempt + 1))
                continue
            if _r.status_code != 200:
                break
            _m = re.search(r'([\d,.]+\s*[KkMmBb]?)\s+monthly\s+listener', _r.text, re.I)
            if _m:
                _raw = _m.group(1).strip().upper().replace(',', '').replace(' ', '')
                try:
                    if 'K' in _raw:
                        return int(float(_raw.replace('K', '')) * 1_000)
                    elif 'M' in _raw:
                        return int(float(_raw.replace('M', '')) * 1_000_000)
                    elif 'B' in _raw:
                        return int(float(_raw.replace('B', '')) * 1_000_000_000)
                    else:
                        return int(_raw)
                except Exception:
                    pass
        except Exception:
            pass
        time.sleep(2)
    return None


def musicbrainz_lookup_by_spotify_id(spotify_id):
    """
    Look up MusicBrainz MBID using a Spotify artist ID.
    Much more precise than name search — returns the MBID string or None.
    """
    if not spotify_id:
        return None
    try:
        r = requests.get(
            "https://musicbrainz.org/ws/2/url/",
            params={
                "resource": f"https://open.spotify.com/artist/{spotify_id}",
                "inc": "artist-rels",
                "fmt": "json",
            },
            headers=MB_HEADERS,
            timeout=10,
        )
        time.sleep(1.1)
        if r.status_code != 200:
            return None
        data = r.json()
        for rel in data.get("relations", []):
            artist = rel.get("artist")
            if artist and artist.get("id"):
                log(f"    -> MB Spotify-ID lookup: {artist.get('name')} (mbid={artist['id']})")
                return artist["id"]
    except Exception as e:
        log(f"    -> MB Spotify-ID lookup error: {e}")
    return None


def musicbrainz_fetch_by_mbid(mbid):
    """Fetch full MB artist record (with url-rels) given a known MBID."""
    result = {
        "instagram": None, "facebook": None, "twitter": None,
        "website": None, "tiktok": None, "youtube": None, "spotify_url": None,
    }
    if not mbid:
        return result
    try:
        r = requests.get(
            f"https://musicbrainz.org/ws/2/artist/{mbid}",
            params={"inc": "url-rels", "fmt": "json"},
            headers=MB_HEADERS,
            timeout=10,
        )
        time.sleep(1.1)
        if r.status_code != 200:
            return result
        relations = r.json().get("relations", [])
    except Exception as e:
        log(f"    -> MB fetch by MBID error: {e}")
        return result

    for rel in relations:
        url = rel.get("url", {}).get("resource", "")
        if not url:
            continue
        if "instagram.com" in url and not result["instagram"]:
            ig = _extract_ig_from_url(url)
            if ig:
                result["instagram"] = ig
                log(f"    -> MB (by ID) Instagram: @{ig}")
        elif "facebook.com" in url and not result["facebook"]:
            fb = _extract_fb_from_url(url)
            if fb:
                result["facebook"] = fb
        elif rel.get("type") == "official homepage" and not result["website"]:
            if "instagram.com" not in url and "facebook.com" not in url:
                result["website"] = url
    return result


def musicbrainz_lookup(artist_name):
    """
    Search MusicBrainz for an artist and return their social links.
    Returns dict with instagram, facebook, twitter, website, tiktok, youtube.
    """
    result = {
        "instagram": None, "facebook": None, "twitter": None,
        "website": None, "tiktok": None, "youtube": None,
        "spotify_url": None,
    }

    # Step 1: Search for artist
    try:
        r = requests.get(
            "https://musicbrainz.org/ws/2/artist/",
            params={
                "query": artist_name,
                "fmt": "json",
                "limit": 5,
            },
            headers=MB_HEADERS,
            timeout=10,
        )
        if r.status_code != 200:
            log(f"    -> MusicBrainz search failed: HTTP {r.status_code}")
            return result
        artists = r.json().get("artists", [])
    except Exception as e:
        log(f"    -> MusicBrainz search error: {e}")
        return result

    if not artists:
        log(f"    -> MusicBrainz: no artists found for '{artist_name}'")
        return result

    # Pick highest-score result
    best = max(artists, key=lambda a: a.get("score", 0))
    mbid = best.get("id")
    score = best.get("score", 0)
    log(f"    -> MusicBrainz match: {best.get('name')} (score={score}, mbid={mbid})")

    if score < 60:
        log(f"    -> MusicBrainz: match score too low ({score}), skipping")
        return result

    time.sleep(1.1)  # respect 1 req/sec rate limit

    # Step 2: Fetch full artist record with URL relations
    try:
        r2 = requests.get(
            f"https://musicbrainz.org/ws/2/artist/{mbid}",
            params={"inc": "url-rels", "fmt": "json"},
            headers=MB_HEADERS,
            timeout=10,
        )
        if r2.status_code != 200:
            log(f"    -> MusicBrainz relations failed: HTTP {r2.status_code}")
            return result
        relations = r2.json().get("relations", [])
    except Exception as e:
        log(f"    -> MusicBrainz relations error: {e}")
        return result

    # Step 3: Extract social links from relations
    for rel in relations:
        url = rel.get("url", {}).get("resource", "")
        rel_type = rel.get("type", "").lower()

        if not url:
            continue

        if "instagram.com" in url and not result["instagram"]:
            ig = _extract_ig_from_url(url)
            if ig:
                result["instagram"] = ig
                log(f"    -> MB Instagram: @{ig}")

        elif "facebook.com" in url and not result["facebook"]:
            fb = _extract_fb_from_url(url)
            if fb:
                result["facebook"] = fb
                log(f"    -> MB Facebook: {fb}")

        elif "twitter.com" in url and not result["twitter"]:
            m = re.search(r'twitter\.com/([A-Za-z0-9_]{1,50})', url)
            if m:
                result["twitter"] = m.group(1)
                log(f"    -> MB Twitter: @{result['twitter']}")

        elif "tiktok.com" in url and not result["tiktok"]:
            m = re.search(r'tiktok\.com/@?([A-Za-z0-9_.]{1,50})', url)
            if m:
                result["tiktok"] = m.group(1)

        elif "youtube.com" in url and not result["youtube"]:
            result["youtube"] = url

        elif "spotify.com" in url and not result["spotify_url"]:
            result["spotify_url"] = url

        elif rel_type == "official homepage" and not result["website"]:
            if "instagram.com" not in url and "facebook.com" not in url:
                result["website"] = url
                log(f"    -> MB Website: {url}")

    return result

# ── LAST.FM BIO ───────────────────────────────────────────────────────────────

def get_lastfm_bio(artist_name, api_key="156d007301853d76f0d41665092f879a"):
    try:
        r = requests.get("https://ws.audioscrobbler.com/2.0/", params={
            "method": "artist.getinfo", "artist": artist_name,
            "api_key": api_key, "format": "json", "autocorrect": 1
        }, timeout=8)
        d   = r.json().get("artist", {})
        bio = d.get("bio", {}).get("summary", "")
        return bio
    except Exception:
        return ""

# ── ARTIST WEBSITE ────────────────────────────────────────────────────────────

def scrape_artist_website(url):
    result = {"instagram": None, "facebook": None, "email": None}
    if not url: return result

    html = fetch(url)
    if not html: return result

    result["instagram"] = extract_ig(html)
    result["facebook"]  = extract_facebook(html)
    result["email"]     = extract_email(html)

    # Also check /contact page
    if not result["email"]:
        contact_url = urljoin(url, "/contact")
        html2 = fetch(contact_url)
        if html2:
            result["email"] = extract_email(html2)

    return result

# ── LINKTREE ──────────────────────────────────────────────────────────────────

def resolve_linktree(url):
    html = fetch(url)
    if not html: return None, None
    return extract_ig(html), extract_email(html)

# ── INSTAGRAM PROFILE (via internal API) ──────────────────────────────────────

def fetch_instagram_profile(handle):
    """
    Fetch Instagram profile data via the internal JSON API.
    Falls back to mobile HTML if the API returns 401/403.
    """
    info = {
        "handle":            handle,
        "followers":         None,
        "bio":               "",
        "email":             None,
        "facebook":          None,
        "phone":             None,
        "type":              "unknown",
        "verified":          False,
        "found":             False,
        "definitely_deleted": False,  # True only when profile is provably gone (404 / explicit not-found page)
        "notes":             "",
    }

    # ── Method 1: i.instagram.com internal JSON API ───────────────────────────
    try:
        r = requests.get(
            f"https://i.instagram.com/api/v1/users/web_profile_info/?username={handle}",
            headers=HEADERS_IG_API,
            timeout=12,
        )
        if r.status_code == 200:
            data = r.json()
            user = data.get("data", {}).get("user", {})
            if user:
                info["found"]     = True
                info["bio"]       = (user.get("biography") or "").strip()
                info["followers"] = (user.get("edge_followed_by") or {}).get("count")
                info["verified"]  = bool(user.get("is_verified"))
                log(f"    -> [IG JSON API] Profile found: {user.get('full_name','')}, followers={info['followers']}")
        else:
            log(f"    -> [IG JSON API] HTTP {r.status_code}")
    except Exception as e:
        log(f"    -> [IG JSON API] Error: {e}")

    # ── Method 2: www.instagram.com API endpoint (alternate) ─────────────────
    if not info["found"]:
        try:
            r = requests.get(
                f"https://www.instagram.com/api/v1/users/web_profile_info/?username={handle}",
                headers={
                    **HEADERS_IG_API,
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
                },
                timeout=12,
            )
            if r.status_code == 200:
                data = r.json()
                user = data.get("data", {}).get("user", {})
                if user:
                    info["found"]     = True
                    info["bio"]       = (user.get("biography") or "").strip()
                    info["followers"] = (user.get("edge_followed_by") or {}).get("count")
                    info["verified"]  = bool(user.get("is_verified"))
                    log(f"    -> [IG www API] Profile found: followers={info['followers']}")
        except Exception as e:
            log(f"    -> [IG www API] Error: {e}")

    # ── Method 3: Mobile HTML fallback (Instagram may serve partial data) ─────
    if not info["found"]:
        try:
            html = fetch(f"https://www.instagram.com/{handle}/", HEADERS_MOBILE)
            # Detect explicit "account gone" pages — these are definitive, not transient
            _gone_phrases = ["page not found", "sorry, this page", "user_not_found",
                             "the link you followed may be broken", "this account doesn't exist"]
            if html and any(p in html.lower() for p in _gone_phrases):
                info["definitely_deleted"] = True
                log(f"    -> [IG HTML] Profile @{handle} is definitively gone (not-found page detected)")
                return info
            if html and "Page Not Found" not in html and "Sorry, this page" not in html:
                for pat in [
                    r'"biography"\s*:\s*"((?:[^"\\]|\\.)*?)"',
                    r'<meta name="description" content="([^"]+)"',
                    r'content="([^"]*?)" property="og:description"',
                ]:
                    m = re.search(pat, html, re.S)
                    if m:
                        bio = m.group(1)
                        bio = (bio.replace('\\n', ' ').replace('\\"', '"')
                               .replace('\\u0040', '@').replace('\\u2019', "'"))
                        if len(bio) > 3:
                            info["bio"]   = bio
                            info["found"] = True
                            log(f"    -> [IG HTML] Got bio from mobile page")
                            break

                for pat in [
                    r'"edge_followed_by":\{"count":(\d+)\}',
                    r'"followers_count":(\d+)',
                    r'"followers":(\d+)',
                ]:
                    m = re.search(pat, html)
                    if m:
                        info["followers"] = int(m.group(1))
                        break
        except Exception as e:
            log(f"    -> [IG HTML] Error: {e}")

    # ── Method 4: oEmbed — just verify handle exists ──────────────────────────
    if not info["found"]:
        try:
            r = requests.get(
                f"https://www.instagram.com/oembed/?url=https://www.instagram.com/{handle}/",
                headers=HEADERS_CHROME,
                timeout=8,
            )
            if r.status_code == 200:
                info["found"] = True
                log(f"    -> [IG oEmbed] Handle @{handle} verified as existing")
        except Exception:
            pass

    if not info["found"]:
        info["notes"] = "Could not fetch profile (Instagram requires login for HTML)"
        return info

    # ── Extract contacts from bio ─────────────────────────────────────────────
    if info["bio"]:
        info["email"]    = extract_email(info["bio"])
        info["facebook"] = extract_facebook(info["bio"])
        info["phone"]    = extract_phone(info["bio"])

        for link in extract_links(info["bio"]):
            if "linktr.ee" in link or "linktree" in link:
                ig2, em2 = resolve_linktree(link)
                if em2 and not info["email"]:
                    info["email"] = em2
                    log(f"    -> [IG Linktree] Email: {em2}")

    # ── Classify artist vs producer ───────────────────────────────────────────
    bio_low = (info["bio"] or "").lower()

    # Hard skip keywords — always disqualify, no override possible
    hard_skip_kw = {
        "beat maker", "beatmaker", "music producer", "beat store",
        "sell beats", "selling beats", "buy beats", "lease beats",
        "exclusive beats", "type beat",
        # Engineers — not performers
        "audio engineer", "recording engineer", "sound engineer",
        "mastering engineer", "music engineer", "studio engineer",
        # Session roles — work for other artists, not the target
        "session musician", "session player", "session artist",
        "session guitarist", "session drummer", "session bassist",
    }
    # Soft-skip keywords — skip unless clear performer words override
    # NOTE: "musician" is intentionally NOT here — too many legitimate R&B/hip-hop
    # artists use "musician" in their bio. It's neutral (neither confirms artist
    # nor triggers skip). Only the hard_skip_kw engineering roles are reliable signals.
    soft_skip_kw = [
        "producer", "beats by", "instrumentalist", "composer",
        "film composer", "beatsmith", "tracksmith", "track producer",
        "mixing engineer", "rap producer", "trap producer", "rnb producer",
        "prod by", "prod.", "free beat", "lease beat", "exclusive beat",
    ]
    # Clear performer keywords — override soft-skip
    performer_kw = [
        "singer", "rapper", "vocalist", "performer", "entertainer",
    ]
    # Supporting artist context — confirms music artist status
    artist_context_kw = [
        "artist", "songwriter",
        "new music", "stream now", "out now", "listen now",
        "new single", "new album", "new ep", "available on spotify",
        "on all platforms", "follow me on spotify",
    ]

    hard_hit = next((kw for kw in hard_skip_kw if kw in bio_low), None)
    soft_hits = [kw for kw in soft_skip_kw if kw in bio_low]
    perf_hits = [kw for kw in performer_kw if kw in bio_low]
    ctx_hits  = [kw for kw in artist_context_kw if kw in bio_low]

    if hard_hit:
        info["type"]  = "producer"
        info["notes"] = f"Hard skip keyword in bio: '{hard_hit}'"
    elif soft_hits and not perf_hits:
        info["type"]  = "producer"
        info["notes"] = f"Soft skip (no performer keywords): {', '.join(soft_hits[:3])}"
    elif perf_hits:
        info["type"]  = "artist"
        info["notes"] = f"Performer keywords: {', '.join(perf_hits[:3])}"
    elif ctx_hits:
        info["type"]  = "artist"
        info["notes"] = f"Artist context: {', '.join(ctx_hits[:2])}"
    else:
        info["type"]  = "unknown"
        info["notes"] = "No keywords found in bio"

    time.sleep(0.3)
    return info

# ── STARTPAGE SEARCH (GOOGLE PROXY — primary web search fallback) ─────────────
# Startpage proxies Google results and serves real HTML (no JS-only shell).
# Direct href links — no redirect encoding — so extract_ig works cleanly.

HEADERS_STARTPAGE = {
    **HEADERS_CHROME,
    "Referer": "https://www.startpage.com/",
}

def startpage_search(query):
    try:
        r = requests.get(
            "https://www.startpage.com/do/search",
            params={"q": query, "cat": "web", "language": "english"},
            headers=HEADERS_STARTPAGE,
            timeout=12,
        )
        if r.status_code == 200:
            time.sleep(0.4)
            return r.text
    except Exception:
        pass
    time.sleep(0.4)
    return ""

def validate_instagram_handle(handle):
    """
    Existence check via direct profile page fetch.
    Returns True (exists + available), False (gone/invalid/unavailable), None (uncertain).
    oEmbed is broken (returns HTML for all handles since ~2024), so we check the profile
    page directly: valid profiles have a handle-specific og:title; unavailable pages don't.
    """
    if not handle:
        return False
    handle = handle.strip().lstrip("@")
    try:
        r = requests.get(
            f"https://www.instagram.com/{handle}/",
            headers={"User-Agent": "Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)"},
            timeout=10,
            allow_redirects=True,
        )
        if r.status_code == 404:
            return False
        if r.status_code in (401, 403):
            return None
        if r.status_code == 200:
            text = r.text
            # Unavailable accounts: IG shows a generic "Sorry, this page isn't available" page
            if "sorry, this page" in text.lower() or "page isn't available" in text.lower():
                return False
            # Valid profile: og:title contains the handle
            og_title = re.search(r'<meta property="og:title" content="([^"]+)"', text, re.I)
            if og_title and handle.lower() in og_title.group(1).lower():
                return True
            # Check for "username • Instagram" in <title>
            title_m = re.search(r'<title>([^<]+)</title>', text, re.I)
            if title_m and handle.lower() in title_m.group(1).lower():
                return True
            # Got 200 but can't confirm — treat as uncertain
            return None
        return None
    except Exception:
        return None


def _handle_looks_related(artist_name, handle):
    """
    Check: IG handle must share meaningful content with the artist name.
    For short names (≤3 clean chars) the full name must appear in the handle.
    For longer names, 4+ consecutive chars must appear.
    """
    name_clean   = re.sub(r'[^a-z0-9]', '', artist_name.lower())
    handle_clean = re.sub(r'[^a-z0-9]', '', handle.lower())
    if not name_clean or not handle_clean:
        return False
    # Short names (≤3 chars): require full name match in handle
    if len(name_clean) <= 3:
        return name_clean in handle_clean
    # Normal: at least 4 consecutive chars of the name must appear in the handle
    for length in range(min(len(name_clean), 7), 3, -1):
        for start in range(len(name_clean) - length + 1):
            if name_clean[start:start+length] in handle_clean:
                return True
    return False


def guess_instagram_handles(artist_name):
    """
    Generate likely Instagram handle candidates from the artist name.
    Tries the most obvious transformations first: lowercase-no-spaces,
    with-dots, with-underscores, and common suffix variants.
    Used for small indie artists who aren't indexed by Google/DDG.
    """
    base = re.sub(r'[^a-z0-9]', '', artist_name.lower())
    words = re.sub(r'[^a-z0-9 ]', '', artist_name.lower()).strip().split()
    spaced_dot = '.'.join(words)
    spaced_us  = '_'.join(words)

    raw = [
        base,
        spaced_dot,
        spaced_us,
        f"{base}music",
        f"{base}_music",
        f"_{base}",
        f"the{base}",
        f"{base}official",
    ]
    seen, out = set(), []
    for h in raw:
        if h and len(h) >= 3 and h.lower() not in BAD_IG_HANDLES and h not in seen:
            seen.add(h)
            out.append(h)
    return out


def startpage_find_socials(artist_name):
    """Search Startpage (Google proxy) for artist social profiles.
    Collects ALL candidate handles from hrefs, validates each via oEmbed,
    and accepts only the first that either (a) validates as real or (b) name-matches.
    """
    result = {"instagram": None, "facebook": None}

    ig_queries = [
        f'"{artist_name}" site:instagram.com',
        f"{artist_name} official instagram singer rapper",
        f"{artist_name} instagram music artist",
    ]
    for q in ig_queries:
        html = startpage_search(q)
        if not html:
            continue

        # Collect all candidate instagram handles from hrefs in this page
        candidates = []
        for m in re.finditer(r'href=["\']([^"\']*instagram\.com/([A-Za-z0-9_.]{3,30})[^"\'<\s]*)', html, re.I):
            ig = _extract_ig_from_url(unquote(m.group(1)))
            if ig and ig.lower() not in BAD_IG_HANDLES and ig not in candidates:
                candidates.append(ig)

        # Also try @mention text — but only if it name-matches
        text_ig = extract_ig(html)
        if text_ig and _handle_looks_related(artist_name, text_ig) and text_ig not in candidates:
            candidates.append(text_ig)

        # Validate candidates: name-matched first, then others
        name_matched = [h for h in candidates if _handle_looks_related(artist_name, h)]
        other = [h for h in candidates if h not in name_matched]

        for handle in (name_matched + other):
            valid = validate_instagram_handle(handle)
            if valid is True:
                result["instagram"] = handle
                log(f"    -> Startpage IG (validated): @{handle}")
                break
            elif valid is False:
                log(f"    -> Startpage IG @{handle} rejected (oEmbed 404)")
            # valid is None (uncertain) — accept if it name-matches
            elif valid is None and _handle_looks_related(artist_name, handle):
                result["instagram"] = handle
                log(f"    -> Startpage IG (name-matched, unverified): @{handle}")
                break

        if result["instagram"]:
            break

    if not IG_ONLY and not result["facebook"]:
        for q in [f"{artist_name} facebook music artist", f'"{artist_name}" facebook singer']:
            html = startpage_search(q)
            if not html:
                continue
            for m in re.finditer(r'href=["\']([^"\']*facebook\.com/[^"\'<\s]+)', html, re.I):
                fb = extract_facebook(unquote(m.group(1)))
                if fb:
                    result["facebook"] = fb
                    break
            if not result["facebook"]:
                fb = extract_facebook(html)
                if fb:
                    result["facebook"] = fb
            if result["facebook"]:
                break

    return result

# ── DUCKDUCKGO (LAST-RESORT FALLBACK) ────────────────────────────────────────
# DDG often triggers CAPTCHA challenges; kept as final fallback only.

def _parse_ddg_links(html):
    """
    DDG HTML results redirect through their own domain with uddg= param.
    Decode those as well as any direct href links.
    """
    urls = []
    for m in re.finditer(r'uddg=([^&"\'<\s]+)', html):
        urls.append(unquote(m.group(1)))
    for m in re.finditer(r'href="(https?://[^"]+)"', html):
        urls.append(m.group(1))
    return urls

def ddg_search(query):
    html = fetch(
        f"https://html.duckduckgo.com/html/?q={quote_plus(query)}",
        HEADERS_CHROME,
    )
    time.sleep(0.8)
    return html or ""

def ddg_find_socials(artist_name):
    result = {"instagram": None, "facebook": None}

    ig_queries = [
        f'"{artist_name}" instagram music artist',
        f"{artist_name} official instagram singer rapper",
    ]
    for q in ig_queries:
        html = ddg_search(q)
        if not html or "anomaly" in html:
            continue

        # Collect all candidate handles from decoded DDG links
        candidates = []
        for url in _parse_ddg_links(html):
            if "instagram.com/" in url:
                ig = _extract_ig_from_url(url)
                if ig and ig.lower() not in BAD_IG_HANDLES and ig not in candidates:
                    candidates.append(ig)
        # @mention text fallback — only if name-matched
        text_ig = extract_ig(html)
        if text_ig and _handle_looks_related(artist_name, text_ig) and text_ig not in candidates:
            candidates.append(text_ig)

        name_matched = [h for h in candidates if _handle_looks_related(artist_name, h)]
        other = [h for h in candidates if h not in name_matched]

        for handle in (name_matched + other):
            valid = validate_instagram_handle(handle)
            if valid is True:
                result["instagram"] = handle
                log(f"    -> DDG IG (validated): @{handle}")
                break
            elif valid is False:
                log(f"    -> DDG IG @{handle} rejected (oEmbed 404)")
            elif valid is None and _handle_looks_related(artist_name, handle):
                result["instagram"] = handle
                log(f"    -> DDG IG (name-matched, unverified): @{handle}")
                break

        if result["instagram"]:
            break

    if not IG_ONLY and not result["facebook"]:
        for q in [f"{artist_name} facebook music artist"]:
            html = ddg_search(q)
            if not html or "anomaly" in html:
                continue
            for url in _parse_ddg_links(html):
                if "facebook.com/" in url:
                    fb = extract_facebook(url)
                    if fb:
                        result["facebook"] = fb
                        break
            if not result["facebook"]:
                fb = extract_facebook(html)
                if fb:
                    result["facebook"] = fb
            if result["facebook"]:
                break

    return result

# keep old name as alias
def ddg_find_instagram(artist_name):
    return ddg_find_socials(artist_name)["instagram"]


def _normalize_name_for_search(name):
    """Clean artist name for use in search queries. Special chars like $ break DDG/Startpage."""
    n = name
    # Strip stylized special chars — don't replace them with letters (creates wrong words)
    n = re.sub(r'[^\w\s\-\.]', '', n)
    return n.strip()


def _name_needs_disambiguation(original_name, normalized=None):
    """True for names that produce noisy search results without extra context."""
    clean = (normalized or original_name).strip()
    # Purely numeric
    if re.fullmatch(r'[\d\s\-]+', clean):
        return True
    # Short (≤4 chars after normalization)
    if len(clean) <= 4:
        return True
    # Mostly digits
    if sum(c.isdigit() for c in clean) / max(len(clean), 1) >= 0.5:
        return True
    # Name had special chars stripped — stylized names like S!MONE, TheARTI$T need music context
    if re.search(r'[!$#%^&*]', original_name):
        return True
    return False


def _find_instagram(artist_name):
    """
    Find artist Instagram via web search.
    Strategy:
      1. Original name queries first (search engines handle $ ! etc. — "TheARTI$t" works better than "TheARTIt")
      2. "official" queries — directly targets handles like @theofficial303
      3. General "music" queries — broader context
      4. site:instagram.com queries — last resort
    Within each query result, prefer handles containing "official" over others.
    Always includes "music" context regardless of name length.
    """
    search_name = _normalize_name_for_search(artist_name)
    ambiguous = _name_needs_disambiguation(artist_name, search_name)

    # If the name has special chars (TheARTI$t, S!MONE), use the original name first.
    # Search engines handle $ ! etc. and find the right artist; the normalized version
    # often produces no useful results because "TheARTIt" means nothing to a search engine.
    has_special = search_name != artist_name.strip()
    orig = artist_name.strip()

    original_queries = ([
        f'"{orig}" official instagram',
        f'"{orig}" music instagram',
    ]) if has_special else []

    official_queries = [
        f'"{search_name}" official instagram',
        f'{search_name} official music instagram',
    ]
    general_queries = [
        f'"{search_name}" music instagram',
        f'{search_name} music rapper singer instagram',
    ]
    site_queries = [
        f'"{search_name}" music site:instagram.com',
        f'{search_name} music site:instagram.com',
    ]

    order = [(False, original_queries), (False, official_queries), (False, general_queries), (True, site_queries)]

    _name_exact = re.sub(r'[^a-z0-9]', '', search_name.lower())

    def _reject_handle(ig_handle):
        if not ambiguous:
            return False
        h = re.sub(r'[^a-z0-9]', '', ig_handle.lower())
        return h == _name_exact

    def _search_and_pick(candidates_iter, is_site, source):
        """
        Collect all valid candidates from results, return the best one.
        Prefers handles containing 'official' — catches @theofficial303 over @the303.
        """
        valid_handles = []
        for ig in candidates_iter:
            if not ig or ig.lower() in BAD_IG_HANDLES:
                continue
            if _reject_handle(ig):
                log(f"    -> {source} @{ig}: exact-name match rejected (too generic)")
                continue
            if not is_site and not _handle_looks_related(artist_name, ig):
                continue
            valid = validate_instagram_handle(ig)
            if valid is not False:
                valid_handles.append(ig)
                if len(valid_handles) >= 5:
                    break
            else:
                log(f"    -> {source} @{ig}: invalid profile, skipped")
        if not valid_handles:
            return None
        # Prefer handles with "official" in them
        official = [h for h in valid_handles if "official" in h.lower()]
        chosen = official[0] if official else valid_handles[0]
        log(f"    -> {source} {'site:' if is_site else 'general'}: @{chosen}")
        return chosen

    for is_site, queries in order:
        for q in queries:
            # ── DuckDuckGo ────────────────────────────────────────────────────
            html = ddg_search(q)
            if html and "anomaly" not in html.lower():
                candidates = (_extract_ig_from_url(u) for u in _parse_ddg_links(html))
                result = _search_and_pick(candidates, is_site, "DDG")
                if result:
                    return result

            # ── Startpage ─────────────────────────────────────────────────────
            html = startpage_search(q)
            if html:
                urls = (unquote(m.group(1)) for m in re.finditer(
                    r'href=["\']([^"\']*instagram\.com/[^"\'<\s]+)', html, re.I
                ))
                candidates = (_extract_ig_from_url(u) for u in urls)
                result = _search_and_pick(candidates, is_site, "Startpage")
                if result:
                    return result

    return None

# ── GOOGLE KNOWLEDGE PANEL (FALLBACK) ─────────────────────────────────────────
# Google now serves JS-rendered pages to bots, so this may return nothing.
# Kept as final fallback with consent-cookie bypass attempt.

def google_knowledge_panel(artist_name):
    result = {"instagram": None, "facebook": None, "phone": None,
              "email": None, "website": None, "links": []}

    queries = [
        f"{artist_name} musician",
        f"{artist_name} singer",
        f'"{artist_name}" official instagram',
    ]

    for query in queries:
        url  = f"https://www.google.com/search?q={quote_plus(query)}&hl=en&gl=us"
        html = fetch(url, HEADERS_GOOGLE)

        if not html:
            time.sleep(1)
            continue

        # Skip JS-only shell pages (no real results)
        if html.count('<a') < 10 or len(html) < 5000:
            log(f"    -> Google returned JS-only shell, skipping")
            time.sleep(1)
            continue

        if "detected unusual traffic" in html.lower() or "captcha" in html.lower():
            log(f"    -> Google bot-blocked, skipping")
            time.sleep(2)
            continue

        # JSON-LD sameAs
        for ld_match in re.finditer(
            r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
            html, re.I | re.S
        ):
            try:
                ld = json.loads(ld_match.group(1))
                entries = ld if isinstance(ld, list) else [ld]
                for entry in entries:
                    for link in (entry.get("sameAs") or []):
                        if not result["instagram"]:
                            ig = _extract_ig_from_url(link)
                            if ig: result["instagram"] = ig
                        if not result["facebook"] and "facebook.com" in link:
                            fb = _extract_fb_from_url(link)
                            if fb: result["facebook"] = fb
                        if not result.get("website") and "instagram.com" not in link \
                                and "facebook.com" not in link and link.startswith("http"):
                            result["website"] = link
            except Exception:
                pass

        # /url?q= redirect links
        for m in re.finditer(r'/url\?(?:[^"\'<\s]*&amp;|[^"\'<\s]*)q=(https?[^&"\'<\s]+)', html):
            decoded = unquote(m.group(1))
            if not result["instagram"] and "instagram.com/" in decoded:
                ig = _extract_ig_from_url(decoded)
                if ig: result["instagram"] = ig
            if not result["facebook"] and "facebook.com/" in decoded:
                fb = _extract_fb_from_url(decoded)
                if fb: result["facebook"] = fb

        # Direct href patterns — collect all candidates and validate
        if not result["instagram"]:
            ig_candidates = []
            for p in [
                r'instagram\.com/([A-Za-z0-9_.]{3,30})"',
                r'instagram\.com/([A-Za-z0-9_.]{3,30})\\/',
                r'"https://(?:www\.)?instagram\.com/([A-Za-z0-9_.]{3,30})',
                r'instagram\.com%2F([A-Za-z0-9_.]{3,30})',
            ]:
                for m in re.finditer(p, html, re.I):
                    h = m.group(1).rstrip('/')
                    if h.lower() not in BAD_IG_HANDLES and len(h) >= 3 and h not in ig_candidates:
                        ig_candidates.append(h)
            for h in ig_candidates:
                valid = validate_instagram_handle(h)
                if valid is True:
                    result["instagram"] = h
                    break
                elif valid is None:
                    result["instagram"] = h  # uncertain — keep it
                    break
                # valid is False — skip this handle

        if not result["facebook"]:
            fb = extract_facebook(html)
            if fb: result["facebook"] = fb
        if not result["phone"]:
            ph = extract_phone(html)
            if ph: result["phone"] = ph
        em = extract_email(html)
        if em and not result["email"]: result["email"] = em

        result["links"].extend(extract_links(html))

        if result["instagram"] or result["website"]:
            break

        time.sleep(1.2)

    return result

# ── MAIN RESOLUTION PIPELINE ──────────────────────────────────────────────────

def resolve(artist_name, platform="", existing_ig=None, profile_url=None):
    """
    Full contact resolution pipeline for one artist.
    For Spotify artists, uses Spotify ID → MusicBrainz for maximum precision.
    Returns dict with instagram, facebook, phone, email, ig_followers, etc.
    """
    log(f"\n  [{artist_name}] platform={platform}")
    out = {
        "instagram":       existing_ig,
        "facebook":        None,
        "phone":           None,
        "email":           None,
        "ig_followers":    None,
        "ig_bio":          "",
        "ig_type":         "unknown",
        "ig_verified":     False,
        "contact_quality": "none",
        "listeners":       None,   # verified listener count (set when MB confirms)
        "skip":            False,
        "skip_reason":     "",
    }

    # Pre-validate any existing handle before it blocks the search steps.
    # A clean oEmbed 404 = account provably doesn't exist → clear it so
    # Steps 1–4 run a fresh search and find the real handle.
    if out["instagram"]:
        _pre = validate_instagram_handle(out["instagram"])
        if _pre is False:
            log(f"    -> Existing @{out['instagram']} pre-check: oEmbed 404 — cleared, will re-search")
            out["instagram"] = None
        elif _pre is True:
            log(f"    -> Existing @{out['instagram']} pre-check: valid")
        else:
            log(f"    -> Existing @{out['instagram']} pre-check: uncertain (rate-limited) — keeping for Step 5")

    # ── Step 1: Google Knowledge Panel (PRIMARY) ─────────────────────────────
    # Google runs first — it surfaces the artist's official Instagram on the
    # first result for most independent artists and is faster than MusicBrainz.
    log(f"    Step 1: Google Knowledge Panel...")
    try:
        kp = google_knowledge_panel(artist_name)
        if kp.get("instagram") and not out["instagram"]:
            out["instagram"] = kp["instagram"]
            log(f"    -> Google IG: @{kp['instagram']}")
        if not IG_ONLY:
            if kp.get("facebook") and not out["facebook"]:
                out["facebook"] = kp["facebook"]
                log(f"    -> Google Facebook: {kp['facebook']}")
            if kp.get("phone") and not out["phone"]:
                out["phone"] = kp["phone"]
            if kp.get("email") and not out["email"]:
                out["email"] = kp["email"]
        if kp.get("website") and not out["instagram"]:
            ws = scrape_artist_website(kp["website"])
            if ws.get("instagram") and not out["instagram"]:
                out["instagram"] = ws["instagram"]
                log(f"    -> Google→Website IG: @{ws['instagram']}")
            if not IG_ONLY and ws.get("email") and not out["email"]:
                out["email"] = ws["email"]
                log(f"    -> Google→Website email: {ws['email']}")
        if not kp.get("instagram"):
            log(f"    -> Google: nothing found")
    except Exception as e:
        log(f"    -> Google error: {e}")

    # Step 1b (direct handle guess) intentionally removed — guessing produces
    # false positives: @ariza, @randywhite, @durte all exist as real accounts
    # owned by different people. oEmbed validation only checks existence, not identity.

    # ── Step 2: Spotify-ID → MusicBrainz (Spotify artists only) ─────────────
    # Highly precise — skips ambiguous name search by using the Spotify ID directly.
    # Only runs if Google didn't already find the Instagram.
    if platform == "spotify" and profile_url and "open.spotify.com/artist/" in profile_url:
        m = re.search(r'open\.spotify\.com/artist/([A-Za-z0-9]+)', profile_url)
        if m:
            spotify_id = m.group(1)
            log(f"    Step 2: Spotify ID → MusicBrainz (id={spotify_id})...")
            mbid = musicbrainz_lookup_by_spotify_id(spotify_id)
            if mbid:
                mb_precise = musicbrainz_fetch_by_mbid(mbid)
                if mb_precise.get("instagram") and not out["instagram"]:
                    out["instagram"] = mb_precise["instagram"]
                    log(f"    -> MB IG: @{out['instagram']} (via Spotify ID)")
                if not IG_ONLY:
                    if mb_precise.get("facebook") and not out["facebook"]:
                        out["facebook"] = mb_precise["facebook"]
                if mb_precise.get("website") and not out["instagram"]:
                    ws = scrape_artist_website(mb_precise["website"])
                    if ws.get("instagram") and not out["instagram"]:
                        out["instagram"] = ws["instagram"]
                    if not IG_ONLY and ws.get("email") and not out["email"]:
                        out["email"] = ws["email"]

                # ── Listener count via unified Spotify scraper ───────────────
                _sp2_n = _get_spotify_monthly_listeners(spotify_id)
                if _sp2_n is not None:
                    out["listeners"] = _sp2_n
                    log(f"    -> Spotify monthly listeners: {_sp2_n:,}")
                    if _sp2_n > 100_000:
                        out["skip"]        = True
                        out["skip_reason"] = f"Established artist: {_sp2_n:,} Spotify monthly listeners"
                        log(f"    -> AUTO-SKIP: {_sp2_n:,} Spotify monthly listeners > 100k cap")
            else:
                log(f"    -> MB: no record for Spotify ID {spotify_id}")

    # ── Step 2b: Spotify page social links ───────────────────────────────────
    # Spotify embeds artist external links (Instagram, etc.) in the page HTML.
    # More reliable than search for artists with ambiguous/short names.
    if not out["instagram"] and platform == "spotify" and profile_url:
        _sp_ig_m = re.search(r'open\.spotify\.com/artist/([A-Za-z0-9]+)', profile_url)
        if _sp_ig_m:
            try:
                _sp_pg = requests.get(
                    f"https://open.spotify.com/artist/{_sp_ig_m.group(1)}",
                    headers={
                        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
                        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                        "Accept-Language": "en-US,en;q=0.9",
                    }, timeout=12
                )
                if _sp_pg.status_code == 200:
                    # Instagram links embedded in the page
                    for _ig_url in re.findall(r'https?://(?:www\.)?instagram\.com/([A-Za-z0-9_.]+)', _sp_pg.text):
                        _ig_c = _ig_url.strip("/").split("?")[0]
                        if _ig_c and _ig_c.lower() not in BAD_IG_HANDLES:
                            _v = validate_instagram_handle(_ig_c)
                            if _v is True:
                                out["instagram"] = _ig_c
                                log(f"    -> Spotify page IG: @{_ig_c}")
                                break
            except Exception as _e:
                log(f"    -> Spotify page social scrape error: {_e}")

    # ── Step 3: Instagram web search (DDG site: → Startpage → general) ─────────
    if not out["instagram"]:
        log(f"    Step 3: Instagram search (DDG site:instagram.com → Startpage → general)...")
        ig = _find_instagram(artist_name)
        if ig:
            out["instagram"] = ig
            log(f"    -> Step 3 found: @{ig}")

    # ── Step 3b: MusicBrainz name search (structured data fallback) ──────────
    if not out["instagram"]:
        try:
            mb = musicbrainz_lookup(artist_name)
            if mb.get("instagram"):
                out["instagram"] = mb["instagram"]
                log(f"    -> MB IG: @{mb['instagram']}")
            if mb.get("website") and not out["instagram"]:
                ws = scrape_artist_website(mb["website"])
                if ws.get("instagram"):
                    out["instagram"] = ws["instagram"]
                    log(f"    -> MB Website IG: @{ws['instagram']}")
        except Exception as e:
            log(f"    -> MB error: {e}")

    # ── Step 3c: Handle guessing (last resort for short/unusual names) ────────
    if not out["instagram"]:
        log(f"    Step 3c: Handle guessing (last resort)...")
        _guess_name_exact = re.sub(r'[^a-z0-9]', '', artist_name.lower())
        _guess_ambiguous = _name_needs_disambiguation(artist_name)
        for _h in guess_instagram_handles(artist_name):
            _h_clean = re.sub(r'[^a-z0-9]', '', _h.lower())
            # For ambiguous names, reject handles that are exactly the bare name
            if _guess_ambiguous and _h_clean == _guess_name_exact:
                log(f"    -> Guessed @{_h}: exact-name match rejected (too generic)")
                continue
            _v = validate_instagram_handle(_h)
            if _v is True and _handle_looks_related(artist_name, _h):
                out["instagram"] = _h
                log(f"    -> Guessed handle validated: @{_h}")
                break
            elif _v is False:
                log(f"    -> Guessed @{_h}: oEmbed 404, skipped")

    time.sleep(0.3)

    # ── Step 4b: Name-pattern producer check (before IG lookup) ─────────────
    # Catches producers whose Spotify profile doesn't mention "producer"
    if not out["skip"]:
        producer_name_kw = [
            "beats by", "beat by", "prod by", "prod.", " beats", "beatz",
            " producer", "beatmaker", "beat maker",
        ]
        name_low = artist_name.lower()
        hit = next((kw for kw in producer_name_kw if kw in name_low), None)
        if hit:
            out["skip"]        = True
            out["skip_reason"] = f"Producer keyword in artist name: '{hit}'"
            log(f"    -> NAME-SKIP: {out['skip_reason']}")

    # ── Step 5: Fetch Instagram profile ──────────────────────────────────────
    if out["instagram"]:
        log(f"    Step 5/6: Instagram profile @{out['instagram']}...")
        try:
            ig_info = fetch_instagram_profile(out["instagram"])

            if not ig_info["found"]:
                if ig_info.get("definitely_deleted"):
                    # Profile is provably gone (explicit 404 / not-found page) — safe to clear
                    log(f"    -> @{out['instagram']} definitely deleted/deactivated — cleared")
                    out["instagram"] = None
                else:
                    # Full fetch failed (rate limit/blocking) — run oEmbed sanity check before preserving
                    oembed_valid = validate_instagram_handle(out["instagram"])
                    if oembed_valid is False:
                        log(f"    -> @{out['instagram']} oEmbed 404 — handle cleared (doesn't exist)")
                        out["instagram"] = None
                    else:
                        # oEmbed uncertain (rate-limited) — clear and let Step 5b find a verified handle.
                        # Keeping an unverified handle causes it to appear in Contacts Found even when
                        # the account doesn't exist or belongs to someone else.
                        log(f"    -> @{out['instagram']} unverified (oEmbed rate-limited) — clearing for fresh search")
                        out["instagram"] = None
            else:
                out["ig_followers"] = ig_info.get("followers")
                out["ig_bio"]       = ig_info.get("bio", "")
                out["ig_type"]      = ig_info.get("type", "unknown")
                out["ig_verified"]  = ig_info.get("verified", False)

                if not IG_ONLY:
                    if ig_info.get("email") and not out["email"]:
                        out["email"] = ig_info["email"]
                        log(f"    -> IG bio email: {ig_info['email']}")
                    if ig_info.get("facebook") and not out["facebook"]:
                        out["facebook"] = ig_info["facebook"]
                        log(f"    -> IG bio Facebook: {ig_info['facebook']}")
                    if ig_info.get("phone") and not out["phone"]:
                        out["phone"] = ig_info["phone"]
                        log(f"    -> IG bio phone: {ig_info['phone']}")

                followers_str = f"{out['ig_followers']:,}" if out["ig_followers"] else "unknown"
                log(f"    -> Type: {out['ig_type']} | Followers: {followers_str} | {ig_info.get('notes','')}")

                # ── Identity validation ───────────────────────────────────────
                # If the IG handle has no name connection AND the bio has zero
                # music keywords, this is the wrong person's account — reject it.
                _music_kw = [
                    "singer","rapper","vocalist","artist","songwriter","musician",
                    "new music","out now","stream","spotify","soundcloud","apple music",
                    "mixtape","album","ep","single","on all platforms","rnb","hip hop",
                    "hip-hop","trap","soul","r&b","drill","producer","beatmaker",
                ]
                bio_low = (ig_info.get("bio") or "").lower()
                handle_name_match = _handle_looks_related(artist_name, out["instagram"])
                bio_has_music     = any(kw in bio_low for kw in _music_kw)

                if not handle_name_match and not bio_has_music:
                    log(f"    -> IDENTITY REJECT: @{out['instagram']} has no name match and no music keywords — wrong account")
                    out["instagram"]  = None
                    out["ig_followers"] = None
                    out["ig_bio"]     = ""
                    out["ig_type"]    = "unknown"
                elif out["ig_type"] == "producer":
                    out["skip"]        = True
                    out["skip_reason"] = "Instagram bio identifies as producer"
                elif out["ig_followers"] is not None and out["ig_followers"] < 100:
                    out["skip"]        = True
                    out["skip_reason"] = f"Instagram too small: {out['ig_followers']} followers (under 100)"
                    log(f"    -> AUTO-SKIP: {out['ig_followers']} IG followers < 100")
                elif out["ig_followers"] and out["ig_followers"] >= 100_000:
                    out["skip"]        = True
                    out["skip_reason"] = f"Instagram too large: {out['ig_followers']:,} followers (100K+ = not our target)"
                    log(f"    -> AUTO-SKIP: {out['ig_followers']:,} IG followers >= 100K")
        except Exception as e:
            log(f"    -> Instagram profile error: {e}")
    else:
        log(f"    Step 5/6: Skipped Instagram (no handle found)")

    # ── Step 5b: Re-search if Step 5 cleared the handle ──────────────────────
    # Handles the case where an existing (wrong) handle survived pre-check
    # (oEmbed was uncertain) but was later confirmed invalid in Step 5.
    # We run a fresh Startpage → DDG search and fetch the new handle's profile.
    if not out["instagram"] and not out.get("skip"):
        log(f"    Step 5b: Handle was cleared — running fresh Instagram search...")
        _new_ig = _find_instagram(artist_name)
        if _new_ig:
            log(f"    -> Step 5b found: @{_new_ig} — fetching profile")
            out["instagram"] = _new_ig
            try:
                _ig2 = fetch_instagram_profile(_new_ig)
                if not _ig2["found"]:
                    _oe2 = validate_instagram_handle(_new_ig)
                    if _oe2 is False:
                        log(f"    -> Step 5b @{_new_ig} also invalid (oEmbed 404) — giving up")
                        out["instagram"] = None
                    else:
                        log(f"    -> Step 5b @{_new_ig} fetch failed (transient) — keeping handle")
                else:
                    out["ig_followers"] = _ig2.get("followers")
                    out["ig_bio"]       = _ig2.get("bio", "")
                    out["ig_type"]      = _ig2.get("type", "unknown")
                    out["ig_verified"]  = _ig2.get("verified", False)
                    _music_kw2 = [
                        "singer","rapper","vocalist","artist","songwriter","musician",
                        "new music","out now","stream","spotify","soundcloud","apple music",
                        "mixtape","album","ep","single","on all platforms","rnb","hip hop",
                        "hip-hop","trap","soul","r&b","drill","producer","beatmaker",
                    ]
                    _bio2 = (_ig2.get("bio") or "").lower()
                    if not _handle_looks_related(artist_name, _new_ig) and not any(kw in _bio2 for kw in _music_kw2):
                        log(f"    -> Step 5b IDENTITY REJECT: @{_new_ig} — no name match and no music keywords")
                        out["instagram"]    = None
                        out["ig_followers"] = None
                        out["ig_bio"]       = ""
                        out["ig_type"]      = "unknown"
                    elif _ig2.get("type") == "producer":
                        out["skip"]        = True
                        out["skip_reason"] = "Instagram bio identifies as producer (step 5b)"
                    elif _ig2.get("followers") and _ig2["followers"] >= 100_000:
                        out["skip"]        = True
                        out["skip_reason"] = f"Instagram too large: {_ig2['followers']:,} followers (step 5b)"
                    elif _ig2.get("followers") is not None and _ig2["followers"] < 100:
                        out["skip"]        = True
                        out["skip_reason"] = f"Instagram too small: {_ig2['followers']} followers (step 5b)"
                    else:
                        _f2 = f"{out['ig_followers']:,}" if out["ig_followers"] else "unknown"
                        log(f"    -> Step 5b result: type={out['ig_type']} followers={_f2}")
            except Exception as e:
                log(f"    -> Step 5b profile error: {e}")
        else:
            log(f"    -> Step 5b: no handle found in re-search")

    # ── Step 5c: Spotify monthly listener validation ──────────────────────────
    # Scrape the actual Spotify monthly listener count directly from the page.
    # Only runs for Spotify artists where listener count wasn't already set.
    if not out.get("skip") and out.get("listeners") is None and platform == "spotify" and profile_url:
        _sp5c_m = re.search(r'open\.spotify\.com/artist/([A-Za-z0-9]+)', profile_url)
        if _sp5c_m:
            _sp5c_n = _get_spotify_monthly_listeners(_sp5c_m.group(1))
            if _sp5c_n is not None:
                out["listeners"] = _sp5c_n
                log(f"    -> Spotify monthly listeners: {_sp5c_n:,}")
                if _sp5c_n > 100_000:
                    out["skip"]        = True
                    out["skip_reason"] = f"Established artist: {_sp5c_n:,} Spotify monthly listeners"
                    log(f"    -> AUTO-SKIP: {_sp5c_n:,} Spotify monthly listeners > 100k cap")

    # ── Step 6: Contact quality assessment ───────────────────────────────────
    log(f"    Step 6/6: Contact quality...")
    has_ig    = bool(out["instagram"])
    has_email = bool(out["email"])

    has_fb    = bool(out["facebook"])
    has_phone = bool(out["phone"])

    if out["skip"]:
        out["contact_quality"] = "skip"
        log(f"    -> SKIP: {out['skip_reason']}")
    elif has_ig and has_email:
        out["contact_quality"] = "excellent"
        log(f"    -> EXCELLENT: IG @{out['instagram']} + email {out['email']}")
    elif has_ig:
        out["contact_quality"] = "good"
        log(f"    -> GOOD: IG @{out['instagram']}, no email")
    elif has_email:
        out["contact_quality"] = "email_only"
        log(f"    -> OK: email {out['email']}, no IG")
    elif has_fb or has_phone:
        out["contact_quality"] = "limited"
        log(f"    -> LIMITED: FB={has_fb} phone={has_phone}, no IG or email")
    else:
        out["contact_quality"] = "contactless"
        log(f"    -> CONTACTLESS: no IG, no Facebook, no email, no phone")

    return out


# ── CLI ENTRY POINT ───────────────────────────────────────────────────────────

if __name__ == "__main__":
    import json as _json

    if "--listeners-only" in sys.argv:
        # Lightweight mode: return verified listener count only, no contact search.
        # Spotify: Spotify ID → MusicBrainz → Last.fm URL  (collision-safe, exact artist)
        # Others:  Last.fm by name with strict match
        _JSON_MODE = True
        _name, _platform, _profile_url = "", "", None
        try: _name = sys.argv[sys.argv.index("--name") + 1]
        except: pass
        try: _platform = sys.argv[sys.argv.index("--platform") + 1]
        except: pass
        try: _profile_url = sys.argv[sys.argv.index("--profile-url") + 1] or None
        except: pass

        _listeners = None

        if _platform == "spotify" and _profile_url:
            _sid_m = re.search(r'open\.spotify\.com/artist/([A-Za-z0-9]+)', _profile_url)
            if _sid_m:
                _listeners = _get_spotify_monthly_listeners(_sid_m.group(1))

        print(_json.dumps({"listeners": _listeners}), flush=True)
        sys.exit(0)

    elif "--json" in sys.argv:
        _JSON_MODE = True  # all log() calls now go to stderr

        try:
            name_idx = sys.argv.index("--name") + 1
            name = sys.argv[name_idx]
        except (ValueError, IndexError):
            print(_json.dumps({"error": "Missing --name argument"}), flush=True)
            sys.exit(1)

        platform = ""
        if "--platform" in sys.argv:
            try: platform = sys.argv[sys.argv.index("--platform") + 1]
            except IndexError: pass

        existing_ig = None
        if "--ig" in sys.argv:
            try: existing_ig = sys.argv[sys.argv.index("--ig") + 1] or None
            except IndexError: pass

        profile_url = None
        if "--profile-url" in sys.argv:
            try: profile_url = sys.argv[sys.argv.index("--profile-url") + 1] or None
            except IndexError: pass

        try:
            result = resolve(name, platform=platform, existing_ig=existing_ig, profile_url=profile_url)
        except Exception as e:
            log(f"CRITICAL ERROR in resolve(): {e}")
            import traceback
            traceback.print_exc(file=sys.stderr)
            result = {
                "instagram":       existing_ig,
                "facebook":        None,
                "phone":           None,
                "email":           None,
                "ig_followers":    None,
                "ig_bio":          "",
                "ig_type":         "unknown",
                "ig_verified":     False,
                "contact_quality": "none",
                "skip":            False,
                "skip_reason":     f"Crash: {str(e)}",
            }

        # Only clean JSON goes to stdout — backend reads exactly this line
        print(_json.dumps(result), flush=True)

    else:
        # Interactive test mode
        print("\nRenegade Engine v2 — Contact Resolution Test")
        name = input("Enter artist name to test: ").strip()
        result = resolve(name)
        print(f"\n{'='*55}")
        print(f"RESULT for {name}:")
        print(f"  Instagram  : {result['instagram']}")
        print(f"  Facebook   : {result['facebook']}")
        print(f"  Phone      : {result['phone']}")
        print(f"  Email      : {result['email']}")
        print(f"  IG Followers: {result['ig_followers']}")
        print(f"  IG Type    : {result['ig_type']}")
        print(f"  Quality    : {result['contact_quality']}")
        print("="*55)
