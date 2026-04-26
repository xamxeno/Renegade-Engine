import { useState, useEffect } from "react"
import Dashboard from "./pages/Dashboard"
import ArtistDetail from "./pages/ArtistDetail"

const API = (import.meta.env.VITE_API_URL || "http://localhost:4000").replace(/\/$/, "")
const SECRET = "Third Door Isn't There"
const AUTH_KEY = "renegade_auth"

export default function App() {
  const [authed, setAuthed] = useState(() => localStorage.getItem(AUTH_KEY) === "1")
  const [page, setPage] = useState("dashboard")
  const [selectedId, setSelectedId] = useState(null)

  const navigate = (p, id = null) => {
    setPage(p)
    setSelectedId(id)
  }

  if (!authed) return <LoginScreen onAuth={() => { localStorage.setItem(AUTH_KEY, "1"); setAuthed(true) }} />

  return (
    <div style={{ minHeight: "100vh", background: "var(--color-background-tertiary)", fontFamily: "var(--font-sans)" }}>
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
