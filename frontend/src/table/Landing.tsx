import { useEffect, useRef, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { api, ApiError, GameMode, SeatInfo, SeatsResponse } from "./api";
import { clearSession, landingAction, loadSession, saveSession } from "./session";
import SiteFooter from "../layouts/SiteFooter";
import { t } from "../i18n";
import Icon from "../Icon";
import QrScanner, { scanSupported } from "./QrScanner";
import { getItem, removeItem, setItem } from "../storage";
import { suggestTableName } from "../username";
import { roomIdFromScan } from "./qrPayload";

/**
 * The room id an invitation carried, taken from the address and then wiped
 * from it.
 *
 * Invitations are `…/table#r/<id>`. A fragment is never sent to a server, so
 * the one credential that opens a room cannot land in uvicorn's or Caddy's
 * access log — which a query string would, on every request. It is removed
 * from the address as soon as it is read so it does not sit in the tab, in
 * history, or in the next screenshot.
 *
 * `?join=` is still honoured, because links shared before this change exist in
 * the world. Nothing produces it any more.
 */
function takeInvitation(search: URLSearchParams): string | null {
  const fromHash = roomIdFromScan(window.location.hash);
  if (fromHash) {
    // same entry, no fragment: no new history step to go "back" through
    window.history.replaceState(null, "", window.location.pathname + window.location.search);
    return fromHash;
  }
  return roomIdFromScan(search.get("join") ?? "");
}
import { useAccount } from "../account/useAccount";

export default function Landing() {
  const navigate = useNavigate();
  const [params] = useSearchParams();
  const [name, setName] = useState(
    () => getItem("table.name") ?? getItem("treachery.name") ?? suggestTableName(),
  );
  const acct = useAccount();
  // once they touch the field the name is theirs, and an account default
  // arriving late must not overwrite what they are in the middle of typing
  const [nameTouched, setNameTouched] = useState(false);
  // read once, on the first render, because reading it also wipes it
  const [invitation, setInvitation] = useState(() => takeInvitation(params));
  const [joinCode, setJoinCode] = useState(invitation ?? "");
  const [mode, setMode] = useState<"join" | "create">(invitation ? "join" : "create");
  const [gameMode, setGameMode] = useState<GameMode>("life");
  const [asDisplay, setAsDisplay] = useState(false);
  const [busy, setBusy] = useState(false);
  const [scanning, setScanning] = useState(false);
  const [error, setError] = useState<string | null>(null);
  // a game already in progress: offer the seats so a dropped player can return
  // keyed by the room's public id: the five-character code opens nothing now
  const [rejoin, setRejoin] = useState<{ roomId: string; seats: SeatInfo[] } | null>(null);

  async function offerRejoin(roomId: string) {
    try {
      const s = await api<SeatsResponse>("/rooms/seats", { method: "POST", body: { roomId } });
      setRejoin({ roomId, seats: s.seats });
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
        "/rooms/reclaim",
        { method: "POST", body: { roomId: rejoin.roomId, pid: seat.pid, force: !seat.vacant } },
      );
      saveSession({ code: res.code, urlId: res.urlId, token: res.playerToken });
      navigate(`/table/r/${res.urlId ?? res.code}`, { replace: true });
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Could not take that seat");
    } finally {
      setBusy(false);
    }
  }
  const [autoJoining, setAutoJoining] = useState(
    () => landingAction(loadSession(), invitation) === "autojoin",
  );
  const autoRan = useRef(false);

  /**
   * A signed-in player's default table name follows them to any device, so it
   * beats this device's last-used name. It is written back to storage as well:
   * every other read of the name — the QR auto-join path included — goes
   * through `table.name`, and leaving those on a stale value would mean the
   * setting applied everywhere except the one screen that skips this form.
   */
  useEffect(() => {
    const preferred = acct?.displayName?.trim();
    if (!preferred) return;
    setItem("table.name", preferred);
    if (!nameTouched) setName(preferred);
  }, [acct, nameTouched]);

  /**
   * An invitation arriving at a tab that is already here.
   *
   * `/table` → `/table#r/<id>` changes only the fragment, so the browser does
   * not reload and this component never remounts — the invitation would sit in
   * the address doing nothing. That is not just a test artifact: pasting a link
   * into a tab already showing the landing page does exactly this.
   */
  useEffect(() => {
    const onHash = () => {
      const next = takeInvitation(params);
      if (!next) return;
      autoRan.current = false;
      setInvitation(next);
      setJoinCode(next);
      setMode("join");
      setAutoJoining(landingAction(loadSession(), next) === "autojoin");
    };
    window.addEventListener("hashchange", onHash);
    return () => window.removeEventListener("hashchange", onHash);
  }, [params]);

  useEffect(() => {
    const joinParam = invitation;
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
        const nm = (getItem("table.name") ?? "").trim() || suggestTableName();
        const roomId = joinParam.trim();
        try {
          const res = await api<{ code: string; urlId?: string; playerToken: string }>(
            "/rooms/join",
            { method: "POST", body: { roomId, name: nm, display: false } },
          );
          setItem("table.name", nm);
          saveSession({ code: res.code, urlId: res.urlId, token: res.playerToken });
          navigate(`/table/r/${res.urlId ?? res.code}`, { replace: true });
        } catch (e) {
          setAutoJoining(false);
          setMode("join");
          setJoinCode(roomId);
          setName(nm);
          // a game in progress isn't a dead end — offer the seats to reclaim
          if (e instanceof ApiError && e.status === 409 && (await offerRejoin(roomId))) return;
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
    //  is a dependency: an invitation can arrive after mount, when
    // a link is opened in a tab already showing this page.
  }, [navigate, params, invitation]);

  if (autoJoining) {
    return (
      <div className="tr-landing">
        <header>
          <h1>Table</h1>
          <p className="tagline">Joining…</p>
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
              body: {
                name: trimmed || "Table display",
                mode: gameMode,
                display: asDisplay,
              },
            })
          : await api<{ code: string; urlId?: string; playerToken: string }>("/rooms/join", {
              method: "POST",
              body: {
                roomId: roomIdFromScan(joinCode) ?? joinCode.trim(),
                name: trimmed || "Table display",
                display: asDisplay,
              },
            });
      saveSession({ code: res.code, urlId: res.urlId, token: res.playerToken });
      navigate(`/table/r/${res.urlId ?? res.code}`);
    } catch (e) {
      const roomId = roomIdFromScan(joinCode) ?? joinCode.trim();
      if (mode === "join" && e instanceof ApiError && e.status === 409 && (await offerRejoin(roomId))) {
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
          <h1>Rejoin this game</h1>
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
              <strong>Start a game</strong> and you get a QR code and an invitation link
              to share.
            </li>
            <li>
              <strong>Everyone else scans it, or pastes the link.</strong> No app to
              install, and no account needed to play.
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
              <span>Room ID or invitation link</span>
              {/* No length cap, no upper-casing, no character class. This is
                  base64url and case is meaningful — the old field did all
                  three to a five-character code and would silently destroy
                  this one. Pasting the whole link is the common case, so the
                  field takes that too and picks the id out of it. */}
              <input
                type="text"
                className="room-id-input"
                placeholder="Paste the room ID or link"
                autoCapitalize="none"
                autoCorrect="off"
                spellCheck={false}
                autoComplete="off"
                value={joinCode}
                onChange={(e) => setJoinCode(e.target.value)}
              />
            </label>
            {scanSupported() && (
              <button className="ghost" onClick={() => setScanning(true)}>
                <Icon name="card" /> {t("scan.button")}
              </button>
            )}
          </>
        )}

        {/* Either way round: a spare tablet can open the room as the shared
            screen, or join one that already exists. Creating as the display is
            the natural setup — the screen shows the code everyone scans — and
            the first player to join takes the host's controls. */}
        <label className="display-toggle">
          <input
            type="checkbox"
            checked={asDisplay}
            onChange={(e) => setAsDisplay(e.target.checked)}
          />
          Use this device as the table display (shared screen, not a player)
        </label>

        {!asDisplay && (
          <label className="field">
            <span>Your name at the table</span>
            <input
              type="text"
              placeholder="Your name"
              maxLength={24}
              value={name}
              onChange={(e) => {
                setName(e.target.value);
                setNameTouched(true);
              }}
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
          {busy
            ? "…"
            : mode === "create"
              ? asDisplay ? "Create as display" : "Create room"
              : asDisplay ? "Join as display" : "Join room"}
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
