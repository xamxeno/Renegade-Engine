import { useState, useEffect } from "react"
import Dashboard from "./pages/Dashboard"
import ArtistDetail from "./pages/ArtistDetail"

const API = (import.meta.env.VITE_API_URL || "http://localhost:4000").replace(/\/$/, "")
const SECRET = "Third Door Isn't There"
const AUTH_KEY = "renegade_auth"

export default function App() {
  const [authed, setAuthed] = useState(() => localStorage.getItem(AUTH_KEY) === "1")
  const [page, setPage] = useState(() => {
    const params = new URLSearchParams(window.location.search)
    return params.get("artist") ? "artist" : "dashboard"
  })
  const [selectedId, setSelectedId] = useState(() => {
    const params = new URLSearchParams(window.location.search)
    return params.get("artist") || null
  })

  const navigate = (p, id = null) => {
    setPage(p)
    setSelectedId(id)
    if (p === "artist" && id) {
      window.history.pushState({}, "", `?artist=${id}`)
    } else {
      window.history.pushState({}, "", window.location.pathname)
    }
  }

  if (!authed) return <LoginScreen onAuth={() => { localStorage.setItem(AUTH_KEY, "1"); setAuthed(true) }} />

  return (
    <div style={{ minHeight: "100vh", background: "#050505", fontFamily: "var(--font-sans)", position: "relative" }}>
      <GraffitiBackground />
      {/* Dark overlay so graffiti sits at ~20% visibility */}
      <div style={{ position: "fixed", inset: 0, zIndex: 0, background: "rgba(5,5,5,0.80)", pointerEvents: "none" }} />
      <Header onNav={navigate} currentPage={page} />
      {page === "dashboard" && <Dashboard API={API} onSelect={(id) => navigate("artist", id)} />}
      {page === "artist" && <ArtistDetail API={API} id={selectedId} onBack={() => navigate("dashboard")} />}
    </div>
  )
}

function LoginScreen({ onAuth }) {
  const [input, setInput] = useState("")
  const [shake, setShake] = useState(false)

  const attempt = () => {
    if (input.trim().toLowerCase() === SECRET.toLowerCase()) {
      onAuth()
    } else {
      setShake(true)
      setInput("")
      setTimeout(() => setShake(false), 500)
    }
  }

  return (
    <div style={{ minHeight: "100vh", background: "#050505", display: "flex", alignItems: "center", justifyContent: "center", fontFamily: "-apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif" }}>
      <div style={{ display: "flex", flexDirection: "column", alignItems: "center", gap: 24, width: "min(360px, 90vw)" }}>
        <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 8 }}>
          <div style={{ width: 36, height: 36, borderRadius: 8, background: "linear-gradient(135deg, #ff4d00, #ff0066)", display: "flex", alignItems: "center", justifyContent: "center", fontSize: 18, fontWeight: 700, color: "#fff" }}>R</div>
          <span style={{ color: "#fff", fontWeight: 600, fontSize: 17, letterSpacing: "-0.02em" }}>Renegade Records</span>
        </div>
        <div
          style={{
            width: "100%", background: "#0d0d0d", border: `0.5px solid ${shake ? "#ff4444" : "#1f1f1f"}`,
            borderRadius: 14, padding: "28px 24px", display: "flex", flexDirection: "column", gap: 14,
            transition: "border-color 0.2s",
            animation: shake ? "shake 0.4s ease" : "none",
          }}
        >
          <div style={{ color: "#888", fontSize: 13, textAlign: "center" }}>Enter secret key to continue</div>
          <input
            type="password"
            value={input}
            onChange={e => setInput(e.target.value)}
            onKeyDown={e => e.key === "Enter" && attempt()}
            autoFocus
            placeholder="Secret key"
            style={{ width: "100%", background: "#111", border: "0.5px solid #222", borderRadius: 8, padding: "11px 14px", color: "#fff", fontSize: 14, outline: "none", boxSizing: "border-box" }}
          />
          <button
            onClick={attempt}
            style={{ width: "100%", background: "linear-gradient(135deg, #ff4d00, #ff0066)", border: "none", borderRadius: 8, padding: "11px", color: "#fff", fontSize: 14, fontWeight: 700, cursor: "pointer", letterSpacing: "0.02em" }}
          >
            Enter
          </button>
        </div>
      </div>
      <style>{`@keyframes shake { 0%,100%{transform:translateX(0)} 20%{transform:translateX(-8px)} 60%{transform:translateX(8px)} 80%{transform:translateX(-4px)} }`}</style>
    </div>
  )
}

function GraffitiBackground() {
  return (
    <div style={{ position: "fixed", inset: 0, zIndex: 0, pointerEvents: "none", overflow: "hidden" }}>
      <svg width="100%" height="100%" xmlns="http://www.w3.org/2000/svg" style={{ position: "absolute", inset: 0 }}>
        <defs>
          <filter id="glow-pink"><feGaussianBlur stdDeviation="3" result="blur"/><feMerge><feMergeNode in="blur"/><feMergeNode in="SourceGraphic"/></feMerge></filter>
          <filter id="glow-cyan"><feGaussianBlur stdDeviation="4" result="blur"/><feMerge><feMergeNode in="blur"/><feMergeNode in="SourceGraphic"/></feMerge></filter>
          <filter id="glow-purple"><feGaussianBlur stdDeviation="3.5" result="blur"/><feMerge><feMergeNode in="blur"/><feMergeNode in="SourceGraphic"/></feMerge></filter>
          <filter id="roughen"><feTurbulence type="fractalNoise" baseFrequency="0.04" numOctaves="5" result="noise"/><feDisplacementMap in="SourceGraphic" in2="noise" scale="3" xChannelSelector="R" yChannelSelector="G"/></filter>
        </defs>

        {/* ── BIG GRAFFITI LETTERS (very faint backdrop) ── */}
        <text x="-2%" y="28%" fontFamily="Impact, Arial Black, sans-serif" fontSize="220" fontWeight="900" fill="none" stroke="#ff006615" strokeWidth="3" transform="rotate(-8, 0, 0)" letterSpacing="-8">RENEGADE</text>
        <text x="10%" y="72%" fontFamily="Impact, Arial Black, sans-serif" fontSize="160" fontWeight="900" fill="none" stroke="#aa44ff12" strokeWidth="2" transform="rotate(5, 0, 0)" letterSpacing="-4">UNSIGNED</text>
        <text x="55%" y="52%" fontFamily="Impact, Arial Black, sans-serif" fontSize="100" fontWeight="900" fill="none" stroke="#00ffcc10" strokeWidth="2" transform="rotate(-12, 600, 400)" letterSpacing="2">RAW</text>

        {/* ── SPRAY DRIPS ── */}
        <g opacity="0.18" filter="url(#roughen)">
          <path d="M 80 0 Q 82 60 78 120 Q 80 180 83 260" stroke="#ff0066" strokeWidth="6" fill="none" strokeLinecap="round"/>
          <path d="M 83 260 Q 84 280 80 300 L 78 310 Q 82 320 80 330" stroke="#ff0066" strokeWidth="4" fill="none" strokeLinecap="round"/>
          <ellipse cx="80" cy="335" rx="5" ry="8" fill="#ff0066" opacity="0.6"/>

          <path d="M 92%vw 10% Q 91.5% 25% 92.5% 45% Q 92% 65% 91% 85%" stroke="#00ffcc" strokeWidth="5" fill="none" strokeLinecap="round"/>
          <path d="M 340 0 Q 342 40 338 90 Q 341 150 340 200" stroke="#aa44ff" strokeWidth="7" fill="none" strokeLinecap="round"/>
          <ellipse cx="340" cy="205" rx="6" ry="10" fill="#aa44ff" opacity="0.5"/>
        </g>

        {/* ── MUSIC NOTES ── */}
        <g filter="url(#glow-pink)" opacity="0.55">
          <text x="7%" y="18%" fontSize="52" fill="#ff0066" transform="rotate(-20, 100, 150)">♪</text>
          <text x="88%" y="35%" fontSize="70" fill="#ff0066" transform="rotate(15, 900, 300)">♫</text>
          <text x="45%" y="88%" fontSize="44" fill="#ff006688" transform="rotate(-10, 500, 700)">♪</text>
          <text x="22%" y="62%" fontSize="36" fill="#ff006655" transform="rotate(25, 250, 500)">♩</text>
        </g>
        <g filter="url(#glow-cyan)" opacity="0.5">
          <text x="70%" y="15%" fontSize="60" fill="#00ffcc" transform="rotate(10, 750, 120)">♫</text>
          <text x="3%" y="78%" fontSize="48" fill="#00ffcc" transform="rotate(-15, 50, 650)">♪</text>
          <text x="55%" y="65%" fontSize="32" fill="#00ffcc66" transform="rotate(20, 600, 550)">♩</text>
        </g>
        <g filter="url(#glow-purple)" opacity="0.5">
          <text x="33%" y="12%" fontSize="56" fill="#aa44ff" transform="rotate(-25, 380, 100)">♫</text>
          <text x="80%" y="78%" fontSize="42" fill="#aa44ff" transform="rotate(8, 850, 650)">♪</text>
        </g>

        {/* ── MIC ── */}
        <g transform="translate(78%, 55%) rotate(-18)" opacity="0.12" filter="url(#glow-pink)">
          <rect x="0" y="0" width="28" height="44" rx="14" fill="none" stroke="#ff0066" strokeWidth="3"/>
          <line x1="14" y1="44" x2="14" y2="66" stroke="#ff0066" strokeWidth="3" strokeLinecap="round"/>
          <path d="M 4 66 Q 14 74 24 66" stroke="#ff0066" strokeWidth="3" fill="none" strokeLinecap="round"/>
          <line x1="6" y1="18" x2="22" y2="18" stroke="#ff0066" strokeWidth="1.5" opacity="0.5"/>
          <line x1="6" y1="26" x2="22" y2="26" stroke="#ff0066" strokeWidth="1.5" opacity="0.5"/>
          <line x1="8" y1="34" x2="20" y2="34" stroke="#ff0066" strokeWidth="1.5" opacity="0.5"/>
        </g>

        {/* ── HEADPHONES ── */}
        <g transform="translate(12%, 42%) rotate(12)" opacity="0.13" filter="url(#glow-cyan)">
          <path d="M 10 30 Q 10 0 40 0 Q 70 0 70 30" stroke="#00ffcc" strokeWidth="4" fill="none" strokeLinecap="round"/>
          <rect x="2" y="28" width="16" height="24" rx="6" fill="none" stroke="#00ffcc" strokeWidth="3"/>
          <rect x="62" y="28" width="16" height="24" rx="6" fill="none" stroke="#00ffcc" strokeWidth="3"/>
        </g>

        {/* ── CROWN ── */}
        <g transform="translate(60%, 6%) rotate(-5)" opacity="0.14" filter="url(#glow-purple)">
          <path d="M 0 40 L 10 10 L 25 30 L 40 0 L 55 30 L 70 10 L 80 40 Z" fill="none" stroke="#aa44ff" strokeWidth="3" strokeLinejoin="round"/>
          <line x1="0" y1="40" x2="80" y2="40" stroke="#aa44ff" strokeWidth="3" strokeLinecap="round"/>
        </g>

        {/* ── SPRAY CAN ── */}
        <g transform="translate(88%, 60%) rotate(20)" opacity="0.11" filter="url(#glow-pink)">
          <rect x="8" y="18" width="24" height="50" rx="5" fill="none" stroke="#ff9800" strokeWidth="2.5"/>
          <rect x="12" y="10" width="16" height="10" rx="3" fill="none" stroke="#ff9800" strokeWidth="2"/>
          <rect x="15" y="6" width="10" height="6" rx="2" fill="none" stroke="#ff9800" strokeWidth="2"/>
          <circle cx="20" cy="4" r="3" fill="#ff9800" opacity="0.6"/>
          <circle cx="4" cy="2" r="2" fill="#ff9800" opacity="0.4"/>
          <circle cx="-2" cy="8" r="1.5" fill="#ff9800" opacity="0.3"/>
          <circle cx="1" cy="14" r="1" fill="#ff9800" opacity="0.25"/>
        </g>

        {/* ── STARS / SPARKLES ── */}
        <g opacity="0.4">
          <text x="50%" y="8%" fontSize="22" fill="#ffdd00" filter="url(#glow-pink)">★</text>
          <text x="15%" y="32%" fontSize="14" fill="#ffdd00" opacity="0.6">★</text>
          <text x="94%" y="22%" fontSize="18" fill="#ffdd00" filter="url(#glow-cyan)">✦</text>
          <text x="38%" y="95%" fontSize="16" fill="#ffdd00" opacity="0.5">★</text>
          <text x="66%" y="82%" fontSize="20" fill="#ff0066" filter="url(#glow-pink)">✦</text>
          <text x="5%" y="55%" fontSize="12" fill="#aa44ff" opacity="0.7">✦</text>
          <text x="75%" y="46%" fontSize="10" fill="#00ffcc" opacity="0.6">✦</text>
        </g>

        {/* ── LIGHTNING BOLTS ── */}
        <g opacity="0.15" filter="url(#glow-cyan)">
          <path d="M 96% 70% L 93% 78% L 95% 78% L 92% 87%" stroke="#00ffcc" strokeWidth="2.5" fill="none" strokeLinejoin="round"/>
        </g>
        <g opacity="0.12" filter="url(#glow-purple)">
          <path d="M 28% 3% L 25% 11% L 27% 11% L 24% 19%" stroke="#aa44ff" strokeWidth="2" fill="none" strokeLinejoin="round"/>
        </g>

        {/* ── SOUND WAVES ── */}
        <g opacity="0.1" filter="url(#glow-pink)">
          <path d="M 150 580 Q 160 560 170 580 Q 180 600 190 580 Q 200 560 210 580 Q 220 600 230 580" stroke="#ff0066" strokeWidth="2.5" fill="none" strokeLinecap="round"/>
          <path d="M 140 580 Q 145 545 150 580" stroke="#ff0066" strokeWidth="2" fill="none" strokeLinecap="round"/>
          <path d="M 230 580 Q 235 545 240 580" stroke="#ff0066" strokeWidth="2" fill="none" strokeLinecap="round"/>
        </g>
      </svg>

      {/* Neon corner glow blobs */}
      <div style={{ position: "absolute", top: -120, left: -120, width: 400, height: 400, borderRadius: "50%", background: "radial-gradient(circle, #ff006614 0%, transparent 70%)", pointerEvents: "none" }} />
      <div style={{ position: "absolute", bottom: -100, right: -100, width: 500, height: 500, borderRadius: "50%", background: "radial-gradient(circle, #aa44ff12 0%, transparent 70%)", pointerEvents: "none" }} />
      <div style={{ position: "absolute", top: "40%", right: -80, width: 300, height: 300, borderRadius: "50%", background: "radial-gradient(circle, #00ffcc0e 0%, transparent 70%)", pointerEvents: "none" }} />
      <div style={{ position: "absolute", bottom: "20%", left: -60, width: 260, height: 260, borderRadius: "50%", background: "radial-gradient(circle, #ff98000a 0%, transparent 70%)", pointerEvents: "none" }} />

      <style>{`
        @keyframes floatNote { 0%,100%{transform:translateY(0) rotate(-20deg)} 50%{transform:translateY(-12px) rotate(-20deg)} }
      `}</style>
    </div>
  )
}

function Header({ onNav, currentPage }) {
  return (
    <header style={{
      background: "#0a0a0a",
      borderBottom: "0.5px solid #1f1f1f",
      padding: "0 2rem",
      display: "flex",
      alignItems: "center",
      gap: "2rem",
      height: "56px"
    }}>
      <div style={{ display: "flex", alignItems: "center", gap: "10px" }}>
        <div style={{
          width: 28, height: 28, borderRadius: 6,
          background: "linear-gradient(135deg, #ff4d00, #ff0066)",
          display: "flex", alignItems: "center", justifyContent: "center",
          fontSize: 14, fontWeight: 700, color: "#fff"
        }}>R</div>
        <span style={{ color: "#fff", fontWeight: 600, fontSize: 15, letterSpacing: "-0.02em" }}>
          Renegade Records
        </span>
        <span style={{ color: "#444", fontSize: 13 }}>/ Engine</span>
      </div>
      <nav style={{ display: "flex", gap: "0.25rem", marginLeft: "auto" }}>
        {[["dashboard", "Leads"], ["artist", "Detail"]].map(([p, label]) => (
          <button
            key={p}
            onClick={() => onNav(p)}
            style={{
              background: currentPage === p ? "#1a1a1a" : "transparent",
              border: "none", color: currentPage === p ? "#fff" : "#666",
              padding: "6px 14px", borderRadius: 6, cursor: "pointer",
              fontSize: 13, fontWeight: currentPage === p ? 500 : 400
            }}
          >
            {label}
          </button>
        ))}
      </nav>
    </header>
  )
}
