import requests, re, json, sys, urllib.parse
sys.stdout.reconfigure(encoding='utf-8')

channel_id = 'UCB2p5CC7dSyjztmvhJr9Q9g'
payload = {
    'context': {'client': {'clientName': 'WEB', 'clientVersion': '2.20240101.00.00', 'hl': 'en', 'gl': 'US'}},
    'browseId': channel_id, 'params': 'EgVhYm91dA=='
}
r = requests.post('https://www.youtube.com/youtubei/v1/browse',
    params={'key': 'AIzaSyAO_FJ2SlqU8Q4STEHLGCilw_Y9_11qcW8'},
    json=payload, headers={'Content-Type': 'application/json', 'Origin': 'https://www.youtube.com'}, timeout=15)
data = r.json()
data_str = json.dumps(data)

# Subscriber count - WORKS
subs = re.findall(r'"accessibilityLabel":\s*"([^"]*subscribers)"', data_str)
print("Subs:", subs[0] if subs else None)

# Channel handle (@xxx) - WORKS (confirmed earlier)
handle = re.findall(r'"channelHandleText":\{"simpleText":"([^"]+)"', data_str)
print("Handle:", handle[0] if handle else None)

# For channel name, let's look at the header object structure
header = data.get('header', {})
print("Header keys:", list(header.keys()))
phv = header.get('pageHeaderRenderer', {}).get('pageTitle', '')
print("pageTitle:", phv)

# Try pageHeaderViewModel
if 'pageHeaderRenderer' in header:
    phr = header['pageHeaderRenderer']
    print("pageHeaderRenderer keys:", list(phr.keys()))
    phvm = phr.get('content', {}).get('pageHeaderViewModel', {})
    print("pageHeaderViewModel keys:", list(phvm.keys()))
    title_obj = phvm.get('title', {})
    print("title obj:", title_obj)
