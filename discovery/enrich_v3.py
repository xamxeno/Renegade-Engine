"""
enrich_v3.py — Simple Instagram finder. No Claude API.
Pipeline: Spotify scrape → direct social links → DDG search → IG verify
"""

import sys, re, json, time, random, argparse
import urllib.request, urllib.parse, urllib.error

HEADERS = {
    "User-Agent": "curl/8.5.0",
    "Accept": "*/*",
}

def fetch(url, timeout=15):
    try:
        req = urllib.request.Request(url, headers=HEADERS)
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.read().decode("utf-8", errors="ignore")
    except Exception as e:
        return ""

def find_instagram_in_text(text):
    """Pull @handle or instagram.com/handle from any block of text."""
    patterns = [
        r'instagram\.com/([A-Za-z0-9_.]{2,40})(?:[/?"\s]|$)',
        r'"instagram":\s*"([A-Za-z0-9_.]{2,40})"',
        r'@([A-Za-z0-9_.]{2,40})',
    ]
    for p in patterns:
        m = re.search(p, text, re.IGNORECASE)
        if m:
            handle = m.group(1).rstrip("/").strip()
            if handle.lower() not in ("reels", "p", "stories", "explore", "accounts", "music", "artist"):
                return handle
    return None

def scrape_spotify(profile_url):
    """Scrape Spotify artist page for social links and name confirmation."""
    html = fetch(profile_url)
    if not html:
        return {}
    ig = find_instagram_in_text(html)
    # Also look for externalUrl fields in the embedded JSON
    m = re.search(r'"externalUrl":\{"spotify":"(https://[^"]+)"', html)
    external = m.group(1) if m else None
    return {"instagram": ig, "external_url": external, "html_len": len(html)}

def verify_ig(handle, artist_name):
    """Check if instagram.com/{handle} looks like this artist's page."""
    url = f"https://www.instagram.com/{handle}/"
    html = fetch(url, timeout=12)
    if not html or len(html) < 500:
        return False
    name_lower = artist_name.lower()
    # Check for artist name or handle appearing in the page
    if name_lower in html.lower():
        return True
    # Check og:title / og:description
    m = re.search(r'og:title[^>]+content="([^"]+)"', html, re.IGNORECASE)
    if m and name_lower in m.group(1).lower():
        return True
    return False

def ddg_search(query):
    """DuckDuckGo HTML search, return raw result page."""
    q = urllib.parse.quote_plus(query)
    url = f"https://html.duckduckgo.com/html/?q={q}"
    headers = {**HEADERS, "Accept": "text/html"}
    try:
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=15) as r:
            return r.read().decode("utf-8", errors="ignore")
    except:
        return ""

def find_ig_via_ddg(artist_name, platform_url=""):
    """Search DDG for artist's Instagram, verify each candidate."""
    queries = [
        f'"{artist_name}" site:instagram.com',
        f'"{artist_name}" instagram music artist',
    ]
    candidates = set()
    for q in queries:
        html = ddg_search(q)
        if not html:
            time.sleep(1)
            continue
        # Extract all instagram.com/handle links from results
        for handle in re.findall(r'instagram\.com/([A-Za-z0-9_.]{2,40})(?:[/?"\s<]|$)', html, re.IGNORECASE):
            if handle.lower() not in ("reels", "p", "stories", "explore", "accounts", "music", "artist", "instagram"):
                candidates.add(handle)
        time.sleep(random.uniform(1.5, 2.5))

    for handle in candidates:
        if verify_ig(handle, artist_name):
            return handle
        time.sleep(0.5)

    return None

def enrich(name, platform, profile_url, **kwargs):
    result = {"name": name, "platform": platform, "instagram": None, "method": None}

    # Step 1: scrape Spotify page for direct IG link
    if profile_url and "spotify" in profile_url:
        log(f"Scraping Spotify page...")
        data = scrape_spotify(profile_url)
        log(f"  Page size: {data.get('html_len', 0)} chars")
        if data.get("instagram"):
            handle = data["instagram"]
            log(f"  Found IG link on Spotify page: @{handle}")
            if verify_ig(handle, name):
                result["instagram"] = handle
                result["method"] = "spotify_direct"
                return result
            else:
                log(f"  Could not verify @{handle} — trying DDG")
        # Follow external URL if present
        ext = data.get("external_url")
        if ext and not result["instagram"]:
            log(f"  Following external URL: {ext}")
            ext_html = fetch(ext)
            handle = find_instagram_in_text(ext_html)
            if handle:
                log(f"  Found IG in external site: @{handle}")
                if verify_ig(handle, name):
                    result["instagram"] = handle
                    result["method"] = "external_site"
                    return result

    # Step 2: DDG search
    log(f"Searching DDG for @{name} instagram...")
    handle = find_ig_via_ddg(name, profile_url)
    if handle:
        result["instagram"] = handle
        result["method"] = "ddg_search"
        return result

    log(f"Not found after all steps.")
    return result

def log(msg):
    print(msg, file=sys.stderr)

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--name", required=True)
    parser.add_argument("--platform", default="spotify")
    parser.add_argument("--profile-url", default="")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    result = enrich(args.name, args.platform, args.profile_url)

    if args.json:
        print(json.dumps(result))
    else:
        ig = result.get("instagram")
        method = result.get("method", "")
        if ig:
            print(f"Found: @{ig} (via {method})")
        else:
            print("Not found")
