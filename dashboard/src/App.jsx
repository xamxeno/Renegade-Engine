import { useState, useEffect } from "react"
import Dashboard from "./pages/Dashboard"
import ArtistDetail from "./pages/ArtistDetail"

const API = (import.meta.env.VITE_API_URL || "http://localhost:4000").replace(/\/$/, "")

export default function App() {
  const [page, setPage] = useState("dashboard")
  const [selectedId, setSelectedId] = useState(null)

  const navigate = (p, id = null) => {
    setPage(p)
    setSelectedId(id)
  }

  return (
    <div style={{ minHeight: "100vh", background: "var(--color-background-tertiary)", fontFamily: "var(--font-sans)" }}>
      <Header onNav={navigate} currentPage={page} />
      {page === "dashboard" && <Dashboard API={API} onSelect={(id) => navigate("artist", id)} />}
      {page === "artist" && <ArtistDetail API={API} id={selectedId} onBack={() => navigate("dashboard")} />}
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
