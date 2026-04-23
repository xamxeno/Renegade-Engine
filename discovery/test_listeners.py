import requests, re, json, os, sys
from base64 import b64encode

# Load .env manually from backend folder
def load_env():
    env_path = os.path.join(os.path.dirname(__file__), '..', 'backend', '.env')
    if os.path.exists(env_path):
        with open(env_path) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#') and '=' in line:
                    k, _, v = line.partition('=')
                    os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))
load_env()

ARTIST_ID = "0eulFYzjHkalG4jALSAQAo"  # MkX
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}

print("=" * 60)
print("TEST A: Spotify direct page scrape")
print("=" * 60)
r = requests.get(f"https://open.spotify.com/artist/{ARTIST_ID}", headers=HEADERS, timeout=15)
print(f"Status: {r.status_code}, Size: {len(r.text):,} bytes")
print(f"First 300 chars: {r.text[:300]!r}")

print()
print("=" * 60)
print("TEST A2: Anonymous Spotify web-player token → spclient API")
print("=" * 60)
try:
    tok_r = requests.get(
        "https://open.spotify.com/get_access_token?reason=transport&productType=web_player",
        headers={**HEADERS, "Referer": "https://open.spotify.com/"},
        timeout=10
    )
    print(f"Token status: {tok_r.status_code}")
    tok_data = tok_r.json()
    anon_token = tok_data.get("accessToken")
    print(f"Anonymous token obtained: {'YES' if anon_token else 'NO'}")
    if anon_token:
        # Try the artist overview GraphQL endpoint
        import urllib.parse
        vars_str = json.dumps({"uri": f"spotify:artist:{ARTIST_ID}", "locale": ""})
        ext_str = json.dumps({"persistedQuery": {"version": 1, "sha256Hash": "591ed473fa2f02b3f42b17f4e8faf8e4e31b7d5d1d0da6f3e9e6e3c3a3b3c3d"}})
        # Try simple artist data endpoint
        art_r = requests.get(
            f"https://api.spotify.com/v1/artists/{ARTIST_ID}",
            headers={"Authorization": f"Bearer {anon_token}"},
            timeout=10
        )
        art_data = art_r.json()
        print(f"Artist API status: {art_r.status_code}")
        print(f"name: {art_data.get('name')}")
        print(f"popularity: {art_data.get('popularity')}")
        print(f"followers: {art_data.get('followers', {}).get('total')}")
except Exception as e:
    print(f"Error: {e}")

print()
print("=" * 60)
print("TEST A3: Spotify Web API with client credentials")
print("=" * 60)
client_id = os.getenv("SPOTIFY_CLIENT_ID", "")
client_secret = os.getenv("SPOTIFY_CLIENT_SECRET", "")
print(f"client_id found: {'YES (' + client_id[:8] + '...)' if client_id else 'NO'}")
if client_id and client_secret:
    creds = b64encode(f"{client_id}:{client_secret}".encode()).decode()
    t = requests.post("https://accounts.spotify.com/api/token",
        data={"grant_type": "client_credentials"},
        headers={"Authorization": f"Basic {creds}"},
        timeout=8
    ).json()
    token = t.get("access_token")
    if token:
        artist = requests.get(
            f"https://api.spotify.com/v1/artists/{ARTIST_ID}",
            headers={"Authorization": f"Bearer {token}"},
            timeout=8
        ).json()
        print(f"name: {artist.get('name')}, popularity: {artist.get('popularity')}, followers: {artist.get('followers', {}).get('total')}")
    else:
        print(f"Token error: {t}")

print()
print("=" * 60)
print("TEST B: Instagram oEmbed — raw response inspection")
print("=" * 60)
for handle in ["303music", "theofficial303", "mkxmusic"]:
    rb = requests.get(
        f"https://www.instagram.com/oembed/?url=https://www.instagram.com/{handle}/",
        headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"},
        timeout=10
    )
    content_type = rb.headers.get("content-type", "")
    try:
        d = rb.json()
        author = d.get("author_name")
        print(f"@{handle}: {rb.status_code} JSON  author_name={repr(author)}")
    except Exception:
        print(f"@{handle}: {rb.status_code} HTML  content-type={content_type[:60]}  first100={rb.text[:100]!r}")
