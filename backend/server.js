const express = require('express')
const cors = require('cors')
const { createClient } = require('@supabase/supabase-js')
const nodemailer = require('nodemailer')
const { spawn } = require('child_process')
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

const IG_PRODUCER_KEYWORDS = [
  'producer','beat maker','beatmaker','mixing engineer','mastering engineer',
  'audio engineer','sound engineer','fl studio','ableton','logic pro',
  'prod by','beats by','trap producer','rnb producer','hip hop producer',
  'record producer','music producer','executive producer','beatsmith',
  'recording engineer','sound designer','instrumental'
]

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
  // Bio
  let bio = ''
  const bioM = html.match(/"biography"\s*:\s*"((?:[^"\\]|\\.)*)"/)
  if (bioM) bio = bioM[1].replace(/\\n/g, ' ').replace(/\\u[\dA-Fa-f]{4}/g, '').toLowerCase()
  return { followers, bio }
}

async function verifyWorker () {
  if (_verifyBusy || _verifyQueue.length === 0) return
  _verifyBusy = true

  while (_verifyQueue.length > 0) {
    const { id, handle, name } = _verifyQueue.shift()
    _verifyStats.current = name
    console.log(`[Verify] ${name} @${handle} — checking IG...`)

    try {
      const html = await fetchIGPage(handle)
      const { followers, bio } = parseIGPage(html)

      let quality = 'verified'
      const updates = { updated_at: new Date().toISOString() }
      if (followers !== null) updates.ig_followers = followers

      // Instagram blocks most plain fetches — if we got nothing, trust the manually-pasted handle
      if (!html || html.length < 500) {
        quality = 'verified'
        console.log(`[Verify] ${name} @${handle} — IG blocked, trusting manual handle`)
      } else if (followers !== null && followers > 500000) {
        quality = 'skip'
        console.log(`[Verify] ${name} — too large (${followers.toLocaleString()} followers)`)
      } else if (bio && IG_PRODUCER_KEYWORDS.some(kw => bio.includes(kw))) {
        quality = 'skip'
        console.log(`[Verify] ${name} — producer detected in bio`)
      } else {
        console.log(`[Verify] ${name} @${handle} — VERIFIED (${followers?.toLocaleString() ?? '?'} followers)`)
      }

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
    const { status, min_score, max_followers, max_listeners, platform, search, sort_by, sort_dir, session_id, exclude_session_id } = req.query

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
    if (platform)   query = query.eq('platform', platform)
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
  const { profile_url, name: manualName } = req.body
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

  const { data, error } = await supabase.from('artists').upsert({
    name, platform: 'spotify', platform_id,
    profile_url: `https://open.spotify.com/artist/${platform_id}`,
    listeners: listeners || null,
    followers: 0, contact_quality: 'none',
    status: 'new', discovered_at: new Date().toISOString(), updated_at: new Date().toISOString()
  }, { onConflict: 'platform,platform_id' }).select().single()

  if (error) return res.status(500).json({ error: error.message })
  if (!_enrichBusy) setTimeout(autoEnrichWorker, 100)
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
    const { data, error } = await supabase
      .from('artists')
      .select('session_id, discovered_at')
      .not('session_id', 'is', null)
      .order('discovered_at', { ascending: false })
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
    const { data } = await supabase.from('artists').select('status, score')
    const total = data.length
    const contacted = data.filter(a => a.status === 'contacted').length
    const pitched = data.filter(a => a.status === 'pitched').length
    const signed = data.filter(a => a.status === 'signed').length
    const avg_score = total > 0
      ? Math.round(data.reduce((s, a) => s + (a.score || 0), 0) / total)
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
    // Step 1: get IDs to delete (score < 50 OR null OR producer/contactless, only if status=new)
    const { data: targets, error: fetchErr } = await supabase
      .from('artists')
      .select('id')
      .eq('status', 'new')
      .or('score.is.null,score.lt.50,contact_quality.eq.skip,contact_quality.eq.contactless')
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

    // Push selected IDs to the front of the processing line so the worker
    // handles THESE artists next, before any other unenriched leads.
    for (const id of ids) {
      if (!_priorityQueue.includes(id)) _priorityQueue.push(id)
    }

    console.log(`[BatchEnrich] Priority-queued ${queued} artists for enrichment`)
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
    console.log(`[RescanAll] Reset ${count} leads for full re-enrichment`)
    if (!_enrichBusy) setTimeout(autoEnrichWorker, 100)
    res.json({ success: true, reset: count })
  } catch (err) {
    res.status(500).json({ error: err.message })
  }
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
// Runs enrich_v2.py (Playwright + Claude) on a specific session batch.
// Uses the same _enrichStats / _enrichBusy so the dashboard status bar shows progress.

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
  if (_v2Busy || _enrichBusy) {
    // Main worker is running — wait and retry
    if (_enrichBusy) setTimeout(v2BatchWorker, 5000)
    return
  }
  if (_v2Queue.length === 0) { _v2Busy = false; return }

  _v2Busy = true
  const artist = _v2Queue.shift()

  _enrichStats.current   = artist.name
  _enrichStats.remaining = _v2Queue.length
  console.log(`[V2Scan] -> ${artist.name} (${_v2Queue.length} remaining)`)

  try { await supabase.from('artists').update({ contact_quality: 'searching' }).eq('id', artist.id) } catch {}

  const v2Path = path.join(__dirname, '../discovery/enrich_v2.py')
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

  _enrichStats.current = null
  _v2Busy = false

  if (_v2Queue.length > 0) {
    const delay = Math.floor(Math.random() * 2000) + 1500  // 1.5-3.5s between artists
    setTimeout(v2BatchWorker, delay)
  } else {
    console.log(`[V2Scan] Batch complete — ${_v2Stats.found}/${_v2Stats.processed} contacts found`)
    _v2Stats.session_id = null
  }
}

// ── SERPAPI ENRICHMENT WORKER ──────────────────────────────────────────────────
const SERPAPI_KEY = process.env.SERPAPI_KEY || ''
const SERP_JUNK_HANDLES = new Set(['p','explore','reel','reels','stories','tv','accounts','music','login','shoppingcart'])

let _serpBusy    = false
let _serpPaused  = false
let _serpLimited = false  // true when monthly quota hit
let _serpStats   = { total: 0, processed: 0, found: 0, failed: 0, current: null, limited: false }

function serpSearch (artistName) {
  return new Promise((resolve) => {
    const q = encodeURIComponent(`${artistName} site:instagram.com`)
    const path = `/search?engine=google&q=${q}&api_key=${SERPAPI_KEY}&num=5`
    const req = https.get({ hostname: 'serpapi.com', path, timeout: 15000 }, res => {
      let body = ''
      res.on('data', c => { body += c })
      res.on('end', () => {
        try { resolve({ status: res.statusCode, data: JSON.parse(body) }) }
        catch { resolve({ status: res.statusCode, data: {} }) }
      })
    })
    req.on('error', () => resolve({ status: 0, data: {} }))
    req.on('timeout', () => { req.destroy(); resolve({ status: 0, data: {} }) })
  })
}

function extractHandle (data) {
  const results = data.organic_results || []
  for (const item of results) {
    const link = item.link || ''
    const m = link.match(/instagram\.com\/([A-Za-z0-9_.]+)/)
    if (m) {
      const handle = m[1].replace(/\/$/, '')
      if (!SERP_JUNK_HANDLES.has(handle.toLowerCase())) return handle
    }
  }
  return null
}

async function serpWorker () {
  if (_serpBusy || _serpPaused || _serpLimited || !SERPAPI_KEY) return
  _serpBusy = true

  while (true) {
    // Pick next artist with no instagram
    const { data: artists, error } = await supabase
      .from('artists')
      .select('id, name, platform')
      .is('instagram', null)
      .not('contact_quality', 'eq', 'skip')
      .not('contact_quality', 'eq', 'contactless')
      .not('status', 'eq', 'ignored')
      .order('discovered_at', { ascending: false })
      .limit(1)

    if (error || !artists?.length) break

    const artist = artists[0]
    _serpStats.current = artist.name
    console.log(`[Serp] Searching IG for: ${artist.name}`)

    const { status, data } = await serpSearch(artist.name)

    // Hit monthly limit
    if (status === 429 || data?.error?.includes?.('limit') || data?.error?.includes?.('credits')) {
      console.log('[Serp] Monthly limit hit — pausing until reset')
      _serpLimited = true
      _serpStats.limited = true
      _serpStats.current = null
      // Retry in 24 hours
      setTimeout(() => { _serpLimited = false; _serpStats.limited = false; if (!_serpPaused) serpWorker() }, 24 * 60 * 60 * 1000)
      break
    }

    const handle = extractHandle(data)
    _serpStats.processed++

    if (handle) {
      await supabase.from('artists').update({
        instagram: handle,
        contact_quality: 'verifying',
        updated_at: new Date().toISOString()
      }).eq('id', artist.id)
      _verifyQueue.push({ id: artist.id, handle, name: artist.name })
      _verifyStats.total++
      if (!_verifyBusy) setTimeout(verifyWorker, 500)
      _serpStats.found++
      console.log(`[Serp] ✓ ${artist.name} → @${handle}`)
    } else {
      await supabase.from('artists').update({
        contact_quality: 'contactless',
        updated_at: new Date().toISOString()
      }).eq('id', artist.id)
      _serpStats.failed++
      console.log(`[Serp] ✗ ${artist.name} — not found, flagged for manual scan`)
    }

    _serpStats.current = null
    if (_serpPaused || _serpLimited) break
    await new Promise(r => setTimeout(r, 2000))
  }

  _serpStats.current = null
  _serpBusy = false
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

  // Re-queue any artists stuck in 'verifying' state from a previous crashed run
  const { data: stuck } = await supabase
    .from('artists')
    .select('id, name, instagram')
    .eq('contact_quality', 'verifying')
  if (stuck?.length) {
    for (const a of stuck) {
      if (a.instagram) _verifyQueue.push({ id: a.id, handle: a.instagram, name: a.name })
    }
    _verifyStats.total += stuck.length
    console.log(`[Verify] Re-queued ${stuck.length} stuck verifying leads`)
    setTimeout(verifyWorker, 3000)
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

    const v2Path = path.join(__dirname, '../discovery/enrich_v2.py')
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
        console.error('enrich_v2.py stderr:', stderr.slice(0, 500))
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

// POST /api/discovery/run — stream discovery.py output to dashboard
app.post('/api/discovery/run', (req, res) => {
  res.setHeader('Content-Type', 'application/x-ndjson')
  res.setHeader('Transfer-Encoding', 'chunked')
  res.setHeader('Cache-Control', 'no-cache')

  const discoveryPath = path.join(__dirname, '../discovery/discovery.py')
  const py = spawn('python', [discoveryPath, '--no-prompt'], {
    cwd: path.join(__dirname, '../discovery')
  })

  let lineBuffer = ""
  let saved = 0

  const send = obj => res.write(JSON.stringify(obj) + "\n")

  py.stdout.on('data', chunk => {
    lineBuffer += chunk.toString()
    const lines = lineBuffer.split('\n')
    lineBuffer = lines.pop()
    for (const line of lines) {
      if (!line.trim()) continue
      send({ log: line })
      // Parse progress from lines like "Lead #12/50 saved"
      const m = line.match(/Lead #(\d+)\/(\d+)/)
      if (m) {
        saved = parseInt(m[1])
        const total = parseInt(m[2])
        send({ progress: Math.round((saved / total) * 90) })
      }
      if (line.includes('SCAN COMPLETE') || line.includes('Leads are live')) {
        send({ progress: 100 })
      }
    }
  })

  py.stderr.on('data', chunk => {
    for (const line of chunk.toString().split('\n')) {
      if (line.trim()) send({ log: `[err] ${line}` })
    }
  })

  py.on('close', () => {
    send({ progress: 100, done: true, log: '=== Discovery finished ===' })
    res.end()
  })

  py.on('error', err => {
    send({ log: `ERROR: ${err.message}`, done: true })
    res.end()
  })

  req.on('close', () => py.kill())
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

// GET /api/serp/status
app.get('/api/serp/status', (req, res) => {
  res.json({ ..._serpStats, busy: _serpBusy, paused: _serpPaused, limited: _serpLimited })
})

// POST /api/serp/pause
app.post('/api/serp/pause', (req, res) => {
  _serpPaused = true
  console.log('[Serp] Paused by user')
  res.json({ success: true, paused: true })
})

// POST /api/serp/resume
app.post('/api/serp/resume', (req, res) => {
  _serpPaused = false
  _serpLimited = false
  _serpStats.limited = false
  console.log('[Serp] Resumed by user')
  if (!_serpBusy) serpWorker()
  res.json({ success: true, paused: false })
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
  setTimeout(serpWorker, 8000)
})
