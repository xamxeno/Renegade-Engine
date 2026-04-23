# Renegade Records — Discovery Engine

A 3-stage AI pipeline that discovers artists on Spotify, YouTube, and Deezer,
scores them with Claude AI, resolves their Instagram/email, and manages outreach
from a single dashboard.

---

## Folder Structure

```
renegade-engine/
  discovery/        ← Python scraper + AI scorer (runs on your PC)
  backend/          ← Node.js Express API (hosted on Render)
  dashboard/        ← React frontend (hosted on Vercel)
  supabase_schema.sql ← Run once in Supabase SQL editor
```

---

## STEP 1 — Install Prerequisites

Make sure you have these installed:
- Python 3.10+ → https://python.org
- Node.js 18+ → https://nodejs.org
- Git → https://git-scm.com

Verify by running in terminal:
```
python --version
node --version
```

---

## STEP 2 — Set Up Supabase (Free Database)

1. Go to https://supabase.com → Sign Up → Create a new project
2. Name it: `renegade-records`
3. Choose a region closest to you
4. Wait for project to spin up (~2 mins)
5. Go to: SQL Editor → New Query
6. Paste the contents of `supabase_schema.sql` → click Run
7. Go to: Settings → API
8. Copy:
   - `Project URL` → this is your SUPABASE_URL
   - `anon public` key → this is your SUPABASE_KEY

---

## STEP 3 — Configure the Python Discovery Script

```bash
cd discovery
pip install -r requirements.txt
cp .env.example .env
```

Open `.env` and fill in your keys:
```
SPOTIFY_CLIENT_ID=     ← from developer.spotify.com
SPOTIFY_CLIENT_SECRET= ← from developer.spotify.com
YOUTUBE_API_KEY=       ← from console.cloud.google.com
CLAUDE_API_KEY=        ← from console.anthropic.com
SUPABASE_URL=          ← from Supabase settings
SUPABASE_KEY=          ← from Supabase settings
```

Run it:
```bash
python discovery.py
```

This will:
- Search Spotify, YouTube, Deezer for active artists (1k-50k followers)
- Filter out inactive accounts (no releases in 6 months)
- Parse bios for Instagram handles and emails
- Resolve Linktree pages for contact info
- Score all artists with Claude AI (batches of 20)
- Drop anyone scoring under 40
- Save qualified leads to Supabase (or leads_output.json if Supabase not configured)

Run time: ~5-10 minutes for a full sweep.
Cost: ~$0.50-1.00 in Claude API credits per full run.

---

## STEP 4 — Set Up the Backend API

```bash
cd backend
npm install
cp .env.example .env
```

Fill in `.env`:
```
SUPABASE_URL=     ← same as above
SUPABASE_KEY=     ← same as above
CLAUDE_API_KEY=   ← same as above
RESEND_API_KEY=   ← from resend.com (free tier = 3k emails/mo)
FROM_EMAIL=       ← your studio email
PORT=4000
```

Run locally:
```bash
npm run dev
```

API will be live at: http://localhost:4000

---

## STEP 5 — Set Up the Dashboard

```bash
cd dashboard
npm install
cp .env.example .env
```

`.env` should have:
```
VITE_API_URL=http://localhost:4000
```

Run locally:
```bash
npm run dev
```

Dashboard will open at: http://localhost:3000

---

## STEP 6 — Deploy to Free Hosting (Optional but Recommended)

### Deploy Backend to Render (Free)
1. Push this project to GitHub
2. Go to https://render.com → New → Web Service
3. Connect your GitHub repo
4. Set:
   - Root directory: `backend`
   - Build command: `npm install`
   - Start command: `node server.js`
5. Add all your environment variables in Render's dashboard
6. Deploy → copy the live URL (e.g. `https://renegade-api.onrender.com`)

### Deploy Dashboard to Vercel (Free)
1. Go to https://vercel.com → New Project
2. Import your GitHub repo
3. Set:
   - Root directory: `dashboard`
   - Framework: Vite
4. Add environment variable:
   - `VITE_API_URL` = your Render backend URL
5. Deploy

---

## STEP 7 — Daily Workflow

1. Run `python discovery.py` once a week from your PC
2. Open your Vercel dashboard URL
3. Browse new leads, sorted by AI score
4. Click any artist → Generate Pitch with AI
5. Edit the pitch if needed
6. Send email directly from dashboard OR copy the DM for Instagram

---

## API Endpoints Reference

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | /api/artists | List all leads (filter by status, platform, score) |
| GET | /api/artists/:id | Get single artist detail |
| PATCH | /api/artists/:id | Update status or notes |
| POST | /api/pitch | Generate AI pitch for an artist |
| POST | /api/send-email | Send outreach email |
| GET | /api/stats | Dashboard summary numbers |

---

## Troubleshooting

**Python script finds 0 artists:**
- Check your `.env` keys are correct
- Spotify token expires every hour — re-run if needed
- Try running just Deezer first (no auth needed)

**Supabase connection fails:**
- Make sure your project isn't paused (free tier pauses after 1 week of inactivity)
- Double-check you're using the `anon` key, not the `service_role` key

**Claude scoring fails:**
- Check your Claude API key has credits
- The script will still save artists, just without scores

**Dashboard shows no data:**
- Make sure backend is running (`npm run dev` in /backend)
- Check browser console for CORS errors
- Verify `VITE_API_URL` in dashboard `.env` points to the right port
