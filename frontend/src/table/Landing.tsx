import { useEffect, useRef, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { api, ApiError, GameMode, SeatInfo, SeatsResponse } from "./api";
import { clearSession, landingAction, loadSession, saveSession } from "./session";
import SiteFooter from "../layouts/SiteFooter";
import { t } from "../i18n";
import Icon from "../Icon";
import QrScanner, { scanSupported } from "./QrScanner";
import { getItem, removeItem, setItem } from "../storage";

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
    () => getItem("table.name") ?? getItem("treachery.name") ?? randomName(),
  );
  const [joinCode, setJoinCode] = useState(params.get("join") ?? "");
  const [mode, setMode] = useState<"join" | "create">(params.get("join") ? "join" : "create");
  const [gameMode, setGameMode] = useState<GameMode>("life");
  const [asDisplay, setAsDisplay] = useState(false);
  const [busy, setBusy] = useState(false);
  const [scanning, setScanning] = useState(false);
  const [error, setError] = useState<string | null>(null);
  // a game already in progress: offer the seats so a dropped player can return
  const [rejoin, setRejoin] = useState<{ code: string; seats: SeatInfo[] } | null>(null);

  async function offerRejoin(roomCode: string) {
    try {
      const s = await api<SeatsResponse>(`/rooms/${roomCode}/seats`);
      setRejoin({ code: roomCode, seats: s.seats });
      return true;
    } catch {
      return false;
    }
  }

  async function takeSeat(seat: SeatInfo) {
    if (!rejoin) return;
    if (!seat.vacant && !window.confirm(`${seat.name}'s seat is still in use. Take it over?`)) return;
    setBusy(true);
    try {
      const res = await api<{ code: string; urlId?: string; playerToken: string }>(
        `/rooms/${rejoin.code}/reclaim`,
        { method: "POST", body: { pid: seat.pid, force: !seat.vacant } },
      );
      saveSession({ code: res.code, urlId: res.urlId, token: res.playerToken });
      navigate(`/table/r/${res.urlId ?? res.code}`, { replace: true });
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Could not take that seat");
    } finally {
      setBusy(false);
    }
  }
  const [autoJoining, setAutoJoining] = useState(() => landingAction(loadSession(), params.get("join")) === "autojoin");
  const autoRan = useRef(false);

  useEffect(() => {
    const joinParam = params.get("join");
    const s = loadSession();
    const action = landingAction(s, joinParam);
    if (action === "none") return;

    if (action === "autojoin" && joinParam) {
      // scanned a QR: leave any old game, then join the new room immediately
      if (autoRan.current) return;
      autoRan.current = true;
      void (async () => {
        if (s) {
          await api(`/rooms/${s.code}/leave`, { method: "POST", token: s.token }).catch(() => {});
          clearSession();
        }
        const nm = (getItem("table.name") ?? "").trim() || randomName();
        try {
          const res = await api<{ code: string; urlId?: string; playerToken: string }>(
            `/rooms/${joinParam.trim().toUpperCase()}/join`,
            { method: "POST", body: { name: nm, display: false } },
          );
          setItem("table.name", nm);
          saveSession({ code: res.code, urlId: res.urlId, token: res.playerToken });
          navigate(`/table/r/${res.urlId ?? res.code}`, { replace: true });
        } catch (e) {
          const roomCode = joinParam.trim().toUpperCase();
          setAutoJoining(false);
          setMode("join");
          setJoinCode(roomCode);
          setName(nm);
          // a game in progress isn't a dead end — offer the seats to reclaim
          if (e instanceof ApiError && e.status === 409 && (await offerRejoin(roomCode))) return;
          setError(e instanceof ApiError ? e.message : "Could not join the room");
        }
      })();
      return;
    }

    if (!s) return;
    let cancelled = false;
    // verify against the server before redirecting — a stale/left session must not pull us back in
    api(`/rooms/${s.code}/me`, { token: s.token })
      .then(() => {
        if (!cancelled) navigate(`/table/r/${s.urlId ?? s.code}`, { replace: true });
      })
      .catch(() => {
        if (!cancelled) clearSession();
      });
    return () => {
      cancelled = true;
    };
  }, [navigate, params]);

  if (autoJoining) {
    return (
      <div className="tr-landing">
        <header>
          <h1>Table</h1>
          <p className="tagline">Joining room {params.get("join")}…</p>
        </header>
      </div>
    );
  }

  async function go() {
    const trimmed = name.trim();
    if (!trimmed && !asDisplay) {
      setError("Enter a name first");
      return;
    }
    setBusy(true);
    setError(null);
    if (trimmed) setItem("table.name", trimmed);
    try {
      const res =
        mode === "create"
          ? await api<{ code: string; urlId?: string; playerToken: string }>("/rooms", {
              method: "POST",
              body: { name: trimmed, mode: gameMode },
            })
          : await api<{ code: string; urlId?: string; playerToken: string }>(
              `/rooms/${joinCode.trim().toUpperCase()}/join`,
              { method: "POST", body: { name: trimmed || "display", display: asDisplay } },
            );
      saveSession({ code: res.code, urlId: res.urlId, token: res.playerToken });
      navigate(`/table/r/${res.urlId ?? res.code}`);
    } catch (e) {
      const roomCode = joinCode.trim().toUpperCase();
      if (mode === "join" && e instanceof ApiError && e.status === 409 && (await offerRejoin(roomCode))) {
        setBusy(false);
        return;
      }
      setError(e instanceof ApiError ? e.message : "Something went wrong");
    } finally {
      setBusy(false);
    }
  }

  if (rejoin) {
    return (
      <div className="tr-landing">
        <header>
          <h1>Rejoin {rejoin.code}</h1>
          <p className="tagline">That game is already under way — pick your seat</p>
        </header>
        <ul className="seat-picker">
          {rejoin.seats.map((s) => (
            <li key={s.pid}>
              <button
                className={s.vacant ? "primary" : "ghost"}
                disabled={busy}
                onClick={() => void takeSeat(s)}
              >
                {s.name}
                {s.eliminated && <Icon name="skull" label="eliminated" />}
                <span className="seat-state">{s.vacant ? "left — tap to return" : "in use"}</span>
              </button>
            </li>
          ))}
        </ul>
        {error && <p className="error">{error}</p>}
        <footer>
          <button className="ghost" onClick={() => setRejoin(null)}>
            ← back
          </button>
        </footer>
      </div>
    );
  }

  return (
    <div className="tr-landing">
      <header>
        <h1>Table</h1>
        <p className="tagline">Life totals &amp; hidden roles for game night</p>
      </header>

      <div className="tr-columns">
        <aside className="tr-explainer">
          <h2>How it works</h2>
          <ol>
            <li>
              <strong>Start a game</strong> and a five-character room code appears, with a
              QR code beside it.
            </li>
            <li>
              <strong>Everyone else scans or types it.</strong> No app to install, and no
              account needed to play.
            </li>
            <li>
              <strong>Each player keeps their own total</strong> on their own phone, and
              the whole table stays in sync.
            </li>
          </ol>
          <p className="hint">
            No spare tablet? Any player can show the shared table view on their own phone
            from the menu, without giving up their seat.
          </p>
        </aside>

      <div className="tr-form">
        <div className="tr-mode">
          <button className={mode === "create" ? "active" : ""} onClick={() => setMode("create")}>
            Create
          </button>
          <button className={mode === "join" ? "active" : ""} onClick={() => setMode("join")}>
            Join
          </button>
        </div>

        {mode === "create" && (
          <div className="tr-mode">
            <button
              className={gameMode === "life" ? "active" : ""}
              onClick={() => setGameMode("life")}
            >
              <Icon name="heart" /> Life counter
            </button>
            <button
              className={gameMode === "treachery" ? "active" : ""}
              onClick={() => setGameMode("treachery")}
            >
              <Icon name="sword" /> Treachery
            </button>
          </div>
        )}

        {mode === "join" && (
          <>
            <label className="field">
              <span>Room code</span>
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
            </label>
            {scanSupported() && (
              <button className="ghost" onClick={() => setScanning(true)}>
                <Icon name="card" /> {t("scan.button")}
              </button>
            )}
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
          <label className="field">
            <span>Your name at the table</span>
            <input
              type="text"
              placeholder="Your name"
              maxLength={24}
              value={name}
              onChange={(e) => setName(e.target.value)}
            />
            <span className="hint">
              Shown to the other players. We generated one — change it if you like.
            </span>
          </label>
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
      </div>

      {scanning && (
        <QrScanner
          onClose={() => setScanning(false)}
          onCode={(code) => {
            setScanning(false);
            setJoinCode(code);
          }}
        />
      )}

      <SiteFooter />
    </div>
  );
}
