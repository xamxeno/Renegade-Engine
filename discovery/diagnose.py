"""
python diagnose.py
Writes full results to diagnose_output.txt so nothing gets cut off.
"""
import requests, os, re, json
from urllib.parse import quote_plus
from dotenv import load_dotenv
load_dotenv()

CLAUDE_KEY  = os.getenv("CLAUDE_API_KEY", "")
ARTIST      = "SelfMade Dully"
SPOTIFY_URL = "https://open.spotify.com/artist/5LBVZkJUHPuFHvNcMjVEqM"
SC_URL      = "https://soundcloud.com/user-845130856"
UA          = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124 Safari/537.36"
IG_RE       = re.compile(r'instagram\.com/([A-Za-z0-9._]{2,30})/?', re.I)

lines = []
def p(*args):
    msg = " ".join(str(a) for a in args)
    print(msg)
    lines.append(msg)

p("="*55)
p("ENRICHMENT DIAGNOSTIC")
p("="*55)

p(f"\n[1] API Key: {'SET len='+str(len(CLAUDE_KEY)) if CLAUDE_KEY else 'MISSING'}")

p(f"\n[2] Spotify page...")
try:
    r = requests.get(SPOTIFY_URL, headers={"User-Agent": UA}, timeout=12)
    p(f"    status={r.status_code} size={len(r.text):,}")
    p(f"    ig_links={IG_RE.findall(r.text)[:5] or 'none'}")
except Exception as e:
    p(f"    ERROR: {e}")

p(f"\n[3] SoundCloud page (full inspection)...")
try:
    r = requests.get(SC_URL, headers={"User-Agent": UA}, timeout=12)
    p(f"    status={r.status_code} size={len(r.text):,}")
    html = r.text
    p(f"    IG_RE matches: {IG_RE.findall(html)[:5] or 'none'}")

    ig_idx = html.lower().find("instagram")
    if ig_idx == -1:
        p("    'instagram' NOT found anywhere in page")
    else:
        p(f"    'instagram' found at index {ig_idx}")
        p(f"    Context: {repr(html[max(0,ig_idx-40):ig_idx+120])}")

    if "selfmadedully" in html.lower():
        idx = html.lower().find("selfmadedully")
        p(f"    'selfmadedully' found! Context: {repr(html[max(0,idx-60):idx+80])}")
    else:
        p("    'selfmadedully' NOT in page")

    hydration_match = re.search(r'window\.__sc_hydration\s*=\s*(\[.+?\]);', html, re.S)
    if hydration_match:
        p("    Found __sc_hydration JSON")
        try:
            hdata = json.loads(hydration_match.group(1))
            hstr = json.dumps(hdata)
            p(f"    IG in hydration: {IG_RE.findall(hstr)[:5] or 'none'}")
            if "selfmadedully" in hstr.lower():
                p("    'selfmadedully' IN hydration!")
            for item in hdata:
                if isinstance(item, dict) and item.get("hydratable") == "user":
                    user = item.get("data", {})
                    p(f"    SC user: {user.get('username')} / {user.get('permalink')}")
                    p(f"    Description: {str(user.get('description',''))[:300]}")
                    p(f"    Links: {user.get('links', [])}")
        except Exception as e:
            p(f"    Hydration parse error: {e}")
    else:
        p("    No __sc_hydration — looking for any social JSON...")
        json_ig = re.findall(r'"(?:instagram|social)[^"]*"\s*:\s*"([^"]+)"', html, re.I)
        p(f"    JSON instagram fields: {json_ig[:5] or 'none'}")
        # Also check for any link that has instagram in it
        all_ig_urls = re.findall(r'https?://(?:www\.)?instagram\.com/[^\s"\'<>]+', html, re.I)
        p(f"    Full IG URLs in page: {all_ig_urls[:5] or 'none'}")
except Exception as e:
    p(f"    ERROR: {e}")

p(f"\n[4] Claude — plain (no tools)...")
if not CLAUDE_KEY:
    p("    SKIPPED")
else:
    try:
        r = requests.post("https://api.anthropic.com/v1/messages",
            headers={"x-api-key": CLAUDE_KEY, "anthropic-version": "2023-06-01",
                     "content-type": "application/json"},
            json={"model": "claude-haiku-4-5-20251001", "max_tokens": 30,
                  "messages": [{"role": "user", "content":
                    f'Instagram handle for music artist "{ARTIST}" on Spotify? '
                    f'ONLY the handle, no @. If unknown: UNKNOWN'}]},
            timeout=20)
        p(f"    status={r.status_code}")
        if r.status_code == 200:
            p(f"    answer: '{r.json().get('content',[{}])[0].get('text','').strip()}'")
        else:
            p(f"    error: {r.text[:200]}")
    except Exception as e:
        p(f"    ERROR: {e}")

p(f"\n[5] Claude — web_search tool...")
if not CLAUDE_KEY:
    p("    SKIPPED")
else:
    try:
        r = requests.post("https://api.anthropic.com/v1/messages",
            headers={"x-api-key": CLAUDE_KEY, "anthropic-version": "2023-06-01",
                     "anthropic-beta": "web-search-2025-03-05",
                     "content-type": "application/json"},
            json={"model": "claude-haiku-4-5-20251001", "max_tokens": 200,
                  "tools": [{"type": "web_search_20250305", "name": "web_search"}],
                  "messages": [{"role": "user", "content":
                    f'Search the web. Find the Instagram handle for music artist "{ARTIST}" '
                    f'Spotify: {SPOTIFY_URL}. Check SoundCloud and music sites. '
                    f'Reply with ONLY the raw handle, no @. If not found: UNKNOWN'}]},
            timeout=60)
        p(f"    status={r.status_code}")
        if r.status_code == 200:
            data = r.json()
            p(f"    stop_reason={data.get('stop_reason')}")
            p(f"    blocks={[b.get('type') for b in data.get('content', [])]}")
            for i, block in enumerate(data.get("content", [])):
                bt = block.get("type")
                if bt == "text":
                    p(f"    [{i}] TEXT: '{block['text'].strip()[:200]}'")
                elif bt == "tool_use":
                    p(f"    [{i}] TOOL_USE: {block.get('name')} input={str(block.get('input',''))[:100]}")
                elif bt == "web_search_tool_result":
                    res = block.get("content", [])
                    p(f"    [{i}] WEB_RESULT: {len(res)} results")
                    for x in res[:3]:
                        p(f"         {x.get('title','')[:50]} | {x.get('url','')[:60]}")
                else:
                    p(f"    [{i}] {bt}: {str(block)[:100]}")
        else:
            p(f"    error {r.status_code}: {r.text[:300]}")
    except Exception as e:
        p(f"    ERROR: {e}")

p("\n" + "="*55)
with open("diagnose_output.txt", "w", encoding="utf-8") as f:
    f.write("\n".join(lines))
print("\nSaved to diagnose_output.txt — paste that file here")
