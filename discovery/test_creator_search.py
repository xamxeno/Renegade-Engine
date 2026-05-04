"""
Test script — tries different methods to find podcast/reel creator handles.
Run: python test_creator_search.py
"""
import re, time, random, urllib.parse, urllib.request, requests

# ── Test query ───────────────────────────────────────────────────────────────
TEST_QUERY = "site:instagram.com independent podcaster USA"

def test_bing(query):
    print(f"\n[BING] {query}")
    try:
        url = f"https://www.bing.com/search?q={urllib.parse.quote(query)}&count=50&setlang=en-US"
        req = urllib.request.Request(url, headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
        })
        with urllib.request.urlopen(req, timeout=15) as resp:
            html = resp.read().decode("utf-8", errors="ignore")

        # Show raw snippet so we can see what Bing returns
        ig_hits = re.findall(r'instagram\.com/([a-zA-Z0-9._]{2,30})(?:[/?"\s<&]|$)', html)
        print(f"  Raw IG handles found in HTML: {ig_hits[:10]}")

        # Check if Bing is using redirect URLs
        redirects = re.findall(r'href="(https?://[^"]*instagram[^"]*)"', html)
        print(f"  IG links in href: {redirects[:5]}")

        # Check for any instagram mentions at all
        if 'instagram' in html.lower():
            idx = html.lower().index('instagram')
            print(f"  Context around 'instagram': ...{html[max(0,idx-50):idx+100]}...")
        else:
            print("  'instagram' not found in response at all")

        print(f"  Response size: {len(html)} bytes")
        return ig_hits
    except Exception as e:
        print(f"  ERROR: {e}")
        return []


def test_google_cse(query):
    """Test Google Custom Search - needs GOOGLE_CSE_KEY and GOOGLE_CSE_ID"""
    print(f"\n[Google CSE] {query}")
    print("  Skipped — needs API key")
    return []


def test_youtube_search(keyword):
    """Scrape YouTube search results for creator channels."""
    print(f"\n[YouTube HTML] searching: {keyword}")
    try:
        url = f"https://www.youtube.com/results?search_query={urllib.parse.quote(keyword)}&sp=EgIQAg%253D%253D"  # filter: channels
        r = requests.get(url, headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124.0.0.0 Safari/537.36",
            "Accept-Language": "en-US,en;q=0.9",
        }, timeout=15)

        html = r.text
        # YouTube embeds data as JSON in window["ytInitialData"]
        # Extract channel names and subscriber counts
        channels = re.findall(r'"channelRenderer":\{"channelId":"([^"]+)".*?"simpleText":"([^"]+)"', html)
        subs = re.findall(r'"subscriberCountText":\{"simpleText":"([^"]+)"', html)
        titles = re.findall(r'"title":\{"simpleText":"([^"]+)"\},"navigationEndpoint":\{"clickTrackingParams[^}]*"browseEndpoint":\{"browseId":"UC', html)

        print(f"  Channel IDs found: {len(channels)}")
        for i, (cid, _) in enumerate(channels[:5]):
            sub = subs[i] if i < len(subs) else "?"
            print(f"    {cid} — {sub} subscribers")

        # Also check for Instagram links mentioned in channel descriptions
        ig_in_yt = re.findall(r'instagram\.com/([a-zA-Z0-9._]{2,30})', html)
        print(f"  IG handles found in YouTube page: {list(set(ig_in_yt))[:10]}")

        print(f"  Response size: {len(html)} bytes")
        return channels
    except Exception as e:
        print(f"  ERROR: {e}")
        return []


def test_bing_news(query):
    """Try Bing News search — different results than web search."""
    print(f"\n[Bing News] {query}")
    try:
        url = f"https://www.bing.com/news/search?q={urllib.parse.quote(query)}&setlang=en-US"
        req = urllib.request.Request(url, headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124.0.0.0 Safari/537.36",
            "Accept-Language": "en-US,en;q=0.9",
        })
        with urllib.request.urlopen(req, timeout=15) as resp:
            html = resp.read().decode("utf-8", errors="ignore")
        ig_hits = re.findall(r'instagram\.com/([a-zA-Z0-9._]{2,30})(?:[/?"\s<&]|$)', html)
        print(f"  IG handles: {ig_hits[:10]}")
        return ig_hits
    except Exception as e:
        print(f"  ERROR: {e}")
        return []


def test_insta_direct(handle):
    """Test fetching an Instagram profile page directly."""
    print(f"\n[Instagram direct] @{handle}")
    try:
        r = requests.get(
            f"https://www.instagram.com/{handle}/",
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124.0.0.0 Safari/537.36",
                "Accept": "text/html,application/xhtml+xml,*/*;q=0.8",
                "Accept-Language": "en-US,en;q=0.9",
            },
            timeout=15,
            allow_redirects=True,
        )
        print(f"  Status: {r.status_code} | URL: {r.url}")

        html = r.text
        desc_m = re.search(r'<meta[^>]+property=["\']og:description["\'][^>]+content=["\']([^"\']+)["\']', html)
        title_m = re.search(r'<meta[^>]+property=["\']og:title["\'][^>]+content=["\']([^"\']+)["\']', html)

        if desc_m:
            print(f"  og:description = {desc_m.group(1)}")
        else:
            print("  og:description NOT FOUND")
            if 'login' in r.url or 'accounts/login' in html[:2000]:
                print("  → Redirected to login page (blocked)")
            # Show first 500 chars of body
            body_start = html[:500]
            print(f"  HTML preview: {body_start[:200]}")
        if title_m:
            print(f"  og:title = {title_m.group(1)}")
    except Exception as e:
        print(f"  ERROR: {e}")


def test_youtube_channel_info(channel_id):
    """Test fetching a YouTube channel page."""
    print(f"\n[YouTube channel] {channel_id}")
    try:
        r = requests.get(
            f"https://www.youtube.com/@{channel_id}",
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124.0.0.0 Safari/537.36",
                "Accept-Language": "en-US,en;q=0.9",
            },
            timeout=15,
        )
        html = r.text
        # Subscriber count
        subs = re.search(r'"subscriberCountText":\{"simpleText":"([^"]+)"', html)
        # Description
        desc = re.search(r'"description":\{"simpleText":"([^"]{0,300})"', html)
        # Country
        country = re.search(r'"country":\{"simpleText":"([^"]+)"', html)
        # Links (Instagram etc)
        links = re.findall(r'"url":"(https?://(?:www\.)?instagram\.com/[^"]+)"', html)

        print(f"  Subscribers: {subs.group(1) if subs else 'not found'}")
        print(f"  Country: {country.group(1) if country else 'not found'}")
        print(f"  Description: {desc.group(1)[:150] if desc else 'not found'}")
        print(f"  IG links: {links[:3]}")
        print(f"  Status: {r.status_code}")
    except Exception as e:
        print(f"  ERROR: {e}")


# ── Run all tests ────────────────────────────────────────────────────────────
print("=" * 60)
print("CREATOR DISCOVERY — METHOD TEST")
print("=" * 60)

# Test 1: Bing site:instagram.com
test_bing("site:instagram.com independent podcaster USA")
time.sleep(2)
test_bing("site:instagram.com content creator reels USA independent")
time.sleep(2)

# Test 2: YouTube search for creators
test_youtube_search("independent podcast host USA 2025")
time.sleep(2)
test_youtube_search("reel content creator USA lifestyle entrepreneur")
time.sleep(2)

# Test 3: Direct Instagram fetch (known handle)
test_insta_direct("garyvee")
time.sleep(2)
test_insta_direct("mrbeast")
time.sleep(2)

# Test 4: YouTube channel info
test_youtube_channel_info("garyvee")
time.sleep(1)

print("\n" + "=" * 60)
print("TEST COMPLETE")
print("=" * 60)
