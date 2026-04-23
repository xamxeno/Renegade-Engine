# Renegade Engine — Project Bible for Claude

## What This Is
A 3-stage AI pipeline for Renegade Records to discover unsigned artists, score them, resolve their Instagram/email contacts, and manage outreach — all from a single dashboard.

**Owner:** Renegade Records (renegaderecordsusa@gmail.com)
**Version:** 0.3 BETA

---

## Tech Stack

| Layer | Tech | Location | Runs On |
|---|---|---|---|
| Discovery | Python 3.10+ | `discovery/` | Local PC |
| Enrichment | Python + resolve.py | `discovery/` | Local PC |
| Backend API | Node.js + Express | `backend/server.js` | Render (port 4000) |
| Dashboard | React + Vite | `dashboard/src/` | Vercel |
| Database | Supabase (Postgres) | `supabase_schema.sql` | Supabase cloud |

---

## Folder Structure

```
Git Repo/
  backend/
    server.js          ← All API endpoints + background enrichment worker
    package.json
    .env               ← SUPABASE_URL, SUPABASE_KEY, CLAUDE_API_KEY, RESEND_API_KEY
  dashboard/
    src/
      pages/
        Dashboard.jsx  ← Main leads table, filters, mass actions
        ArtistDetail.jsx ← Single artist view, pitch generator, enrich button
      main.jsx
      App.jsx
    .env               ← VITE_API_URL=http://localhost:4000
  discovery/
    discovery.py       ← Finds artists on Spotify/Last.fm/Deezer, scores with Claude
    enrich.py          ← Batch enrichment from JSON leads files
    resolve.py         ← Deep contact resolution (IG, email, phone) — called by backend too
    sync_supabase.py   ← Push local leads JSON → Supabase
    leads_*.json       ← Output files from discovery runs
  supabase_schema.sql  ← Run once in Supabase SQL editor to create tables
  run.bat              ← Windows shortcut to start backend
```

---

## Database Schema (Supabase `artists` table)

| Column | Type | Notes |
|---|---|---|
| id | uuid | Primary key |
| name | text | Artist name |
| platform | text | `spotify`, `deezer`, `lastfm` |
| platform_id | text | Spotify/Deezer/Lastfm ID |
| followers | integer | Platform follower count |
| listeners | integer | Monthly listeners (Spotify scrape or Last.fm) |
| genres | text | Genre string |
| profile_url | text | Spotify/platform URL |
| image_url | text | Artist photo |
| instagram | text | IG handle (no @) |
| facebook | text | Facebook URL |
| phone | text | Phone number |
| email | text | Contact email |
| ig_followers | integer | Instagram follower count |
| contact_quality | text | `none`, `searching`, `found`, `contactless`, `skip` |
| score | integer | Claude AI score 0–100 |
| score_reason | text | Why Claude gave that score |
| needs | text | Production need signals from bio |
| pitch_draft | text | AI-generated pitch |
| notes | text | Manual user notes |
| status | text | `new`, `contacted`, `pitched`, `signed`, `ignored` |
| session_id | text | Groups artists from same discovery run |
| discovered_at | timestamptz | When added |
| updated_at | timestamptz | Last modified |

**contact_quality values:**
- `none` → not enriched yet (enrichment worker will pick up)
- `searching` → enrichment worker currently processing this artist
- `found` → has instagram or email
- `contactless` → enrichment ran, found nothing
- `skip` → flagged (producer keyword, 100K+ followers, blocked region, or manually flagged) — shows in Flush Junk preview

---

## Discovery Pipeline (discovery.py)

**Target artists:**
- Regions: USA, Canada, UK, Australia, UAE only
- Followers: 500–100,000
- Monthly listeners: 1,000–100,000 (Spotify), 500–100,000 (Last.fm), 1,000–100,000 (Deezer)
- Minimum score: 60 (Claude AI scoring)

**What it does:**
1. Pulls artists from Spotify playlists + keyword search, Last.fm, Deezer
2. Filters blocked regions, listener caps
3. Scores each artist with Claude (batches of 20) — costs ~$0.50–1.00/run
4. Saves to `leads_YYYYMMDD_HHMM.json` and optionally syncs to Supabase

**Run:**
```bash
cd discovery
python discovery.py
```

---

## Contact Resolution (resolve.py)

**Sources in priority order:**
1. MusicBrainz — structured social links
2. Last.fm bio — IG/email mentions
3. Official site — scrape homepage + /contact
4. Instagram API — fetch bio/followers via i.instagram.com
5. DuckDuckGo — HTML search fallback
6. Google — HTML search fallback

**Current mode:** `IG_ONLY = True` — only finds Instagram (email/phone/Facebook disabled until IG bugs resolved)

**CLI usage:**
```bash
python resolve.py --name "Artist Name" --platform spotify --profile-url https://open.spotify.com/artist/ID
```

**IMPORTANT — never pass `--ig` for background enrichment.** Always do a fresh IG search so stale/wrong handles get corrected. The manual enrich endpoint also follows this rule.

---

## Backend API (server.js) — Key Endpoints

| Method | Endpoint | What It Does |
|---|---|---|
| GET | `/api/artists` | List leads — filters: status, platform, min_score, search, session_id |
| GET | `/api/artists/:id` | Single artist |
| POST | `/api/artists/add` | Manually add artist by Spotify URL |
| PATCH | `/api/artists/:id` | Update status/notes |
| DELETE | `/api/artists/:id` | **FLAGS** the lead (contact_quality='skip'), does NOT delete |
| POST | `/api/artists/batch` | Mass status update or mass flag |
| POST | `/api/enrich/:id` | Run resolve.py for one artist (manual trigger) |
| GET | `/api/enrich/status` | Background worker progress |
| POST | `/api/enrich/pause` | Pause background worker |
| POST | `/api/enrich/resume` | Resume background worker |
| POST | `/api/artists/rescan-all` | Clear all contact data, re-enrich everyone |
| GET | `/api/flush/preview` | Preview what Flush Junk would remove |
| DELETE | `/api/flush` | **Actually deletes** flagged/junk leads (only real delete in the system) |
| POST | `/api/pitch` | Generate AI pitch for an artist |
| GET | `/api/stats` | Dashboard summary counts |

---

## Background Enrichment Worker

- Lives in `server.js`, starts automatically when backend boots
- Picks up artists with `contact_quality = 'none'` or `null`
- Processes one artist at a time (avoids IP bans)
- Order: Spotify first → Deezer → Last.fm, newest session first, lowest followers first
- Calls `resolve.py --json` as a child process
- Timeout: 120 seconds per artist
- After all done: checks again every 10 minutes

**Stuck artists** (contact_quality='searching' after crash) are reset to 'none' on server startup.

---

## Critical Rules — Never Break These

1. **Never auto-delete leads.** Everything suspicious gets flagged (`contact_quality='skip'`). Only `DELETE /api/flush` actually removes records — and only when the user explicitly triggers it.

2. **Never pass `--ig` in autoEnrichWorker.** Stale IG handles (like wrong usernames) must be re-discovered fresh. The background worker and manual enrich endpoint both skip passing the stored instagram to resolve.py.

3. **Never delete contacted/pitched/signed leads** in any auto-flush or background process. Only `status='new'` and `status='ignored'` leads are eligible for flagging/flushing.

4. **contact_quality='skip' leads stay in the DB** and show in the Flush Junk preview. The user reviews them before they're gone.

5. **IG_ONLY mode is active** in resolve.py — don't add email/phone logic until Instagram resolution is stable.

---

## What Gets Flagged (contact_quality='skip')

- Producer keywords in bio or name (e.g., "music producer", "beat store", "mixing engineer")
- 100K+ Instagram followers
- 100K+ Spotify followers or monthly listeners
- Blocked region signals (Pakistan, India, Nigeria, Indonesia, Brazil, Mexico, Korea, Japan, China, Philippines, Ghana)
- Instagram bio explicitly identifies as producer
- IG follower count under 100 (too small)

**Note:** These are soft signals with false positives. DL Incognito is a real example — flagged as producer, actually an artist with 52K listeners. Always review before flushing.

---

## Common Issues & Fixes

| Problem | Likely Cause | Fix |
|---|---|---|
| Wrong Instagram stored | Stale handle from old enrichment | Clear `instagram` field in Supabase, set `contact_quality='none'` to re-enrich |
| "Searching contacts for X" but X not in leads | X was flagged/deleted during enrichment | Fixed: `_enrichStats.current` now clears after flag/delete |
| Lead scanned but not appearing | Platform filter defaults to Spotify — Deezer/Last.fm leads hidden | Change platform filter in dashboard |
| Enrichment worker stuck | Server crashed mid-enrichment | Restarts reset all `contact_quality='searching'` to `'none'` automatically |
| Supabase connection fails | Free tier pauses after 1 week inactive | Wake up the project at supabase.com |

---

## Environment Variables

**backend/.env**
```
SUPABASE_URL=
SUPABASE_KEY=
CLAUDE_API_KEY=
RESEND_API_KEY=
FROM_EMAIL=
PORT=4000
```

**dashboard/.env**
```
VITE_API_URL=http://localhost:4000
```

**discovery/.env**
```
SPOTIFY_CLIENT_ID=
SPOTIFY_CLIENT_SECRET=
LASTFM_API_KEY=
CLAUDE_API_KEY=
SUPABASE_URL=
SUPABASE_KEY=
```

---

## Running Locally

```bash
# Terminal 1 — Backend
cd "C:/Renegade Engine 0.3 BETA/Git Repo/backend"
node server.js

# Terminal 2 — Dashboard
cd "C:/Renegade Engine 0.3 BETA/Git Repo/dashboard"
npm run dev

# Discovery (run manually when needed)
cd "C:/Renegade Engine 0.3 BETA/Git Repo/discovery"
python discovery.py
```
