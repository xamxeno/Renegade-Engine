import { useState, useEffect, useCallback, useRef } from "react"

const STATUS_COLORS = {
  new:       { bg: "#0e1a2e", text: "#6c8cff" },
  contacted: { bg: "#1a2a1a", text: "#4caf50" },
  pitched:   { bg: "#2a1a0e", text: "#ff9800" },
  signed:    { bg: "#2a0e1a", text: "#ff4081" },
  ignored:   { bg: "#1a1a1a", text: "#555" }
}

export default function Dashboard({ API, onSelect }) {
  const [artists, setArtists] = useState([])
  const [stats, setStats] = useState({})
  const [loading, setLoading] = useState(true)
  const [search, setSearch] = useState("")
  const [filterStatus, setFilterStatus] = useState("")
  const [filterPlatform, setFilterPlatform] = useState(() => sessionStorage.getItem("re_platform") || "")
  const [minScore, setMinScore] = useState(() => Number(sessionStorage.getItem("re_minScore") || 0))
  const [sweetSpot, setSweetSpot] = useState(() => sessionStorage.getItem("re_sweetSpot") === "1")
  const [sortBy, setSortBy] = useState(() => sessionStorage.getItem("re_sortBy") || "listeners")
  const [sortDir, setSortDir] = useState(() => sessionStorage.getItem("re_sortDir") || "asc")
  const [activeTab, setActiveTab] = useState(() => sessionStorage.getItem("re_tab") || "all")
  const [flushing, setFlushing] = useState(false)
  const [flushPreview, setFlushPreview] = useState(null)
  const [enrichStatus, setEnrichStatus] = useState(null)
  const [listenerRefreshStatus, setListenerRefreshStatus] = useState(null)
  const [windowWidth, setWindowWidth] = useState(window.innerWidth)
  const [selectedIds, setSelectedIds] = useState(new Set())
  const [retryingContactless, setRetryingContactless] = useState(false)
  const [scoringSelected, setScoringSelected] = useState(false)
  const [scoringAll, setScoringAll] = useState(false)
  const [confirmingDelete, setConfirmingDelete] = useState(false)
  const [enrichingSelected, setEnrichingSelected] = useState(false)
  const [refreshingListeners, setRefreshingListeners] = useState(false)
  const [rescanningAll, setRescanningAll] = useState(false)
  const [confirmRescan, setConfirmRescan] = useState(false)
  const [bioScanStatus, setBioScanStatus] = useState(null)
  const [bioScanning, setBioScanning] = useState(false)
  const [sessions, setSessions] = useState([])
  const [filterSession, setFilterSession] = useState("")
  const [v2Status, setV2Status] = useState(null)
  const [scanningBatch, setScanningBatch] = useState(false)
  const [spotifyDumpOpen, setSpotifyDumpOpen] = useState(false)
  const [spotifyLeads, setSpotifyLeads] = useState([])
  const [spotifyChunk, setSpotifyChunk] = useState(0)
  const [syncingJson, setSyncingJson] = useState(false)
  const [pastePanelOpen, setPastePanelOpen] = useState(false)
  const [pasteText, setPasteText] = useState("")
  const [pasteResult, setPasteResult] = useState(null)
  const [discoveryOpen, setDiscoveryOpen] = useState(false)
  const [discoveryRunning, setDiscoveryRunning] = useState(false)
  const [discoveryLog, setDiscoveryLog] = useState([])
  const [discoveryProgress, setDiscoveryProgress] = useState(0)
  const [verifyStatus, setVerifyStatus] = useState(null)

  const searchTimer = useRef(null)
  const searchMounted = useRef(false)
  const fetchSeq = useRef(0)

  const fetchArtists = useCallback(async () => {
    const seq = ++fetchSeq.current
    setLoading(true)
    try {
      const params = new URLSearchParams()
      if (filterStatus)   params.set("status", filterStatus)
      if (sweetSpot) {
        params.set("min_score",     60)
        params.set("max_followers", 35000)
      } else {
        if (minScore) params.set("min_score", minScore)
      }
      if (search) params.set("search", search)
      if (filterSession) params.set("session_id", filterSession)

      if (filterPlatform) params.set("platform", filterPlatform)
      const [ar, st] = await Promise.all([
        fetch(`${API}/api/artists?${params}`).then(r => r.json()),
        fetch(`${API}/api/stats`).then(r => r.json())
      ])
      // Discard result if a newer fetch already started — prevents race condition
      if (seq !== fetchSeq.current) return
      setArtists(ar.artists || [])
      setStats(st)
    } catch {
      if (seq !== fetchSeq.current) return
      setArtists(DEMO_DATA)
      setStats({ total: DEMO_DATA.length, contacted: 2, pitched: 1, signed: 1, avg_score: 72 })
    }
    if (seq === fetchSeq.current) setLoading(false)
  }, [API, filterStatus, filterPlatform, filterSession, minScore, sweetSpot, search, activeTab])

  const loadSessions = useCallback(async () => {
    try {
      const r = await fetch(`${API}/api/sessions`)
      const d = await r.json()
      setSessions(d.sessions || [])
    } catch {}
  }, [API])

  // Immediate refetch on filter changes
  useEffect(() => { fetchArtists() }, [filterStatus, filterPlatform, filterSession, minScore, sweetSpot, activeTab])

  // Persist filter/tab state so back-navigation restores them
  useEffect(() => { sessionStorage.setItem("re_tab", activeTab) }, [activeTab])
  useEffect(() => { sessionStorage.setItem("re_platform", filterPlatform) }, [filterPlatform])
  useEffect(() => { sessionStorage.setItem("re_minScore", minScore) }, [minScore])
  useEffect(() => { sessionStorage.setItem("re_sweetSpot", sweetSpot ? "1" : "0") }, [sweetSpot])
  useEffect(() => { sessionStorage.setItem("re_sortBy", sortBy) }, [sortBy])
  useEffect(() => { sessionStorage.setItem("re_sortDir", sortDir) }, [sortDir])

  // Load sessions once on mount
  useEffect(() => { loadSessions() }, [loadSessions])

  useEffect(() => {
    if (!spotifyDumpOpen) return
    setSpotifyChunk(0)
    fetch(`${API}/api/artists?platform=spotify`)
      .then(r => r.json())
      .then(d => {
        const all = d.artists || []
        // Only show leads that still need Instagram found — exclude done/in-progress/junk
        const pending = all.filter(a => !a.instagram && a.contact_quality !== 'skip')
        setSpotifyLeads(pending)
      })
      .catch(() => {})
  }, [spotifyDumpOpen, API])

  const [flaggingSpotify, setFlaggingSpotify] = useState(false)
  const [confirmFlagSpotify, setConfirmFlagSpotify] = useState(false)

  const flagAllSpotifyLeads = async () => {
    if (!confirmFlagSpotify) { setConfirmFlagSpotify(true); return }
    setFlaggingSpotify(true)
    try {
      const ids = spotifyLeads.map(a => a.id)
      await fetch(`${API}/api/artists/batch`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ ids, action: 'delete' })
      })
      const flaggedSet = new Set(ids)
      setArtists(prev => prev.map(a => flaggedSet.has(a.id) ? { ...a, contact_quality: 'skip' } : a))
      setSpotifyLeads([])
      setConfirmFlagSpotify(false)
    } catch {}
    setFlaggingSpotify(false)
  }

  const syncInstagramJson = async () => {
    setSyncingJson(true)
    try {
      const r = await fetch(`${API}/api/sync-instagram-json`, { method: 'POST' })
      const d = await r.json()
      if (d.error) alert(`Sync failed: ${d.error}`)
      else { alert(`Synced: ${d.updated} updated, ${d.skipped} skipped`); fetchArtists() }
    } catch { alert('Sync failed — server unreachable') }
    setSyncingJson(false)
  }

  const syncPastedJson = async () => {
    let entries
    try { entries = JSON.parse(pasteText.trim()) } catch { setPasteResult({ error: "Invalid JSON — check your format." }); return }
    if (!Array.isArray(entries)) { setPasteResult({ error: "Expected a JSON array [ ... ]" }); return }
    setSyncingJson(true)
    setPasteResult(null)
    try {
      const r = await fetch(`${API}/api/sync-instagram-paste`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ entries })
      })
      const d = await r.json()
      if (d.error) setPasteResult({ error: d.error })
      else {
        setPasteResult({ ok: true, updated: d.updated, skipped: d.skipped })
        await fetchArtists()
        // Auto bio-scan all leads that were just synced (those with instagram handles)
        const withIG = entries.filter(e => e.instagram)
        if (withIG.length > 0) {
          // Fetch fresh IDs for these Spotify URLs
          const urls = withIG.map(e => e.spotify_url || e.profile_url).filter(Boolean)
          try {
            const idRes = await fetch(`${API}/api/artists?limit=1000`)
            const idData = await idRes.json()
            const ids = (idData.artists || [])
              .filter(a => urls.includes(a.profile_url) && a.instagram)
              .map(a => a.id)
            if (ids.length > 0) scanBios(ids)
          } catch {}
        }
      }
    } catch { setPasteResult({ error: 'Server unreachable' }) }
    setSyncingJson(false)
  }

  const runDiscovery = async () => {
    setDiscoveryRunning(true)
    setDiscoveryLog([])
    setDiscoveryProgress(0)
    try {
      const r = await fetch(`${API}/api/discovery/run`, { method: 'POST' })
      const reader = r.body.getReader()
      const dec = new TextDecoder()
      let buf = ""
      while (true) {
        const { done, value } = await reader.read()
        if (done) break
        buf += dec.decode(value, { stream: true })
        const lines = buf.split("\n")
        buf = lines.pop()
        for (const line of lines) {
          if (!line.trim()) continue
          try {
            const msg = JSON.parse(line)
            if (msg.log)      setDiscoveryLog(l => [...l, msg.log])
            if (msg.progress) setDiscoveryProgress(msg.progress)
            if (msg.done)     { fetchArtists(); loadSessions() }
          } catch { setDiscoveryLog(l => [...l, line]) }
        }
      }
    } catch (e) { setDiscoveryLog(l => [...l, `Error: ${e.message}`]) }
    setDiscoveryRunning(false)
  }

  // Debounced refetch on search changes
  useEffect(() => {
    if (!searchMounted.current) { searchMounted.current = true; return }
    clearTimeout(searchTimer.current)
    searchTimer.current = setTimeout(fetchArtists, 380)
    return () => clearTimeout(searchTimer.current)
  }, [search])

  useEffect(() => {
    const onResize = () => setWindowWidth(window.innerWidth)
    window.addEventListener('resize', onResize)
    return () => window.removeEventListener('resize', onResize)
  }, [])

  // Clear selection and pending confirmations when switching tabs
  useEffect(() => { setSelectedIds(new Set()); setConfirmingDelete(false); setConfirmRescan(false) }, [activeTab])

  // Poll enrichment status every 8s
  const prevProcessed = useRef(0)
  useEffect(() => {
    const poll = async () => {
      try {
        const r = await fetch(`${API}/api/enrich/status`)
        const d = await r.json()
        setEnrichStatus(d)
        if (d.processed > prevProcessed.current) {
          prevProcessed.current = d.processed
          fetchArtists()
        }
      } catch {}
    }
    poll()
    const interval = setInterval(poll, 8000)
    return () => clearInterval(interval)
  }, [API])

  // Poll listener refresh status every 4s — faster so progress feels live
  const prevLRBusy = useRef(false)
  useEffect(() => {
    const poll = async () => {
      try {
        const r = await fetch(`${API}/api/artists/listener-refresh-status`)
        const d = await r.json()
        setListenerRefreshStatus(d)
        // When job finishes, reload the table so updated listener counts appear
        if (prevLRBusy.current && !d.busy) fetchArtists()
        prevLRBusy.current = d.busy
      } catch {}
    }
    poll()
    const interval = setInterval(poll, 4000)
    return () => clearInterval(interval)
  }, [API])

  // Poll v2 batch scan status every 6s
  const prevV2Busy = useRef(false)
  useEffect(() => {
    const poll = async () => {
      try {
        const r = await fetch(`${API}/api/enrich/v2-status`)
        const d = await r.json()
        setV2Status(d)
        if (prevV2Busy.current && !d.busy) { fetchArtists(); loadSessions() }
        prevV2Busy.current = d.busy
      } catch {}
    }
    poll()
    const interval = setInterval(poll, 6000)
    return () => clearInterval(interval)
  }, [API])


  // Poll IG verification status every 5s
  const prevVerifyBusy = useRef(false)
  useEffect(() => {
    const poll = async () => {
      try {
        const r = await fetch(`${API}/api/verify-status`)
        const d = await r.json()
        setVerifyStatus(d)
        if (prevVerifyBusy.current && !d.busy) fetchArtists()
        prevVerifyBusy.current = d.busy
      } catch {}
    }
    poll()
    const interval = setInterval(poll, 5000)
    return () => clearInterval(interval)
  }, [API])

  // Poll bio scan status every 4s
  const prevBioScanBusy = useRef(false)
  useEffect(() => {
    const poll = async () => {
      try {
        const r = await fetch(`${API}/api/artists/scan-bios/status`)
        const d = await r.json()
        setBioScanStatus(d)
        if (prevBioScanBusy.current && !d.running) { fetchArtists(); setBioScanning(false) }
        prevBioScanBusy.current = d.running
      } catch {}
    }
    poll()
    const interval = setInterval(poll, 4000)
    return () => clearInterval(interval)
  }, [API])

  const scanBios = async (ids) => {
    if (!ids || ids.length === 0) return
    setBioScanning(true)
    try {
      await fetch(`${API}/api/artists/scan-bios`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ ids })
      })
    } catch {}
  }

  const previewFlush = async () => {
    try {
      const r = await fetch(`${API}/api/flush/preview`)
      const d = await r.json()
      setFlushPreview(d)
    } catch {
      setFlushPreview({ count: 0, leads: [], error: "Could not reach server" })
    }
  }

  const confirmFlush = async () => {
    setFlushing(true)
    try {
      const r = await fetch(`${API}/api/flush`, { method: "DELETE" })
      const d = await r.json()
      setFlushPreview(null)
      fetchArtists()
      alert(`Done — ${d.deleted} junk leads removed.`)
    } catch {
      alert("Flush failed — check the server.")
    }
    setFlushing(false)
  }

  // ── Selection & Mass Actions ──────────────────────────────────────────────────

  const toggleSelect = useCallback((id, e) => {
    e.stopPropagation()
    setConfirmingDelete(false)
    setSelectedIds(prev => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }, [])

  const clearSelection = () => { setSelectedIds(new Set()); setConfirmingDelete(false) }

  const massUpdateStatus = async (newStatus) => {
    const ids = [...selectedIds]
    if (!ids.length) return
    try {
      await fetch(`${API}/api/artists/batch`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ ids, action: 'status', status: newStatus })
      })
      clearSelection()
      fetchArtists()
    } catch {}
  }

  const massDelete = async () => {
    if (!confirmingDelete) { setConfirmingDelete(true); return }
    const ids = [...selectedIds]
    try {
      await fetch(`${API}/api/artists/batch`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ ids, action: 'delete' })
      })
      const flaggedSet = new Set(ids)
      setArtists(prev => prev.map(a => flaggedSet.has(a.id) ? { ...a, contact_quality: 'skip' } : a))
      clearSelection()
    } catch {}
  }

  const retryContactless = async () => {
    setRetryingContactless(true)
    try {
      await fetch(`${API}/api/enrich/retry-contactless`, { method: 'POST' })
      fetchArtists()
    } catch {}
    setRetryingContactless(false)
  }

  const rescanAll = async () => {
    if (!confirmRescan) { setConfirmRescan(true); return }
    setConfirmRescan(false)
    setRescanningAll(true)
    try {
      const r = await fetch(`${API}/api/artists/rescan-all`, { method: 'POST' })
      const text = await r.text()
      let d
      try { d = JSON.parse(text) } catch { throw new Error(`Server returned non-JSON (${r.status}): ${text.slice(0, 120)}`) }
      if (!r.ok) throw new Error(d.error || `HTTP ${r.status}`)
      if (d.success) {
        alert(`Rescan started for ${d.reset} leads.\nAll contact data has been cleared — the worker will re-enrich everyone with fresh searches and correct listener counts. This takes a while.`)
        fetchArtists()
      }
    } catch (err) {
      alert(`Rescan failed: ${err.message}`)
    }
    setRescanningAll(false)
  }

  const scanBatch = async () => {
    if (!filterSession || scanningBatch) return
    setScanningBatch(true)
    try {
      const r = await fetch(`${API}/api/enrich/scan-batch`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ session_id: filterSession })
      })
      const d = await r.json()
      if (d.queued > 0) {
        alert(`V2 scan started for ${d.queued} leads.\nWatch the status bar for progress.`)
      } else {
        alert(d.error ? `Server error: ${d.error}` : (d.message || `No eligible leads — server returned: ${JSON.stringify(d)}`))
      }
    } catch {
      alert('Scan failed — check the server.')
    }
    setScanningBatch(false)
  }

  const refreshListeners = async () => {
    setRefreshingListeners(true)
    try {
      const r = await fetch(`${API}/api/artists/refresh-listeners`, { method: 'POST' })
      const d = await r.json()
      if (d.success) {
        alert(`Listener refresh started for ${d.started} artists.\nThis runs in the background — counts will update over the next few minutes. Click Refresh to see updated values.`)
      }
    } catch {
      alert('Refresh failed — check the server.')
    }
    setRefreshingListeners(false)
  }

  const runEnrichmentOnSelected = async () => {
    const ids = [...selectedIds]
    if (!ids.length) return
    setEnrichingSelected(true)
    try {
      const r = await fetch(`${API}/api/enrich/batch-selected`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ ids })
      })
      const d = await r.json()
      clearSelection()
      fetchArtists()
      if (d.queued) alert(`Queued ${d.queued} leads for enrichment. The background worker will find their Instagrams.`)
    } catch {}
    setEnrichingSelected(false)
  }

  const scoreSelected = async () => {
    const ids = [...selectedIds]
    setScoringSelected(true)
    try {
      const r = await fetch(`${API}/api/score`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ ids })
      })
      const d = await r.json()
      clearSelection()
      fetchArtists()
      if (d.scored) alert(`Scored ${d.scored} leads.`)
    } catch {}
    setScoringSelected(false)
  }

  const scoreAllLeads = async () => {
    setScoringAll(true)
    try {
      const r = await fetch(`${API}/api/score`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({}) })
      const d = await r.json()
      fetchArtists()
      if (d.scored !== undefined) alert(`Scored ${d.scored} leads.`)
    } catch {}
    setScoringAll(false)
  }

  // ── Sorting & filtering ───────────────────────────────────────────────────────

  const filtered = artists.filter(a =>
    !search || a.name.toLowerCase().includes(search.toLowerCase())
  )

  const byPlatform = {}
  artists.forEach(a => {
    const key = a.platform || "unknown"
    if (!byPlatform[key]) byPlatform[key] = []
    byPlatform[key].push(a.listeners || a.followers || 0)
  })

  const getPercentile = (artist) => {
    const vals = byPlatform[artist.platform || "unknown"] || []
    if (vals.length <= 1) return 0
    const target = artist.listeners || artist.followers || 0
    const below = vals.filter(v => v < target).length
    return below / (vals.length - 1)
  }

  const STATUS_ORDER = { new: 0, contacted: 1, pitched: 2, signed: 3, ignored: 4 }

  const sortedArtists = [...filtered].sort((a, b) => {
    // Primary: status priority
    const sa = STATUS_ORDER[a.status] ?? 0
    const sb = STATUS_ORDER[b.status] ?? 0
    if (sa !== sb) return sa - sb

    // Secondary: user-selected sort
    if (sortBy === "name") {
      const cmp = (a.name || "").localeCompare(b.name || "")
      return sortDir === "asc" ? cmp : -cmp
    }
    let va, vb
    if (sortBy === "listeners" || sortBy === "followers") {
      va = getPercentile(a); vb = getPercentile(b)
    } else if (sortBy === "score") {
      va = a.score ?? -1; vb = b.score ?? -1
    } else if (sortBy === "ig_followers") {
      va = a.ig_followers ?? -1; vb = b.ig_followers ?? -1
    } else {
      va = a.score ?? -1; vb = b.score ?? -1
    }
    return sortDir === "asc" ? va - vb : vb - va
  })

  // Build batch label map: session_id → "Batch N" or "Testing Batch"
  const batchLabelMap = {}
  sessions.forEach((s, i) => {
    const isOldest = i === sessions.length - 1
    batchLabelMap[s.session_id] = isOldest ? "Testing" : `Batch ${sessions.length - i}`
  })

  const allLeads          = sortedArtists.filter(a => a.contact_quality !== 'skip')
  const verifiedArtists   = sortedArtists.filter(a => a.instagram && a.contact_quality !== 'skip')
  const unverifiedArtists = sortedArtists.filter(a => !a.instagram && a.contact_quality !== 'skip')
  const inProgressArtists = sortedArtists.filter(a => a.contact_quality === 'verifying' && a.instagram)
  const flaggedArtists    = sortedArtists.filter(a => a.contact_quality === 'skip')
  const displayedArtists  =
    activeTab === "verified"    ? verifiedArtists :
    activeTab === "unverified"  ? unverifiedArtists :
    activeTab === "inprogress"  ? inProgressArtists :
    activeTab === "flagged"     ? flaggedArtists :
    allLeads

  return (
    <div style={{ padding: "2rem 2rem calc(2rem + env(safe-area-inset-bottom))", maxWidth: 1280, margin: "0 auto", minHeight: "100vh", position: "relative", zIndex: 1 }}>

      {/* ── Spotify Links Dump Modal ── */}
      {spotifyDumpOpen && (() => {
        const CHUNK = 25
        const chunks = []
        for (let i = 0; i < spotifyLeads.length; i += CHUNK) chunks.push(spotifyLeads.slice(i, i + CHUNK))
        const chunk = chunks[spotifyChunk] || []
        const chunkText = chunk.length === 0 ? "Loading..." : chunk.filter(a => a.profile_url).map(a => `${a.name}: ${a.profile_url}`).join("\n")
        return (
          <div style={{ position: "fixed", inset: 0, background: "rgba(0,0,0,0.9)", zIndex: 1000, display: "flex", alignItems: "center", justifyContent: "center" }}>
            <div style={{ background: "rgba(17,17,17,0.82)", border: "0.5px solid #2a2a2a", borderRadius: 14, padding: "2rem", width: "min(700px, 92vw)", display: "flex", flexDirection: "column", gap: 14 }}>
              <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
                <div>
                  <div style={{ color: "#fff", fontWeight: 600, fontSize: 16 }}>
                    Spotify Links — {spotifyLeads.length} unverified leads
                  </div>
                  <div style={{ color: "#555", fontSize: 12, marginTop: 3 }}>
                    Chunk {spotifyChunk + 1} of {chunks.length || 1} · 25 per chunk · paste into Claude to find Instagrams
                  </div>
                </div>
                <button onClick={() => setSpotifyDumpOpen(false)} style={{ background: "transparent", border: "none", color: "#555", fontSize: 22, cursor: "pointer" }}>×</button>
              </div>
              <textarea
                readOnly
                value={chunkText}
                style={{ width: "100%", height: 400, background: "#0a0a0a", border: "0.5px solid #222", borderRadius: 8, padding: "12px", color: "#ccc", fontSize: 12, fontFamily: "monospace", resize: "vertical", outline: "none", boxSizing: "border-box" }}
                onClick={e => e.target.select()}
              />
              <div style={{ display: "flex", gap: 10, alignItems: "center", flexWrap: "wrap" }}>
                <button
                  onClick={() => setSpotifyChunk(c => Math.max(0, c - 1))}
                  disabled={spotifyChunk === 0}
                  style={{ background: "#1a1a1a", border: "0.5px solid #333", borderRadius: 8, padding: "9px 18px", color: spotifyChunk === 0 ? "#333" : "#888", fontSize: 13, cursor: spotifyChunk === 0 ? "default" : "pointer" }}
                >← Prev</button>
                <span style={{ color: "#444", fontSize: 12, flex: 1, textAlign: "center" }}>{spotifyChunk + 1} / {chunks.length || 1}</span>
                <button
                  onClick={() => setSpotifyChunk(c => Math.min(chunks.length - 1, c + 1))}
                  disabled={spotifyChunk >= chunks.length - 1}
                  style={{ background: "#1a1a1a", border: "0.5px solid #333", borderRadius: 8, padding: "9px 18px", color: spotifyChunk >= chunks.length - 1 ? "#333" : "#888", fontSize: 13, cursor: spotifyChunk >= chunks.length - 1 ? "default" : "pointer" }}
                >Next →</button>
                <button
                  onClick={() => navigator.clipboard.writeText(chunkText)}
                  style={{ background: "#1DB954", border: "none", borderRadius: 8, padding: "9px 22px", color: "#000", fontSize: 13, fontWeight: 700, cursor: "pointer" }}
                >Copy Chunk</button>
              </div>
              <div style={{ borderTop: "0.5px solid #1a1a1a", paddingTop: 12, display: "flex", alignItems: "center", justifyContent: "space-between", gap: 10, flexWrap: "wrap" }}>
                <span style={{ color: "#444", fontSize: 12 }}>Flag all {spotifyLeads.length} listed leads as junk (moves them to Flagged tab)</span>
                <button
                  onClick={flagAllSpotifyLeads}
                  disabled={flaggingSpotify || spotifyLeads.length === 0}
                  style={{ background: confirmFlagSpotify ? "#3a0808" : "#1a0808", border: `0.5px solid ${confirmFlagSpotify ? "#ff5555" : "#3a1515"}`, borderRadius: 8, padding: "8px 18px", color: confirmFlagSpotify ? "#ff5555" : "#cc4444", fontSize: 13, fontWeight: confirmFlagSpotify ? 700 : 500, cursor: flaggingSpotify || spotifyLeads.length === 0 ? "default" : "pointer", whiteSpace: "nowrap" }}
                >
                  {flaggingSpotify ? "Flagging..." : confirmFlagSpotify ? `Confirm Flag All ${spotifyLeads.length}` : "Flag All Listed"}
                </button>
              </div>
            </div>
          </div>
        )
      })()}

      {/* ── Discovery Modal ── */}
      {discoveryOpen && (
        <div style={{ position: "fixed", inset: 0, background: "rgba(0,0,0,0.92)", zIndex: 1000, display: "flex", alignItems: "center", justifyContent: "center" }}>
          <div style={{ background: "rgba(13,13,13,0.82)", border: "1px solid #2a1a4a", borderRadius: 16, padding: "2rem", width: "min(620px, 92vw)", display: "flex", flexDirection: "column", gap: 16 }}>
            <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
              <div>
                <div style={{ color: "#fff", fontWeight: 700, fontSize: 17, letterSpacing: "-0.02em" }}>Run Discovery</div>
                <div style={{ color: "#555", fontSize: 12, marginTop: 3 }}>Spotify · USA, Canada, UK, Australia, UAE · under 100K listeners · no duplicate leads</div>
              </div>
              {!discoveryRunning && <button onClick={() => { setDiscoveryOpen(false); setDiscoveryLog([]); setDiscoveryProgress(0) }} style={{ background: "transparent", border: "none", color: "#555", fontSize: 22, cursor: "pointer" }}>×</button>}
            </div>

            {/* Progress bar */}
            <div style={{ background: "rgba(17,17,17,0.82)", borderRadius: 99, height: 6, overflow: "hidden" }}>
              <div style={{ height: "100%", width: `${discoveryProgress}%`, background: "linear-gradient(90deg,#6633ff,#1DB954)", borderRadius: 99, transition: "width 0.4s ease" }} />
            </div>
            <div style={{ color: "#444", fontSize: 11, textAlign: "right", marginTop: -10 }}>{discoveryProgress}%</div>

            {/* Log output */}
            <div
              ref={el => { if (el) el.scrollTop = el.scrollHeight }}
              style={{ background: "#050505", border: "0.5px solid #1a1a1a", borderRadius: 8, padding: "12px", height: 260, overflowY: "auto", fontFamily: "monospace", fontSize: 11, color: "#555", display: "flex", flexDirection: "column", gap: 2 }}
            >
              {discoveryLog.length === 0 && !discoveryRunning && (
                <span style={{ color: "#333" }}>Click Start to begin a new discovery run.</span>
              )}
              {discoveryLog.map((line, i) => (
                <div key={i} style={{ color: line.includes("ERROR") || line.includes("error") ? "#f44336" : line.includes("saved") || line.includes("COMPLETE") ? "#4caf50" : line.includes("Skip") || line.includes("SKIP") ? "#555" : "#888" }}>{line}</div>
              ))}
              {discoveryRunning && <div style={{ color: "#6633ff", animation: "pulse 1s infinite" }}>● running...</div>}
            </div>

            <div style={{ display: "flex", gap: 10, justifyContent: "flex-end" }}>
              {!discoveryRunning && (
                <button onClick={() => { setDiscoveryOpen(false); setDiscoveryLog([]); setDiscoveryProgress(0) }} style={{ background: "#1a1a1a", border: "0.5px solid #333", borderRadius: 8, padding: "9px 20px", color: "#888", fontSize: 13, cursor: "pointer" }}>Close</button>
              )}
              <button
                onClick={runDiscovery}
                disabled={discoveryRunning}
                style={{ background: discoveryRunning ? "#1a1a2a" : "linear-gradient(135deg,#4411bb,#1DB954)", border: "none", borderRadius: 8, padding: "9px 26px", color: discoveryRunning ? "#444" : "#fff", fontSize: 13, fontWeight: 700, cursor: discoveryRunning ? "default" : "pointer", letterSpacing: "0.02em" }}
              >
                {discoveryRunning ? "Running..." : "Start Discovery"}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* ── Paste JSON Sync Panel ── */}
      {pastePanelOpen && (
        <div style={{ position: "fixed", inset: 0, background: "rgba(0,0,0,0.9)", zIndex: 1000, display: "flex", alignItems: "center", justifyContent: "center" }}>
          <div style={{ background: "rgba(17,17,17,0.82)", border: "0.5px solid #2a2a2a", borderRadius: 14, padding: "2rem", width: "min(660px, 92vw)", display: "flex", flexDirection: "column", gap: 14 }}>
            <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
              <div>
                <div style={{ color: "#fff", fontWeight: 600, fontSize: 16 }}>Paste Instagram JSON</div>
                <div style={{ color: "#555", fontSize: 12, marginTop: 3 }}>Paste a JSON array from Claude — leads get marked verified or contactless instantly</div>
              </div>
              <button onClick={() => { setPastePanelOpen(false); setPasteText(""); setPasteResult(null) }} style={{ background: "transparent", border: "none", color: "#555", fontSize: 22, cursor: "pointer" }}>×</button>
            </div>

            <div style={{ background: "#0a0a0a", border: "0.5px solid #1a1a1a", borderRadius: 8, padding: "10px 12px" }}>
              <div style={{ color: "#444", fontSize: 11, marginBottom: 6, fontFamily: "monospace" }}>Expected format:</div>
              <div style={{ color: "#555", fontSize: 11, fontFamily: "monospace", lineHeight: 1.6 }}>
                {`[`}<br/>
                {`  { "name": "Artist Name", "spotify_url": "https://open.spotify.com/artist/...", "instagram": "handle" },`}<br/>
                {`  { "name": "No IG Artist", "spotify_url": "https://...", "instagram": null }`}<br/>
                {`]`}
              </div>
            </div>

            <textarea
              value={pasteText}
              onChange={e => { setPasteText(e.target.value); setPasteResult(null) }}
              placeholder="Paste your JSON array here..."
              style={{ width: "100%", height: 280, background: "#0a0a0a", border: "0.5px solid #222", borderRadius: 8, padding: "12px", color: "#ccc", fontSize: 12, fontFamily: "monospace", resize: "vertical", outline: "none", boxSizing: "border-box" }}
            />

            {pasteResult && (
              <div style={{ background: pasteResult.error ? "#1a0808" : "#0a1a0a", border: `0.5px solid ${pasteResult.error ? "#3a1515" : "#1a3a1a"}`, borderRadius: 8, padding: "10px 14px", fontSize: 13, color: pasteResult.error ? "#f44336" : "#4caf50" }}>
                {pasteResult.error ? pasteResult.error : `Synced ${pasteResult.updated} leads — ${pasteResult.queued ?? 0} queued for IG verification. Watch the progress bar at the top.`}
              </div>
            )}

            <div style={{ display: "flex", gap: 10, justifyContent: "flex-end" }}>
              <button onClick={() => { setPastePanelOpen(false); setPasteText(""); setPasteResult(null) }} style={{ background: "#1a1a1a", border: "0.5px solid #333", borderRadius: 8, padding: "9px 20px", color: "#888", fontSize: 13, cursor: "pointer" }}>Close</button>
              <button onClick={syncPastedJson} disabled={syncingJson || !pasteText.trim()} style={{ background: syncingJson ? "#111" : "#9966ff", border: "none", borderRadius: 8, padding: "9px 22px", color: syncingJson ? "#333" : "#fff", fontSize: 13, fontWeight: 700, cursor: syncingJson || !pasteText.trim() ? "default" : "pointer" }}>
                {syncingJson ? "Syncing..." : "Sync to Leads"}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* ── Flush preview modal ── */}
      {flushPreview && (
        <div style={{ position: "fixed", inset: 0, background: "rgba(0,0,0,0.85)", zIndex: 1000, display: "flex", alignItems: "center", justifyContent: "center" }}>
          <div style={{ background: "rgba(17,17,17,0.82)", border: "0.5px solid #2a2a2a", borderRadius: 14, padding: "2rem", maxWidth: 520, width: "90%" }}>
            <h2 style={{ color: "#fff", margin: "0 0 6px", fontSize: 18, fontWeight: 600 }}>Flush Junk Leads</h2>
            <p style={{ color: "#666", fontSize: 13, margin: "0 0 16px" }}>
              Permanently removes leads with score &lt; 50, flagged leads, or leads with no contact info.<br/>
              <strong style={{ color: "#888" }}>Contacted / Pitched / Signed leads are never touched.</strong>
            </p>
            <div style={{ background: "#1a0a0a", border: "0.5px solid #3a1a1a", borderRadius: 8, padding: "12px 16px", marginBottom: 16 }}>
              <div style={{ color: "#f44336", fontSize: 22, fontWeight: 700 }}>{flushPreview.count} leads will be removed</div>
              {flushPreview.error && <div style={{ color: "#f44336", fontSize: 12, marginTop: 4 }}>{flushPreview.error}</div>}
            </div>
            {flushPreview.leads?.length > 0 && (
              <div style={{ marginBottom: 16, maxHeight: 180, overflowY: "auto" }}>
                <div style={{ color: "#444", fontSize: 11, marginBottom: 6 }}>Preview (first 20):</div>
                {flushPreview.leads.map(l => (
                  <div key={l.id} style={{ display: "flex", justifyContent: "space-between", padding: "4px 0", borderBottom: "0.5px solid #1a1a1a", fontSize: 12 }}>
                    <span style={{ color: "#888" }}>{l.name}</span>
                    <span style={{ color: l.score > 0 ? "#ff9800" : "#555" }}>score {l.score ?? "—"}{l.contact_quality === "skip" ? " · producer" : ""}</span>
                  </div>
                ))}
              </div>
            )}
            <div style={{ display: "flex", gap: 10, justifyContent: "flex-end" }}>
              <button onClick={() => setFlushPreview(null)} style={{ background: "#1a1a1a", border: "0.5px solid #333", borderRadius: 8, padding: "9px 20px", color: "#888", fontSize: 13, cursor: "pointer" }}>Cancel</button>
              <button onClick={confirmFlush} disabled={flushing || flushPreview.count === 0} style={{ background: flushing ? "#333" : "#c0392b", border: "none", borderRadius: 8, padding: "9px 20px", color: "#fff", fontSize: 13, cursor: "pointer", fontWeight: 600 }}>
                {flushing ? "Removing..." : `Remove ${flushPreview.count} leads`}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* ── Floating mass-action bar ── */}
      {selectedIds.size > 0 && (
        <div style={{
          position: "fixed", bottom: 28, left: "50%", transform: "translateX(-50%)",
          background: "#161616", border: "1px solid #2a2a2a", borderRadius: 14,
          padding: "11px 18px", display: "flex", gap: 8, alignItems: "center",
          zIndex: 500, boxShadow: "0 8px 40px rgba(0,0,0,0.8)",
          flexWrap: "wrap", maxWidth: "92vw",
        }}>
          <span style={{ color: "#777", fontSize: 13, whiteSpace: "nowrap" }}>
            {selectedIds.size} selected · Mark as:
          </span>
          {['new', 'contacted', 'pitched', 'signed', 'ignored'].map(s => (
            <button key={s} onClick={() => massUpdateStatus(s)} style={{
              background: STATUS_COLORS[s]?.bg || "#111",
              border: `1px solid ${STATUS_COLORS[s]?.text || '#333'}55`,
              borderRadius: 7, padding: "6px 13px",
              color: STATUS_COLORS[s]?.text || "#888",
              fontSize: 12, cursor: "pointer", fontWeight: 500, whiteSpace: "nowrap",
              textTransform: "capitalize",
            }}>{s}</button>
          ))}
          <div style={{ width: 1, height: 22, background: "#2a2a2a", margin: "0 2px" }} />
          <button
            onClick={runEnrichmentOnSelected}
            disabled={enrichingSelected}
            style={{
              background: enrichingSelected ? "#111" : "#0a1a0a",
              border: `1px solid ${enrichingSelected ? '#222' : '#1a4a1a'}`,
              borderRadius: 7, padding: "6px 13px",
              color: enrichingSelected ? "#333" : "#4caf50",
              fontSize: 12, cursor: enrichingSelected ? "default" : "pointer",
              fontWeight: 500, whiteSpace: "nowrap",
            }}
          >
            {enrichingSelected ? "Queuing..." : "Run Enrichment"}
          </button>
          <div style={{ width: 1, height: 22, background: "#2a2a2a", margin: "0 2px" }} />
          <button
            onClick={scoreSelected}
            disabled={scoringSelected}
            style={{
              background: scoringSelected ? "#111" : "#1a1a0a",
              border: `1px solid ${scoringSelected ? '#222' : '#4a4a1a'}`,
              borderRadius: 7, padding: "6px 13px",
              color: scoringSelected ? "#333" : "#cccc44",
              fontSize: 12, cursor: scoringSelected ? "default" : "pointer",
              fontWeight: 500, whiteSpace: "nowrap",
            }}
          >
            {scoringSelected ? "Scoring..." : "Score"}
          </button>
          <div style={{ width: 1, height: 22, background: "#2a2a2a", margin: "0 2px" }} />
          <button onClick={massDelete} style={{
            background: confirmingDelete ? "#3a0808" : "#1a0808",
            border: `1px solid ${confirmingDelete ? '#ff5555' : '#3a1515'}`,
            borderRadius: 7, padding: "6px 13px",
            color: confirmingDelete ? "#ff5555" : "#cc4444",
            fontSize: 12, cursor: "pointer", fontWeight: 500, whiteSpace: "nowrap",
          }}>
            {confirmingDelete ? `Confirm Flag (${selectedIds.size})` : 'Flag'}
          </button>
          <button onClick={clearSelection} style={{ background: "transparent", border: "none", color: "#444", fontSize: 20, cursor: "pointer", lineHeight: 1, padding: "2px 4px" }}>×</button>
        </div>
      )}

      {/* ── Header ── */}
      {(() => {
        const mob = windowWidth < 600
        const btnStyle = (bg, border, color, extra = {}) => ({
          background: bg, border, borderRadius: 8,
          padding: mob ? "7px 10px" : "8px 16px",
          color, fontSize: mob ? 11 : 13,
          cursor: "pointer", fontWeight: 500,
          whiteSpace: "nowrap", ...extra
        })
        return (
          <div style={{ display: "flex", flexDirection: mob ? "column" : "row", alignItems: mob ? "flex-start" : "center", justifyContent: "space-between", gap: mob ? 10 : 0, marginBottom: "1.5rem" }}>
            <div>
              <h1 style={{ fontSize: 22, fontWeight: 700, color: "#fff", margin: 0, letterSpacing: "-0.04em", background: "linear-gradient(90deg,#fff 60%,#1DB954)", WebkitBackgroundClip: "text", WebkitTextFillColor: "transparent" }}>Renegade Engine</h1>
              <p style={{ color: "#444", fontSize: 12, margin: "4px 0 0", letterSpacing: "0.06em", textTransform: "uppercase" }}>Artist Lead Dashboard · Spotify</p>
            </div>
            <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
              <button
                onClick={refreshListeners}
                disabled={refreshingListeners || listenerRefreshStatus?.busy}
                title="Re-fetch verified listener counts for all leads"
                style={btnStyle("#0a0a1a", "0.5px solid #1a1a3a", (refreshingListeners || listenerRefreshStatus?.busy) ? "#333" : "#6c8cff", { cursor: (refreshingListeners || listenerRefreshStatus?.busy) ? "default" : "pointer" })}
              >
                {listenerRefreshStatus?.busy
                  ? `${listenerRefreshStatus.processed}/${listenerRefreshStatus.total}...`
                  : refreshingListeners ? "Starting..." : mob ? "Listeners" : "Refresh Listeners"}
              </button>
              {filterSession ? (() => {
                const idx = sessions.findIndex(s => s.session_id === filterSession)
                const isOldest = idx === sessions.length - 1
                const batchNum = sessions.length - idx
                const label = isOldest ? "Testing Batch" : `Batch ${batchNum}`
                return (
                  <button
                    onClick={scanBatch}
                    disabled={scanningBatch || v2Status?.busy}
                    title={`Run Playwright + Claude enrichment on all leads in ${label}`}
                    style={btnStyle((scanningBatch || v2Status?.busy) ? "#0a0a0a" : "#0d1a2a", `0.5px solid ${(scanningBatch || v2Status?.busy) ? "#1a1a1a" : "#1a4a6a"}`, (scanningBatch || v2Status?.busy) ? "#333" : "#4a9acc", { cursor: (scanningBatch || v2Status?.busy) ? "default" : "pointer", fontWeight: 600 })}
                  >
                    {scanningBatch ? "Starting..." : v2Status?.busy ? `${v2Status.processed}/${v2Status.total}...` : `Scan ${label}`}
                  </button>
                )
              })() : (
                <button
                  onClick={() => {
                    const ids = displayedArtists.filter(a => a.instagram).map(a => a.id)
                    scanBios(ids)
                  }}
                  disabled={bioScanning || bioScanStatus?.running}
                  title="Scan Instagram bios of visible leads and flag producers/DJs"
                  style={btnStyle("#0a0f00", `0.5px solid ${(bioScanning || bioScanStatus?.running) ? "#222" : "#1a3a00"}`, (bioScanning || bioScanStatus?.running) ? "#333" : "#88cc44", { cursor: (bioScanning || bioScanStatus?.running) ? "default" : "pointer" })}
                >
                  {bioScanStatus?.running
                    ? `Scanning ${bioScanStatus.processed}/${bioScanStatus.total}...`
                    : "Scan Bios"}
                </button>
              )}
              <button onClick={() => { setDiscoveryOpen(true) }} style={btnStyle("linear-gradient(135deg,#1a0a2e,#0d1a2e)", "1px solid #6633ff44", "#aa66ff", { fontWeight: 700, letterSpacing: "0.02em" })}>
                + Discovery
              </button>
              <button onClick={() => setSpotifyDumpOpen(true)} style={btnStyle("#0a1a0f", "0.5px solid #1DB95433", "#1DB954")}>
                Spotify
              </button>
              <button onClick={() => setPastePanelOpen(true)} style={btnStyle("#0d0a1a", "0.5px solid #3a1a6a", "#9966ff")}>
                Paste
              </button>
              <button onClick={scoreAllLeads} disabled={scoringAll} style={btnStyle("#1a1a0a", `0.5px solid ${scoringAll ? "#222" : "#4a4a1a"}`, scoringAll ? "#333" : "#cccc44", { cursor: scoringAll ? "default" : "pointer" })}>
                {scoringAll ? "Scoring..." : mob ? "Score All" : "Score All Leads"}
              </button>
              <button onClick={previewFlush} style={btnStyle("#1a0808", "0.5px solid #3a1515", "#cc4444")}>
                {mob ? "Flush" : "Flush Junk"}
              </button>
            </div>
          </div>
        )
      })()}

      {/* ── Auto-enrichment status bar ── */}
      {enrichStatus?.busy && (
        <div style={{ background: "#0d1a0d", border: "0.5px solid #1a3a1a", borderRadius: 8, padding: "8px 14px", marginBottom: "0.5rem", fontSize: 12, color: "#4caf50", display: "flex", alignItems: "center", gap: 10 }}>
          <span style={{ width: 7, height: 7, borderRadius: "50%", background: "#4caf50", display: "inline-block", animation: "pulse 1.5s infinite" }} />
          <span>Searching contacts for <strong>{enrichStatus.current}</strong></span>
          {enrichStatus.remaining > 0 && (
            <span style={{ color: "#2a5a2a" }}>{enrichStatus.remaining} remaining</span>
          )}
        </div>
      )}

      {/* ── V2 batch scan status bar ── */}
      {v2Status?.busy && (
        <div style={{ background: "#0d0d1a", border: "0.5px solid #2a2a6a", borderRadius: 8, padding: "8px 14px", marginBottom: "0.5rem", fontSize: 12, color: "#8888ff", display: "flex", alignItems: "center", gap: 10 }}>
          <span style={{ width: 7, height: 7, borderRadius: "50%", background: "#8888ff", display: "inline-block", animation: "pulse 1.5s infinite" }} />
          <span>V2 Scan — <strong>{enrichStatus?.current || "processing"}</strong></span>
          <span style={{ color: "#2a2a5a" }}>Playwright + Claude</span>
          <span style={{ color: "#3a3a8a", marginLeft: "auto" }}>
            {v2Status.processed}/{v2Status.total} · {v2Status.found} found
          </span>
        </div>
      )}
      {v2Status && !v2Status.busy && v2Status.total > 0 && !v2Status.session_id && (
        <div style={{ background: "#0a0f1a", border: "0.5px solid #1a2a4a", borderRadius: 8, padding: "8px 14px", marginBottom: "0.5rem", fontSize: 12, color: "#4a6a9a", display: "flex", alignItems: "center", gap: 10 }}>
          <span>V2 scan complete — {v2Status.found}/{v2Status.total} contacts found</span>
        </div>
      )}

      {/* ── IG Verification status bar (paste sync only) ── */}
      {verifyStatus?.busy && verifyStatus.queue > 0 && (
        <div style={{ background: "#0d0d1a", border: "0.5px solid #3a1a6a", borderRadius: 8, padding: "8px 14px", marginBottom: "0.5rem", fontSize: 12, color: "#aa66ff", display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap" }}>
          <span style={{ width: 7, height: 7, borderRadius: "50%", background: "#aa66ff", display: "inline-block", animation: "pulse 1.5s infinite", flexShrink: 0 }} />
          <span>Verifying <strong>{verifyStatus.current}</strong></span>
          <span style={{ color: "#3a2a6a", marginLeft: "auto", whiteSpace: "nowrap" }}>
            {verifyStatus.processed}/{verifyStatus.total} · {verifyStatus.verified} verified
          </span>
        </div>
      )}

      {/* ── Bio scan status bar ── */}
      {bioScanStatus?.running && (
        <div style={{ background: "#0a0f0a", border: "0.5px solid #1a3a00", borderRadius: 8, padding: "8px 14px", marginBottom: "0.5rem", fontSize: 12, color: "#88cc44", display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap" }}>
          <span style={{ width: 7, height: 7, borderRadius: "50%", background: "#88cc44", display: "inline-block", animation: "pulse 1.5s infinite", flexShrink: 0 }} />
          <span>Scanning bios — <strong>{bioScanStatus.current}</strong></span>
          <span style={{ color: "#2a4a00", marginLeft: "auto", whiteSpace: "nowrap" }}>
            {bioScanStatus.processed}/{bioScanStatus.total} · {bioScanStatus.flagged} removed
          </span>
        </div>
      )}
      {bioScanStatus && !bioScanStatus.running && bioScanStatus.total > 0 && (
        <div style={{ background: "#0a0f0a", border: "0.5px solid #1a3a00", borderRadius: 8, padding: "8px 14px", marginBottom: "0.5rem", fontSize: 12, color: "#88cc44", display: "flex", alignItems: "center", gap: 10 }}>
          <span>Bio scan complete — {bioScanStatus.flagged} producers/DJs removed out of {bioScanStatus.total}</span>
        </div>
      )}

      {/* ── Listener refresh status bar ── */}
      {listenerRefreshStatus?.busy && (
        <div style={{ background: "#0a0a1a", border: "0.5px solid #1a1a3a", borderRadius: 8, padding: "8px 14px", marginBottom: "0.5rem", fontSize: 12, color: "#6c8cff", display: "flex", alignItems: "center", gap: 10 }}>
          <span style={{ width: 7, height: 7, borderRadius: "50%", background: "#6c8cff", display: "inline-block", animation: "pulse 1.5s infinite" }} />
          <span>Refreshing listeners — <strong>{listenerRefreshStatus.current}</strong></span>
          <span style={{ color: "#2a2a5a", marginLeft: "auto" }}>
            {listenerRefreshStatus.processed}/{listenerRefreshStatus.total} · {listenerRefreshStatus.updated} updated
          </span>
        </div>
      )}
      {listenerRefreshStatus && !listenerRefreshStatus.busy && listenerRefreshStatus.total > 0 && (
        <div style={{ background: "#0a0f0a", border: "0.5px solid #1a2a1a", borderRadius: 8, padding: "8px 14px", marginBottom: "0.5rem", fontSize: 12, color: "#4a8a4a", display: "flex", alignItems: "center", gap: 10 }}>
          <span>Listener refresh complete — {listenerRefreshStatus.updated}/{listenerRefreshStatus.total} updated</span>
        </div>
      )}

      {/* ── Stats cards ── */}
      {(() => {
        const isMobile = windowWidth <= 430
        return (
          <div style={{ display: "grid", gridTemplateColumns: isMobile ? "repeat(3, 1fr)" : "repeat(5, 1fr)", gap: 12, marginBottom: "1.5rem" }}>
            {[
              [filterSession ? "Batch Leads" : (filterStatus || minScore > 0 || sweetSpot ? "Showing" : "Total Leads"),
               filterSession ? (sessions.find(s => s.session_id === filterSession)?.count ?? sortedArtists.length) : sortedArtists.length],
              ["Contacted",   stats.contacted || 0],
              ["Pitched",     stats.pitched || 0],
              ["Signed",      stats.signed || 0],
              ["Avg Score",   `${stats.avg_score || 0}/100`]
            ].map(([label, val]) => (
              <div key={label} style={{ background: "linear-gradient(135deg,#111 0%,#0d0d0d 100%)", border: "0.5px solid #1f1f1f", borderRadius: 12, padding: isMobile ? "10px 10px" : "16px 18px", boxShadow: "0 2px 16px rgba(0,0,0,0.4)" }}>
                <div style={{ color: "#444", fontSize: isMobile ? 10 : 11, marginBottom: 8, letterSpacing: "0.08em", textTransform: "uppercase" }}>{label}</div>
                <div style={{ color: "#fff", fontSize: isMobile ? 20 : 26, fontWeight: 700, letterSpacing: "-0.03em" }}>{val}</div>
              </div>
            ))}
          </div>
        )
      })()}

      {/* ── Tabs ── */}
      <div style={{ display: "flex", gap: 4, marginBottom: "1rem", borderBottom: "0.5px solid #1f1f1f", paddingBottom: 0, flexWrap: "wrap" }}>
        {[
          ["all",         "All Leads",          allLeads.length],
          ["verified",    "Verified Contacts",  verifiedArtists.length],
          ["unverified",  "Unverified",         unverifiedArtists.length],
          ["flagged",     "Flagged",            flaggedArtists.length],
          ["inprogress",  "In Progress",        inProgressArtists.length],
        ].map(([tab, label, count]) => (
          <button key={tab} onClick={() => setActiveTab(tab)} style={{
            background: "transparent", border: "none",
            borderBottom: activeTab === tab ? "2px solid #ff4d00" : "2px solid transparent",
            color: activeTab === tab ? "#fff" : "#555",
            padding: "8px 16px", fontSize: 13,
            fontWeight: activeTab === tab ? 600 : 400,
            cursor: "pointer", marginBottom: -1,
          }}>
            {label}
            {count !== null && (
              <span style={{ color: activeTab === tab ? "#ff4d00" : "#333", fontSize: 12 }}> ({count})</span>
            )}
          </button>
        ))}
      </div>


      {/* ── Filter bar ── */}
      <div style={{ display: "flex", gap: 10, marginBottom: "1.25rem", flexWrap: "wrap", alignItems: "center" }}>
        <input
          value={search}
          onChange={e => setSearch(e.target.value)}
          placeholder="Search artists..."
          style={{ flex: 1, minWidth: 200, background: "rgba(17,17,17,0.82)", border: "0.5px solid #222", borderRadius: 8, padding: "8px 12px", color: "#fff", fontSize: 13, outline: "none" }}
        />
        <button
          onClick={() => setSweetSpot(s => !s)}
          title="1k–35k listeners · score ≥ 60 · indie/DIY signals · no managers"
          style={{ background: sweetSpot ? "#ff4d00" : "#111", border: sweetSpot ? "1px solid #ff4d00" : "0.5px solid #333", borderRadius: 8, padding: "8px 14px", color: sweetSpot ? "#fff" : "#888", fontSize: 13, cursor: "pointer", fontWeight: sweetSpot ? 600 : 400, whiteSpace: "nowrap" }}
        >
          {sweetSpot ? "Sweet Spot ON" : "Sweet Spot"}
        </button>
        <select value={filterStatus} onChange={e => setFilterStatus(e.target.value)}
          style={{ background: "rgba(17,17,17,0.82)", border: "0.5px solid #222", borderRadius: 8, padding: "8px 12px", color: "#888", fontSize: 13 }}>
          <option value="">All statuses</option>
          {["new","contacted","pitched","signed","ignored"].map(s => <option key={s} value={s}>{s}</option>)}
        </select>
        <select value={filterPlatform} onChange={e => setFilterPlatform(e.target.value)}
          style={{ background: "rgba(17,17,17,0.82)", border: "0.5px solid #222", borderRadius: 8, padding: "8px 12px", color: "#888", fontSize: 13 }}>
          <option value="">All platforms</option>
          <option value="spotify">Spotify</option>
        </select>
        <select value={sortBy} onChange={e => setSortBy(e.target.value)}
          style={{ background: "rgba(17,17,17,0.82)", border: "0.5px solid #222", borderRadius: 8, padding: "8px 12px", color: "#ccc", fontSize: 13 }}>
          <option value="score">Sort: Score</option>
          <option value="listeners">Sort: Listeners</option>
          <option value="followers">Sort: Followers</option>
          <option value="ig_followers">Sort: IG Size</option>
          <option value="name">Sort: Name</option>
        </select>
        <button onClick={() => setSortDir(d => d === "desc" ? "asc" : "desc")}
          title={sortDir === "desc" ? "High → Low" : "Low → High"}
          style={{ background: "rgba(17,17,17,0.82)", border: "0.5px solid #222", borderRadius: 8, padding: "8px 12px", color: "#888", fontSize: 14, cursor: "pointer", minWidth: 38, textAlign: "center" }}>
          {sortDir === "desc" ? "↓" : "↑"}
        </button>
        <div style={{ display: "flex", alignItems: "center", gap: 8, opacity: sweetSpot ? 0.3 : 1 }}>
          <span style={{ color: "#555", fontSize: 12 }}>Min score</span>
          <input type="range" min="0" max="100" value={sweetSpot ? 60 : minScore}
            onChange={e => !sweetSpot && setMinScore(e.target.value)} disabled={sweetSpot} style={{ width: 80 }} />
          <span style={{ color: "#888", fontSize: 12, minWidth: 28 }}>{sweetSpot ? 60 : minScore}</span>
        </div>
        <select
          value={filterSession}
          onChange={e => setFilterSession(e.target.value)}
          style={{ background: "rgba(17,17,17,0.82)", border: "0.5px solid #222", borderRadius: 8, padding: "8px 12px", color: "#888", fontSize: 13, maxWidth: 180 }}
        >
          <option value="">All Batches</option>
          {sessions.map((s, i) => {
            const sid = s.session_id
            const date = sid.length >= 13
              ? `${sid.slice(6,8)}/${sid.slice(4,6)}/${sid.slice(0,4)} ${sid.slice(9,11)}:${sid.slice(11,13)}`
              : sid
            const isOldest = i === sessions.length - 1
            const batchNum = sessions.length - i
            const label = isOldest ? `Testing Batch — ${date}` : `Batch ${batchNum} — ${date}`
            return (
              <option key={sid} value={sid}>
                {label} ({s.count})
              </option>
            )
          })}
        </select>
        <button onClick={() => { loadSessions(); fetchArtists() }} style={{ background: "#222", border: "0.5px solid #333", borderRadius: 8, padding: "8px 16px", color: "#888", fontSize: 13, cursor: "pointer", fontWeight: 500 }}>Refresh</button>
      </div>

      {filterSession && (() => {
        const idx = sessions.findIndex(s => s.session_id === filterSession)
        const s = sessions[idx]
        if (!s) return null
        const isOldest = idx === sessions.length - 1
        const batchNum = sessions.length - idx
        const sid = s.session_id
        const date = sid.length >= 13
          ? `${sid.slice(6,8)}/${sid.slice(4,6)}/${sid.slice(0,4)} at ${sid.slice(9,11)}:${sid.slice(11,13)}`
          : sid
        const batchLabel = isOldest ? "Testing Batch" : `Batch ${batchNum}`
        return (
          <div style={{ background: "#0d0d1a", border: "0.5px solid #2a2a5a", borderRadius: 8, padding: "8px 14px", marginBottom: "1rem", fontSize: 12, color: "#8888ff", display: "flex", alignItems: "center", gap: 10 }}>
            <span style={{ fontWeight: 600 }}>{batchLabel}</span>
            <span style={{ color: "#2a2a5a" }}>·</span>
            <span style={{ color: "#555" }}>Run on {date} · {s.count} leads</span>
            <button onClick={() => setFilterSession("")} style={{ marginLeft: "auto", background: "transparent", border: "0.5px solid #2a2a5a", borderRadius: 6, padding: "2px 10px", color: "#555", fontSize: 11, cursor: "pointer" }}>
              Clear
            </button>
          </div>
        )
      })()}

      {sweetSpot && (
        <div style={{ background: "#1a0e00", border: "0.5px solid #ff4d0033", borderRadius: 8, padding: "8px 14px", marginBottom: "1rem", fontSize: 12, color: "#ff7733", display: "flex", alignItems: "center", gap: 8 }}>
          <span style={{ fontWeight: 600 }}>Sweet Spot active</span>
          <span style={{ color: "#774422" }}>·</span>
          <span style={{ color: "#885533" }}>Indie artists: 1k–35k listeners, score ≥ 60, DIY signals — most likely to need you and actually reply</span>
        </div>
      )}

      {loading && artists.length === 0 ? (
        <div style={{ textAlign: "center", color: "#444", padding: "3rem", fontSize: 14 }}>Scanning leads...</div>
      ) : (
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(280px, 1fr))", gap: 12, opacity: loading ? 0.5 : 1, transition: "opacity 0.15s" }}>
          {displayedArtists.map(a => (
            <ArtistCard
              key={a.id}
              artist={a}
              onClick={() => onSelect(a.id)}
              selected={selectedIds.has(a.id)}
              onSelect={(e) => toggleSelect(a.id, e)}
              batchLabel={!filterSession && a.session_id ? batchLabelMap[a.session_id] : null}
            />
          ))}
          {displayedArtists.length === 0 && (
            <div style={{ gridColumn: "1/-1", textAlign: "center", color: "#444", padding: "3rem", fontSize: 14 }}>
              {activeTab === "verified"
                ? "No verified contacts yet — update artists_instagram.json and click Sync JSON."
                : "No leads found. Run the discovery script to populate leads."}
            </div>
          )}
        </div>
      )}
    </div>
  )
}

function ArtistCard({ artist, onClick, selected, onSelect, batchLabel }) {
  const isFlagged = artist.contact_quality === 'skip'
  const sc = isFlagged ? { bg: "#2a0808", text: "#cc3333" } : (STATUS_COLORS[artist.status] || STATUS_COLORS.new)
  const score = artist.score || 0
  const scoreColor = score >= 70 ? "#4caf50" : score >= 50 ? "#ff9800" : "#666"

  const statusGlow = sc.text + "35"
  const statusBorder = sc.text + "55"

  return (
    <a
      href={`?artist=${artist.id}`}
      onClick={e => { e.preventDefault(); onClick() }}
      style={{
        display: "block", textDecoration: "none",
        background: selected
          ? `radial-gradient(ellipse at top left, ${sc.text}44 0%, #16162a 70%)`
          : `radial-gradient(ellipse at top left, ${statusGlow} 0%, #111 65%)`,
        border: selected ? `1.5px solid #ff4d0077` : `0.5px solid ${statusBorder}`,
        borderRadius: 12, padding: "14px 16px", cursor: "pointer",
        transition: "border-color 0.15s, background 0.15s",
        position: "relative",
      }}
      onMouseEnter={e => { if (!selected) e.currentTarget.style.borderColor = "#333" }}
      onMouseLeave={e => { if (!selected) e.currentTarget.style.borderColor = "#1f1f1f" }}
    >
      {/* Selection checkbox */}
      <div
        onClick={e => { e.preventDefault(); e.stopPropagation(); onSelect(e) }}
        title={selected ? "Deselect" : "Select"}
        style={{
          position: "absolute", top: 10, left: 10,
          width: 26, height: 26, borderRadius: 6,
          border: selected ? "none" : "1.5px solid #2e2e2e",
          background: selected ? "#ff4d00" : "rgba(0,0,0,0.5)",
          cursor: "pointer", display: "flex", alignItems: "center",
          justifyContent: "center", zIndex: 2, flexShrink: 0,
        }}
      >
        {selected && <span style={{ color: "#fff", fontSize: 14, lineHeight: 1, fontWeight: 700 }}>✓</span>}
      </div>

      <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 10, paddingLeft: 36 }}>
        {artist.image_url ? (
          <img src={artist.image_url} alt={artist.name}
            style={{ width: 40, height: 40, borderRadius: "50%", objectFit: "cover", flexShrink: 0 }} />
        ) : (
          <div style={{ width: 40, height: 40, borderRadius: "50%", background: "#1a1a1a", display: "flex", alignItems: "center", justifyContent: "center", color: "#444", fontSize: 14, fontWeight: 600, flexShrink: 0 }}>
            {artist.name?.[0]?.toUpperCase()}
          </div>
        )}
        <div style={{ minWidth: 0 }}>
          <div style={{ color: "#fff", fontWeight: 500, fontSize: 14, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>
            {artist.name}
          </div>
          <div style={{ color: "#555", fontSize: 12 }}>
            {artist.platform}{(() => { const n = artist.listeners || artist.followers || 0; return n > 0 ? ` · ${n.toLocaleString()} listeners` : '' })()}
          </div>
        </div>
        <div style={{ marginLeft: "auto", fontWeight: 600, fontSize: 15, color: scoreColor, flexShrink: 0 }}>
          {score}
        </div>
      </div>

      <div style={{ fontSize: 12, color: "#555", marginBottom: 8, lineHeight: 1.5, height: 34, overflow: "hidden", paddingLeft: 2 }}>
        {artist.score_reason || "Pending analysis"}
      </div>

      {(() => {
        const n = artist.listeners || artist.followers || 0
        if (!n) return null
        const label = n.toLocaleString() + " listeners"
        if (n < 5000)  return <div style={{ fontSize: 11, color: "#4caf50",  marginBottom: 4 }}>Micro · {label}</div>
        if (n < 15000) return <div style={{ fontSize: 11, color: "#8bc34a",  marginBottom: 4 }}>Rising · {label}</div>
        if (n < 35000) return <div style={{ fontSize: 11, color: "#cddc39",  marginBottom: 4 }}>Growing · {label}</div>
        if (n < 60000) return <div style={{ fontSize: 11, color: "#ff9800",  marginBottom: 4 }}>Mid-tier · {label}</div>
        return               <div style={{ fontSize: 11, color: "#f44336",  marginBottom: 4 }}>Established · {label}</div>
      })()}

      {artist.needs && (
        <div style={{ fontSize: 10, marginBottom: 6, color: artist.needs.startsWith("managed") ? "#f44336" : "#66bb6a", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
          {artist.needs.startsWith("managed") ? "⚠ " : "✓ "}{artist.needs}
        </div>
      )}

      <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
        <span style={{ background: sc.bg, color: sc.text, fontSize: 11, padding: "3px 8px", borderRadius: 4 }}>
          {isFlagged ? "flagged" : artist.status}
        </span>
        {artist.instagram && (
          <span style={{ background: "#1a1a2a", color: "#8888ff", fontSize: 11, padding: "3px 8px", borderRadius: 4 }}>
            IG{artist.ig_followers
              ? ` · ${artist.ig_followers >= 1000 ? (artist.ig_followers / 1000).toFixed(1) + 'k' : artist.ig_followers}`
              : ''}
          </span>
        )}
        {artist.facebook && <span style={{ background: "#1a1f2e", color: "#5b9bd5", fontSize: 11, padding: "3px 8px", borderRadius: 4 }}>FB</span>}
        {artist.phone    && <span style={{ background: "#2a1a2a", color: "#bb88ff", fontSize: 11, padding: "3px 8px", borderRadius: 4 }}>Tel</span>}
        {artist.email    && <span style={{ background: "#1a2a1a", color: "#66bb6a", fontSize: 11, padding: "3px 8px", borderRadius: 4 }}>Email</span>}
        {artist.contact_quality === "excellent" && (
          <span style={{ background: "#2a2000", color: "#ffcc00", fontSize: 11, padding: "3px 8px", borderRadius: 4 }}>Hot</span>
        )}
        {artist.contact_quality === "contactless" && (
          <span style={{ background: "#1a1a1a", color: "#444", fontSize: 11, padding: "3px 8px", borderRadius: 4 }}>No Contact</span>
        )}
        {batchLabel && (
          <span style={{ background: "#0d0d1a", color: "#444", fontSize: 10, padding: "3px 8px", borderRadius: 4, marginLeft: "auto" }}>
            {batchLabel}
          </span>
        )}
      </div>
    </a>
  )
}

const DEMO_DATA = [
  { id: "1", name: "Maya Rivers",   platform: "spotify", followers: 12400, score: 84, status: "new",       score_reason: "Active R&B artist, recent releases, no label",              instagram: "mayarivermusic", ig_followers: 8200, email: null, image_url: null },
  { id: "2", name: "Dante Morel",   platform: "youtube", followers: 8200,  score: 76, status: "contacted", score_reason: "Hip-hop artist, high engagement rate",                        instagram: null, email: "dante@gmail.com", image_url: null },
  { id: "3", name: "Zara Bloom",    platform: "deezer",  followers: 31000, score: 68, status: "pitched",   score_reason: "Pop singer with strong fanbase, needs better production",    instagram: "zarabloom", ig_followers: 14700, email: null, image_url: null },
  { id: "4", name: "Kai Summers",   platform: "spotify", followers: 5600,  score: 91, status: "signed",    score_reason: "Incredible vocal talent, very low production quality",       instagram: "kaisummers_", ig_followers: 3100, email: "kai@me.com", image_url: null },
  { id: "5", name: "Leon Baptiste", platform: "youtube", followers: 19800, score: 55, status: "new",       score_reason: "Consistent uploads, R&B with trap influence",                instagram: null, email: null, image_url: null, contact_quality: "contactless" },
  { id: "6", name: "Amara Voss",    platform: "spotify", followers: 7300,  score: 79, status: "new",       score_reason: "Soul/pop crossover, self-produced demos sound amateur",      instagram: "amaravoss", ig_followers: 5900, email: null, image_url: null },
]
