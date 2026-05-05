const express = require('express')
const cors = require('cors')
const { createClient } = require('@supabase/supabase-js')
const nodemailer = require('nodemailer')
const { spawn } = require('child_process')
// content_discovery v2 — YouTube-based engine (deployed 2026-05-04)
const path = require('path')
const https = require('https')
require('dotenv').config()

const app = express()
app.use(cors({
  origin: (origin, cb) => cb(null, true), // allow all origins — lock down after deploy if needed
  credentials: true
}))
app.use(express.json())

const supabase = createClient(
  process.env.SUPABASE_URL || '',
  process.env.SUPABASE_KEY || ''
)

// ── IG VERIFICATION WORKER ─────────────────────────────────────────────────────
let _verifyQueue = []
let _verifyBusy  = false
let _verifyStats = { total: 0, processed: 0, verified: 0, flagged: 0, current: null }

// Shared producer/DJ keyword list used by verifyWorker AND runBioScan
const PRODUCER_KEYWORDS = [
  'producer','beat maker','beatmaker','mixing engineer','mastering engineer',
  'audio engineer','sound engineer','fl studio','ableton','logic pro',
  'prod by','beats by','trap producer','rnb producer','hip hop producer',
  'record producer','music producer','executive producer','beatsmith',
  'recording engineer','sound designer','instrumental',
  'deejay','disc jockey','turntablist','drum and bass producer',
  'dnb producer','d&b producer','house producer','edm producer',
  'techno producer','dubstep producer','garage producer',
  'foley artist','composer','film composer','music composer',
  'songwriter for hire','ghostwriter','session musician','session guitarist',
  'session bassist','session drummer','live sound','front of house',
  'studio engineer','tracking engineer','mix engineer','beat store','beatz',
]

// Bios that explicitly block cold outreach or signal the artist is already unreachable
const OUTREACH_BLOCKER_KEYWORDS = [
  // explicitly blocking unsolicited DMs
  'no dms', 'no dm', 'no unsolicited', 'no soliciting', 'no solicitation',
  'no cold', 'not accepting dms', 'dm closed', 'dms closed',
  // gatekeeper / management wall
  'bookings only', 'booking inquiries only', 'for bookings contact',
  'management only', 'contact management', 'contact my management',
  'all inquiries', 'business inquiries only', 'business only',
  'inquiries only', 'for features contact', 'for collabs contact',
  // already signed / label deal
  'signed to ', 'signed with ', 'signed artist', 'major label',
  'represented by', 'managed by ',
  // too established to be a target
  'grammy nominated', 'grammy award', 'grammy winner', 'grammy winning',
  'platinum certified', 'gold certified', 'riaa certified',
  'billboard #1', 'top 40 artist', 'topping charts',
]

// Check bio/description text for producer signals (word-boundary DJ match)
function isProducerText (text) {
  if (!text) return false
  const t = text.toLowerCase()
  if (/\bdj\b/.test(t)) return true
  return PRODUCER_KEYWORDS.some(kw => t.includes(kw))
}

// Check IG username for producer signals (no spaces in usernames)
function isProducerUsername (handle) {
  if (!handle) return false
  const h = handle.toLowerCase()
  // username starts with "dj" followed by anything (djfrank, dj_x, dj.x)
  if (/^dj[^a-z]/i.test(h) || h.startsWith('dj') && h.length > 2) return true
  // concatenated forms: "beatmaker" → "beatmaker", "producer" → "producer"
  return PRODUCER_KEYWORDS.some(kw => h.includes(kw.replace(/\s+/g, '')))
}

// Check if bio signals the artist won't respond to cold outreach
function isOutreachBlocked (text) {
  if (!text) return false
  const t = text.toLowerCase()
  return OUTREACH_BLOCKER_KEYWORDS.some(kw => t.includes(kw))
}

function fetchIGPage (handle) {
  return new Promise(resolve => {
    const req = https.get({
      hostname: 'www.instagram.com',
      path: `/${handle}/`,
      headers: { 'User-Agent': 'curl/8.5.0', 'Accept': '*/*' },
      timeout: 14000
    }, res => {
      let body = ''
      res.on('data', c => { body += c; if (body.length > 200000) res.destroy() })
      res.on('end', () => resolve(body))
    })
    req.on('error', () => resolve(''))
    req.on('timeout', () => { req.destroy(); resolve('') })
  })
}

function parseIGPage (html) {
  let followers = null
  // meta description: "1,234 Followers, ..."
  const metaM = html.match(/content="([\d,]+)\s+Followers/i)
  if (metaM) followers = parseInt(metaM[1].replace(/,/g, ''))
  // JSON blob fallback: "edge_followed_by":{"count":1234}
  if (followers === null) {
    const jsonM = html.match(/"edge_followed_by"\s*:\s*\{"count"\s*:\s*(\d+)\}/)
    if (jsonM) followers = parseInt(jsonM[1])
  }

  // Bio — try "biography" JSON key first, fall back to og:description
  let bio = ''
  const bioM = html.match(/"biography"\s*:\s*"((?:[^"\\]|\\.)*)"/)
  if (bioM) {
    bio = bioM[1].replace(/\\n/g, ' ').replace(/\\u[\dA-Fa-f]{4}/g, '').toLowerCase()
  } else {
    const ogM = html.match(/<meta[^>]+property="og:description"[^>]+content="([^"]+)"/i)
            || html.match(/<meta[^>]+content="([^"]+)"[^>]+property="og:description"/i)
    if (ogM) bio = ogM[1].toLowerCase()
  }

  // Email — business accounts expose public_email in page JSON; also scan bio text
  let email = null
  const pubEmailM = html.match(/"public_email"\s*:\s*"([^"@\s]+@[^"]+)"/)
  if (pubEmailM && pubEmailM[1]) email = pubEmailM[1].toLowerCase()
  if (!email && bio) {
    const bioEmailM = bio.match(/[\w.+-]+@[\w-]+\.[\w.]{2,}/)
    if (bioEmailM) email = bioEmailM[0]
  }

  // Private account flag — private = must follow first before DMs work
  const privateM = html.match(/"is_private"\s*:\s*(true|false)/)
  const isPrivate = privateM ? privateM[1] === 'true' : false

  return { followers, bio, email, isPrivate }
}

async function fetchSpotifyBio (profileUrl) {
  if (!profileUrl || !profileUrl.includes('spotify.com')) return ''
  try {
    const r = await fetch(profileUrl, { headers: { 'User-Agent': 'Twitterbot/1.0' }, signal: AbortSignal.timeout(10000) })
    const html = await r.text()
    const m = html.match(/<meta[^>]+property="og:description"[^>]+content="([^"]+)"/i)
      || html.match(/<meta[^>]+content="([^"]+)"[^>]+property="og:description"/i)
    return m ? m[1].toLowerCase() : ''
  } catch { return '' }
}

async function verifyWorker () {
  if (_verifyBusy || _verifyQueue.length === 0) return
  _verifyBusy = true

  while (_verifyQueue.length > 0) {
    const { id, handle, name, profile_url } = _verifyQueue.shift()
    _verifyStats.current = name
    console.log(`[Verify] ${name} @${handle} — checking IG...`)

    try {
      const html = await Promise.race([
        fetchIGPage(handle),
        new Promise(r => setTimeout(() => r(''), 15000))
      ])
      const { followers, bio, email, isPrivate } = parseIGPage(html)

      let quality = 'verified'
      let skipReason = ''
      const updates = { updated_at: new Date().toISOString() }
      if (followers !== null) updates.ig_followers = followers
      if (email) { updates.email = email; console.log(`[Verify] ${name} — email found: ${email}`) }

      if (!html || html.length < 500) {
        // IG blocked — fall back to Spotify bio check before trusting the handle
        const spotifyBio = profile_url ? await fetchSpotifyBio(profile_url) : ''
        if (isProducerText(spotifyBio)) {
          quality = 'skip'; skipReason = 'producer (Spotify bio)'
        } else if (isOutreachBlocked(spotifyBio)) {
          quality = 'skip'; skipReason = 'outreach blocked (Spotify bio)'
        } else {
          quality = 'verified'
          console.log(`[Verify] ${name} @${handle} — IG blocked, trusting handle`)
        }
      } else if (followers !== null && followers > 500000) {
        quality = 'skip'; skipReason = `too large (${followers.toLocaleString()} followers)`
      } else if (isProducerText(bio)) {
        quality = 'skip'; skipReason = 'producer in IG bio'
      } else if (isOutreachBlocked(bio)) {
        quality = 'skip'; skipReason = 'outreach blocked in IG bio'
      } else if (isPrivate && !email) {
        quality = 'skip'; skipReason = 'private account, no email — unreachable'
      } else {
        console.log(`[Verify] ${name} @${handle} — VERIFIED (${followers?.toLocaleString() ?? '?'} followers)${email ? ' +email' : ''}${isPrivate ? ' (private, has email)' : ''}`)
      }

      if (skipReason) console.log(`[Verify] ${name} — SKIP: ${skipReason}`)

      updates.contact_quality = quality
      await supabase.from('artists').update(updates).eq('id', id)
      _verifyStats.processed++
      if (quality === 'verified') _verifyStats.verified++
      if (quality === 'skip')     _verifyStats.flagged++
    } catch (e) {
      console.error(`[Verify] Error on ${name}: ${e.message}`)
      await supabase.from('artists').update({ contact_quality: 'verified', updated_at: new Date().toISOString() }).eq('id', id)
      _verifyStats.processed++
    }

    await new Promise(r => setTimeout(r, 1800))
  }

  _verifyStats.current = null
  _verifyBusy = false
}

// GET /api/artists — list all leads with optional filters
app.get('/api/artists', async (req, res) => {
  try {
    const { status, min_score, max_followers, max_listeners, platform, exclude_platform, search, sort_by, sort_dir, session_id, exclude_session_id } = req.query

    // 'listeners' = actual monthly listeners (Spotify scrape or Last.fm).
    // 'followers' = platform follower/fan count (Spotify API followers).
    // These are different: an artist can have 2k Spotify followers but 90k monthly listeners.
    // We filter by BOTH columns to correctly exclude high-listener artists.
    const followerCap = (max_listeners || max_followers)
      ? parseInt(max_listeners || max_followers)
      : 100000

    const SORT_MAP = { listeners: 'listeners', followers: 'followers', score: 'score', name: 'name', ig_followers: 'ig_followers' }
    const sortField = SORT_MAP[sort_by] || 'score'
    const ascending = sort_dir === 'asc'

    let query = supabase.from('artists').select('*')
      .order(sortField, { ascending, nullsFirst: false })
      .order('score',   { ascending: false, nullsFirst: false })  // tiebreaker
      .lte('followers', followerCap)
      // Also cap by monthly listeners when the column is populated (new records).
      // Old records (listeners=null) pass through; followers cap above catches them.
      .or(`listeners.is.null,listeners.lte.${followerCap}`)

    if (status)     query = query.eq('status', status)
    if (min_score !== undefined && min_score !== '' && parseInt(min_score) > 0)
      query = query.gte('score', parseInt(min_score))
    if (platform)         query = query.eq('platform', platform)
    // neq excludes NULLs in Postgres — explicitly keep NULL platform rows (old music leads)
    if (exclude_platform) query = query.or(`platform.neq.${exclude_platform},platform.is.null`)
    if (search)     query = query.ilike('name', `%${search}%`)
    if (session_id)         query = query.eq('session_id', session_id)
    // neq alone excludes NULLs in PostgreSQL — explicitly include NULL rows for Past Leads
    if (exclude_session_id) query = query.or(`session_id.neq.${exclude_session_id},session_id.is.null`)

    const { data, error } = await query
    if (error) throw error
    res.json({ artists: data, count: data.length })
  } catch (err) {
    res.status(500).json({ error: err.message })
  }
})

let _listenerRefresh = { busy: false, current: null, processed: 0, total: 0, updated: 0 }

// POST /api/artists/add — manually insert a single artist by Spotify URL; auto-enrich picks it up
app.post('/api/artists/add', async (req, res) => {
  const { profile_url, name: manualName, instagram, session_id: customSession } = req.body
  if (!profile_url) return res.status(400).json({ error: 'profile_url required' })
  const m = profile_url.match(/open\.spotify\.com\/artist\/([A-Za-z0-9]+)/)
  if (!m) return res.status(400).json({ error: 'Only Spotify artist URLs supported' })
  const platform_id = m[1]

  let name = manualName || null, listeners = null
  if (!name) {
    try {
      // Twitterbot UA gets Spotify's SEO/OG page — Chrome UA gets a 6KB bot shell with no useful data
      const r = await fetch(`https://open.spotify.com/artist/${platform_id}`, {
        headers: { 'User-Agent': 'Twitterbot/1.0' }
      })
      const html = await r.text()
      // Name from <title>Artist Name | Spotify</title>
      const titleM = html.match(/<title>([^<]+?)\s*[|\-–]\s*Spotify/i)
      if (titleM) name = titleM[1].trim()
      // Listener count from og:description "Artist · 15K monthly listeners."
      const lm = html.match(/([\d,.]+\s*[KkMmBb]?)\s+monthly\s+listener/i)
      if (lm) {
        const raw = lm[1].trim().toUpperCase().replace(/,/g, '').replace(/\s/g, '')
        if (raw.includes('K')) listeners = Math.round(parseFloat(raw.replace('K', '')) * 1000)
        else if (raw.includes('M')) listeners = Math.round(parseFloat(raw.replace('M', '')) * 1000000)
        else if (raw.includes('B')) listeners = Math.round(parseFloat(raw.replace('B', '')) * 1000000000)
        else listeners = parseInt(raw) || null
      }
    } catch {}
  }

  if (!name) return res.status(500).json({ error: 'Could not scrape artist name — pass name in body' })

  // Check if already exists — don't overwrite contact_quality/status of flagged or verified leads
  const { data: existing } = await supabase.from('artists')
    .select('id, contact_quality, status').eq('platform', 'spotify').eq('platform_id', platform_id).maybeSingle()
  if (existing && ['skip', 'verified', 'found', 'contactless'].includes(existing.contact_quality)) {
    return res.json({ success: true, artist: existing, already_exists: true })
  }

  const sessionId = customSession || 'manual_searched'
  const payload = {
    name, platform: 'spotify', platform_id,
    profile_url: `https://open.spotify.com/artist/${platform_id}`,
    listeners: listeners || null,
    followers: 0, contact_quality: instagram ? 'verifying' : 'none',
    status: 'new', session_id: sessionId,
    discovered_at: new Date().toISOString(), updated_at: new Date().toISOString()
  }
  if (instagram) payload.instagram = instagram.replace(/^@/, '').trim()

  const { data, error } = await supabase.from('artists').upsert(payload, { onConflict: 'platform,platform_id' }).select().single()

  if (error) return res.status(500).json({ error: error.message })

  // If IG handle provided, queue for bio verification immediately
  if (instagram && data) {
    const handle = instagram.replace(/^@/, '').trim()
    _verifyQueue.push({ id: data.id, handle, name: data.name })
    _verifyStats.total++
    if (!_verifyBusy) verifyWorker()
  } else if (!_enrichBusy) {
    setTimeout(autoEnrichWorker, 100)
  }

  res.json({ success: true, artist: data })
})

// GET /api/artists/listener-refresh-status — must be before /:id
app.get('/api/artists/listener-refresh-status', (req, res) => {
  res.json(_listenerRefresh)
})

// POST /api/artists/refresh-listeners — must be before /:id
app.post('/api/artists/refresh-listeners', async (req, res) => {
  if (_listenerRefresh.busy) return res.json({ success: false, error: 'Already running' })
  try {
    const { data, error } = await supabase
      .from('artists')
      .select('id, name, platform, profile_url')
    if (error) throw error

    _listenerRefresh = { busy: true, current: null, processed: 0, total: data.length, updated: 0 }
    res.json({ success: true, started: data.length })

    const resolvePath = path.join(__dirname, '../discovery/resolve.py')

    for (const artist of data) {
      _listenerRefresh.current = artist.name
      await new Promise(done => {
        const args = [resolvePath, '--listeners-only', '--name', artist.name, '--platform', artist.platform || '']
        if (artist.profile_url) args.push('--profile-url', artist.profile_url)

        const py = spawn(PYTHON_CMD, args)
        let out = ''
        const kill = setTimeout(() => { py.kill(); done() }, 25000)

        py.stdout.on('data', d => { out += d })
        py.on('close', async () => {
          clearTimeout(kill)
          try {
            const result = JSON.parse(out.trim())
            if (result.listeners && result.listeners > 0) {
              await supabase.from('artists').update({ listeners: result.listeners }).eq('id', artist.id)
              _listenerRefresh.updated++
              console.log(`[RefreshListeners] ${artist.name}: ${result.listeners.toLocaleString()}`)
            }
          } catch {}
          _listenerRefresh.processed++
          done()
        })
        py.on('error', () => { clearTimeout(kill); _listenerRefresh.processed++; done() })
      })
      // Brief pause so Spotify doesn't rate-limit the batch
      await new Promise(r => setTimeout(r, 2000))
    }

    console.log(`[RefreshListeners] Done — ${_listenerRefresh.updated}/${data.length} updated`)
    _listenerRefresh = { busy: false, current: null, processed: data.length, total: data.length, updated: _listenerRefresh.updated }
  } catch (err) {
    _listenerRefresh.busy = false
    if (!res.headersSent) res.status(500).json({ error: err.message })
  }
})

// POST /api/artists/:id/refresh-listeners — refresh listener count for one artist
app.post('/api/artists/:id/refresh-listeners', async (req, res) => {
  try {
    const { data: artist, error } = await supabase
      .from('artists').select('id, name, platform, profile_url').eq('id', req.params.id).single()
    if (error || !artist) return res.status(404).json({ error: 'Artist not found' })

    const resolvePath = path.join(__dirname, '../discovery/resolve.py')
    const args = [resolvePath, '--listeners-only', '--name', artist.name, '--platform', artist.platform || '']
    if (artist.profile_url) args.push('--profile-url', artist.profile_url)

    const listeners = await new Promise((resolve) => {
      const py = spawn(PYTHON_CMD, args)
      let out = ''
      const kill = setTimeout(() => { py.kill(); resolve(null) }, 25000)
      py.stdout.on('data', d => { out += d })
      py.on('close', () => {
        clearTimeout(kill)
        try {
          const result = JSON.parse(out.trim())
          resolve(result.listeners && result.listeners > 0 ? result.listeners : null)
        } catch { resolve(null) }
      })
      py.on('error', () => { clearTimeout(kill); resolve(null) })
    })

    if (listeners) {
      await supabase.from('artists').update({ listeners, updated_at: new Date().toISOString() }).eq('id', artist.id)
      console.log(`[RefreshOne] ${artist.name}: ${listeners.toLocaleString()}`)
      res.json({ success: true, listeners })
    } else {
      res.json({ success: false, error: 'Could not fetch listener count' })
    }
  } catch (err) {
    res.status(500).json({ error: err.message })
  }
})

// GET /api/artists/:id
app.get('/api/artists/:id', async (req, res) => {
  try {
    const { data, error } = await supabase
      .from('artists')
      .select('*')
      .eq('id', req.params.id)
      .single()
    if (error) throw error
    res.json(data)
  } catch (err) {
    res.status(500).json({ error: err.message })
  }
})

// GET /api/sessions — distinct discovery session IDs with lead counts, newest first
app.get('/api/sessions', async (req, res) => {
  try {
    let q = supabase.from('artists').select('session_id, discovered_at')
      .not('session_id', 'is', null)
      .order('discovered_at', { ascending: false })
    if (req.query.platform) q = q.eq('platform', req.query.platform)
    const { data, error } = await q
    if (error) throw error
    const seen = new Map()
    for (const row of data) {
      if (!seen.has(row.session_id)) {
        seen.set(row.session_id, { session_id: row.session_id, discovered_at: row.discovered_at, count: 1 })
      } else {
        seen.get(row.session_id).count++
      }
    }
    res.json({ sessions: [...seen.values()] })
  } catch (err) {
    res.status(500).json({ error: err.message })
  }
})

// PATCH /api/artists/:id — update status (contacted, pitched, signed, ignored)
app.patch('/api/artists/:id', async (req, res) => {
  try {
    const { status, notes } = req.body
    const updates = {}
    if (status) updates.status = status
    if (notes !== undefined) updates.notes = notes
    updates.updated_at = new Date().toISOString()
    const { data, error } = await supabase
      .from('artists')
      .update(updates)
      .eq('id', req.params.id)
      .select()
      .single()
    if (error) throw error
    res.json(data)
  } catch (err) {
    res.status(500).json({ error: err.message })
  }
})

// DELETE /api/artists/:id — permanently remove a lead
app.delete('/api/artists/:id', async (req, res) => {
  try {
    const { error } = await supabase.from('artists').update({ contact_quality: 'skip', updated_at: new Date().toISOString() }).eq('id', req.params.id)
    if (error) throw error
    res.json({ success: true, flagged: true })
  } catch (err) {
    res.status(500).json({ error: err.message })
  }
})

// POST /api/pitch — generate AI pitch for an artist
app.post('/api/pitch', async (req, res) => {
  try {
    const { artist_id, pitch_type = 'attention' } = req.body
    const { data: artist, error } = await supabase
      .from('artists')
      .select('*')
      .eq('id', artist_id)
      .single()
    if (error) throw error

    const genre  = artist.genres || ''
    const reason = artist.score_reason || ''

    // Pure template — no AI, no risk of long output
    const VIBE_MAP = [
      ['trap soul',       'the vibe is smooth but hits hard'],
      ['trap',            'the energy goes crazy'],
      ['neo soul',        'the sound is smooth as hell'],
      ['alternative r&b', 'lowkey haunting honestly'],
      ['alt r&b',         'lowkey haunting honestly'],
      ['r&b',             'that sound hits different'],
      ['rnb',             'that sound hits different'],
      ['hip-hop',         'the energy is wild'],
      ['hip hop',         'the energy is wild'],
      ['rap',             'the bars are hard'],
      ['drill',           'that pressure is insane'],
      ['pop',             'those hooks are clean'],
      ['afrobeats',       'the rhythm is infectious'],
      ['dancehall',       'that energy is crazy'],
      ['lo-fi',           'super relaxing honestly'],
      ['lofi',            'super relaxing honestly'],
      ['soul',            'that voice hits deep'],
      ['gospel',          'the emotion in it is real'],
      ['jazz',            'the sound is lowkey addictive'],
      ['indie',           'the sound is really distinct'],
      ['electronic',      'the production is clean as hell'],
      ['trance',          'the drop hits different'],
      ['house',           'the groove is addictive'],
    ]

    const genreLower = (genre || '').toLowerCase()
    const vibe = VIBE_MAP.find(([k]) => genreLower.includes(k))?.[1] || 'the sound is different'

    // Use AI only to pick a casual 3-word compliment, nothing more
    let vibePhrase = vibe
    if (process.env.CLAUDE_API_KEY) {
      try {
        const r = await fetch('https://api.anthropic.com/v1/messages', {
          method: 'POST',
          headers: {
            'x-api-key': process.env.CLAUDE_API_KEY,
            'anthropic-version': '2023-06-01',
            'content-type': 'application/json'
          },
          body: JSON.stringify({
            model: 'claude-haiku-4-5-20251001',
            max_tokens: 15,
            messages: [{
              role: 'user',
              content: `3-5 casual words describing ${genre} music vibe. lowercase. no punctuation. examples: "that sound hits different" "the energy goes crazy" "super smooth honestly". just the phrase.`
            }]
          })
        })
        const d = await r.json()
        const raw = (d.content?.[0]?.text || '').trim().toLowerCase().replace(/[^a-z\s]/g, '')
        if (raw && raw.split(' ').length <= 6) vibePhrase = raw
      } catch {}
    }

    const pitch = pitch_type === 'attention'
      ? `sups! heard your tracks, ${vibePhrase}. you producing these yourself?`
      : `sups! heard your music, ${vibePhrase}. think we can make it sound better, open for a free demo?`

    await supabase.from('artists').update({ pitch_draft: pitch }).eq('id', artist_id)
    res.json({ pitch })
  } catch (err) {
    res.status(500).json({ error: err.message })
  }
})

// POST /api/artists/:id/claude-scan — web-search IG (via resolve.py) + Claude re-score/re-analyze
app.post('/api/artists/:id/claude-scan', async (req, res) => {
  const CLAUDE_API_KEY = process.env.CLAUDE_API_KEY
  if (!CLAUDE_API_KEY) return res.status(500).json({ error: 'CLAUDE_API_KEY not set' })

  const { data: artist, error } = await supabase.from('artists').select('*').eq('id', req.params.id).single()
  if (error || !artist) return res.status(404).json({ error: 'Artist not found' })

  try {
    // ── Step 1: web-search for Instagram via resolve.py (same as Find Contacts) ──
    const resolvePath = path.join(__dirname, '../discovery/resolve.py')
    const args = [resolvePath, '--json', '--name', artist.name, '--platform', artist.platform || '']
    if (artist.profile_url) args.push('--profile-url', artist.profile_url)

    const resolveResult = await new Promise(resolve => {
      const py = spawn(PYTHON_CMD, args)
      let out = ''
      const kill = setTimeout(() => { py.kill(); resolve(null) }, 90000)
      py.stdout.on('data', d => { out += d })
      py.on('close', () => {
        clearTimeout(kill)
        for (const line of out.split('\n').reverse()) {
          try { return resolve(JSON.parse(line.trim())) } catch {}
        }
        resolve(null)
      })
      py.on('error', () => { clearTimeout(kill); resolve(null) })
    })

    // If resolve found IG but followers exceed the 100K cap, discard it — wrong/celebrity match
    const rawHandle    = resolveResult?.instagram || null
    const rawFollowers = resolveResult?.ig_followers || null
    const igTooLarge   = rawFollowers && rawFollowers > 100000
    const igHandle     = (rawHandle && !igTooLarge) ? rawHandle : null
    const igFollowers  = igHandle ? rawFollowers : null
    const igFound      = !!igHandle

    // ── Step 2: Claude re-scores and re-analyzes ──
    const genreInfo = artist.genres && artist.genres.trim()
      ? artist.genres
      : 'not specified (likely hip-hop/R&B/trap based on platform and listener profile)'
    const scorePrompt = `You are a music A&R analyst for Renegade Records (independent hip-hop/R&B label).
Score this artist 0-100 for outreach potential and write a 2-3 sentence analysis. Be specific — reference their listener count and any genre signals.

Artist: ${artist.name}
Genres: ${genreInfo}
Monthly listeners: ${(artist.listeners || artist.followers || 0).toLocaleString()}
Instagram: ${igHandle ? `@${igHandle} (${igFollowers?.toLocaleString() ?? '?'} followers)` : 'not found'}
Platform: ${artist.platform}
Bio/notes: ${artist.score_reason || 'none'}

Scoring criteria: listener range (sweet spot 5K-80K), genre fit (R&B, Hip-Hop, Trap Soul best), unsigned signals, engagement potential, production need signals.

Respond ONLY with valid JSON:
{"score": 0-100, "score_reason": "2-3 sentence analysis referencing their listener count and genre", "needs": "one-line production need signal or empty string"}`

    const claudeRes = await fetch('https://api.anthropic.com/v1/messages', {
      method: 'POST',
      headers: { 'x-api-key': CLAUDE_API_KEY, 'anthropic-version': '2023-06-01', 'content-type': 'application/json' },
      body: JSON.stringify({ model: 'claude-haiku-4-5-20251001', max_tokens: 300, messages: [{ role: 'user', content: scorePrompt }] })
    })
    const claudeData = await claudeRes.json()
    const raw = (claudeData.content?.[0]?.text || '').trim()
    let scored = {}
    try { scored = JSON.parse(raw.match(/\{[\s\S]*\}/)?.[0] || raw) } catch {}

    // ── Step 3: Save everything ──
    const updates = {
      score:        scored.score        ?? artist.score,
      score_reason: scored.score_reason || artist.score_reason,
      needs:        scored.needs        || artist.needs,
      updated_at:   new Date().toISOString()
    }

    if (igHandle) {
      updates.instagram       = igHandle
      updates.ig_followers    = igFollowers
      updates.contact_quality = 'verifying'
      _verifyQueue.push({ id: artist.id, handle: igHandle, name: artist.name })
      _verifyStats.total++
      if (!_verifyBusy) verifyWorker()
    } else if (!artist.instagram) {
      updates.contact_quality = 'contactless'
    }

    await supabase.from('artists').update(updates).eq('id', artist.id)

    console.log(`[ClaudeScan] ${artist.name} — score ${updates.score}, IG ${igHandle || (igTooLarge ? `discarded (${rawHandle} has ${rawFollowers?.toLocaleString()} followers)` : 'not found')}`)
    res.json({
      success:      true,
      ig_found:     igFound,
      ig_too_large: igTooLarge || false,
      ig_discarded: igTooLarge ? rawHandle : null,
      instagram:    igHandle,
      score:        updates.score,
      score_reason: updates.score_reason,
      needs:        updates.needs
    })
  } catch (err) {
    res.status(500).json({ error: err.message })
  }
})

// POST /api/score — Claude-score a list of artist IDs (or all unscored if no ids given)
app.post('/api/score', async (req, res) => {
  const { ids } = req.body || {}
  try {
    let query = supabase.from('artists').select('id,name,platform,listeners,followers,genres,instagram,ig_followers,needs,contact_quality')
    if (ids?.length) query = query.in('id', ids)
    const { data: artists, error } = await query
    if (error) throw error
    if (!artists?.length) return res.json({ scored: 0 })

    const CLAUDE_API_KEY = process.env.CLAUDE_API_KEY
    if (!CLAUDE_API_KEY) return res.status(500).json({ error: 'CLAUDE_API_KEY not set' })

    const BATCH = 20
    let scored = 0
    for (let i = 0; i < artists.length; i += BATCH) {
      const batch = artists.slice(i, i + BATCH)
      const payload = batch.map((a, idx) => ({
        index: idx,
        name: a.name,
        platform: a.platform,
        listeners: a.listeners || a.followers || 0,
        genres: (() => { try { return JSON.parse(a.genres || '[]') } catch { return [] } })().slice(0, 5),
        has_instagram: !!a.instagram,
        ig_followers: a.ig_followers || 0,
        needs: a.needs || '',
        contact_quality: a.contact_quality || 'none',
      }))

      const prompt = `You are a lead-scoring analyst for Renegade Records — a recording studio targeting INDEPENDENT artists who need professional help RIGHT NOW.

Sweet-spot client: solo performer, unsigned/self-managed, 1k–15k monthly listeners, R&B / Hip-Hop / Neo Soul / Trap Soul, US/Canada/UK/Australia/UAE, zero label backing.

SCORING RULES:
90-100  PERFECT: 1k–10k listeners + R&B/Hip-Hop/Neo Soul/Trap Soul + indie/DIY signals + no management
80-89   STRONG: 10k–20k listeners OR 1k–10k with neutral needs, genre matches
70-79   GOOD: 20k–35k listeners, genre matches, no management flags
60-69   BORDERLINE: good genre + under 20k but some flag (empty needs, minimal data)
0-59    DO NOT USE

HARD ZERO: Producer, beatmaker, DJ, engineer, radio station, playlist, compilation. Genres: reggaeton, afrobeats, K-pop, Bollywood, country, rock, EDM, jazz, classical. Listeners above 35k. needs contains: managed by, warner, universal, sony, atlantic, columbia.

Return ONLY valid JSON array:
[{"index": 0, "score": 82, "reason": "One sentence", "is_solo_artist": true}]

Artists:
${JSON.stringify(payload)}`

      try {
        const r = await fetch('https://api.anthropic.com/v1/messages', {
          method: 'POST',
          headers: { 'x-api-key': CLAUDE_API_KEY, 'anthropic-version': '2023-06-01', 'content-type': 'application/json' },
          body: JSON.stringify({ model: 'claude-haiku-4-5-20251001', max_tokens: 2000, messages: [{ role: 'user', content: prompt }] })
        })
        const d = await r.json()
        let raw = (d.content?.[0]?.text || '').trim().replace(/```json?\n?/g, '').replace(/```/g, '').trim()
        const results = JSON.parse(raw)
        for (const s of results) {
          const artist = batch[s.index]
          if (!artist) continue
          const scoreVal = s.is_solo_artist === false ? 0 : (s.score || 0)
          await supabase.from('artists').update({ score: scoreVal, score_reason: s.reason || '', updated_at: new Date().toISOString() }).eq('id', artist.id)
          scored++
        }
      } catch (e) {
        console.error('[Score] Batch error:', e.message)
      }
    }
    res.json({ scored })
  } catch (err) {
    res.status(500).json({ error: err.message })
  }
})

// POST /api/send-email — send outreach email
app.post('/api/send-email', async (req, res) => {
  try {
    const { artist_id, subject, body } = req.body
    const { data: artist } = await supabase
      .from('artists')
      .select('*')
      .eq('id', artist_id)
      .single()

    if (!artist.email) {
      return res.status(400).json({ error: 'Artist has no email on record' })
    }

    const transporter = nodemailer.createTransport({
      host: 'smtp.resend.com',
      port: 465,
      secure: true,
      auth: {
        user: 'resend',
        pass: process.env.RESEND_API_KEY
      }
    })

    await transporter.sendMail({
      from: process.env.FROM_EMAIL || 'studio@renegaderecords.com',
      to: artist.email,
      subject: subject || `Renegade Records — Let's Work Together`,
      text: body
    })

    await supabase
      .from('artists')
      .update({ status: 'contacted', contacted_at: new Date().toISOString() })
      .eq('id', artist_id)

    res.json({ success: true })
  } catch (err) {
    res.status(500).json({ error: err.message })
  }
})

// GET /api/stats — dashboard summary numbers
app.get('/api/stats', async (req, res) => {
  try {
    const { data } = await supabase.from('artists').select('status, score, contact_quality')
    const active = data.filter(a => a.contact_quality !== 'skip')
    const total = active.length
    const contacted = active.filter(a => a.status === 'contacted').length
    const pitched = active.filter(a => a.status === 'pitched').length
    const signed = active.filter(a => a.status === 'signed').length
    const avg_score = total > 0
      ? Math.round(active.reduce((s, a) => s + (a.score || 0), 0) / total)
      : 0
    res.json({ total, contacted, pitched, signed, avg_score })
  } catch (err) {
    res.status(500).json({ error: err.message })
  }
})


// GET /api/flush/preview — count junk leads that would be deleted
// Junk = (score < 50 OR score is null OR contact_quality = 'skip'/'contactless') AND status = 'new'
// Never touches leads that have been contacted / pitched / signed.
app.get('/api/flush/preview', async (req, res) => {
  try {
    const { data, error } = await supabase
      .from('artists')
      .select('id, name, score, contact_quality, status, followers')
      .eq('status', 'new')
      .or('score.is.null,score.lt.50,contact_quality.eq.skip,contact_quality.eq.contactless')
    if (error) throw error
    res.json({ count: data.length, leads: data.slice(0, 20) }) // preview first 20
  } catch (err) {
    res.status(500).json({ error: err.message })
  }
})

// DELETE /api/flush — delete all junk new leads
app.delete('/api/flush', async (req, res) => {
  try {
    // Step 1: get IDs to delete — status=new, score<60 or null, skip/contactless
    // score>=60 leads are always protected (Claude-validated)
    const { data: targets, error: fetchErr } = await supabase
      .from('artists')
      .select('id, score')
      .eq('status', 'new')
      .or('contact_quality.eq.skip,contact_quality.eq.contactless,score.lt.60,score.is.null')
      .not('score', 'gte', 60)
    if (fetchErr) throw fetchErr
    if (!targets.length) return res.json({ deleted: 0, message: 'Nothing to flush' })

    const ids = targets.map(t => t.id)

    // Step 2: delete in batches of 100 (Supabase in-filter limit)
    let deleted = 0
    for (let i = 0; i < ids.length; i += 100) {
      const batch = ids.slice(i, i + 100)
      const { error: delErr } = await supabase
        .from('artists')
        .delete()
        .in('id', batch)
      if (delErr) throw delErr
      deleted += batch.length
    }

    res.json({ deleted, message: `Flushed ${deleted} junk leads` })
  } catch (err) {
    res.status(500).json({ error: err.message })
  }
})

// Merge resolve.py result with existing artist data.
// All contact fields fall back to whatever was in the DB — a failed re-scan
// never wipes a valid stored contact. Quality is re-derived from merged data.
function buildContactUpdates(result, artist) {
  const updates = {
    instagram:    result.instagram    || artist.instagram    || null,
    facebook:     result.facebook     || artist.facebook     || null,
    phone:        result.phone        || artist.phone        || null,
    email:        result.email        || artist.email        || null,
    ig_followers: result.ig_followers || artist.ig_followers || null,
    updated_at:   new Date().toISOString()
  }
  // Never let a partial re-scan downgrade quality — derive from what we actually have
  if (result.contact_quality === 'skip') {
    updates.contact_quality = 'skip'
  } else if (updates.instagram && updates.email) {
    updates.contact_quality = 'excellent'
  } else if (updates.instagram) {
    updates.contact_quality = 'good'
  } else if (updates.email) {
    updates.contact_quality = 'email_only'
  } else if (updates.facebook || updates.phone) {
    updates.contact_quality = 'limited'
  } else {
    updates.contact_quality = 'contactless'
  }
  return updates
}

// POST /api/artists/batch — mass status update or delete
app.post('/api/artists/batch', async (req, res) => {
  try {
    const { ids, action, status } = req.body
    if (!ids || !Array.isArray(ids) || ids.length === 0)
      return res.status(400).json({ error: 'ids array required' })

    if (action === 'delete') {
      for (let i = 0; i < ids.length; i += 100) {
        const { error } = await supabase.from('artists').update({ contact_quality: 'skip', updated_at: new Date().toISOString() }).in('id', ids.slice(i, i + 100))
        if (error) throw error
      }
      return res.json({ success: true, flagged: ids.length })
    }

    if (action === 'status' && status) {
      const valid = ['contacted', 'pitched', 'signed', 'ignored', 'new']
      if (!valid.includes(status)) return res.status(400).json({ error: 'Invalid status' })
      const updates = { status, updated_at: new Date().toISOString() }
      for (let i = 0; i < ids.length; i += 100) {
        const { error } = await supabase.from('artists').update(updates).in('id', ids.slice(i, i + 100))
        if (error) throw error
      }
      return res.json({ success: true, updated: ids.length })
    }

    res.status(400).json({ error: 'Invalid action — use action="delete" or action="status"' })
  } catch (err) {
    res.status(500).json({ error: err.message })
  }
})

// POST /api/enrich/batch-selected — queue enrichment for a specific set of artist IDs
// Resets their contact_quality to 'none' so the background worker picks them up next.
app.post('/api/enrich/batch-selected', async (req, res) => {
  try {
    const { ids } = req.body
    if (!ids || !Array.isArray(ids) || ids.length === 0)
      return res.status(400).json({ error: 'ids array required' })

    let queued = 0
    for (let i = 0; i < ids.length; i += 100) {
      const batch = ids.slice(i, i + 100)
      const { error } = await supabase
        .from('artists')
        .update({ contact_quality: 'none', updated_at: new Date().toISOString() })
        .in('id', batch)
      if (error) throw error
      queued += batch.length
    }

    console.log(`[BatchEnrich] Reset ${queued} artists — enrich worker will pick them up`)
    if (!_enrichBusy) setTimeout(autoEnrichWorker, 100)
    res.json({ success: true, queued })
  } catch (err) {
    res.status(500).json({ error: err.message })
  }
})

// POST /api/artists/rescan-all — wipe all contact data for every 'new' lead and re-enrich from scratch.
// Clears instagram, ig_followers, listeners, email, phone, facebook so the worker does fresh searches.
// Never touches contacted / pitched / signed artists.
app.post('/api/artists/rescan-all', async (req, res) => {
  try {
    const { data, error } = await supabase
      .from('artists')
      .update({
        instagram:       null,
        facebook:        null,
        phone:           null,
        email:           null,
        ig_followers:    null,
        contact_quality: 'none',
        updated_at:      new Date().toISOString()
      })
      .eq('status', 'new')
      .select('id')
    if (error) throw error
    const count = data?.length || 0
    console.log(`[RescanAll] Reset ${count} leads — enrich worker will re-enrich`)
    if (!_enrichBusy) setTimeout(autoEnrichWorker, 100)
    res.json({ success: true, reset: count })
  } catch (err) {
    res.status(500).json({ error: err.message })
  }
})

// POST /api/artists/scan-bios — scan visible leads and DELETE:
//   • producers / DJs (username, IG bio, Spotify bio)
//   • bios that block cold outreach ("no dms", "bookings only", "signed to X", etc.)
//   • private accounts with no email (unreachable — DMs require follow-back)
let _bioScanStats = { total: 0, processed: 0, flagged: 0, current: null, running: false }

async function runBioScan(ids) {
  _bioScanStats = { total: ids.length, processed: 0, flagged: 0, current: null, running: true }
  console.log(`[BioScan] Starting scan of ${ids.length} artists`)

  const { data: artists, error } = await supabase.from('artists').select('id,name,instagram,email,profile_url,platform').in('id', ids)
  if (error || !artists) { _bioScanStats.running = false; return }

  for (const artist of artists) {
    _bioScanStats.current = artist.name
    const handle = (artist.instagram || '').trim()
    let flagged = false
    let reason = ''

    // 1. Check username for producer/DJ patterns
    if (handle && isProducerUsername(handle)) {
      flagged = true; reason = 'producer username'
    }

    // 2. Fetch IG page — check bio for producer, outreach blocker, private+no-email
    if (!flagged && handle) {
      try {
        const html = await Promise.race([
          fetchIGPage(handle),
          new Promise(r => setTimeout(() => r(''), 15000))
        ])
        if (html && html.length > 500) {
          const { bio, email: igEmail, isPrivate } = parseIGPage(html)
          // Save email if found and not already stored
          if (igEmail && !artist.email) {
            await supabase.from('artists').update({ email: igEmail }).eq('id', artist.id)
          }
          const hasEmail = !!(igEmail || artist.email)
          if (isProducerText(bio)) {
            flagged = true; reason = 'producer in IG bio'
          } else if (isOutreachBlocked(bio)) {
            flagged = true; reason = 'outreach blocked in IG bio'
          } else if (isPrivate && !hasEmail) {
            flagged = true; reason = 'private account, no email — unreachable'
          }
        }
      } catch {}
    }

    // 3. Fallback: Spotify bio (works even when IG is blocked)
    if (!flagged && artist.profile_url) {
      const spotifyBio = await fetchSpotifyBio(artist.profile_url)
      if (isProducerText(spotifyBio)) {
        flagged = true; reason = 'producer in Spotify bio'
      } else if (isOutreachBlocked(spotifyBio)) {
        flagged = true; reason = 'outreach blocked in Spotify bio'
      }
    }

    if (flagged) {
      await supabase.from('artists').delete().eq('id', artist.id)
      _bioScanStats.flagged++
      console.log(`[BioScan] Deleted ${artist.name} — ${reason}`)
    }
    _bioScanStats.processed++
    await new Promise(r => setTimeout(r, 800))
  }

  _bioScanStats.current = null
  _bioScanStats.running = false
  console.log(`[BioScan] Done — ${_bioScanStats.flagged} removed out of ${ids.length}`)
}

app.post('/api/artists/scan-bios', async (req, res) => {
  try {
    const { ids } = req.body
    if (!Array.isArray(ids) || ids.length === 0) return res.status(400).json({ error: 'ids array required' })
    if (_bioScanStats.running) return res.status(409).json({ error: 'Bio scan already running' })
    runBioScan(ids) // fire and forget
    res.json({ success: true, queued: ids.length })
  } catch (err) {
    res.status(500).json({ error: err.message })
  }
})

app.get('/api/artists/scan-bios/status', (req, res) => {
  res.json(_bioScanStats)
})

// POST /api/enrich/retry-contactless — reset all contactless artists so worker re-processes them
app.post('/api/enrich/retry-contactless', async (req, res) => {
  try {
    const { data, error } = await supabase
      .from('artists')
      .update({ contact_quality: 'none', updated_at: new Date().toISOString() })
      .eq('contact_quality', 'contactless')
      .select('id')
    if (error) throw error
    const count = data?.length || 0
    console.log(`[RetryContactless] Reset ${count} contactless artists for re-enrichment`)
    if (!_enrichBusy) setTimeout(autoEnrichWorker, 100)
    res.json({ success: true, reset: count })
  } catch (err) {
    res.status(500).json({ error: err.message })
  }
})

// ── V2 BATCH SCAN WORKER ──────────────────────────────────────────────────────
// Runs enrich_v3.py (Playwright + Claude) on a specific session batch.
// Runs enrich_v3.py on a specific session batch.

let _v2Queue  = []   // { id, name, platform, profile_url }
let _v2Busy   = false
let _v2Stats  = { total: 0, processed: 0, found: 0, session_id: null }

// POST /api/enrich/scan-batch — queue all leads in a session through enrich_v2
app.post('/api/enrich/scan-batch', async (req, res) => {
  try {
    const { session_id } = req.body
    if (!session_id) return res.status(400).json({ error: 'session_id required' })

    // Fetch ALL leads in this session
    const { data, error } = await supabase
      .from('artists')
      .select('id, name, platform, profile_url, contact_quality, status')
      .eq('session_id', session_id)

    if (error) throw error

    const allLeads = data || []
    const PROTECTED = ['contacted', 'pitched', 'signed']
    const eligible = allLeads.filter(a => !PROTECTED.includes(a.status))
    const skipped  = allLeads.filter(a => a.contact_quality === 'skip').length
    const protected_ = allLeads.filter(a => PROTECTED.includes(a.status)).length

    console.log(`[V2Scan] session="${session_id}" total=${allLeads.length} eligible=${eligible.length} skip=${skipped} protected=${protected_}`)
    if (allLeads.length > 0) {
      const sample = allLeads.slice(0, 3).map(a => `${a.name}(cq=${a.contact_quality},st=${a.status})`).join(', ')
      console.log(`[V2Scan] sample: ${sample}`)
    }

    if (!eligible.length) {
      const total = allLeads.length
      const msg = total === 0
        ? `No leads found in DB for session "${session_id}" — session ID mismatch?`
        : `All ${total} leads are protected (contacted/pitched/signed = ${protected_})`
      return res.json({ success: true, queued: 0, message: msg })
    }

    // Reset contact data so v2 does a full fresh scan
    const ids = eligible.map(a => a.id)
    for (let i = 0; i < ids.length; i += 100) {
      await supabase.from('artists').update({
        instagram: null, ig_followers: null, email: null, facebook: null,
        contact_quality: 'none', updated_at: new Date().toISOString()
      }).in('id', ids.slice(i, i + 100))
    }

    _v2Queue = eligible.map(a => ({ id: a.id, name: a.name, platform: a.platform || 'spotify', profile_url: a.profile_url || '' }))
    _v2Stats = { total: _v2Queue.length, processed: 0, found: 0, session_id }

    console.log(`[V2Scan] Queued ${_v2Queue.length} leads from batch ${session_id}`)
    if (!_v2Busy) setTimeout(v2BatchWorker, 200)

    res.json({ success: true, queued: _v2Queue.length })
  } catch (err) {
    res.status(500).json({ error: err.message })
  }
})

// GET /api/enrich/v2-status — progress for the v2 batch scan
app.get('/api/enrich/v2-status', (req, res) => {
  res.json({
    busy:      _v2Busy,
    ..._v2Stats,
    remaining: _v2Queue.length,
  })
})

async function v2BatchWorker () {
  if (_v2Busy) return
  if (_v2Queue.length === 0) { _v2Busy = false; return }

  _v2Busy = true
  const artist = _v2Queue.shift()
  console.log(`[V2Scan] -> ${artist.name} (${_v2Queue.length} remaining)`)

  try { await supabase.from('artists').update({ contact_quality: 'searching' }).eq('id', artist.id) } catch {}

  const v2Path = path.join(__dirname, '../discovery/enrich_v3.py')
  const args   = [v2Path, '--json', '--name', artist.name, '--platform', artist.platform]
  if (artist.profile_url) args.push('--profile-url', artist.profile_url)

  await new Promise((done) => {
    const py = spawn(PYTHON_CMD, args)
    let stdout = '', stderr = ''
    const killTimer = setTimeout(() => { py.kill() }, 180000)  // 3 min timeout for Playwright

    py.stdout.on('data', d => { stdout += d })
    py.stderr.on('data', d => {
      stderr += d
      // Stream v2 log lines to our console so we can see progress
      const lines = d.toString().split('\n').filter(l => l.trim())
      lines.forEach(l => console.log(`  [V2] ${l}`))
    })

    py.on('close', async () => {
      clearTimeout(killTimer)

      let result = null
      for (const line of stdout.split('\n').reverse()) {
        try { result = JSON.parse(line.trim()); break } catch {}
      }

      _v2Stats.processed++

      if (!result) {
        console.error(`[V2Scan] Parse failed for ${artist.name}`)
        try { await supabase.from('artists').update({ contact_quality: 'contactless' }).eq('id', artist.id) } catch {}
        done(); return
      }

      if (result.skip) {
        console.log(`[V2Scan] Flag ${artist.name}: ${result.skip_reason}`)
        await supabase.from('artists').update({ contact_quality: 'skip', updated_at: new Date().toISOString() }).eq('id', artist.id)
        done(); return
      }

      // Fetch existing artist data to merge (never wipe a valid contact)
      const { data: existing } = await supabase.from('artists').select('*').eq('id', artist.id).single()
      const updates = buildContactUpdates(result, existing || {})
      if (result.tiktok && !updates.tiktok) updates.tiktok = result.tiktok

      if (updates.instagram) {
        _v2Stats.found++
        console.log(`[V2Scan] Found @${updates.instagram} for ${artist.name} via [${(result.sources||[]).join(', ')}]`)
      } else {
        console.log(`[V2Scan] No contact for ${artist.name}`)
      }

      try { await supabase.from('artists').update(updates).eq('id', artist.id) } catch (e) {
        console.error(`[V2Scan] Save failed: ${e.message}`)
      }

      done()
    })

    py.on('error', err => { clearTimeout(killTimer); console.error(`[V2Scan] Spawn error: ${err.message}`); done() })
  })

  _v2Busy = false

  if (_v2Queue.length > 0) {
    const delay = Math.floor(Math.random() * 2000) + 1500  // 1.5-3.5s between artists
    setTimeout(v2BatchWorker, delay)
  } else {
    console.log(`[V2Scan] Batch complete — ${_v2Stats.found}/${_v2Stats.processed} contacts found`)
    _v2Stats.session_id = null
  }
}

// ── AUTO ENRICH WORKER ────────────────────────────────────────────────────────
// Picks up leads with contact_quality='none'/null and runs enrich_v3.py on them.

let _enrichBusy  = false
let _enrichStats = { total: 0, processed: 0, found: 0, current: null, remaining: 0 }

async function autoEnrichWorker () {
  if (_enrichBusy) return
  _enrichBusy = true

  while (true) {
    const { data: candidates, error } = await supabase
      .from('artists')
      .select('id, name, platform, profile_url')
      .or('contact_quality.is.null,contact_quality.eq.none')
      .not('status', 'eq', 'ignored')
      .order('discovered_at', { ascending: false })
      .limit(1)

    if (error || !candidates?.length) break

    const artist = candidates[0]
    _enrichStats.current = artist.name

    // Count remaining for status reporting
    const { count } = await supabase
      .from('artists')
      .select('id', { count: 'exact', head: true })
      .or('contact_quality.is.null,contact_quality.eq.none')
      .not('status', 'eq', 'ignored')
    _enrichStats.remaining = count || 0

    console.log(`[Enrich] -> ${artist.name} (${_enrichStats.remaining} remaining)`)
    await supabase.from('artists').update({ contact_quality: 'searching', updated_at: new Date().toISOString() }).eq('id', artist.id)

    const v3Path = path.join(__dirname, '../discovery/enrich_v3.py')
    const args = [v3Path, '--json', '--name', artist.name, '--platform', artist.platform || 'spotify']
    if (artist.profile_url) args.push('--profile-url', artist.profile_url)

    await new Promise((done) => {
      const py = spawn(PYTHON_CMD, args)
      let stdout = '', stderr = ''
      const killTimer = setTimeout(() => { py.kill() }, 120000)

      py.stdout.on('data', d => { stdout += d })
      py.stderr.on('data', d => {
        stderr += d
        d.toString().split('\n').filter(l => l.trim()).forEach(l => console.log(`  [enrich_v3] ${l}`))
      })

      py.on('close', async () => {
        clearTimeout(killTimer)
        _enrichStats.processed++

        let result = null
        for (const line of stdout.split('\n').reverse()) {
          try { result = JSON.parse(line.trim()); break } catch {}
        }

        if (!result) {
          console.error(`[Enrich] Parse failed for ${artist.name}`)
          await supabase.from('artists').update({ contact_quality: 'contactless', updated_at: new Date().toISOString() }).eq('id', artist.id)
          done(); return
        }

        if (result.skip) {
          console.log(`[Enrich] Flag ${artist.name}: ${result.skip_reason}`)
          await supabase.from('artists').update({ contact_quality: 'skip', updated_at: new Date().toISOString() }).eq('id', artist.id)
          done(); return
        }

        const updates = {
          instagram:    result.instagram    || null,
          email:        result.email        || null,
          ig_followers: result.ig_followers || null,
          updated_at:   new Date().toISOString()
        }
        if (updates.instagram) {
          console.log(`[Enrich] Verifying @${updates.instagram} for ${artist.name}...`)
          const igHtml = await Promise.race([
            fetchIGPage(updates.instagram),
            new Promise(r => setTimeout(() => r(''), 15000))
          ])
          const { followers, bio } = parseIGPage(igHtml)

          if (followers !== null) updates.ig_followers = followers

          if (!igHtml || igHtml.length < 500) {
            // IG blocked — trust the found handle
            updates.contact_quality = 'verified'
            console.log(`[Enrich] ✓ ${artist.name} → @${updates.instagram} (IG blocked, trusted)`)
          } else if (followers !== null && followers > 500000) {
            updates.contact_quality = 'skip'
            console.log(`[Enrich] Flag ${artist.name} — IG too large (${followers.toLocaleString()} followers)`)
          } else if (bio && IG_PRODUCER_KEYWORDS.some(kw => bio.includes(kw))) {
            updates.contact_quality = 'skip'
            console.log(`[Enrich] Flag ${artist.name} — producer detected in IG bio`)
          } else {
            updates.contact_quality = 'verified'
            _enrichStats.found++
            console.log(`[Enrich] ✓ ${artist.name} → @${updates.instagram} (${followers?.toLocaleString() ?? '?'} followers)`)
          }
        } else if (updates.email) {
          updates.contact_quality = 'email_only'
          console.log(`[Enrich] ✓ ${artist.name} — email only`)
        } else {
          updates.contact_quality = 'contactless'
          console.log(`[Enrich] ✗ ${artist.name} — no contact found`)
        }

        await supabase.from('artists').update(updates).eq('id', artist.id)
        done()
      })

      py.on('error', async (err) => {
        clearTimeout(killTimer)
        console.error(`[Enrich] Spawn error for ${artist.name}: ${err.message}`)
        await supabase.from('artists').update({ contact_quality: 'contactless', updated_at: new Date().toISOString() }).eq('id', artist.id)
        _enrichStats.processed++
        done()
      })
    })

    _enrichStats.current = null
    // Small gap between artists to avoid rate limits
    await new Promise(r => setTimeout(r, 2000))
  }

  _enrichStats.current = null
  _enrichStats.remaining = 0
  _enrichBusy = false

  // Re-check in 10 minutes in case new leads were added
  setTimeout(() => { if (!_enrichBusy) autoEnrichWorker() }, 10 * 60 * 1000)
}

// Detect python command name once at startup
let PYTHON_CMD = 'python'
;(async () => {
  for (const cmd of ['python', 'python3']) {
    const ok = await new Promise(res => {
      const p = spawn(cmd, ['--version'])
      p.on('close', code => res(code === 0))
      p.on('error', () => res(false))
    })
    if (ok) { PYTHON_CMD = cmd; console.log(`[Python] Using: ${cmd}`); break }
  }
})()

async function resetStuckArtists () {
  // Reset artists stuck in 'searching' from a crashed enrich worker
  const { data: stuckSearching } = await supabase
    .from('artists')
    .select('id')
    .eq('contact_quality', 'searching')
  if (stuckSearching?.length) {
    await supabase.from('artists').update({ contact_quality: 'none', updated_at: new Date().toISOString() })
      .in('id', stuckSearching.map(a => a.id))
    console.log(`[Enrich] Reset ${stuckSearching.length} stuck 'searching' leads to 'none'`)
  }

  // Reset any leads stuck in 'verifying' — enrich worker will re-process them fresh
  const { data: stuckVerifying } = await supabase
    .from('artists')
    .select('id')
    .eq('contact_quality', 'verifying')
  if (stuckVerifying?.length) {
    await supabase.from('artists').update({ contact_quality: 'none', updated_at: new Date().toISOString() })
      .in('id', stuckVerifying.map(a => a.id))
    console.log(`[Enrich] Reset ${stuckVerifying.length} stuck 'verifying' leads to 'none'`)
  }
}

// Flag junk leads with contact_quality='skip' instead of deleting — user reviews via Flush Junk.
async function autoFlushJunk () {
  const flagIds = async (ids, label) => {
    for (let i = 0; i < ids.length; i += 100) {
      await supabase.from('artists').update({ contact_quality: 'skip', updated_at: new Date().toISOString() }).in('id', ids.slice(i, i + 100))
    }
    console.log(`[AutoFlush] Flagged ${ids.length} ${label}`)
  }

  // 1. Flag established artists (> 100k followers, IG followers, or monthly listeners)
  try {
    const { data, error } = await supabase
      .from('artists')
      .select('id, name, followers, ig_followers, listeners')
      .eq('status', 'new')
      .not('contact_quality', 'in', '("skip","verified","verifying")')
      .or('followers.gt.100000,ig_followers.gt.100000,listeners.gt.100000')
    if (!error && data?.length) {
      await flagIds(data.map(t => t.id), `established artists (100K+): ${data.map(t => t.name).join(', ')}`)
    }
  } catch (err) {
    console.error('[AutoFlush] Followers flush error:', err.message)
  }

  // 1b. Flag blocked-region artists
  try {
    const BLOCKED_REGION_SIGNALS = [
      'pakistan','pakistani','india','indian','hindi','urdu','bollywood',
      'karachi','lahore','islamabad','mumbai','delhi','kolkata','rawalpindi',
      'indonesia','indonesian','philippines','filipino',
      'mexico','mexican','korea','korean','japan','japanese','china','chinese',
    ]
    const { data: allNew, error } = await supabase
      .from('artists')
      .select('id, name, needs, genres')
      .eq('status', 'new')
      .not('contact_quality', 'in', '("skip","verified","verifying")')
    if (!error && allNew?.length) {
      const blockedIds = allNew
        .filter(a => {
          const text = ((a.needs || '') + ' ' + (a.genres || '')).toLowerCase()
          return BLOCKED_REGION_SIGNALS.some(sig => text.includes(sig))
        })
        .map(a => a.id)
      if (blockedIds.length) {
        await flagIds(blockedIds, `blocked-region artists`)
      }
    }
  } catch (err) {
    console.error('[AutoFlush] Region flush error:', err.message)
  }

  // 3. Flag producer names
  const PRODUCER_NAME_PATTERNS = [
    'prod.', 'prod by', 'prodby', 'prod_by', 'beatz', 'beatmaker', 'beat maker',
    'type beat', 'on the beat', 'the producer', 'tha producer', 'producer',
  ]
  try {
    const { data, error } = await supabase
      .from('artists')
      .select('id, name')
      .eq('status', 'new')
      .not('contact_quality', 'in', '("skip","verified","verifying")')
    if (!error && data?.length) {
      const producerIds = data
        .filter(a => PRODUCER_NAME_PATTERNS.some(p => a.name.toLowerCase().includes(p)))
        .map(a => a.id)
      if (producerIds.length) await flagIds(producerIds, `producer-named artists`)
    }
  } catch (err) {
    console.error('[AutoFlush] Producer name flush error:', err.message)
  }

}

// POST /api/enrich/:id — run reverse search for one artist from the dashboard
// MUST be defined after all named /api/enrich/... routes so Express doesn't
// swallow scan-batch, pause, resume etc. as the :id wildcard.
app.post('/api/enrich/:id', async (req, res) => {
  try {
    const { data: artist, error } = await supabase
      .from('artists').select('*').eq('id', req.params.id).single()
    if (error || !artist) return res.status(404).json({ error: 'Artist not found' })

    if (artist.contact_quality === 'searching') {
      return res.json({ success: false, error: 'Already being searched by background worker — check back in a moment' })
    }

    const v2Path = path.join(__dirname, '../discovery/enrich_v3.py')
    const args = [
      v2Path, '--json',
      '--name', artist.name,
      '--platform', artist.platform || ''
    ]
    if (artist.profile_url) args.push('--profile-url', artist.profile_url)

    const py = spawn(PYTHON_CMD, args)
    let stdout = '', stderr = '', responded = false

    const killTimer = setTimeout(() => {
      if (!responded) {
        py.kill()
        responded = true
        res.status(500).json({ error: 'Contact search timed out after 150s' })
      }
    }, 150000)

    py.stdout.on('data', d => { stdout += d })
    py.stderr.on('data', d => { stderr += d })

    py.on('close', async (code) => {
      clearTimeout(killTimer)
      if (responded) return
      responded = true

      let result = null
      for (const line of stdout.split('\n').reverse()) {
        try { result = JSON.parse(line.trim()); break } catch {}
      }
      if (!result) {
        console.error('enrich_v3.py stderr:', stderr.slice(0, 500))
        return res.status(500).json({ error: 'Could not parse enrichment result', stderr: stderr.slice(0, 200) })
      }

      if (result.skip) {
        console.log(`[AutoFlush] Flag ${artist.name}: ${result.skip_reason}`)
        await supabase.from('artists').update({ contact_quality: 'skip', updated_at: new Date().toISOString() }).eq('id', req.params.id)
        return res.json({ success: true, flagged: true, reason: result.skip_reason })
      }

      const updates = {
        instagram:    result.instagram    || null,
        email:        result.email        || null,
        ig_followers: result.ig_followers || null,
        updated_at:   new Date().toISOString()
      }
      if (updates.instagram && updates.email) updates.contact_quality = 'excellent'
      else if (updates.instagram)             updates.contact_quality = 'good'
      else if (updates.email)                 updates.contact_quality = 'email_only'
      else                                    updates.contact_quality = 'contactless'

      let { data: saved, error: saveErr } = await supabase
        .from('artists')
        .update(updates)
        .eq('id', req.params.id)
        .select()
        .single()

      if (saveErr && saveErr.message.includes('schema cache')) {
        const safeUpdates = { ...updates }
        for (const col of ['contact_quality', 'ig_followers']) {
          if (saveErr.message.includes(col)) delete safeUpdates[col]
        }
        const retry = await supabase
          .from('artists')
          .update(safeUpdates)
          .eq('id', req.params.id)
          .select()
          .single()
        saved   = retry.data
        saveErr = retry.error
        if (!saveErr) console.warn('[enrich] Saved contacts without missing columns — run schema migration in Supabase')
      }

      if (saveErr) {
        console.error('[enrich] Supabase save failed:', saveErr.message)
        return res.json({ success: true, contacts: updates, save_warning: saveErr.message })
      }

      res.json({ success: true, contacts: saved })
    })

    py.on('error', err => {
      clearTimeout(killTimer)
      if (!responded) {
        responded = true
        res.status(500).json({ error: `Python error: ${err.message}` })
      }
    })
  } catch (err) {
    res.status(500).json({ error: err.message })
  }
})

// ── Discovery process state — survives client disconnects ────────────────────
let _discovery = {
  running: false,
  py: null,
  log: [],       // full log history so reconnecting clients catch up
  progress: 0,
  clients: [],   // active SSE response objects
}

function discoveryBroadcast(obj) {
  const line = JSON.stringify(obj) + "\n"
  _discovery.clients = _discovery.clients.filter(r => !r.writableEnded)
  _discovery.clients.forEach(r => { try { r.write(line) } catch {} })
}

// POST /api/discovery/run — start discovery or reconnect to running one
app.post('/api/discovery/run', (req, res) => {
  res.setHeader('Content-Type', 'application/x-ndjson')
  res.setHeader('Transfer-Encoding', 'chunked')
  res.setHeader('Cache-Control', 'no-cache')

  // If already running, replay log history then subscribe to live updates
  if (_discovery.running) {
    _discovery.log.forEach(obj => { try { res.write(JSON.stringify(obj) + "\n") } catch {} })
    _discovery.clients.push(res)
    req.on('close', () => { _discovery.clients = _discovery.clients.filter(r => r !== res) })
    return
  }

  // Start fresh discovery process
  _discovery = { running: true, py: null, log: [], progress: 0, clients: [res] }

  const discoveryPath = path.join(__dirname, '../discovery/discovery.py')
  const py = spawn('python', [discoveryPath, '--no-prompt'], {
    cwd: path.join(__dirname, '../discovery')
  })
  _discovery.py = py

  const emit = obj => {
    _discovery.log.push(obj)
    discoveryBroadcast(obj)
  }

  let lineBuffer = ""
  py.stdout.on('data', chunk => {
    lineBuffer += chunk.toString()
    const lines = lineBuffer.split('\n')
    lineBuffer = lines.pop()
    for (const line of lines) {
      if (!line.trim()) continue
      const logObj = { log: line }
      const m = line.match(/Lead #(\d+)\/(\d+)/)
      if (m) {
        _discovery.progress = Math.round((parseInt(m[1]) / parseInt(m[2])) * 90)
        logObj.progress = _discovery.progress
      }
      if (line.includes('DISCOVERY COMPLETE') || line.includes('Leads are live')) {
        _discovery.progress = 100
        logObj.progress = 100
      }
      emit(logObj)
    }
  })

  py.stderr.on('data', chunk => {
    for (const line of chunk.toString().split('\n')) {
      if (line.trim()) emit({ log: `[err] ${line}` })
    }
  })

  py.on('close', () => {
    const final = { progress: 100, done: true, log: '=== Discovery finished ===' }
    emit(final)
    _discovery.running = false
    _discovery.py = null
    _discovery.clients.forEach(r => { try { r.end() } catch {} })
    _discovery.clients = []
  })

  py.on('error', err => {
    emit({ log: `ERROR: ${err.message}`, done: true })
    _discovery.running = false
    _discovery.clients.forEach(r => { try { r.end() } catch {} })
    _discovery.clients = []
  })

  // Client disconnect — remove from list but DON'T kill the process
  req.on('close', () => { _discovery.clients = _discovery.clients.filter(r => r !== res) })
})

// GET /api/discovery/status — lets dashboard check if discovery is still running on reconnect
app.get('/api/discovery/status', (req, res) => {
  res.json({ running: _discovery.running, progress: _discovery.progress, logLines: _discovery.log.length })
})

// ── Instagram Discovery ────────────────────────────────────────────────────────
let _igDiscovery = { running: false, py: null, log: [], progress: 0, clients: [] }

function igDiscoveryBroadcast(obj) {
  const line = JSON.stringify(obj) + "\n"
  _igDiscovery.clients = _igDiscovery.clients.filter(r => !r.writableEnded)
  _igDiscovery.clients.forEach(r => { try { r.write(line) } catch {} })
}

app.post('/api/insta-discover', (req, res) => {
  res.setHeader('Content-Type', 'application/x-ndjson')
  res.setHeader('Transfer-Encoding', 'chunked')
  res.setHeader('Cache-Control', 'no-cache')

  if (_igDiscovery.running) {
    _igDiscovery.log.forEach(obj => { try { res.write(JSON.stringify(obj) + "\n") } catch {} })
    _igDiscovery.clients.push(res)
    req.on('close', () => { _igDiscovery.clients = _igDiscovery.clients.filter(r => r !== res) })
    return
  }

  _igDiscovery = { running: true, py: null, log: [], progress: 0, clients: [res] }

  const scriptPath = path.join(__dirname, '../discovery/insta_discovery.py')
  const py = spawn('python', [scriptPath, '--no-prompt'], { cwd: path.join(__dirname, '../discovery') })
  _igDiscovery.py = py

  const emit = obj => { _igDiscovery.log.push(obj); igDiscoveryBroadcast(obj) }

  let lineBuffer = ""
  py.stdout.on('data', chunk => {
    lineBuffer += chunk.toString()
    const lines = lineBuffer.split('\n')
    lineBuffer = lines.pop()
    for (const line of lines) {
      if (!line.trim()) continue
      const logObj = { log: line }
      if (line.includes('complete')) { logObj.progress = 100 }
      emit(logObj)
    }
  })

  py.stderr.on('data', chunk => {
    for (const line of chunk.toString().split('\n')) {
      if (line.trim()) emit({ log: `[err] ${line}` })
    }
  })

  py.on('close', () => {
    emit({ progress: 100, done: true, log: '=== Instagram Discovery finished ===' })
    _igDiscovery.running = false
    _igDiscovery.py = null
    _igDiscovery.clients.forEach(r => { try { r.end() } catch {} })
    _igDiscovery.clients = []
  })

  py.on('error', err => {
    emit({ log: `ERROR: ${err.message}`, done: true })
    _igDiscovery.running = false
    _igDiscovery.clients.forEach(r => { try { r.end() } catch {} })
    _igDiscovery.clients = []
  })

  req.on('close', () => { _igDiscovery.clients = _igDiscovery.clients.filter(r => r !== res) })
})

app.get('/api/insta-discover/status', (req, res) => {
  res.json({ running: _igDiscovery.running, progress: _igDiscovery.progress, logLines: _igDiscovery.log.length })
})

let _contentDiscovery = { running: false, py: null, log: [], progress: 0, clients: [] }

function contentDiscoveryBroadcast(obj) {
  const line = JSON.stringify(obj) + "\n"
  _contentDiscovery.clients = _contentDiscovery.clients.filter(r => !r.writableEnded)
  _contentDiscovery.clients.forEach(r => { try { r.write(line) } catch {} })
}

app.post('/api/content-discover', (req, res) => {
  res.setHeader('Content-Type', 'application/x-ndjson')
  res.setHeader('Transfer-Encoding', 'chunked')
  res.setHeader('Cache-Control', 'no-cache')

  if (_contentDiscovery.running) {
    _contentDiscovery.log.forEach(obj => { try { res.write(JSON.stringify(obj) + "\n") } catch {} })
    _contentDiscovery.clients.push(res)
    req.on('close', () => { _contentDiscovery.clients = _contentDiscovery.clients.filter(r => r !== res) })
    return
  }

  _contentDiscovery = { running: true, py: null, log: [], progress: 0, clients: [res] }

  const scriptPath = path.join(__dirname, '../discovery/content_discovery.py')
  const py = spawn('python', [scriptPath, '--no-prompt'], { cwd: path.join(__dirname, '../discovery') })
  _contentDiscovery.py = py

  const emit = obj => { _contentDiscovery.log.push(obj); contentDiscoveryBroadcast(obj) }

  let lineBuffer = ""
  py.stdout.on('data', chunk => {
    lineBuffer += chunk.toString()
    const lines = lineBuffer.split('\n')
    lineBuffer = lines.pop()
    for (const line of lines) {
      if (!line.trim()) continue
      const logObj = { log: line }
      if (line.includes('complete')) { logObj.progress = 100 }
      emit(logObj)
    }
  })

  py.stderr.on('data', chunk => {
    for (const line of chunk.toString().split('\n')) {
      if (line.trim()) emit({ log: `[err] ${line}` })
    }
  })

  py.on('close', () => {
    emit({ progress: 100, done: true, log: '=== Creator Discovery finished ===' })
    _contentDiscovery.running = false
    _contentDiscovery.py = null
    _contentDiscovery.clients.forEach(r => { try { r.end() } catch {} })
    _contentDiscovery.clients = []
  })

  py.on('error', err => {
    emit({ log: `ERROR: ${err.message}`, done: true })
    _contentDiscovery.running = false
    _contentDiscovery.clients.forEach(r => { try { r.end() } catch {} })
    _contentDiscovery.clients = []
  })

  req.on('close', () => { _contentDiscovery.clients = _contentDiscovery.clients.filter(r => r !== res) })
})

app.get('/api/content-discover/status', (req, res) => {
  res.json({ running: _contentDiscovery.running, progress: _contentDiscovery.progress, logLines: _contentDiscovery.log.length })
})

// GET /api/verify-status
app.get('/api/verify-status', (req, res) => {
  res.json({
    busy:      _verifyBusy,
    queue:     _verifyQueue.length,
    total:     _verifyStats.total,
    processed: _verifyStats.processed,
    verified:  _verifyStats.verified,
    flagged:   _verifyStats.flagged,
    current:   _verifyStats.current
  })
})

// GET /api/enrich/status — background worker progress
app.get('/api/enrich/status', (req, res) => {
  res.json({ busy: _enrichBusy, ..._enrichStats })
})

// POST /api/import-instagram — import artists found via Instagram (no Spotify required)
// Accepts { artists: [ { name, instagram, instagram_url, spotify_url, notes } ] }
app.post('/api/import-instagram', async (req, res) => {
  try {
    const body = req.body
    const list = Array.isArray(body) ? body : (body.artists || body.entries || [])
    if (!list.length) return res.status(400).json({ error: 'No artists found in payload' })

    let saved = 0, skipped = 0, queued = 0
    const toQueue = []

    for (const entry of list) {
      const name = (entry.name || '').trim()
      const ig   = (entry.instagram || '').replace(/^@/, '').trim()
      if (!name || !ig) { skipped++; continue }

      const spotifyUrl = entry.spotify_url || entry.profile_url || ''
      const spotifyM   = spotifyUrl.match(/open\.spotify\.com\/artist\/([A-Za-z0-9]+)/)
      const platform    = spotifyM ? 'spotify'   : 'instagram'
      const platform_id = spotifyM ? spotifyM[1] : ig

      const payload = {
        name,
        platform,
        platform_id,
        profile_url:     spotifyUrl || `https://instagram.com/${ig}`,
        instagram:       ig,
        contact_quality: 'verifying',
        status:          'new',
        session_id:      'manual_searched',
        notes:           entry.notes || null,
        discovered_at:   new Date().toISOString(),
        updated_at:      new Date().toISOString(),
      }

      const { data, error } = await supabase
        .from('artists')
        .upsert(payload, { onConflict: 'platform,platform_id', ignoreDuplicates: false })
        .select('id, name, instagram')
        .single()

      if (error) { skipped++; continue }
      saved++
      toQueue.push({ id: data.id, handle: ig, name: data.name })
      queued++
    }

    // Queue for IG bio verification
    const alreadyQueued = new Set(_verifyQueue.map(q => q.id))
    for (const item of toQueue) {
      if (!alreadyQueued.has(item.id)) _verifyQueue.push(item)
    }
    _verifyStats.total += queued
    _verifyStats.processed = Math.min(_verifyStats.processed, _verifyStats.total)
    if (!_verifyBusy && _verifyQueue.length > 0) verifyWorker()

    console.log(`[ImportIG] ${saved} saved, ${queued} queued for verification, ${skipped} skipped`)
    res.json({ success: true, saved, skipped, queued })
  } catch (err) {
    res.status(500).json({ error: err.message })
  }
})

// POST /api/sync-instagram-paste — accept JSON array, queue with instagram for IG verification
app.post('/api/sync-instagram-paste', async (req, res) => {
  try {
    const entries = req.body.entries
    if (!Array.isArray(entries)) return res.status(400).json({ error: 'Expected entries array' })

    let updated = 0, skipped = 0, queued = 0
    const toQueue = []

    for (const entry of entries) {
      const spotifyUrl = entry.spotify_url || entry.profile_url || ''
      if (!spotifyUrl) { skipped++; continue }

      const updates = { updated_at: new Date().toISOString() }
      if (entry.instagram) {
        updates.instagram    = entry.instagram
        updates.contact_quality = 'verifying'  // holds here until worker confirms
      } else {
        updates.contact_quality = 'contactless'
      }

      const { data: rows, error } = await supabase
        .from('artists').update(updates).eq('profile_url', spotifyUrl)
        .select('id, name, instagram')
      if (error) { skipped++; continue }
      updated++

      if (entry.instagram && rows?.[0]) {
        toQueue.push({ id: rows[0].id, handle: entry.instagram, name: rows[0].name })
        queued++
      }
    }

    // Add to verify queue (skip duplicates already queued)
    const alreadyQueued = new Set(_verifyQueue.map(q => q.id))
    for (const item of toQueue) {
      if (!alreadyQueued.has(item.id)) _verifyQueue.push(item)
    }
    _verifyStats.total     += queued
    _verifyStats.processed  = Math.min(_verifyStats.processed, _verifyStats.total)

    if (!_verifyBusy && _verifyQueue.length > 0) verifyWorker()

    console.log(`[SyncPaste] ${updated} updated, ${queued} queued for IG verification, ${skipped} skipped`)
    res.json({ success: true, updated, skipped, queued })
  } catch (err) {
    res.status(500).json({ error: err.message })
  }
})

// POST /api/sync-instagram-json — read artists_instagram.json and mark leads verified/contactless
app.post('/api/sync-instagram-json', async (req, res) => {
  try {
    const fs = require('fs')
    const jsonPath = path.join(__dirname, '../discovery/artists_instagram.json')
    const raw = fs.readFileSync(jsonPath, 'utf8')
    const entries = JSON.parse(raw)

    let updated = 0, skipped = 0
    for (const entry of entries) {
      const spotifyUrl = entry.spotify_url || entry.profile_url || ''
      if (!spotifyUrl) { skipped++; continue }

      const updates = { updated_at: new Date().toISOString() }
      if (entry.instagram) {
        updates.instagram = entry.instagram
        updates.contact_quality = 'verified'
      } else {
        updates.contact_quality = 'contactless'
      }

      const { error } = await supabase
        .from('artists')
        .update(updates)
        .eq('profile_url', spotifyUrl)

      if (error) { skipped++; continue }
      updated++
    }

    console.log(`[SyncJSON] ${updated} updated, ${skipped} skipped`)
    res.json({ success: true, updated, skipped, total: entries.length })
  } catch (err) {
    res.status(500).json({ error: err.message })
  }
})

const PORT = process.env.PORT || 4000
app.listen(PORT, async () => {
  console.log(`Renegade API running on port ${PORT}`)
  await resetStuckArtists()
  await autoFlushJunk()
  setInterval(autoFlushJunk, 3 * 60 * 1000)
  setTimeout(autoEnrichWorker, 8000)
})
