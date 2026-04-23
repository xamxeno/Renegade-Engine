# Renegade Records Engine — Claude Code Session Prompt

You are working on the **Renegade Records Artist Discovery Engine**, a full-stack tool for a music label to find independent artists who are the right size to pitch production services to.

---

## What This Is

A 3-tier pipeline:
1. **Python discovery** (`discovery/discovery.py`) — scrapes Spotify playlists + keyword search to find emerging artists, scores them with Claude AI, saves to JSON + Supabase
2. **Python enrichment** (`discovery/resolve.py`) — finds each artist's Instagram, email, Facebook, phone by searching MusicBrainz + DuckDuckGo + Startpage + scraping their website
3. **Node.js backend** (`backend/server.js`) — Express API that serves leads, triggers enrichment, manages status; auto-enrich worker runs resolve.py in background
4. **React dashboard** (`dashboard/src/`) — Vite + React UI to browse leads, manage contacts, generate pitch messages

**Database**: Supabase (Postgres). Single table: `artists`.

**Owner**: Renegade Records, a music production company that pitches mixing/vocal production services to independent artists with 1K–100K monthly listeners.

---

## File Structure

```
/
├── backend/
│   ├── server.js           # Express API + auto-enrich worker
│   ├── .env                # SUPABASE_URL, SUPABASE_KEY (no Spotify keys here)
│   └── package.json
├── dashboard/
│   ├── src/
│   │   ├── pages/Dashboard.jsx      # Main leads list, filters, batch actions
│   │   └── pages/ArtistDetail.jsx   # Single lead detail panel
│   ├── .env                         # VITE_API_URL=http://localhost:4000
│   └── package.json
├── discovery/
│   ├── discovery.py        # Spotify playlist + keyword discovery, Claude scoring
│   ├── resolve.py          # Contact enrichment (Instagram, email, etc.)
│   ├── sync_supabase.py    # Push local leads JSON → Supabase
│   ├── requirements.txt    # requests, python-dotenv
│   └── .env                # SPOTIFY_CLIENT_ID, SPOTIFY_CLIENT_SECRET, CLAUDE_API_KEY, SUPABASE_URL, SUPABASE_KEY
├── supabase_schema.sql     # Full table + index definitions
├── run.bat                 # Starts backend + dashboard
└── setup.bat               # npm install for backend + dashboard
```

---

## Database Schema (Supabase `artists` table)

```sql
id uuid PRIMARY KEY
name text NOT NULL
platform text                  -- 'spotify', 'lastfm', 'deezer'
platform_id text               -- Spotify artist ID
followers integer              -- platform follower count (Spotify API)
listeners integer              -- Spotify monthly listeners (scraped from page)
genres text                    -- JSON array string e.g. '["hip-hop","r-n-b"]'
profile_url text               -- https://open.spotify.com/artist/...
image_url text
instagram text                 -- handle only, no @
facebook text
phone text
email text
ig_followers integer
contact_quality text           -- 'none' | 'searching' | 'contactless' | 'good' | 'excellent'
score integer                  -- Claude AI score 0-100
score_reason text
needs text                     -- production need signals from bio
pitch_draft text
notes text
status text                    -- 'new' | 'contacted' | 'pitched' | 'signed' | 'ignored'
session_id text                -- groups artists from one discovery run
contacted_at timestamptz
discovered_at timestamptz
updated_at timestamptz
UNIQUE(platform, platform_id)
```

### `contact_quality` lifecycle
- `'none'` → auto-enrich worker will pick this up and run resolve.py
- `'searching'` → currently being enriched (set at start of resolve run)
- `'contactless'` → enrichment ran but found nothing (or failed) — worker does NOT re-pick
- `'good'` → found Instagram or email
- `'excellent'` → found Instagram + email or multiple channels

---

## Backend API Endpoints (`backend/server.js`)

**Port**: 4000. Uses `@supabase/supabase-js`, Express, child_process `spawn`.

### Artists CRUD
- `GET /api/artists` — list with filters: `status`, `min_score`, `max_listeners`, `platform`, `search`, `sort_by`, `sort_dir`, `session_id`, `exclude_session_id`
- `GET /api/artists/:id` — single artist
- `PATCH /api/artists/:id` — update fields (status, notes, pitch_draft, etc.)
- `DELETE /api/artists/:id` — delete one lead
- `POST /api/artists/add` — add artist by Spotify URL (scrapes name via Twitterbot UA, auto-enrich picks up)

### Enrichment
- `POST /api/enrich/:id` — enrich one artist immediately (runs resolve.py --json synchronously, waits up to 90s)
- `POST /api/enrich/batch-selected` — reset `contact_quality='none'` for selected IDs, worker picks up
- `POST /api/enrich/retry-contactless` — reset all contactless → none, worker re-processes
- `GET /api/enrich/status` — `{ busy, paused, processed, found, skipped, current, remaining }`
- `POST /api/enrich/pause` — pause background worker (finishes current artist, stops)
- `POST /api/enrich/resume` — resume paused worker

### Listener Refresh
- `GET /api/artists/listener-refresh-status` — `{ busy, processed, total, updated, current }`
- `POST /api/artists/refresh-listeners` — refresh ALL artists' listener counts (runs resolve.py --listeners-only per artist, 2s delay between)
- `POST /api/artists/:id/refresh-listeners` — refresh listener count for ONE artist (used by lead panel ↻ button)

### Batch Actions
- `POST /api/artists/rescan-all` — wipe instagram/ig_followers/email/phone/facebook/contact_quality for all 'new' leads, triggers re-enrichment
- `POST /api/artists/flush-preview` — returns count of leads that would be auto-deleted (ig_followers or listeners > 100K)
- `POST /api/artists/auto-flush` — delete leads exceeding 100K followers/listeners cap

### AI + Email
- `POST /api/pitch` — generate pitch message via Claude API (`{ artist_id, pitch_type: 'attention'|'sales' }`)
- `POST /api/send-email` — send pitch email via nodemailer

---

## Auto-Enrich Worker (`server.js`)

Runs in background continuously. Key variables:
```javascript
let _enrichBusy   = false
let _enrichPaused = false
let _enrichStats  = { processed, found, skipped, current, remaining }
```

Flow:
1. `pickNextUnenriched()` — selects one artist where `contact_quality = 'none'`, ordered by listeners ASC (smallest first, easiest to pitch)
2. Sets `contact_quality = 'searching'`
3. Spawns `python resolve.py --json --name "..." --platform "..." --profile-url "..." [--ig "..."]`
4. 120s kill timer
5. On result: if `result.skip` or `result.ig_followers > 100000` → **delete** artist. Else → update all contact fields
6. 2s pause between artists, then loops

**Important**: `contact_quality = 'contactless'` means "tried and failed" — worker skips these. Only `'none'` gets picked up.

---

## resolve.py — Contact Enrichment Pipeline

**CLI modes:**
```bash
# Full enrichment (used by auto-enrich worker)
python resolve.py --json --name "ArtistName" --platform spotify --profile-url "https://open.spotify.com/artist/ID" [--ig "existing_handle"]

# Listener count only (used by Refresh Listeners)
python resolve.py --listeners-only --name "ArtistName" --platform spotify --profile-url "https://open.spotify.com/artist/ID"
```

**Output** (stdout JSON):
```json
{
  "instagram": "handle",
  "ig_followers": 12500,
  "email": null,
  "facebook": null,
  "phone": null,
  "listeners": 14500,
  "contact_quality": "good",
  "skip": false,
  "skip_reason": null
}
```

**Key functions:**

### `_get_spotify_monthly_listeners(artist_id)`
Uses `User-Agent: Twitterbot/1.0` to fetch `https://open.spotify.com/artist/{id}`.
Spotify serves an SEO/OG page to social crawlers containing `og:description: "Artist · 15K monthly listeners."`.
Parses K/M/B suffixes: "15K" → 15000, "1.2M" → 1200000.
3 retries with backoff. Returns int or None.

> **WHY Twitterbot**: Chrome/Firefox UA gets a 6KB JavaScript shell (bot detection). Twitterbot gets a 9.5KB static OG page with the listener count in the meta description. This was confirmed by testing.

### `_find_instagram(artist_name)`
Search strategy (in order):
1. `"{name}" official instagram` — finds handles like @theofficial303
2. `{name} official music instagram`
3. `"{name}" music instagram`
4. `{name} music rapper singer instagram`
5. `"{name}" music site:instagram.com`
6. `{name} music site:instagram.com`

Uses DDG then Startpage for each query.

Within each query result, scans up to 5 candidates and **prefers handles containing "official"** — catches @theofficial303 over @the303 even if @the303 appears first.

`_reject_handle()`: for ambiguous names (short/numeric like "303"), rejects handles that are exactly the bare name (e.g. @303).

`_handle_looks_related()`: handle must share 4+ consecutive chars with artist name.

**No guessing** — if search engines can't find it, leave it blank. A blank Instagram is better than a wrong one.

### `validate_instagram_handle(handle)`
Fetches `https://www.instagram.com/{handle}/` with Googlebot UA.
- "sorry, this page isn't available" in body → `False` (deleted/unavailable)
- og:title or `<title>` contains the handle → `True` (valid)
- 200 but unconfirmable → `None` (uncertain, keep)

> **WHY not oEmbed**: Instagram oEmbed has been broken since ~2024 — returns HTML for all handles (valid and invalid), not JSON. Direct profile page check is the replacement.

### `_name_needs_disambiguation(name)`
Returns True for: purely numeric names, ≤4 chars, >50% digits, contains `!$#%^&*`.
Used to trigger `_reject_handle()` for bare-name handles.

### Identity validation (inside `resolve()`)
After finding Instagram and fetching profile data:
- Rejects if no name match AND no music keywords in bio
- Auto-skips if ig_followers < 100 (too small) or >= 100K (too big)
- Auto-skips if bio identifies as "producer"

---

## discovery.py — Artist Discovery

Finds artists via:
1. Spotify playlist search (genre playlists: hip-hop, r&b, pop, etc.)
2. Spotify keyword search
3. Last.fm + Deezer as fallback

Filters out:
- Artists outside USA/Canada/UK/Australia/UAE (BLOCKED_REGIONS list)
- Artists with listeners outside 1K–100K range
- Junk accounts (beat stores, labels, orchestras, music schools, etc.)
- Artists already in the database

Scores each artist with Claude AI (0-100) and saves to:
- `discovery/leads_YYYYMMDD_HHMM.json`
- Supabase (upsert with `unique(platform, platform_id)`)

`spotify_monthly_listeners(artist_id)`:
Same Twitterbot approach as resolve.py. Uses `SP_PAGE_HEADERS = {"User-Agent": "Twitterbot/1.0"}`. Parses K/M/B suffixes. 3 retries.

---

## Dashboard Components

### `Dashboard.jsx`
- Tabs: All / New / Contacted / Pitched / Session (latest discovery run)
- Filters: platform, min score, search by name
- Sort: listeners, score, ig_followers, name
- Buttons:
  - **Refresh Listeners** — updates all leads' listener counts
  - **Rescan All Leads** — wipes contact data for all 'new' leads, triggers re-enrichment (2-click confirm)
  - **Flush Junk** — removes leads exceeding 100K cap
- Auto-enrichment status bar: shows current artist being searched, remaining count, **⏸ Pause / ▶ Resume** button
- Listener refresh status bar: shows progress
- `autoFlushJunk`: runs every 3 minutes, auto-deletes leads with ig_followers or listeners > 100K

### `ArtistDetail.jsx`
- Stats grid: AI Score, Status, Listeners (with **↻ refresh button**), Contact Quality
- Contact channels: Instagram DM, Facebook, Phone, Email — with action buttons
- **Find Contacts** button — triggers per-artist enrichment
- Status dropdown + notes → Save changes
- Pitch message section: Grab Attention / Sales Pitch (Claude-generated), Send Email, DM on Instagram
- Remove Lead button (2-click confirm)

---

## Environment Variables

### `backend/.env`
```
SUPABASE_URL=https://xxx.supabase.co
SUPABASE_KEY=eyJ...
PORT=4000
```

### `discovery/.env`
```
SPOTIFY_CLIENT_ID=xxx
SPOTIFY_CLIENT_SECRET=xxx
CLAUDE_API_KEY=sk-ant-...
SUPABASE_URL=https://xxx.supabase.co
SUPABASE_KEY=eyJ...
LASTFM_API_KEY=xxx
```

### `dashboard/.env`
```
VITE_API_URL=http://localhost:4000
```

> **Note**: The backend `.env` does NOT have Spotify credentials — it doesn't need them. Only `discovery/.env` needs Spotify keys (for discovery.py). resolve.py's Twitterbot scraper needs no credentials.

---

## How to Run

```bash
# Install dependencies (first time)
setup.bat

# Start everything
run.bat
# OR manually:
cd backend && npm run dev
cd dashboard && npm run dev
```

Dashboard: `http://localhost:5173`  
Backend: `http://localhost:4000`

Python scripts run from backend via `spawn('python', [...])` — must be in PATH.

---

## Critical Technical Decisions

### Spotify listener scraping = Twitterbot UA
Spotify's bot detection serves a 6KB JS shell to Chrome/Firefox UAs. Social media crawlers (Twitterbot) get a 9.5KB static OG page with `"Artist · 15K monthly listeners."` in `og:description`. **Never use Chrome UA for Spotify page scraping.**

### Instagram oEmbed is broken
Since ~2024, `https://www.instagram.com/oembed/?url=...` returns HTML (not JSON) for all handles. Replace with direct profile page fetch + check for handle in og:title.

### Spotify Web API missing fields
Spotify client credentials API no longer returns `popularity` or `followers.total` for most artists — the response only has `external_urls`, `href`, `id`, `images`, `name`, `type`, `uri`. Do not rely on these fields.

### Route ordering in Express
Specific routes (`/listener-refresh-status`, `/refresh-listeners`, `/rescan-all`) MUST be defined BEFORE the `/:id` wildcard or Express matches them as artist IDs.

### contact_quality='contactless' vs 'none'
`'none'` = not yet searched, worker WILL pick up.  
`'contactless'` = searched, found nothing or failed, worker will NOT re-pick.  
Setting `'none'` on failure would cause infinite retry loops — always set `'contactless'` on parse failure.

### Instagram handle guessing = REMOVED
The old system guessed handles like `@303music` or `@artist_official` — these regularly matched random non-music accounts. Now: if search engines don't surface it, leave it blank.

### Prefer "official" handles
When scanning search results, collect multiple candidates and prefer handles containing "official" (e.g. @theofficial303 over @the303). Artists with short/common names often claim the `official` variant because the bare name was taken.

---

## Common Issues & Fixes

| Symptom | Root Cause | Fix |
|---|---|---|
| Listeners show 0/null | Chrome UA gets bot-blocked by Spotify | Use Twitterbot/1.0 UA |
| Wrong Instagram saved | Bare-name search returns unrelated account | "official" queries first + prefer "official" in results |
| Enrichment infinite loop | Parse failure set contact_quality='none' → re-queued | Always set 'contactless' on failure |
| Listener refresh starts enrichment | Express /:id wildcard caught /listener-refresh-status | Specific routes must be before /:id |
| Batch refresh gives 0 | Spotify rate-limits 200+ rapid requests | 2s delay between each artist |
| Auto-flush deletes good leads | Scrape returned wrong listener count | Fix scraper first; auto-flush runs after correct count saved |

---

## What's Working (as of this build)

- ✅ Spotify listener counts via Twitterbot UA (K/M/B suffix parsing)
- ✅ Per-artist listener refresh button in lead panel (↻)
- ✅ Global "Refresh Listeners" updates all leads including pitched/contacted
- ✅ Instagram search with "official" queries first + prefers official handles in results
- ✅ Instagram validation via direct profile page (not broken oEmbed)
- ✅ No Instagram handle guessing — blank if not found
- ✅ Enrichment pause/resume button in dashboard
- ✅ Rescan All Leads wipes and re-enriches all 'new' leads
- ✅ Auto-enrich worker processes one artist at a time (no IP bans)
- ✅ contact_quality='contactless' prevents infinite retry loops
- ✅ Manually add artist by Spotify URL via dashboard

## What Still Needs Work / Known Limitations

- Spotify OG page rounds listener counts (14,957 → "15K") — we get ~±500 accuracy, not exact
- Instagram internal API returns 401 for all handles (require_login) — no follower count from API
- IG follower count comes from scraping the profile page (slower, may fail)
- Step 2b (extracting Instagram links from Spotify artist page) uses Chrome UA — blocked, rarely finds anything
- Google search rarely works (serves JS-rendered pages to bots)
- Last.fm data still used in scoring but removed from listener count logic
