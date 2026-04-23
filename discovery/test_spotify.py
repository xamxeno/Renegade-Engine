"""
Quick Spotify API test — shows exactly what's working and what's not
"""
import os, requests
from base64 import b64encode
from dotenv import load_dotenv
load_dotenv()

CLIENT_ID     = os.getenv("SPOTIFY_CLIENT_ID", "")
CLIENT_SECRET = os.getenv("SPOTIFY_CLIENT_SECRET", "")

print("\n" + "="*55)
print("  Spotify API Diagnostic")
print("="*55)
print(f"  Client ID     : {CLIENT_ID[:8]}..." if CLIENT_ID else "  Client ID     : MISSING")
print(f"  Client Secret : {CLIENT_SECRET[:8]}..." if CLIENT_SECRET else "  Client Secret : MISSING")

# Step 1 - Get token
print("\n  [1] Getting access token...")
try:
    creds = b64encode(f"{CLIENT_ID}:{CLIENT_SECRET}".encode()).decode()
    r = requests.post("https://accounts.spotify.com/api/token",
        headers={"Authorization": f"Basic {creds}"},
        data={"grant_type": "client_credentials"}, timeout=10)
    token = r.json().get("access_token")
    if token:
        print(f"  [OK] Token received: {token[:20]}...")
    else:
        print(f"  [FAIL] {r.json()}")
        exit()
except Exception as e:
    print(f"  [ERROR] {e}")
    exit()

H = {"Authorization": f"Bearer {token}"}

# Step 2 - Test genre search
print("\n  [2] Testing genre search (r-n-b)...")
r = requests.get("https://api.spotify.com/v1/search",
    headers=H, params={"q": "genre:r-n-b", "type": "artist", "limit": 5})
items = r.json().get("artists", {}).get("items", [])
print(f"  Results: {len(items)} artists")
for a in items:
    print(f"    - {a['name']} | {a['followers']['total']:,} followers | {a.get('genres',[][:2])}")

# Step 3 - Test keyword search (more reliable)
print("\n  [3] Testing keyword search (rnb soul usa)...")
r = requests.get("https://api.spotify.com/v1/search",
    headers=H, params={"q": "rnb soul", "type": "artist", "limit": 10})
items = r.json().get("artists", {}).get("items", [])
print(f"  Results: {len(items)} artists")
for a in items:
    print(f"    - {a['name']} | {a['followers']['total']:,} followers | {a.get('genres',[])[:2]}")

# Step 4 - Test category playlists (gets fresh artists)
print("\n  [4] Testing browse categories...")
r = requests.get("https://api.spotify.com/v1/browse/categories",
    headers=H, params={"locale": "en_US", "limit": 10})
cats = r.json().get("categories", {}).get("items", [])
print(f"  Categories found: {len(cats)}")
for c in cats[:5]:
    print(f"    - {c['name']} ({c['id']})")

# Step 5 - Test playlist-based artist discovery
print("\n  [5] Testing featured playlists for artist discovery...")
r = requests.get("https://api.spotify.com/v1/browse/featured-playlists",
    headers=H, params={"locale": "en_US", "limit": 5})
playlists = r.json().get("playlists", {}).get("items", [])
print(f"  Featured playlists: {len(playlists)}")
for p in playlists[:3]:
    print(f"    - {p['name']} ({p['id']})")

# Step 6 - Get tracks from a playlist and extract artists
if playlists:
    pid = playlists[0]["id"]
    pname = playlists[0]["name"]
    print(f"\n  [6] Extracting artists from '{pname}'...")
    r = requests.get(f"https://api.spotify.com/v1/playlists/{pid}/tracks",
        headers=H, params={"limit": 20, "fields": "items(track(artists(name,id)))"})
    tracks = r.json().get("items", [])
    artists_seen = set()
    for t in tracks:
        for a in t.get("track", {}).get("artists", []):
            if a["id"] not in artists_seen:
                artists_seen.add(a["id"])
                print(f"    - {a['name']} ({a['id']})")

print("\n" + "="*55)
print("  Diagnostic complete")
print("="*55 + "\n")
