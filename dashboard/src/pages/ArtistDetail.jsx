import { useState, useEffect, useRef } from "react"

export default function ArtistDetail({ API, id, onBack }) {
  const [artist, setArtist] = useState(null)
  const [pitch, setPitch] = useState("")
  const [generating, setGenerating] = useState(null) // 'attention' | 'sales' | null
  const [sending, setSending] = useState(false)
  const [notes, setNotes] = useState("")
  const [status, setStatus] = useState("")
  const [msg, setMsg] = useState(null)
  const [enriching, setEnriching] = useState(false)
  const [refreshingListeners, setRefreshingListeners] = useState(false)
  const [removing, setRemoving] = useState(false)
  const [confirmRemove, setConfirmRemove] = useState(false)
  const autoTriggered = useRef(false)

  useEffect(() => {
    if (!id) return
    autoTriggered.current = false
    fetch(`${API}/api/artists/${id}`)
      .then(r => r.json())
      .then(d => {
        setArtist(d)
        setNotes(d.notes || "")
        setStatus(d.status || "new")
        setPitch(d.pitch_draft || "")
        // Auto-search contacts if never searched and no contacts exist
        const neverSearched = !d.contact_quality || d.contact_quality === 'none'
        const noContacts = !d.instagram && !d.email && !d.facebook && !d.phone
        const notBusy = d.contact_quality !== 'searching'
        if (neverSearched && noContacts && notBusy && !autoTriggered.current) {
          autoTriggered.current = true
          // Delay slightly so UI renders first
          setTimeout(() => findContactsFor(d.id, d.name), 400)
        }
      })
      .catch(() => {
        const demo = {
          id, name: "Maya Rivers", platform: "spotify", followers: 12400,
          score: 84, status: "new", score_reason: "Active R&B artist, recent releases, no label attached",
          instagram: "mayarivermusic", email: null, profile_url: "https://open.spotify.com",
          genres: '["r-n-b","soul"]', image_url: null, notes: "", pitch_draft: ""
        }
        setArtist(demo)
        setNotes(demo.notes)
        setStatus(demo.status)
      })
  }, [id])

  const generatePitch = async (pitch_type) => {
    setGenerating(pitch_type)
    try {
      const r = await fetch(`${API}/api/pitch`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ artist_id: id, pitch_type })
      })
      const d = await r.json()
      setPitch(d.pitch)
    } catch {
      if (pitch_type === 'attention') {
        setPitch(`hey! heard your tracks, the vibe is smooth as hell. you doing all the production yourself or got someone on it?`)
      } else {
        setPitch(`hey! heard your tracks, the sound hits different. we're Renegade Records — we work with independent artists on mixing and vocal production. if you're tryna level up the sound, we should link. you open to it?`)
      }
    }
    setGenerating(null)
  }

  const saveStatus = async () => {
    try {
      await fetch(`${API}/api/artists/${id}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ status, notes })
      })
      setMsg({ type: "success", text: "Saved" })
    } catch {
      setMsg({ type: "error", text: "Save failed (demo mode)" })
    }
    setTimeout(() => setMsg(null), 2000)
  }

  const findContactsFor = async (artistId, artistName) => {
    setEnriching(true)
    setMsg({ type: "info", text: `Auto-searching contacts for ${artistName || "artist"}... (30-90s)` })
    try {
      const r = await fetch(`${API}/api/enrich/${artistId}`, { method: "POST" })
      const d = await r.json()

      // Artist was flagged (producer or too many followers)
      if (d.flagged) {
        setMsg({ type: "error", text: `Flagged: ${d.reason}` })
        setEnriching(false)
        setTimeout(() => fetchArtist(), 1000)
        return
      }

      if (d.success) {
        setArtist(prev => ({ ...prev, ...d.contacts }))
        const c = d.contacts
        const found = [
          c.instagram && `Instagram (@${c.instagram})`,
          c.email     && `Email (${c.email})`,
          c.facebook  && `Facebook`,
          c.phone     && `Phone`,
        ].filter(Boolean)
        if (d.save_warning) {
          setMsg({ type: "error", text: `Found contacts but couldn't save: ${d.save_warning}` })
        } else if (found.length > 0) {
          setMsg({ type: "success", text: `Saved: ${found.join(", ")}` })
        } else {
          setMsg({ type: "error", text: "No contacts found for this artist" })
        }
      } else {
        setMsg({ type: "error", text: d.error || "Enrichment failed" })
      }
    } catch {
      setMsg({ type: "error", text: "Backend not reachable" })
    }
    setEnriching(false)
    setTimeout(() => setMsg(null), 4000)
  }

  const findContacts = () => findContactsFor(id, artist?.name)

  const refreshListeners = async () => {
    setRefreshingListeners(true)
    setMsg({ type: "info", text: "Fetching listener count..." })
    try {
      const r = await fetch(`${API}/api/artists/${id}/refresh-listeners`, { method: "POST" })
      const d = await r.json()
      if (d.success) {
        setArtist(prev => ({ ...prev, listeners: d.listeners }))
        setMsg({ type: "success", text: `Updated: ${d.listeners.toLocaleString()} listeners` })
      } else {
        setMsg({ type: "error", text: d.error || "Could not fetch listener count" })
      }
    } catch {
      setMsg({ type: "error", text: "Backend not reachable" })
    }
    setRefreshingListeners(false)
    setTimeout(() => setMsg(null), 3000)
  }

  const removeLead = async () => {
    if (!confirmRemove) { setConfirmRemove(true); return }
    setRemoving(true)
    setConfirmRemove(false)
    try {
      const r = await fetch(`${API}/api/artists/${id}`, { method: "DELETE" })
      const d = await r.json()
      if (!r.ok) {
        setMsg({ type: "error", text: `Flag failed: ${d.error || r.status}` })
        setRemoving(false)
        return
      }
    } catch (e) {
      setMsg({ type: "error", text: `Flag failed: ${e.message}` })
      setRemoving(false)
      return
    }
    onBack()
  }

  const sendEmail = async () => {
    if (!artist?.email) return
    setSending(true)
    try {
      await fetch(`${API}/api/send-email`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ artist_id: id, subject: `Renegade Records — Let's Work`, body: pitch })
      })
      setMsg({ type: "success", text: "Email sent!" })
      setStatus("contacted")
    } catch {
      setMsg({ type: "error", text: "Email failed (demo mode)" })
    }
    setSending(false)
    setTimeout(() => setMsg(null), 3000)
  }

  if (!artist) return (
    <div style={{ padding: "3rem", textAlign: "center", color: "#444" }}>Loading artist...</div>
  )

  const score = artist.score || 0
  const scoreColor = score >= 70 ? "#4caf50" : score >= 50 ? "#ff9800" : "#ff4444"
  let genres = []
  try { genres = JSON.parse(artist.genres || "[]") } catch {}

  const STATUS_COLORS = {
    new:       "#6c8cff",
    contacted: "#4caf50",
    pitched:   "#ff9800",
    signed:    "#ff4081",
    ignored:   "#555"
  }
  const statusColor = STATUS_COLORS[status || artist.status] || "#6c8cff"

  return (
    <div style={{
      padding: "2rem 2rem calc(2rem + env(safe-area-inset-bottom))",
      maxWidth: 800, margin: "0 auto",
      minHeight: "100vh",
      background: `radial-gradient(ellipse at top, ${statusColor}40 0%, #0a0a0a 65%)`,
      transition: "background 0.4s ease"
    }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "1.5rem" }}>
        <button onClick={onBack} style={{
          background: "transparent", border: "0.5px solid #222",
          color: "#888", padding: "6px 12px", borderRadius: 6,
          cursor: "pointer", fontSize: 13
        }}>← Back to leads</button>
        {confirmRemove ? (
          <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
            <span style={{ color: "#888", fontSize: 12 }}>Sure?</span>
            <button onClick={removeLead} disabled={removing} style={{
              background: "#3a0808", border: "0.5px solid #cc4444",
              color: "#ff4444", padding: "6px 12px", borderRadius: 6,
              cursor: "pointer", fontSize: 13, fontWeight: 600
            }}>{removing ? "Flagging..." : "Yes, Flag"}</button>
            <button onClick={() => setConfirmRemove(false)} style={{
              background: "transparent", border: "0.5px solid #333",
              color: "#666", padding: "6px 10px", borderRadius: 6,
              cursor: "pointer", fontSize: 13
            }}>Cancel</button>
          </div>
        ) : (
          <button onClick={removeLead} style={{
            background: "transparent", border: "0.5px solid #3a1515",
            color: "#cc4444", padding: "6px 12px", borderRadius: 6,
            cursor: "pointer", fontSize: 13
          }}>Flag Lead</button>
        )}
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(280px, 1fr))", gap: 16, marginBottom: 16 }}>
        <div style={{ background: "#111", border: "0.5px solid #1f1f1f", borderRadius: 12, padding: "20px" }}>
          <div style={{ display: "flex", alignItems: "center", gap: 12, marginBottom: 14 }}>
            <div style={{
              width: 52, height: 52, borderRadius: "50%", background: "#1a1a1a",
              display: "flex", alignItems: "center", justifyContent: "center",
              fontSize: 20, fontWeight: 700, color: "#444"
            }}>
              {artist.name?.[0]?.toUpperCase()}
            </div>
            <div>
              <div style={{ color: "#fff", fontWeight: 600, fontSize: 16 }}>{artist.name}</div>
              <div style={{ color: "#555", fontSize: 13 }}>{artist.platform} · {(artist.listeners || artist.followers || 0).toLocaleString()} listeners</div>
            </div>
          </div>

          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 10 }}>
            <div style={{ background: "#0d0d0d", borderRadius: 8, padding: "10px 12px" }}>
              <div style={{ color: "#444", fontSize: 11, marginBottom: 4 }}>AI Score</div>
              <div style={{ color: scoreColor, fontWeight: 600, fontSize: 13 }}>{score}/100</div>
            </div>
            <div style={{ background: "#0d0d0d", borderRadius: 8, padding: "10px 12px" }}>
              <div style={{ color: "#444", fontSize: 11, marginBottom: 4 }}>Status</div>
              <div style={{ color: "#ff9800", fontSize: 13 }}>{status}</div>
            </div>
            <div style={{ background: "#0d0d0d", borderRadius: 8, padding: "10px 12px" }}>
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 4 }}>
                <span style={{ color: "#444", fontSize: 11 }}>Listeners</span>
                <button onClick={refreshListeners} disabled={refreshingListeners} title="Refresh listener count from Spotify"
                  style={{ background: "none", border: "none", color: refreshingListeners ? "#444" : "#555", fontSize: 11, cursor: refreshingListeners ? "default" : "pointer", padding: 0, lineHeight: 1 }}>
                  {refreshingListeners ? "..." : "↻"}
                </button>
              </div>
              <div style={{ color: "#ccc", fontSize: 13 }}>{(artist.listeners || artist.followers || 0).toLocaleString()}</div>
            </div>
            <div style={{ background: "#0d0d0d", borderRadius: 8, padding: "10px 12px" }}>
              <div style={{ color: "#444", fontSize: 11, marginBottom: 4 }}>Contact Quality</div>
              <div style={{ color: artist.contact_quality === "excellent" ? "#ffcc00" : artist.contact_quality === "good" ? "#66bb6a" : "#555", fontSize: 13, fontWeight: 500 }}>
                {artist.contact_quality || "unknown"}
              </div>
            </div>
          </div>

          {/* Contact Channels */}
          <div style={{ marginTop: 14, display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 6 }}>
            <span style={{ color: "#555", fontSize: 12 }}>Contact Channels</span>
            <button onClick={findContacts} disabled={enriching} style={{
              background: enriching ? "#1a1a1a" : "#1a0d00",
              border: "0.5px solid #ff4d0033",
              borderRadius: 6, padding: "5px 12px",
              color: enriching ? "#555" : "#ff4d00",
              fontSize: 12, cursor: enriching ? "default" : "pointer"
            }}>
              {enriching ? "Searching..." : "Find Contacts"}
            </button>
          </div>
          <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
            {artist.instagram && (
              <div style={{ display: "flex", alignItems: "center", gap: 8, background: "#0d0d0d", borderRadius: 8, padding: "9px 12px" }}>
                <span style={{ color: "#8888ff", fontSize: 12, minWidth: 60 }}>Instagram</span>
                <a href={`https://instagram.com/${artist.instagram}`} target="_blank" rel="noreferrer"
                  style={{ color: "#ccc", fontSize: 13, flex: 1 }}>@{artist.instagram}</a>
                {artist.ig_followers && <span style={{ color: "#555", fontSize: 11 }}>{artist.ig_followers.toLocaleString()} followers</span>}
                <a href={`https://ig.me/m/${artist.instagram}`} target="_blank" rel="noreferrer"
                  style={{ background: "#1a1a3a", border: "0.5px solid #333", borderRadius: 5, padding: "4px 10px", color: "#8888ff", fontSize: 11, textDecoration: "none" }}>
                  DM
                </a>
              </div>
            )}
            {artist.facebook && (
              <div style={{ display: "flex", alignItems: "center", gap: 8, background: "#0d0d0d", borderRadius: 8, padding: "9px 12px" }}>
                <span style={{ color: "#5b9bd5", fontSize: 12, minWidth: 60 }}>Facebook</span>
                <a href={`https://${artist.facebook}`} target="_blank" rel="noreferrer"
                  style={{ color: "#ccc", fontSize: 13, flex: 1 }}>{artist.facebook}</a>
                <a href={`https://${artist.facebook}`} target="_blank" rel="noreferrer"
                  style={{ background: "#1a1f3a", border: "0.5px solid #333", borderRadius: 5, padding: "4px 10px", color: "#5b9bd5", fontSize: 11, textDecoration: "none" }}>
                  Visit
                </a>
              </div>
            )}
            {artist.phone && (
              <div style={{ display: "flex", alignItems: "center", gap: 8, background: "#0d0d0d", borderRadius: 8, padding: "9px 12px" }}>
                <span style={{ color: "#bb88ff", fontSize: 12, minWidth: 60 }}>Phone</span>
                <span style={{ color: "#ccc", fontSize: 13, flex: 1 }}>{artist.phone}</span>
                <a href={`tel:${artist.phone}`}
                  style={{ background: "#2a1a3a", border: "0.5px solid #333", borderRadius: 5, padding: "4px 10px", color: "#bb88ff", fontSize: 11, textDecoration: "none" }}>
                  Call
                </a>
              </div>
            )}
            {artist.email && (
              <div style={{ display: "flex", alignItems: "center", gap: 8, background: "#0d0d0d", borderRadius: 8, padding: "9px 12px" }}>
                <span style={{ color: "#66bb6a", fontSize: 12, minWidth: 60 }}>Email</span>
                <span style={{ color: "#ccc", fontSize: 13, flex: 1 }}>{artist.email}</span>
                <a href={`mailto:${artist.email}`}
                  style={{ background: "#1a2a1a", border: "0.5px solid #333", borderRadius: 5, padding: "4px 10px", color: "#66bb6a", fontSize: 11, textDecoration: "none" }}>
                  Mail
                </a>
              </div>
            )}
            {!artist.instagram && !artist.facebook && !artist.phone && !artist.email && (
              <div style={{ color: "#555", fontSize: 13, padding: "8px 0" }}>
                No contacts found yet.{" "}
                <button onClick={findContacts} disabled={enriching} style={{
                  background: "none", border: "none", color: "#ff4d00",
                  cursor: "pointer", fontSize: 13, padding: 0, textDecoration: "underline"
                }}>
                  {enriching ? "Searching..." : "Run reverse search"}
                </button>
              </div>
            )}
          </div>

          {genres.length > 0 && (
            <div style={{ marginTop: 12, display: "flex", gap: 6, flexWrap: "wrap" }}>
              {genres.map(g => (
                <span key={g} style={{ background: "#1a1a2e", color: "#6c8cff", fontSize: 11, padding: "3px 8px", borderRadius: 4 }}>
                  {g}
                </span>
              ))}
            </div>
          )}

          {artist.profile_url && (
            <a href={artist.profile_url} target="_blank" rel="noreferrer"
              style={{ display: "block", marginTop: 12, color: "#ff4d00", fontSize: 13 }}>
              View on {artist.platform} →
            </a>
          )}
        </div>

        <div style={{ background: "#111", border: "0.5px solid #1f1f1f", borderRadius: 12, padding: "20px" }}>
          <div style={{ color: "#888", fontSize: 12, marginBottom: 8 }}>AI analysis</div>
          <p style={{ color: "#ccc", fontSize: 13, lineHeight: 1.7, margin: "0 0 16px" }}>
            {artist.score_reason || "No analysis yet."}
          </p>

          <div style={{ color: "#888", fontSize: 12, marginBottom: 8 }}>Update status</div>
          <select value={status} onChange={e => setStatus(e.target.value)}
            style={{ width: "100%", background: "#0d0d0d", border: "0.5px solid #222", borderRadius: 6, padding: "8px 10px", color: "#ccc", fontSize: 13, marginBottom: 10 }}>
            {["new","contacted","pitched","signed","ignored"].map(s => (
              <option key={s} value={s}>{s}</option>
            ))}
          </select>

          <div style={{ color: "#888", fontSize: 12, marginBottom: 6 }}>Notes</div>
          <textarea value={notes} onChange={e => setNotes(e.target.value)}
            rows={3} style={{
              width: "100%", background: "#0d0d0d", border: "0.5px solid #222",
              borderRadius: 6, padding: "8px 10px", color: "#ccc", fontSize: 13,
              resize: "vertical", boxSizing: "border-box"
            }} />

          <button onClick={saveStatus} style={{
            marginTop: 8, width: "100%", background: "#1a1a1a", border: "0.5px solid #333",
            borderRadius: 6, padding: "9px", color: "#ccc", fontSize: 13, cursor: "pointer"
          }}>Save changes</button>
        </div>
      </div>

      <div style={{ background: "#111", border: "0.5px solid #1f1f1f", borderRadius: 12, padding: "20px" }}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 12 }}>
          <div style={{ color: "#fff", fontWeight: 500, fontSize: 15 }}>Pitch Message</div>
          <div style={{ display: "flex", gap: 8 }}>
            <button
              onClick={() => generatePitch("attention")}
              disabled={!!generating}
              style={{
                background: "#1a1a1a", border: "0.5px solid #333", borderRadius: 6,
                padding: "6px 12px", color: generating === "attention" ? "#555" : "#aaa",
                fontSize: 12, cursor: generating ? "default" : "pointer"
              }}
            >
              {generating === "attention" ? "Writing..." : "Grab Attention"}
            </button>
            <button
              onClick={() => generatePitch("sales")}
              disabled={!!generating}
              style={{
                background: generating === "sales" ? "#333" : "#ff4d00",
                border: "none", borderRadius: 6,
                padding: "6px 12px", color: generating === "sales" ? "#888" : "#fff",
                fontSize: 12, cursor: generating ? "default" : "pointer", fontWeight: 500
              }}
            >
              {generating === "sales" ? "Writing..." : "Sales Pitch"}
            </button>
          </div>
        </div>

        <textarea
          value={pitch}
          onChange={e => setPitch(e.target.value)}
          rows={3}
          placeholder="Generate or write your own..."
          style={{
            width: "100%", background: "#0d0d0d", border: "0.5px solid #222",
            borderRadius: 8, padding: "12px", color: "#ccc", fontSize: 14,
            lineHeight: 1.7, resize: "none", boxSizing: "border-box"
          }}
        />

        <div style={{ display: "flex", gap: 10, marginTop: 12, alignItems: "center", flexWrap: "wrap" }}>
          {artist.email && (
            <button onClick={sendEmail} disabled={sending || !pitch} style={{
              background: "#1a3a1a", border: "0.5px solid #2a5a2a",
              borderRadius: 6, padding: "9px 20px", color: "#4caf50",
              fontSize: 13, cursor: "pointer", fontWeight: 500
            }}>
              {sending ? "Sending..." : `Send email`}
            </button>
          )}
          {artist.instagram && (
            <a href={`https://ig.me/m/${artist.instagram}`} target="_blank" rel="noreferrer" style={{
              background: "#1a1a3a", border: "0.5px solid #2a2a5a",
              borderRadius: 6, padding: "9px 20px", color: "#8888ff",
              fontSize: 13, fontWeight: 500, textDecoration: "none"
            }}>
              DM on Instagram
            </a>
          )}
          {artist.facebook && (
            <a href={`https://${artist.facebook}`} target="_blank" rel="noreferrer" style={{
              background: "#1a1f3a", border: "0.5px solid #2a2f5a",
              borderRadius: 6, padding: "9px 20px", color: "#5b9bd5",
              fontSize: 13, fontWeight: 500, textDecoration: "none"
            }}>
              Message on Facebook
            </a>
          )}
          {artist.phone && (
            <a href={`tel:${artist.phone}`} style={{
              background: "#2a1a3a", border: "0.5px solid #3a2a5a",
              borderRadius: 6, padding: "9px 20px", color: "#bb88ff",
              fontSize: 13, fontWeight: 500, textDecoration: "none"
            }}>
              Call {artist.phone}
            </a>
          )}
          {!artist.email && !artist.instagram && !artist.facebook && !artist.phone && (
            <span style={{ color: "#444", fontSize: 13 }}>No contact info — use <strong style={{ color: "#ff4d00" }}>Find Contacts</strong> above</span>
          )}
          {msg && (
            <span style={{ fontSize: 13, color: msg.type === "success" ? "#4caf50" : msg.type === "info" ? "#ff9800" : "#ff4444" }}>
              {msg.text}
            </span>
          )}
        </div>
      </div>
    </div>
  )
}
