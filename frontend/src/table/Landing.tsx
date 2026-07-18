import { useEffect, useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { api, ApiError, GameMode } from "./api";
import { clearSession, loadSession, saveSession } from "./session";

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
  const [name, setName] = useState(
    () => localStorage.getItem("table.name") ?? localStorage.getItem("treachery.name") ?? randomName(),
  );
  const [joinCode, setJoinCode] = useState(params.get("join") ?? "");
  const [mode, setMode] = useState<"join" | "create">(params.get("join") ? "join" : "create");
  const [gameMode, setGameMode] = useState<GameMode>("life");
  const [asDisplay, setAsDisplay] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const s = loadSession();
    if (!s) return;
    let cancelled = false;
    // verify against the server before redirecting — a stale/left session must not pull us back in
    api(`/rooms/${s.code}/me`, { token: s.token })
      .then(() => {
        if (!cancelled) navigate(`/table/r/${s.code}`, { replace: true });
      })
      .catch(() => {
        if (!cancelled) clearSession();
      });
    return () => {
      cancelled = true;
    };
  }, [navigate]);

  async function go() {
    const trimmed = name.trim();
    if (!trimmed && !asDisplay) {
      setError("Enter a name first");
      return;
    }
    setBusy(true);
    setError(null);
    if (trimmed) localStorage.setItem("table.name", trimmed);
    try {
      const res =
        mode === "create"
          ? await api<{ code: string; playerToken: string }>("/rooms", {
              method: "POST",
              body: { name: trimmed, mode: gameMode },
            })
          : await api<{ code: string; playerToken: string }>(
              `/rooms/${joinCode.trim().toUpperCase()}/join`,
              { method: "POST", body: { name: trimmed || "display", display: asDisplay } },
            );
      saveSession({ code: res.code, token: res.playerToken });
      navigate(`/table/r/${res.code}`);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Something went wrong");
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className="tr-landing">
      <header>
        <h1>Table</h1>
        <p className="tagline">Life totals &amp; hidden roles for game night</p>
      </header>

      <div className="tr-form">
        <div className="tr-mode">
          <button className={mode === "create" ? "active" : ""} onClick={() => setMode("create")}>
            Create game
          </button>
          <button className={mode === "join" ? "active" : ""} onClick={() => setMode("join")}>
            Join game
          </button>
        </div>

        {mode === "create" && (
          <div className="tr-mode">
            <button
              className={gameMode === "life" ? "active" : ""}
              onClick={() => setGameMode("life")}
            >
              ♥ Life counter
            </button>
            <button
              className={gameMode === "treachery" ? "active" : ""}
              onClick={() => setGameMode("treachery")}
            >
              ⚔ Treachery
            </button>
          </div>
        )}

        {mode === "join" && (
          <>
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
            <label className="display-toggle">
              <input
                type="checkbox"
                checked={asDisplay}
                onChange={(e) => setAsDisplay(e.target.checked)}
              />
              Join as table display (shared screen, not a player)
            </label>
          </>
        )}

        {!asDisplay && (
          <input
            type="text"
            placeholder="Your name"
            maxLength={24}
            value={name}
            onChange={(e) => setName(e.target.value)}
          />
        )}

        {error && <p className="error">{error}</p>}
        <button
          className="primary"
          disabled={busy || (mode === "join" && joinCode.trim().length < 5)}
          onClick={() => void go()}
        >
          {busy ? "…" : mode === "create" ? "Create room" : asDisplay ? "Connect display" : "Join room"}
        </button>
      </div>

      <footer>
        <Link to="/">← mtg.skadoosh.dev</Link>
      </footer>
    </main>
  );
}
