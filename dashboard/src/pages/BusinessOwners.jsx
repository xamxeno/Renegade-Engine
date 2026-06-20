import { useState, useEffect, useCallback, useRef, useMemo } from "react"

const STATUS_COLORS = {
  new:       { bg: "#0d1a0d", text: "#4caf50" },
  contacted: { bg: "#1a1a0d", text: "#cddc39" },
  pitched:   { bg: "#1a0d00", text: "#ff9800" },
  signed:    { bg: "#1a0d1a", text: "#e040fb" },
  ignored:   { bg: "#1a0d0d", text: "#f44336" },
}

const TYPE_COLORS = {
  restaurant:   "#ff6b35",
  cafe:         "#c8935a",
  gym:          "#4caf50",
  retail:       "#2196f3",
  "gas station":"#ffc107",
  institute:    "#9c27b0",
  farmhouse:    "#8bc34a",
  beauty:       "#e91e63",
  hospitality:  "#00bcd4",
  business:     "#607d8b",
}

export default function BusinessOwners({ API, onSelect }) {
  const [owners, setOwners]             = useState([])
  const [loading, setLoading]           = useState(true)
  const [search, setSearch]             = useState("")
  const [filterStatus, setFilterStatus] = useState("")
  const [filterType, setFilterType]     = useState("")
  const [filterSession, setFilterSession] = useState("")
  const [sortBy, setSortBy]             = useState("discovered_at")
  const [sortDir, setSortDir]           = useState("desc")
  const [sessions, setSessions]         = useState([])

  const [discoveryOpen, setDiscoveryOpen]         = useState(false)
  const [discoveryRunning, setDiscoveryRunning]   = useState(false)
  const [discoveryLog, setDiscoveryLog]           = useState([])
  const [discoveryProgress, setDiscoveryProgress] = useState(0)

  const searchTimer   = useRef(null)
  const searchMounted = useRef(false)
  const fetchSeq      = useRef(0)
  const logRef        = useRef(null)

  // ── Data fetching ────────────────────────────────────────────────────────────
  const fetchOwners = useCallback(async () => {
    const seq = ++fetchSeq.current
    setLoading(true)
    try {
      const params = new URLSearchParams()
      params.set("platform", "business")
      if (filterStatus)  params.set("status", filterStatus)
      if (filterSession) params.set("session_id", filterSession)
      if (search)        params.set("search", search)
      const r    = await fetch(`${API}/api/artists?${params}`)
      const data = await r.json()
      if (seq === fetchSeq.current)
        setOwners(Array.isArray(data) ? data : (data?.artists || []))
    } catch {
      if (seq === fetchSeq.current) setOwners([])
    }
    if (seq === fetchSeq.current) setLoading(false)
  }, [API, filterStatus, filterSession, search])

  const loadSessions = useCallback(async () => {
    try {
      const r    = await fetch(`${API}/api/sessions?platform=business`)
      const data = await r.json()
      setSessions(Array.isArray(data?.sessions) ? data.sessions : [])
    } catch {}
  }, [API])

  useEffect(() => { fetchOwners(); loadSessions() }, [filterStatus, filterSession])

  useEffect(() => {
    if (!searchMounted.current) { searchMounted.current = true; return }
    clearTimeout(searchTimer.current)
    searchTimer.current = setTimeout(fetchOwners, 380)
    return () => clearTimeout(searchTimer.current)
  }, [search])

  // Auto-scroll discovery log
  useEffect(() => {
    if (logRef.current) logRef.current.scrollTop = logRef.current.scrollHeight
  }, [discoveryLog])

  // ── Discovery stream ─────────────────────────────────────────────────────────
  const streamDiscovery = async (fresh) => {
    setDiscoveryRunning(true)
    if (fresh) { setDiscoveryLog([]); setDiscoveryProgress(0) }
    try {
      const r      = await fetch(`${API}/api/business-discover`, { method: 'POST' })
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
            if (msg.ping) continue
            if (msg.log)                    setDiscoveryLog(l => [...l, msg.log])
            if (msg.progress !== undefined) setDiscoveryProgress(msg.progress)
            if (msg.done)                   { fetchOwners(); loadSessions() }
          } catch { setDiscoveryLog(l => [...l, line]) }
        }
      }
    } catch (e) {
      try {
        const st = await fetch(`${API}/api/business-discover/status`).then(r => r.json())
        if (st.running) {
          setDiscoveryLog(l => [...l, '● Connection dropped — reconnecting...'])
          await new Promise(ok => setTimeout(ok, 3000))
          return streamDiscovery(false)
        }
      } catch {}
      setDiscoveryLog(l => [...l, `Error: ${e.message}`])
    }
    setDiscoveryRunning(false)
  }

  useEffect(() => {
    fetch(`${API}/api/business-discover/status`)
      .then(r => r.json())
      .then(d => {
        if (d.running) {
          setDiscoveryOpen(true)
          setDiscoveryLog([`● Reconnected — Business Discovery running (${d.logLines} lines logged)`])
          setDiscoveryProgress(d.progress || 0)
          streamDiscovery(false)
        }
      }).catch(() => {})
  }, [API])

  // ── Filtering + sorting ──────────────────────────────────────────────────────
  const filtered = useMemo(() => {
    let list = owners.filter(a => a.contact_quality !== 'skip')
    if (filterType) list = list.filter(a => (a.needs || '') === filterType)
    return list
  }, [owners, filterType])

  const sorted = useMemo(() => [...filtered].sort((a, b) => {
    if (sortBy === 'name') {
      const cmp = (a.name || '').localeCompare(b.name || '')
      return sortDir === 'desc' ? -cmp : cmp
    }
    if (sortBy === 'followers') {
      return sortDir === 'desc' ? (b.ig_followers || 0) - (a.ig_followers || 0) : (a.ig_followers || 0) - (b.ig_followers || 0)
    }
    const va = a[sortBy] || '', vb = b[sortBy] || ''
    return sortDir === 'desc' ? String(vb).localeCompare(String(va)) : String(va).localeCompare(String(vb))
  }), [filtered, sortBy, sortDir])

  const businessTypes = useMemo(() => {
    const types = [...new Set(owners.map(a => a.needs).filter(Boolean))].sort()
    return types
  }, [owners])

  const stats = useMemo(() => ({
    total:     filtered.length,
    hasEmail:  filtered.filter(a => a.email).length,
    contacted: filtered.filter(a => a.status === 'contacted').length,
    signed:    filtered.filter(a => a.status === 'signed').length,
  }), [filtered])

  // ── Status update ────────────────────────────────────────────────────────────
  const updateStatus = async (id, status) => {
    await fetch(`${API}/api/artists/${id}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ status }),
    })
    setOwners(prev => prev.map(a => a.id === id ? { ...a, status } : a))
  }

  // ── Styles ───────────────────────────────────────────────────────────────────
  const cardStyle = {
    background: "#0d0d0d", border: "0.5px solid #1f1f1f", borderRadius: 12,
    padding: "16px 20px",
  }

  const btnStyle = (bg, border, color, extra = {}) => ({
    background: bg, border, borderRadius: 7, padding: "7px 14px",
    color, fontSize: 12, fontWeight: 600, cursor: "pointer",
    letterSpacing: "0.01em", whiteSpace: "nowrap", ...extra,
  })

  const thStyle = {
    padding: "10px 12px", color: "#555", fontSize: 11, fontWeight: 600,
    textAlign: "left", borderBottom: "0.5px solid #1a1a1a", textTransform: "uppercase", letterSpacing: "0.05em",
  }

  const tdStyle = (extra = {}) => ({
    padding: "11px 12px", color: "#ccc", fontSize: 13,
    borderBottom: "0.5px solid #111", verticalAlign: "middle", ...extra,
  })

  return (
    <div style={{ padding: "24px 28px", maxWidth: 1400, margin: "0 auto", fontFamily: "var(--font-sans)", position: "relative", zIndex: 1 }}>

      {/* ── Header ── */}
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 24 }}>
        <div>
          <h1 style={{ color: "#fff", fontSize: 22, fontWeight: 700, margin: 0, letterSpacing: "-0.03em" }}>
            Business Owners
          </h1>
          <p style={{ color: "#555", fontSize: 13, margin: "4px 0 0" }}>
            Instagram business owners with LinkedIn · restaurants, gyms, retail, and more
          </p>
        </div>
        <button
          onClick={() => { setDiscoveryOpen(true); if (!discoveryRunning) streamDiscovery(true) }}
          style={btnStyle(
            discoveryRunning ? "#1a1a2a" : "linear-gradient(135deg,#0055cc,#0088ff)",
            discoveryRunning ? "1px solid #3355aa" : "none",
            discoveryRunning ? "#5577cc" : "#fff",
            { padding: "9px 20px", fontSize: 13, position: "relative" }
          )}
        >
          {discoveryRunning && (
            <span style={{ position: "absolute", top: 6, right: 6, width: 6, height: 6, borderRadius: "50%", background: "#4caf50", animation: "pulse 1.5s infinite" }} />
          )}
          {discoveryRunning ? "Running..." : "+ Business Discovery"}
        </button>
      </div>

      {/* ── Stats ── */}
      <div style={{ display: "grid", gridTemplateColumns: "repeat(4, 1fr)", gap: 12, marginBottom: 20 }}>
        {[
          ["Total Leads", stats.total, "#2196f3"],
          ["Has Email", stats.hasEmail, "#4caf50"],
          ["Contacted", stats.contacted, "#cddc39"],
          ["Signed", stats.signed, "#e040fb"],
        ].map(([label, val, color]) => (
          <div key={label} style={{ ...cardStyle, display: "flex", flexDirection: "column", gap: 4 }}>
            <div style={{ color: "#555", fontSize: 11, textTransform: "uppercase", letterSpacing: "0.06em" }}>{label}</div>
            <div style={{ color, fontSize: 26, fontWeight: 700, letterSpacing: "-0.03em" }}>{val}</div>
          </div>
        ))}
      </div>

      {/* ── Filters ── */}
      <div style={{ display: "flex", gap: 10, marginBottom: 18, flexWrap: "wrap", alignItems: "center" }}>
        <input
          value={search}
          onChange={e => setSearch(e.target.value)}
          placeholder="Search name, handle, email..."
          style={{ background: "#111", border: "0.5px solid #222", borderRadius: 7, padding: "8px 12px", color: "#fff", fontSize: 13, outline: "none", width: 220 }}
        />
        <select
          value={filterType}
          onChange={e => setFilterType(e.target.value)}
          style={{ background: "#111", border: "0.5px solid #222", borderRadius: 7, padding: "8px 12px", color: "#fff", fontSize: 13, cursor: "pointer" }}
        >
          <option value="">All Types</option>
          {businessTypes.map(t => <option key={t} value={t}>{t.charAt(0).toUpperCase() + t.slice(1)}</option>)}
        </select>
        <select
          value={filterStatus}
          onChange={e => setFilterStatus(e.target.value)}
          style={{ background: "#111", border: "0.5px solid #222", borderRadius: 7, padding: "8px 12px", color: "#fff", fontSize: 13, cursor: "pointer" }}
        >
          <option value="">All Statuses</option>
          {["new","contacted","pitched","signed","ignored"].map(s => (
            <option key={s} value={s}>{s.charAt(0).toUpperCase() + s.slice(1)}</option>
          ))}
        </select>
        {sessions.length > 0 && (
          <select
            value={filterSession}
            onChange={e => setFilterSession(e.target.value)}
            style={{ background: "#111", border: "0.5px solid #222", borderRadius: 7, padding: "8px 12px", color: "#fff", fontSize: 13, cursor: "pointer" }}
          >
            <option value="">All Sessions</option>
            {sessions.map(s => <option key={s} value={s}>{s}</option>)}
          </select>
        )}
        <div style={{ marginLeft: "auto", color: "#555", fontSize: 12 }}>
          {loading ? "Loading..." : `${sorted.length} leads`}
        </div>
      </div>

      {/* ── Table ── */}
      <div style={{ ...cardStyle, padding: 0, overflow: "hidden" }}>
        <table style={{ width: "100%", borderCollapse: "collapse" }}>
          <thead>
            <tr>
              <th style={thStyle}>Profile</th>
              <th style={thStyle}>Business Type</th>
              <th style={thStyle}>
                <span style={{ cursor: "pointer" }} onClick={() => { setSortBy("ig_followers"); setSortDir(d => d === "desc" ? "asc" : "desc") }}>
                  Followers {sortBy === "ig_followers" ? (sortDir === "desc" ? "▼" : "▲") : ""}
                </span>
              </th>
              <th style={thStyle}>Email</th>
              <th style={thStyle}>LinkedIn</th>
              <th style={thStyle}>Status</th>
              <th style={thStyle}>Actions</th>
            </tr>
          </thead>
          <tbody>
            {loading ? (
              <tr><td colSpan={7} style={{ ...tdStyle(), textAlign: "center", color: "#444", padding: 40 }}>Loading...</td></tr>
            ) : sorted.length === 0 ? (
              <tr>
                <td colSpan={7} style={{ ...tdStyle(), textAlign: "center", color: "#444", padding: 48 }}>
                  {owners.length === 0
                    ? "No business owners found yet. Click \"+ Business Discovery\" to start."
                    : "No leads match your filters."
                  }
                </td>
              </tr>
            ) : sorted.map(owner => {
              const typeColor = TYPE_COLORS[owner.needs] || "#607d8b"
              const sc = STATUS_COLORS[owner.status] || STATUS_COLORS.new
              const igUrl = `https://www.instagram.com/${owner.instagram || owner.platform_id}/`
              const liInBio = (owner.notes || owner.score_reason || "").toLowerCase().includes("linkedin") || true

              return (
                <tr
                  key={owner.id}
                  style={{ cursor: "pointer", transition: "background 0.15s" }}
                  onMouseEnter={e => e.currentTarget.style.background = "#111"}
                  onMouseLeave={e => e.currentTarget.style.background = "transparent"}
                  onClick={() => onSelect(owner.id)}
                >
                  {/* Profile */}
                  <td style={tdStyle()}>
                    <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
                      {owner.image_url
                        ? <img src={owner.image_url} alt="" style={{ width: 36, height: 36, borderRadius: "50%", objectFit: "cover", border: "1px solid #222" }} onError={e => e.target.style.display='none'} />
                        : <div style={{ width: 36, height: 36, borderRadius: "50%", background: "#1a1a2a", display: "flex", alignItems: "center", justifyContent: "center", fontSize: 14, color: "#555" }}>🏢</div>
                      }
                      <div>
                        <div style={{ color: "#fff", fontWeight: 600, fontSize: 13 }}>{owner.name}</div>
                        <a
                          href={igUrl} target="_blank" rel="noopener noreferrer"
                          onClick={e => e.stopPropagation()}
                          style={{ color: "#666", fontSize: 11, textDecoration: "none" }}
                        >
                          @{owner.instagram || owner.platform_id}
                        </a>
                      </div>
                    </div>
                  </td>

                  {/* Business Type */}
                  <td style={tdStyle()}>
                    <span style={{ background: typeColor + "22", color: typeColor, borderRadius: 5, padding: "3px 8px", fontSize: 11, fontWeight: 600, textTransform: "capitalize" }}>
                      {owner.needs || "business"}
                    </span>
                  </td>

                  {/* Followers */}
                  <td style={tdStyle({ color: "#aaa" })}>
                    {owner.ig_followers ? Number(owner.ig_followers).toLocaleString() : "—"}
                  </td>

                  {/* Email */}
                  <td style={tdStyle()}>
                    {owner.email
                      ? <a href={`mailto:${owner.email}`} onClick={e => e.stopPropagation()} style={{ color: "#4caf50", fontSize: 12, textDecoration: "none" }}>{owner.email}</a>
                      : <span style={{ color: "#333", fontSize: 12 }}>—</span>
                    }
                  </td>

                  {/* LinkedIn signal */}
                  <td style={tdStyle({ textAlign: "center" })}>
                    <span style={{ fontSize: 16 }}>🔗</span>
                  </td>

                  {/* Status */}
                  <td style={tdStyle()}>
                    <span style={{ background: sc.bg, color: sc.text, borderRadius: 5, padding: "3px 8px", fontSize: 11, fontWeight: 600, textTransform: "capitalize" }}>
                      {owner.status || "new"}
                    </span>
                  </td>

                  {/* Actions */}
                  <td style={tdStyle()} onClick={e => e.stopPropagation()}>
                    <div style={{ display: "flex", gap: 6 }}>
                      <a
                        href={igUrl} target="_blank" rel="noopener noreferrer"
                        style={{ ...btnStyle("#0a1a2a", "0.5px solid #1a4a6a", "#5599cc"), textDecoration: "none" }}
                      >
                        IG
                      </a>
                      <select
                        value={owner.status || "new"}
                        onChange={e => updateStatus(owner.id, e.target.value)}
                        style={{ background: "#111", border: "0.5px solid #222", borderRadius: 5, padding: "5px 8px", color: "#ccc", fontSize: 11, cursor: "pointer" }}
                      >
                        {["new","contacted","pitched","signed","ignored"].map(s => (
                          <option key={s} value={s}>{s}</option>
                        ))}
                      </select>
                    </div>
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>

      {/* ── Discovery Panel ── */}
      {discoveryOpen && (
        <div style={{ position: "fixed", inset: 0, background: "rgba(0,0,0,0.88)", zIndex: 1000, display: "flex", alignItems: "center", justifyContent: "center" }}>
          <div style={{ background: "#0d0d0d", border: "1px solid #1a2a4a", borderRadius: 16, padding: "24px", width: "min(640px, 92vw)", display: "flex", flexDirection: "column", gap: 16 }}>
            <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
              <div>
                <div style={{ color: "#fff", fontWeight: 700, fontSize: 17 }}>Business Owner Discovery</div>
                <div style={{ color: "#555", fontSize: 12, marginTop: 3 }}>
                  Searching Instagram for business owners with LinkedIn · 33 queries across 5 regions
                </div>
              </div>
              {!discoveryRunning && (
                <button onClick={() => { setDiscoveryOpen(false); setDiscoveryLog([]) }} style={{ background: "transparent", border: "none", color: "#555", fontSize: 22, cursor: "pointer" }}>×</button>
              )}
            </div>

            {/* Progress bar */}
            {discoveryRunning && (
              <div style={{ background: "#111", borderRadius: 4, height: 4, overflow: "hidden" }}>
                <div style={{ background: "linear-gradient(90deg,#0055cc,#0088ff)", height: "100%", width: `${discoveryProgress || 10}%`, transition: "width 0.5s", animation: discoveryProgress < 100 ? "progressPulse 2s infinite" : "none" }} />
              </div>
            )}

            {/* Log */}
            <div
              ref={logRef}
              style={{ background: "#050505", border: "0.5px solid #1a1a1a", borderRadius: 8, padding: "12px 14px", height: 300, overflowY: "auto", fontFamily: "monospace", fontSize: 11, color: "#777", display: "flex", flexDirection: "column", gap: 2 }}
            >
              {discoveryLog.length === 0
                ? <span style={{ color: "#333" }}>Starting discovery...</span>
                : discoveryLog.map((line, i) => (
                    <span key={i} style={{
                      color: line.includes("SAVED") ? "#4caf50"
                           : line.includes("ERROR") || line.includes("[err]") ? "#f44336"
                           : line.includes("Synced") ? "#2196f3"
                           : line.includes("===") ? "#888"
                           : "#666"
                    }}>{line}</span>
                  ))
              }
            </div>

            <div style={{ display: "flex", gap: 10, justifyContent: "flex-end" }}>
              {discoveryRunning ? (
                <div style={{ color: "#555", fontSize: 12, display: "flex", alignItems: "center", gap: 8 }}>
                  <span style={{ width: 7, height: 7, borderRadius: "50%", background: "#4caf50", display: "inline-block", animation: "pulse 1.5s infinite" }} />
                  Scanning business owners...
                </div>
              ) : (
                <button
                  onClick={() => streamDiscovery(true)}
                  style={btnStyle("linear-gradient(135deg,#0055cc,#0088ff)", "none", "#fff", { padding: "9px 24px" })}
                >
                  Run Again
                </button>
              )}
            </div>
          </div>
        </div>
      )}

      <style>{`
        @keyframes pulse { 0%,100%{opacity:1} 50%{opacity:0.4} }
        @keyframes progressPulse { 0%,100%{opacity:1} 50%{opacity:0.7} }
      `}</style>
    </div>
  )
}
