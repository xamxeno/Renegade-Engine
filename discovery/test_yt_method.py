"""
Test YouTube-based creator discovery pipeline.
Finds channels, extracts IG handles from their About page redirect URLs.
"""
import requests, re, json, sys, urllib.parse, time
sys.stdout.reconfigure(encoding='utf-8')

YT_BROWSE_KEY = 'AIzaSyAO_FJ2SlqU8Q4STEHLGCilw_Y9_11qcW8'
HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124.0.0.0 Safari/537.36',
    'Accept-Language': 'en-US,en;q=0.9'
}

def yt_search_channels(keyword, max_results=20):
    url = f'https://www.youtube.com/results?search_query={urllib.parse.quote(keyword)}&sp=EgIQAg%253D%253D'
    r = requests.get(url, headers=HEADERS, timeout=15)
    channels = re.findall(r'"channelId":"([^"]+)"', r.text)
    seen = []
    for c in channels:
        if c not in seen:
            seen.append(c)
    return seen[:max_results]

def get_channel_about(channel_id):
    payload = {
        'context': {'client': {'clientName': 'WEB', 'clientVersion': '2.20240101.00.00', 'hl': 'en', 'gl': 'US'}},
        'browseId': channel_id,
        'params': 'EgVhYm91dA=='  # base64('about')
    }
    r = requests.post(
        'https://www.youtube.com/youtubei/v1/browse',
        params={'key': YT_BROWSE_KEY},
        json=payload,
        headers={**HEADERS, 'Content-Type': 'application/json', 'Origin': 'https://www.youtube.com'},
        timeout=15
    )
    data_str = json.dumps(r.json())

    # Extract social links from YouTube redirect URLs
    # Format: youtube.com/redirect?...&q=https%3A//instagram.com/handle
    ig_handles = []
    other_links = []
    redirect_blocks = re.findall(r'youtube\.com/redirect[^"]{0,500}', data_str)
    for block in redirect_blocks:
        # Find q= parameter
        q_idx = block.find('q=')
        if q_idx == -1:
            continue
        q_val = block[q_idx+2:]
        # End at & or " or \
        end = len(q_val)
        for ch in ['&', '"', '\\']:
            pos = q_val.find(ch)
            if pos != -1 and pos < end:
                end = pos
        q_val = q_val[:end]
        decoded = urllib.parse.unquote(q_val)
        if 'instagram.com' in decoded:
            ig = re.search(r'instagram\.com/([a-zA-Z0-9._]{2,30})', decoded)
            if ig:
                ig_handles.append(ig.group(1))
        elif any(s in decoded for s in ['twitter.com', 'x.com', 'tiktok.com', 'facebook.com', 'linktree', 'linktr.ee']):
            other_links.append(decoded[:80])

    # Subscriber count
    subs = None
    subs_match = re.search(r'subscriberCountText[^}]{0,200}simpleText":"([^"]+)"', data_str)
    if subs_match:
        subs = subs_match.group(1)

    # Channel name from header
    name_match = re.search(r'"pageHeaderRenderer".*?"text":"([^"]{2,60})"', data_str, re.DOTALL)
    name = name_match.group(1) if name_match else channel_id

    # Description
    desc_match = re.search(r'"description":\{"simpleText":"([^"]{5,500})"', data_str)
    desc = desc_match.group(1) if desc_match else ''

    # Channel handle (@username)
    handle_match = re.search(r'"channelHandleText":\{"simpleText":"([^"]+)"', data_str)
    yt_handle = handle_match.group(1) if handle_match else None

    return {
        'id': channel_id,
        'name': name,
        'yt_handle': yt_handle,
        'subs': subs,
        'desc': desc[:200],
        'ig': list(set(ig_handles)),
        'other_links': list(set(other_links))
    }


# ── Test ──────────────────────────────────────────────────────────────────────
KEYWORDS = [
    'independent podcast host USA 2025',
    'reel content creator lifestyle USA',
    'solo entrepreneur podcast USA',
    'personal brand content creator USA',
    'podcast entrepreneur small business USA',
]

print("=" * 60)
print("YouTube Creator Discovery — Method Test")
print("=" * 60)

all_ig = []
for kw in KEYWORDS:
    print(f"\n[Search] {kw}")
    channels = yt_search_channels(kw)
    print(f"  Found {len(channels)} channels")
    for cid in channels[:10]:
        time.sleep(0.4)
        info = get_channel_about(cid)
        ig_str = f"@{info['ig'][0]}" if info['ig'] else 'no IG'
        print(f"  {info['name'][:35]:35} | {info['subs'] or '?':15} | {ig_str}")
        if info['ig']:
            all_ig.extend(info['ig'])
        if info['other_links']:
            print(f"    Other: {info['other_links'][:2]}")
    time.sleep(1)

print(f"\n{'='*60}")
print(f"Total unique IG handles found: {len(set(all_ig))}")
print(f"Handles: {list(set(all_ig))}")
