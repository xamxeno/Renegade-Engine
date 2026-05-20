import { useState, useEffect, useCallback, useRef, useMemo } from "react"

const STATUS_COLORS = {
  new:       { bg: "#0d1a0d", text: "#4caf50" },
  contacted: { bg: "#1a1a0d", text: "#cddc39" },
  pitched:   { bg: "#1a0d00", text: "#ff9800" },
  signed:    { bg: "#1a0d1a", text: "#e040fb" },
  ignored:   { bg: "#1a0d0d", text: "#f44336" },
}

export default function VideoLeads({ API, onSelect }) {
  const [artists, setArtists]           = useState([])
  const [loading, setLoading]           = useState(true)
  const [search, setSearch]             = useState("")
  const [filterStatus, setFilterStatus] = useState("")
  const [sortBy, setSortBy]             = useState("score")
  const [sortDir, setSortDir]           = useState("desc")
  const [minScore, setMinScore]         = useState(0)
  const [sessions, setSessions]         = useState([])
  const [filterSession, setFilterSession] = useState("")
  const [selectedIds, setSelectedIds]   = useState(new Set())
  const [activeTab, setActiveTab]       = useState("all")
  const [sourceFilter, setSourceFilter] = useState("all")

  const [discoveryOpen, setDiscoveryOpen]         = useState(false)
  const [discoveryRunning, setDiscoveryRunning]   = useState(false)
  const [discoveryLog, setDiscoveryLog]           = useState([])
  const [discoveryProgress, setDiscoveryProgress] = useState(0)

  const [flushCreatorsOpen, setFlushCreatorsOpen] = useState(false)
  const [flushCount, setFlushCount]     = useState(null)
  const [flushConfirm, setFlushConfirm] = useState(false)
  const [flushing, setFlushing]         = useState(false)

  const [scoring, setScoring]           = useState(false)
  const [bulkBusy, setBulkBusy]         = useState(false)
  const [enrichStatus, setEnrichStatus] = useState(null)

  const searchTimer   = useRef(null)
  const searchMounted = useRef(false)
  const fetchSeq      = useRef(0)

  // ── Data fetching ──────────────────────────────────────────────────────────
  const fetchArtists = useCallback(async () => {
    const seq = ++fetchSeq.current
    setLoading(true)
    try {
      const params = new URLSearchParams()
      params.set("platform", "creator")
      if (filterStatus)  params.set("status", filterStatus)
      if (search)        params.set("search", search)
      if (filterSession) params.set("session_id", filterSession)
      if (minScore > 0)  params.set("min_score", minScore)
      const r    = await fetch(`${API}/api/artists?${params}`)
      const data = await r.json()
      if (seq === fetchSeq.current)
        setArtists(Array.isArray(data) ? data : (data?.artists || []))
    } catch {
      if (seq === fetchSeq.current) setArtists([])
    }
    if (seq === fetchSeq.current) setLoading(false)
  }, [API, filterStatus, filterSession, minScore, search])

  const loadSessions = useCallback(async () => {
    try {
      const r    = await fetch(`${API}/api/sessions?platform=creator`)
      const data = await r.json()
      setSessions(Array.isArray(data?.sessions) ? data.sessions : [])
    } catch {}
  }, [API])

  useEffect(() => { fetchArtists(); loadSessions() }, [filterStatus, filterSession, minScore])

  useEffect(() => {
    if (!searchMounted.current) { searchMounted.current = true; return }
    clearTimeout(searchTimer.current)
    searchTimer.current = setTimeout(fetchArtists, 380)
    return () => clearTimeout(searchTimer.current)
  }, [search])

  // Enrichment worker status poll
  useEffect(() => {
    const poll = async () => {
      const r = await fetch(`${API}/api/enrich/status`).catch(() => null)
      if (!r?.ok) return
      const d = await r.json()
      setEnrichStatus((d.running || d.busy) ? d : null)
    }
    poll()
    const t = setInterval(poll, 8000)
    return () => clearInterval(t)
  }, [API])

  // ── Creator discovery stream ───────────────────────────────────────────────
  const streamDiscovery = async (fresh) => {
    setDiscoveryRunning(true)
    if (fresh) { setDiscoveryLog([]); setDiscoveryProgress(0) }
    try {
      const r      = await fetch(`${API}/api/content-discover`, { method: 'POST' })
      const reader = r.body.getReader()
      const dec    = new TextDecoder()
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
            if (msg.log)                    setDiscoveryLog(l => [...l, msg.log])
            if (msg.progress !== undefined) setDiscoveryProgress(msg.progress)
            if (msg.done)                   { fetchArtists(); loadSessions() }
          } catch { setDiscoveryLog(l => [...l, line]) }
        }
      }
    } catch (e) { setDiscoveryLog(l => [...l, `Error: ${e.message}`]) }
    setDiscoveryRunning(false)
  }

  useEffect(() => {
    fetch(`${API}/api/content-discover/status`)
      .then(r => r.json())
      .then(d => {
        if (d.running) {
          setDiscoveryOpen(true)
          setDiscoveryLog([`● Reconnected — Creator discovery running (${d.logLines} lines logged)`])
          setDiscoveryProgress(d.progress || 0)
          streamDiscovery(false)
        }
      }).catch(() => {})
  }, [API])

  // ── Tab filtering (client-side) ────────────────────────────────────────────
  const allCreators    = useMemo(() => artists.filter(a => a.contact_quality !== 'skip'), [artists])
  const contactLeads   = useMemo(() => allCreators.filter(a => a.instagram || a.email), [allCreators])
  const noContactLeads = useMemo(() => allCreators.filter(a => a.contact_quality === 'contactless'), [allCreators])
  const flaggedLeads   = useMemo(() => artists.filter(a => a.contact_quality === 'skip'), [artists])

  const TAB_DEFS = [
    ['all',        'All Leads',   allCreators.length],
    ['contact',    'Has Contact', contactLeads.length],
    ['no_contact', 'No Contact',  noContactLeads.length],
    ['flagged',    'Flagged',     flaggedLeads.length],
  ]

  const tabArtists = useMemo(() => ({
    all: allCreators, contact: contactLeads,
    no_contact: noContactLeads, flagged: flaggedLeads,
  }[activeTab] ?? allCreators), [activeTab, allCreators, contactLeads, noContactLeads, flaggedLeads])

  const sourceFiltered = useMemo(() => {
    if (sourceFilter === 'all') return tabArtists
    return tabArtists.filter(a => {
      const url = (a.profile_url || '').toLowerCase()
      if (sourceFilter === 'youtube')   return url.includes('youtube')
      if (sourceFilter === 'instagram') return url.includes('instagram')
      if (sourceFilter === 'twitter')   return url.includes('twitter') || url.includes('x.com')
      return true
    })
  }, [tabArtists, sourceFilter])

  const sorted = useMemo(() => [...sourceFiltered].sort((a, b) => {
    if (sortBy === 'name') {
      const cmp = (a.name || '').localeCompare(b.name || '')
      return sortDir === 'desc' ? -cmp : cmp
    }
    const va = a[sortBy] || 0, vb = b[sortBy] || 0
    return sortDir === 'desc' ? vb - va : va - vb
  }), [sourceFiltered, sortBy, sortDir])

  // ── Computed stats ─────────────────────────────────────────────────────────
  const computedStats = useMemo(() => {
    const active = artists.filter(a => a.contact_quality !== 'skip')
    return {
      total:     active.length,
      contacted: active.filter(a => a.status === 'contacted').length,
      pitched:   active.filter(a => a.status === 'pitched').length,
      signed:    active.filter(a => a.status === 'signed').length,
      avg_score: active.length
        ? Math.round(active.reduce((s, a) => s + (a.score || 0), 0) / active.length)
        : 0,
    }
  }, [artists])

  // ── Selection ──────────────────────────────────────────────────────────────
  const clearSelection = () => setSelectedIds(new Set())

  const selectAll = () => {
    if (selectedIds.size === sorted.length && sorted.length > 0) { clearSelection(); return }
    setSelectedIds(new Set(sorted.map(a => a.id)))
  }

  const toggleSelect = (id, e) => {
    e.stopPropagation()
    e.preventDefault()
    setSelectedIds(prev => {
      const n = new Set(prev)
      n.has(id) ? n.delete(id) : n.add(id)
      return n
    })
  }

  // ── Bulk actions ───────────────────────────────────────────────────────────
  const bulkStatus = async (status) => {
    const ids = [...selectedIds]; if (!ids.length) return
    setBulkBusy(true)
    await fetch(`${API}/api/artists/batch`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ ids, action: 'status', status }),
    }).catch(() => {})
    clearSelection(); fetchArtists(); loadSessions(); setBulkBusy(false)
  }

  const bulkFlag = async () => {
    const ids = [...selectedIds]; if (!ids.length) return
    setBulkBusy(true)
    await fetch(`${API}/api/artists/batch`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ ids, action: 'delete' }),
    }).catch(() => {})
    clearSelection(); fetchArtists(); loadSessions(); setBulkBusy(false)
  }

  const enrichSelected = async () => {
    const ids = [...selectedIds]; if (!ids.length) return
    setBulkBusy(true)
    await fetch(`${API}/api/enrich/batch-selected`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ ids }),
    }).catch(() => {})
    clearSelection(); setBulkBusy(false)
  }

  const scoreSelected = async () => {
    const ids = [...selectedIds]; if (!ids.length) return
    setBulkBusy(true)
    await fetch(`${API}/api/score`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ ids }),
    }).catch(() => {})
    await fetchArtists(); clearSelection(); setBulkBusy(false)
  }

  const scoreAll = async () => {
    setScoring(true)
    const ids = artists.map(a => a.id)
    await fetch(`${API}/api/score`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ ids }),
    }).catch(() => {})
    await fetchArtists(); setScoring(false)
  }

  // ── Flush creators ─────────────────────────────────────────────────────────
  const openFlushCreators = async () => {
    setFlushCreatorsOpen(true); setFlushConfirm(false)
    const r = await fetch(`${API}/api/flush/creators/preview`).catch(() => null)
    const d = r ? await r.json() : {}
    setFlushCount(d.count ?? 0)
  }

  const doFlushCreators = async () => {
    if (!flushConfirm) { setFlushConfirm(true); return }
    setFlushing(true)
    await fetch(`${API}/api/flush/creators`, { method: 'DELETE' }).catch(() => {})
    setFlushing(false); setFlushCreatorsOpen(false); setFlushCount(null)
    fetchArtists(); loadSessions()
  }

  const windowWidth = window.innerWidth
  const mob = windowWidth < 600

  const btnStyle = (bg, border, color, extra = {}) => ({
    background: bg, border, borderRadius: 8,
    padding: mob ? "7px 10px" : "8px 16px",
    color, fontSize: mob ? 11 : 13,
    cursor: "pointer", fontWeight: 500,
    whiteSpace: "nowrap", ...extra
  })

  // ── Render ─────────────────────────────────────────────────────────────────
  return (
    <div style={{ padding: "2rem 2rem calc(2rem + env(safe-area-inset-bottom))", maxWidth: 1280, margin: "0 auto", minHeight: "100vh", position: "relative", zIndex: 1 }}>

      {/* ── Creator Discovery Modal ── */}
      {discoveryOpen && (
        <div style={{ position: "fixed", inset: 0, background: "rgba(0,0,0,0.92)", zIndex: 1000, display: "flex", alignItems: "center", justifyContent: "center" }}>
          <div style={{ background: "rgba(13,13,13,0.88)", border: "1px solid #00ccaa44", borderRadius: 16, padding: "2rem", width: "min(620px, 92vw)", display: "flex", flexDirection: "column", gap: 16 }}>
            <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
              <div>
                <div style={{ color: "#fff", fontWeight: 700, fontSize: 17, letterSpacing: "-0.02em" }}>Creator Discovery</div>
                <div style={{ color: "#555", fontSize: 12, marginTop: 3 }}>Finds YouTube & Instagram creators who need editors · 5K–500K subscribers</div>
              </div>
              {!discoveryRunning && (
                <button onClick={() => { setDiscoveryOpen(false); setDiscoveryLog([]); setDiscoveryProgress(0) }}
                  style={{ background: "transparent", border: "none", color: "#555", fontSize: 22, cursor: "pointer" }}>×</button>
              )}
            </div>
            <div style={{ background: "rgba(17,17,17,0.82)", borderRadius: 99, height: 6, overflow: "hidden" }}>
              <div style={{ height: "100%", width: `${discoveryProgress}%`, background: "linear-gradient(90deg,#006655,#00eebb)", borderRadius: 99, transition: "width 0.4s ease" }} />
            </div>
            <div style={{ color: "#444", fontSize: 11, textAlign: "right", marginTop: -10 }}>{discoveryProgress}%</div>
            <div
              ref={el => { if (el) el.scrollTop = el.scrollHeight }}
              style={{ background: "#050505", border: "0.5px solid #1a1a1a", borderRadius: 8, padding: "12px", height: 260, overflowY: "auto", fontFamily: "monospace", fontSize: 11, color: "#555", display: "flex", flexDirection: "column", gap: 2 }}
            >
              {discoveryLog.length === 0 && !discoveryRunning && (
                <span style={{ color: "#333" }}>Click Start to search YouTube for aesthetic lifestyle creators.</span>
              )}
              {discoveryLog.map((line, i) => (
                <div key={i} style={{ color: line.includes("ERROR") || line.includes("error") ? "#f44336" : line.includes("PASS") || line.includes("complete") || line.includes("Synced") ? "#4caf50" : line.includes("skip") || line.includes("blocked") ? "#555" : "#888" }}>{line}</div>
              ))}
              {discoveryRunning && <div style={{ color: "#00ccaa", animation: "pulse 1s infinite" }}>● running...</div>}
            </div>
            <div style={{ display: "flex", gap: 10, justifyContent: "flex-end", flexWrap: "wrap" }}>
              {!discoveryRunning && (
                <button onClick={() => { setDiscoveryOpen(false); setDiscoveryLog([]); setDiscoveryProgress(0) }}
                  style={{ background: "#1a1a1a", border: "0.5px solid #333", borderRadius: 8, padding: "9px 20px", color: "#888", fontSize: 13, cursor: "pointer" }}>Close</button>
              )}
              {discoveryRunning && (
                <button onClick={() => setDiscoveryOpen(false)}
                  style={{ background: "#001a1a", border: "0.5px solid #003333", borderRadius: 8, padding: "9px 20px", color: "#00aa88", fontSize: 13, cursor: "pointer" }}>Run in Background</button>
              )}
              <button
                onClick={() => streamDiscovery(true)}
                disabled={discoveryRunning}
                style={{ background: discoveryRunning ? "#1a1a2a" : "linear-gradient(135deg,#006655,#00ccaa)", border: "none", borderRadius: 8, padding: "9px 26px", color: discoveryRunning ? "#444" : "#fff", fontSize: 13, fontWeight: 700, cursor: discoveryRunning ? "default" : "pointer", letterSpacing: "0.02em" }}
              >
                {discoveryRunning ? "Running..." : "Start Discovery"}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* ── Flush All Creators Modal ── */}
      {flushCreatorsOpen && (
        <div style={{ position: "fixed", inset: 0, background: "rgba(0,0,0,0.92)", zIndex: 1000, display: "flex", alignItems: "center", justifyContent: "center" }}>
          <div style={{ background: "rgba(13,5,5,0.96)", border: "1px solid #cc222244", borderRadius: 16, padding: "2rem", width: "min(480px, 92vw)", display: "flex", flexDirection: "column", gap: 16 }}>
            <div style={{ color: "#fff", fontWeight: 700, fontSize: 18, letterSpacing: "-0.02em" }}>Flush All Creator Leads</div>
            <div style={{ color: "#666", fontSize: 13, lineHeight: 1.6 }}>
              Permanently deletes <strong style={{ color: "#ff4444" }}>every</strong> creator lead — no exceptions.<br />
              Use this to wipe the slate before a fresh discovery run.
            </div>
            <div style={{ background: "#1a0000", border: "0.5px solid #3a1010", borderRadius: 8, padding: "14px 18px" }}>
              {flushCount === null
                ? <div style={{ color: "#555", fontSize: 14 }}>Loading count...</div>
                : <div style={{ color: "#ff4444", fontSize: 24, fontWeight: 700 }}>{flushCount} creator leads will be deleted</div>
              }
            </div>
            <div style={{ display: "flex", gap: 10, justifyContent: "flex-end" }}>
              <button
                onClick={() => { setFlushCreatorsOpen(false); setFlushConfirm(false) }}
                style={{ background: "#1a1a1a", border: "0.5px solid #333", borderRadius: 8, padding: "9px 20px", color: "#888", fontSize: 13, cursor: "pointer" }}>
                Cancel
              </button>
              <button
                onClick={doFlushCreators}
                disabled={flushing || flushCount === 0}
                style={{ background: flushing ? "#333" : flushConfirm ? "#aa1111" : "#cc1111", border: "none", borderRadius: 8, padding: "9px 22px", color: "#fff", fontSize: 13, fontWeight: 700, cursor: (flushing || flushCount === 0) ? "default" : "pointer" }}
              >
                {flushing ? "Deleting..." : flushConfirm ? "Click Again to Confirm" : `Delete ${flushCount ?? "?"} Leads`}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* ── Header ── */}
      <div style={{ display: "flex", flexDirection: mob ? "column" : "row", alignItems: mob ? "flex-start" : "center", justifyContent: "space-between", gap: mob ? 10 : 0, marginBottom: "1.5rem" }}>
        <div>
          <h1 style={{ fontSize: 22, fontWeight: 700, color: "#fff", margin: 0, letterSpacing: "-0.04em", background: "linear-gradient(90deg,#fff 60%,#00ccaa)", WebkitBackgroundClip: "text", WebkitTextFillColor: "transparent" }}>Video Leads</h1>
          <p style={{ color: "#444", fontSize: 12, margin: "4px 0 0", letterSpacing: "0.06em", textTransform: "uppercase" }}>Podcast Hosts · Reel Creators · Content Creators</p>
        </div>
        <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
          <button onClick={() => { fetchArtists(); loadSessions() }} style={btnStyle("#222", "0.5px solid #333", "#888")}>Refresh</button>
          <button
            onClick={scoreAll}
            disabled={scoring}
            style={btnStyle("#1a1a0a", `0.5px solid ${scoring ? "#222" : "#4a4a1a"}`, scoring ? "#333" : "#cccc44", { cursor: scoring ? "default" : "pointer" })}
          >
            {scoring ? "Scoring..." : "Score All"}
          </button>
          <button
            onClick={() => setDiscoveryOpen(true)}
            style={btnStyle("linear-gradient(135deg,#001a1a,#003333)", `1px solid ${discoveryRunning ? "#00ccaaaa" : "#00ccaa44"}`, "#00eebb", { fontWeight: 700, letterSpacing: "0.02em", position: "relative" })}
          >
            {discoveryRunning && <span style={{ position: "absolute", top: 5, right: 5, width: 6, height: 6, borderRadius: "50%", background: "#4caf50", animation: "pulse 1.5s infinite" }} />}
            + Creator Discovery
          </button>
          <button onClick={openFlushCreators} style={btnStyle("linear-gradient(135deg,#1a0000,#330000)", "1px solid #cc222244", "#ff4444", { fontWeight: 700 })}>
            Flush All
          </button>
        </div>
      </div>

      {/* ── Enrichment status bar ── */}
      {enrichStatus && (
        <div style={{ background: "#0a1a0a", border: "0.5px solid #00aa4444", borderRadius: 8, padding: "8px 14px", marginBottom: "0.75rem", fontSize: 12, color: "#4caf50", display: "flex", alignItems: "center", gap: 10 }}>
          <span style={{ width: 7, height: 7, borderRadius: "50%", background: "#4caf50", display: "inline-block", animation: "pulse 1.5s infinite" }} />
          <span>Searching contacts for <strong>{enrichStatus.current || "artist"}</strong></span>
          {enrichStatus.remaining > 0 && <span style={{ color: "#2a5a2a" }}>{enrichStatus.remaining} remaining</span>}
        </div>
      )}

      {/* ── Stats ── */}
      <div style={{ display: "grid", gridTemplateColumns: "repeat(5, 1fr)", gap: 12, marginBottom: "1.5rem" }}>
        {[
          ["Total",     computedStats.total],
          ["Contacted", computedStats.contacted],
          ["Pitched",   computedStats.pitched],
          ["Signed",    computedStats.signed],
          ["Avg Score", computedStats.avg_score ? `${computedStats.avg_score}/100` : "—"],
        ].map(([label, val]) => (
          <div key={label} style={{ background: "linear-gradient(135deg,#111 0%,#0d0d0d 100%)", border: "0.5px solid #1f1f1f", borderRadius: 12, padding: "16px 18px" }}>
            <div style={{ color: "#444", fontSize: 11, marginBottom: 8, letterSpacing: "0.08em", textTransform: "uppercase" }}>{label}</div>
            <div style={{ color: "#fff", fontSize: 22, fontWeight: 700, letterSpacing: "-0.03em" }}>{val}</div>
          </div>
        ))}
      </div>

      {/* ── Tabs ── */}
      <div style={{ display: "flex", gap: 4, marginBottom: "1rem", flexWrap: "wrap" }}>
        {TAB_DEFS.map(([key, label, count]) => (
          <button
            key={key}
            onClick={() => { setActiveTab(key); clearSelection() }}
            style={{ padding: "6px 16px", borderRadius: 20, border: "1px solid", background: activeTab === key ? "#00ccaa22" : "transparent", borderColor: activeTab === key ? "#00ccaa" : "#333", color: activeTab === key ? "#00eebb" : "#666", cursor: "pointer", fontSize: 13, fontWeight: activeTab === key ? 600 : 400 }}
          >
            {label} <span style={{ opacity: 0.6 }}>({count})</span>
          </button>
        ))}
      </div>

      {/* ── Filter bar ── */}
      <div style={{ display: "flex", gap: 10, marginBottom: "1.25rem", flexWrap: "wrap", alignItems: "center" }}>
        <div
          onClick={selectAll}
          title="Select all"
          style={{ width: 18, height: 18, borderRadius: 4, border: `1.5px solid ${selectedIds.size === sorted.length && sorted.length > 0 ? "#00ccaa" : "#333"}`, background: selectedIds.size === sorted.length && sorted.length > 0 ? "#00ccaa22" : "transparent", cursor: "pointer", display: "flex", alignItems: "center", justifyContent: "center", flexShrink: 0 }}
        >
          {selectedIds.size === sorted.length && sorted.length > 0 && <span style={{ color: "#00ccaa", fontSize: 11 }}>✓</span>}
        </div>
        <input
          value={search}
          onChange={e => setSearch(e.target.value)}
          placeholder="Search creators..."
          style={{ flex: 1, minWidth: 180, background: "rgba(17,17,17,0.82)", border: "0.5px solid #222", borderRadius: 8, padding: "8px 12px", color: "#fff", fontSize: 13, outline: "none" }}
        />
        <select value={filterStatus} onChange={e => setFilterStatus(e.target.value)}
          style={{ background: "rgba(17,17,17,0.82)", border: "0.5px solid #222", borderRadius: 8, padding: "8px 12px", color: "#888", fontSize: 13 }}>
          <option value="">All statuses</option>
          {["new","contacted","pitched","signed","ignored"].map(s => <option key={s} value={s}>{s}</option>)}
        </select>
        <select value={sourceFilter} onChange={e => setSourceFilter(e.target.value)}
          style={{ background: "rgba(17,17,17,0.82)", border: "0.5px solid #222", borderRadius: 8, padding: "8px 12px", color: "#888", fontSize: 13 }}>
          <option value="all">All Sources</option>
          <option value="youtube">YouTube</option>
          <option value="instagram">Instagram</option>
          <option value="twitter">Twitter / X</option>
        </select>
        <select value={sortBy} onChange={e => setSortBy(e.target.value)}
          style={{ background: "rgba(17,17,17,0.82)", border: "0.5px solid #222", borderRadius: 8, padding: "8px 12px", color: "#ccc", fontSize: 13 }}>
          <option value="score">Sort: Score</option>
          <option value="followers">Sort: Followers</option>
          <option value="ig_followers">Sort: IG Size</option>
          <option value="name">Sort: Name</option>
        </select>
        <button
          onClick={() => setSortDir(d => d === "desc" ? "asc" : "desc")}
          style={{ background: "rgba(17,17,17,0.82)", border: "0.5px solid #222", borderRadius: 8, padding: "8px 12px", color: "#888", fontSize: 14, cursor: "pointer", minWidth: 38, textAlign: "center" }}
        >
          {sortDir === "desc" ? "↓" : "↑"}
        </button>
        <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
          <span style={{ color: "#555", fontSize: 12 }}>Min</span>
          <input type="range" min="0" max="100" value={minScore} onChange={e => setMinScore(e.target.value)} style={{ width: 80 }} />
          <span style={{ color: "#888", fontSize: 12, minWidth: 28 }}>{minScore}</span>
        </div>
        <select value={filterSession} onChange={e => setFilterSession(e.target.value)}
          style={{ background: "rgba(17,17,17,0.82)", border: "0.5px solid #222", borderRadius: 8, padding: "8px 12px", color: "#888", fontSize: 13, maxWidth: 200 }}>
          <option value="">All Batches</option>
          {sessions.map((s, i) => {
            const sid  = s.session_id
            const date = sid.length >= 15
              ? `${sid.slice(8,10)}/${sid.slice(6,8)} ${sid.slice(11,13)}:${sid.slice(13,15)}`
              : sid
            return <option key={sid} value={sid}>Batch {sessions.length - i} · {date} ({s.count})</option>
          })}
        </select>
      </div>

      {/* ── Bulk actions bar ── */}
      {selectedIds.size > 0 && (
        <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: "1rem", background: "rgba(0,204,170,0.06)", border: "0.5px solid #00ccaa33", borderRadius: 10, padding: "10px 14px", flexWrap: "wrap" }}>
          <span style={{ color: "#00ccaa", fontSize: 13, fontWeight: 600, marginRight: 4 }}>{selectedIds.size} selected</span>
          <button onClick={() => bulkStatus("contacted")} disabled={bulkBusy} style={{ background: "#1a1a0d", border: "0.5px solid #cddc3944", borderRadius: 7, padding: "6px 14px", color: "#cddc39", fontSize: 12, cursor: "pointer", fontWeight: 500 }}>Contacted</button>
          <button onClick={() => bulkStatus("pitched")}   disabled={bulkBusy} style={{ background: "#1a0d00", border: "0.5px solid #ff980044", borderRadius: 7, padding: "6px 14px", color: "#ff9800", fontSize: 12, cursor: "pointer", fontWeight: 500 }}>Pitched</button>
          <button onClick={() => bulkStatus("signed")}    disabled={bulkBusy} style={{ background: "#1a0d1a", border: "0.5px solid #e040fb44", borderRadius: 7, padding: "6px 14px", color: "#e040fb", fontSize: 12, cursor: "pointer", fontWeight: 500 }}>Signed</button>
          <button onClick={() => bulkStatus("ignored")}   disabled={bulkBusy} style={{ background: "#1a0d0d", border: "0.5px solid #f4433644", borderRadius: 7, padding: "6px 14px", color: "#f44336", fontSize: 12, cursor: "pointer", fontWeight: 500 }}>Ignore</button>
          <div style={{ width: 1, height: 22, background: "#2a2a2a" }} />
          <button onClick={enrichSelected} disabled={bulkBusy} style={{ background: "#0a1a0a", border: "0.5px solid #1a4a1a44", borderRadius: 7, padding: "6px 14px", color: "#4caf50", fontSize: 12, cursor: bulkBusy ? "default" : "pointer", fontWeight: 500 }}>Enrich</button>
          <button onClick={scoreSelected}  disabled={bulkBusy} style={{ background: "#1a1a0a", border: "0.5px solid #4a4a1a44", borderRadius: 7, padding: "6px 14px", color: "#cccc44", fontSize: 12, cursor: bulkBusy ? "default" : "pointer", fontWeight: 500 }}>Score</button>
          <button onClick={bulkFlag} disabled={bulkBusy} style={{ background: "#1a0808", border: "0.5px solid #cc333344", borderRadius: 7, padding: "6px 14px", color: "#cc3333", fontSize: 12, cursor: "pointer", fontWeight: 500 }}>🚩 Flag</button>
          <button onClick={clearSelection} style={{ background: "transparent", border: "none", color: "#555", fontSize: 12, cursor: "pointer", marginLeft: "auto" }}>Clear</button>
        </div>
      )}

      {/* ── Lead grid ── */}
      {loading && artists.length === 0 ? (
        <div style={{ textAlign: "center", color: "#444", padding: "3rem", fontSize: 14 }}>Loading creator leads...</div>
      ) : (
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(280px, 1fr))", gap: 12, opacity: loading ? 0.5 : 1, transition: "opacity 0.15s" }}>
          {sorted.map(a => (
            <CreatorCard
              key={a.id}
              artist={a}
              onClick={() => onSelect(a.id)}
              selected={selectedIds.has(a.id)}
              onSelect={(e) => toggleSelect(a.id, e)}
            />
          ))}
          {sorted.length === 0 && !loading && (
            <div style={{ gridColumn: "1/-1", textAlign: "center", color: "#444", padding: "3rem", fontSize: 14 }}>
              {artists.length > 0
                ? "No leads match the current filters."
                : "No creator leads yet. Click + Creator Discovery to find YouTube creators."}
            </div>
          )}
        </div>
      )}
    </div>
  )
}

function CreatorCard({ artist, onClick, selected, onSelect }) {
  const isFlagged  = artist.contact_quality === 'skip'
  const sc         = isFlagged ? { bg: "#2a0808", text: "#cc3333" } : (STATUS_COLORS[artist.status] || STATUS_COLORS.new)
  const score      = artist.score || 0
  const scoreColor = score >= 70 ? "#4caf50" : score >= 50 ? "#ff9800" : "#666"

  const url         = (artist.profile_url || '').toLowerCase()
  const sourceLabel = url.includes('youtube') ? 'YouTube' : url.includes('twitter') || url.includes('x.com') ? 'Twitter/X' : 'Instagram'
  const profileUrl  = artist.profile_url || (artist.instagram ? `https://www.instagram.com/${artist.instagram}/` : null)

  return (
    <div
      onClick={onClick}
      style={{
        background: selected ? "rgba(0,204,170,0.06)" : "rgba(13,13,13,0.82)",
        border: `0.5px solid ${selected ? "#00ccaa55" : isFlagged ? "#3a1515" : "#1f1f1f"}`,
        borderRadius: 12, padding: "14px 16px",
        cursor: "pointer", transition: "border-color 0.15s, background 0.15s",
        position: "relative",
      }}
    >
      <div
        onClick={onSelect}
        style={{ position: "absolute", top: 10, right: 10, width: 16, height: 16, borderRadius: 4, border: `1.5px solid ${selected ? "#00ccaa" : "#333"}`, background: selected ? "#00ccaa22" : "transparent", cursor: "pointer", display: "flex", alignItems: "center", justifyContent: "center" }}
      >
        {selected && <span style={{ color: "#00ccaa", fontSize: 10, lineHeight: 1 }}>✓</span>}
      </div>

      <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 10 }}>
        {artist.image_url ? (
          <img src={artist.image_url} alt="" style={{ width: 40, height: 40, borderRadius: "50%", objectFit: "cover", flexShrink: 0 }} onError={e => { e.target.style.display = "none" }} />
        ) : (
          <div style={{ width: 40, height: 40, borderRadius: "50%", background: "linear-gradient(135deg,#006655,#00ccaa)", display: "flex", alignItems: "center", justifyContent: "center", fontSize: 16, fontWeight: 700, color: "#fff", flexShrink: 0 }}>
            {artist.name?.[0]?.toUpperCase()}
          </div>
        )}
        <div style={{ minWidth: 0 }}>
          <div style={{ color: "#fff", fontWeight: 500, fontSize: 14, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>{artist.name}</div>
          <div style={{ color: "#555", fontSize: 12 }}>
            {sourceLabel}{artist.followers ? ` · ${artist.followers.toLocaleString()} ${sourceLabel === 'YouTube' ? 'subs' : 'followers'}` : ""}
          </div>
        </div>
        <div style={{ marginLeft: "auto", fontWeight: 600, fontSize: 15, color: scoreColor, flexShrink: 0 }}>{score || "—"}</div>
      </div>

      <div style={{ fontSize: 12, color: "#555", marginBottom: 8, lineHeight: 1.5, height: 34, overflow: "hidden", paddingLeft: 2 }}>
        {artist.score_reason || "Pending analysis"}
      </div>

      <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
        <span style={{ background: sc.bg, color: sc.text, fontSize: 11, padding: "3px 8px", borderRadius: 4 }}>
          {isFlagged ? "flagged" : artist.status}
        </span>
        <span style={{ background: "#001a1a", color: "#00aa88", fontSize: 11, padding: "3px 8px", borderRadius: 4 }}>
          {sourceLabel}
        </span>
        {artist.email    && <span style={{ background: "#1a2a1a", color: "#66bb6a", fontSize: 11, padding: "3px 8px", borderRadius: 4 }}>Email</span>}
        {artist.instagram && <span style={{ background: "#1a1a2a", color: "#8888ff", fontSize: 11, padding: "3px 8px", borderRadius: 4 }}>IG</span>}
        {profileUrl && (
          <a
            href={profileUrl}
            target="_blank"
            rel="noreferrer"
            onClick={e => e.stopPropagation()}
            style={{ background: "#1a1a1a", color: "#555", fontSize: 11, padding: "3px 8px", borderRadius: 4, textDecoration: "none", marginLeft: "auto" }}
          >
            Profile ↗
          </a>
        )}
      </div>
    </div>
  )
}
