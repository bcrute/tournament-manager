import { useEffect, useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { api, ApiError } from "./api";
import { loadSession, saveSession } from "./session";

function randomName() {
  const chars = "abcdefghjkmnpqrstuvwxyz23456789";
  return Array.from(
    crypto.getRandomValues(new Uint8Array(5)),
    (b) => chars[b % chars.length],
  ).join("");
}

export default function Landing() {
  const navigate = useNavigate();
  const [params] = useSearchParams();
  const [name, setName] = useState(() => localStorage.getItem("treachery.name") ?? randomName());
  const [joinCode, setJoinCode] = useState(params.get("join") ?? "");
  const [mode, setMode] = useState<"join" | "create">(params.get("join") ? "join" : "create");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const s = loadSession();
    if (s) navigate(`/treachery/r/${s.code}`, { replace: true });
  }, [navigate]);

  async function go() {
    const trimmed = name.trim();
    if (!trimmed) {
      setError("Enter a name first");
      return;
    }
    setBusy(true);
    setError(null);
    localStorage.setItem("treachery.name", trimmed);
    try {
      const res =
        mode === "create"
          ? await api<{ code: string; playerToken: string }>("/rooms", {
              method: "POST",
              body: { name: trimmed },
            })
          : await api<{ code: string; playerToken: string }>(
              `/rooms/${joinCode.trim().toUpperCase()}/join`,
              { method: "POST", body: { name: trimmed } },
            );
      saveSession({ code: res.code, token: res.playerToken });
      navigate(`/treachery/r/${res.code}`);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Something went wrong");
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className="tr-landing">
      <header>
        <h1>Treachery</h1>
        <p className="tagline">Hidden roles for Commander</p>
      </header>

      <div className="tr-form">
        <input
          type="text"
          placeholder="Your name"
          maxLength={24}
          value={name}
          onChange={(e) => setName(e.target.value)}
        />
        <div className="tr-mode">
          <button className={mode === "create" ? "active" : ""} onClick={() => setMode("create")}>
            Create game
          </button>
          <button className={mode === "join" ? "active" : ""} onClick={() => setMode("join")}>
            Join game
          </button>
        </div>
        {mode === "join" && (
          <input
            type="text"
            className="code-input"
            placeholder="ROOM CODE"
            maxLength={5}
            autoCapitalize="characters"
            autoComplete="off"
            value={joinCode}
            onChange={(e) => setJoinCode(e.target.value.toUpperCase())}
          />
        )}
        {error && <p className="error">{error}</p>}
        <button
          className="primary"
          disabled={busy || (mode === "join" && joinCode.trim().length < 5)}
          onClick={() => void go()}
        >
          {busy ? "…" : mode === "create" ? "Create room" : "Join room"}
        </button>
      </div>

      <footer>
        <Link to="/">← mtg.skadoosh.dev</Link>
      </footer>
    </main>
  );
}
