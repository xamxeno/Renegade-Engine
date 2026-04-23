"""
Renegade Records — Force sync leads to Supabase
Run this to push your existing leads JSON into Supabase
"""
import json, glob, os, requests
from dotenv import load_dotenv

load_dotenv()

SUPABASE_URL = os.getenv("SUPABASE_URL", "")
SUPABASE_KEY = os.getenv("SUPABASE_KEY", "")

def run():
    if not SUPABASE_URL or not SUPABASE_KEY:
        print("ERROR: SUPABASE_URL or SUPABASE_KEY missing in .env")
        return

    # Load latest leads file
    files = sorted(glob.glob("leads_*.json"), reverse=True)
    if not files:
        print("No leads file found. Run discovery.py first.")
        return

    print(f"Loading: {files[0]}")
    with open(files[0], "r", encoding="utf-8") as f:
        artists = json.load(f)

    print(f"Syncing {len(artists)} artists to Supabase...")

    # Try both key formats
    headers_options = [
        {
            "apikey":        SUPABASE_KEY,
            "Authorization": f"Bearer {SUPABASE_KEY}",
            "Content-Type":  "application/json",
            "Prefer":        "resolution=merge-duplicates"
        },
        {
            "Authorization": f"Bearer {SUPABASE_KEY}",
            "Content-Type":  "application/json",
            "Prefer":        "resolution=merge-duplicates",
            "apikey":        SUPABASE_KEY,
        }
    ]

    # Test connection first
    test = requests.get(
        f"{SUPABASE_URL}/rest/v1/artists?limit=1",
        headers=headers_options[0]
    )
    print(f"Connection test: {test.status_code}")
    if test.status_code == 401:
        print("Auth failed — check your SUPABASE_KEY in .env")
        print(f"Response: {test.text[:200]}")
        return
    if test.status_code == 404 or "relation" in test.text.lower():
        print("Table not found — did you run supabase_schema.sql?")
        return

    ok, failed = 0, 0
    for i, a in enumerate(artists):
        payload = {
            "name":         a["name"],
            "platform":     a["platform"],
            "platform_id":  a.get("platform_id", a["name"]),
            "followers":    a.get("followers", 0),
            "genres":       json.dumps(a.get("genres", [])),
            "profile_url":  a.get("profile_url", ""),
            "image_url":    a.get("image_url", ""),
            "instagram":    a.get("instagram"),
            "email":        a.get("email"),
            "score":        a.get("score", 50),
            "score_reason": a.get("score_reason", ""),
            "status":       "new"
        }
        res = requests.post(
            f"{SUPABASE_URL}/rest/v1/artists",
            headers=headers_options[0],
            json=payload
        )
        if res.status_code in [200, 201]:
            ok += 1
        else:
            failed += 1
            if failed <= 3:
                print(f"  Failed [{a['name']}]: {res.status_code} — {res.text[:100]}")

        if (i + 1) % 50 == 0:
            print(f"  Progress: {i+1}/{len(artists)} — {ok} synced")

    print(f"\nDone! Synced {ok}/{len(artists)} artists to Supabase")
    if failed > 0:
        print(f"Failed: {failed} — check errors above")

if __name__ == "__main__":
    run()
