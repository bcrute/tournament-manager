import { useEffect, useRef, useState } from "react";
import { QRCodeSVG } from "qrcode.react";
import { useNavigate, useParams } from "react-router-dom";
import { api, ApiError, GameMode, PlayerInfo, RoomState } from "./api";
import { t } from "../i18n";
import Icon from "../Icon";
import { createBackGuard } from "./backGuard";
import { CarouselEntry, carouselEntries, clampIndex, indexOfPid, step } from "./carousel";
import { clearSession, loadSession } from "./session";
import DisplayView from "./DisplayView";
import LifePanel from "./LifePanel";
import NotesSheet from "./NotesSheet";
import RoomBar from "./RoomBar";
import RoundClock from "./RoundClock";
import { getAccount } from "../account/api";
import TournamentSheet from "./TournamentSheet";
import QrSheet from "./QrSheet";
import RulesSheet from "./RulesSheet";
import SlideToUnveil from "./SlideToUnveil";
import { useAutoHide } from "./useAutoHide";
import { useRoom } from "./useRoom";
import { useWakeLock } from "./useWakeLock";

const ROLE_ORDER = ["Leader", "Guardian", "Assassin", "Traitor"];

function distSummary(dist: Record<string, number>) {
  return ROLE_ORDER.filter((r) => dist[r] > 0)
    .map((r) => `${dist[r]} ${r}${dist[r] > 1 ? "s" : ""}`)
    .join(" · ");
}

export default function Room() {
  const { code: urlParam = "" } = useParams();
  const navigate = useNavigate();
  const session = loadSession();

  useEffect(() => {
    // match on the url id; fall back to the code so links shared before this
    // change, and any still in someone's history, keep working
    const mine = session && (session.urlId === urlParam || session.code === urlParam.toUpperCase());
    if (!mine) navigate("/table", { replace: true });
  }, [session, urlParam, navigate]);

  if (!session || !(session.urlId === urlParam || session.code === urlParam.toUpperCase()))
    return null;
  return <RoomInner code={session.code} token={session.token} />;
}

interface Toast {
  id: number;
  text: string;
  zoomPid?: number;
}

type Tab = "card" | "life" | "table";

function RoomInner({ code, token }: { code: string; token: string }) {
  // counting an additional turn is a tournament action; the room is just where
  // the players happen to be looking when time is called
  async function countTurn(delta: number) {
    const t = state?.tournament;
    if (!t) return;
    // counting a turn decides the pod, so the server requires proof the caller
    // is actually at this table — that's the entrant token, not the room token
    const { loadSeat } = await import("../tournament/api");
    const seat = loadSeat();
    const auth = seat && seat.code === t.code ? `?token=${encodeURIComponent(seat.token)}` : "";
    await fetch(`/api/tournament/${t.code}/pods/${t.podId}/turn${auth}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ delta }),
    }).catch(() => {});
    await refetch();
  }

  const navigate = useNavigate();
  const { state, gone, error, stale, refetch } = useRoom(code, token);
  const [tab, setTab] = useState<Tab | null>(null);
  const [cardIndex, setCardIndex] = useState(0);
  const [zoomPid, setZoomPid] = useState<number | null>(null);
  const [notesOpen, setNotesOpen] = useState(false);
  const [rulesOpen, setRulesOpen] = useState(false);
  const [tourneyOpen, setTourneyOpen] = useState(false);
  const [qrOpen, setQrOpen] = useState(false);
  // "Your games & notes" only means something with an account behind it
  const [signedIn, setSignedIn] = useState(false);
  useEffect(() => {
    void getAccount().then((r) => setSignedIn(!!r.account)).catch(() => setSignedIn(false));
  }, []);
  const [toasts, setToasts] = useState<Toast[]>([]);
  const prev = useRef<{ status: string; pids: Set<number>; first: number | null } | null>(null);
  const toastId = useRef(0);

  useEffect(() => {
    if (gone) navigate("/table", { replace: true });
  }, [gone, navigate]);

  // keep the screen on during active games and on table displays; lobby screens may sleep
  useWakeLock(state?.room.status === "playing" || state?.me.isDisplay === true);

  // game over (last player standing, or the host ended it): everyone counts down together
  const [countdown, setCountdown] = useState<number | null>(null);
  const gameOver = state?.room.status === "ended";
  useEffect(() => {
    if (!gameOver) {
      setCountdown(null);
      return;
    }
    setCountdown(5);
    const iv = window.setInterval(() => setCountdown((c) => (c === null ? null : c - 1)), 1000);
    return () => window.clearInterval(iv);
  }, [gameOver]);
  const isHost = state?.me.isHost === true;
  useEffect(() => {
    // one client drives the return so the room resets exactly once
    if (countdown === 0 && isHost) {
      void api(`/rooms/${code}/reopen`, { method: "POST", token }).catch(() => {});
    }
  }, [countdown, isHost, code, token]);

  const pushToast = (text: string, zoomPid?: number) => {
    const id = ++toastId.current;
    setToasts((t) => [...t, { id, text, zoomPid }]);
    window.setTimeout(() => setToasts((t) => t.filter((x) => x.id !== id)), 7000);
  };

  // Double back is a bonus shortcut only — the ⋮ menu is the real exit, because a
  // back-swipe in a QR-launched tab can leave the site entirely (OS-level, uncatchable).
  const backGuard = useRef(createBackGuard()).current;
  const onBackRef = useRef<() => void>(() => {});
  useEffect(() => {
    const arm = () => {
      if (history.state?.tableRoom !== code) history.pushState({ tableRoom: code }, "");
    };
    arm();
    const onPop = () => onBackRef.current();
    // keep the sentinel topped up: bfcache restores and tab switches can drop it
    const onShow = () => arm();
    window.addEventListener("popstate", onPop);
    window.addEventListener("pageshow", onShow);
    document.addEventListener("visibilitychange", onShow);
    return () => {
      window.removeEventListener("popstate", onPop);
      window.removeEventListener("pageshow", onShow);
      document.removeEventListener("visibilitychange", onShow);
    };
  }, [code]);

  // toasts for mid-game reveals and the first-turn announcement (tracked by stable pid, not name)
  useEffect(() => {
    if (!state) return;
    const revealed = state.players.filter((p) => p.revealed && !p.isMe);
    const pids = new Set(revealed.map((p) => p.pid));
    const p = prev.current;
    if (p && p.status === "playing" && state.room.status === "playing") {
      for (const rp of revealed) {
        if (!p.pids.has(rp.pid)) pushToast(t("status.revealed", { name: rp.name }), rp.pid);
      }
    }
    if (p && p.status === "lobby" && state.room.status === "playing") {
      // a fresh deal: land on the default screen (card in treachery), not last game's tab
      setTab(null);
      setCardIndex(0);
    }
    if (p && state.room.firstPid !== null && p.first !== state.room.firstPid && p.status === "lobby" && state.room.status === "playing") {
      const who = state.room.firstPlayer;
      const isLeader = state.room.mode === "treachery";
      pushToast(
        state.room.firstPid === state.me.pid
          ? t("status.youGoFirst")
          : t("status.goesFirst", { name: `${who}${isLeader ? " (Leader)" : ""}` }),
      );
    }
    prev.current = { status: state.room.status, pids, first: state.room.firstPid };
  }, [state]);

  if (error) return <main className="tr-landing"><p className="error">{error}</p></main>;
  if (!state) return <main className="tr-landing"><p className="tagline">Loading…</p></main>;

  const act = (path: string) => api(`/rooms/${code}${path}`, { method: "POST", token });

  async function leaveNow() {
    try {
      await act("/leave");
    } catch {
      // leaving a dead room is fine
    }
    clearSession();
    navigate("/table", { replace: true });
  }

  async function leave(confirmMsg: string) {
    if (!window.confirm(confirmMsg)) return;
    await leaveNow();
  }

  async function toggleTracking(tracking: boolean) {
    if (!state) return;
    try {
      await api(`/rooms/${code}/tracker`, { method: "POST", token, body: { tracking } });
    } catch (e) {
      window.alert(e instanceof ApiError ? e.message : "Could not switch view");
    }
  }

  async function toggleDisplay(display: boolean) {
    if (!state) return;
    const msg = display
      ? "Use this device as the shared table display? It gives up its seat in the game."
      : "Take a seat as a player?";
    if (!window.confirm(msg)) return;
    try {
      await api(`/rooms/${code}/display`, { method: "POST", token, body: { display } });
    } catch (e) {
      window.alert(e instanceof ApiError ? e.message : "Could not switch");
    }
  }

  async function renameSelf() {
    if (!state) return;
    const nm = window.prompt("Your name", state.me.name)?.trim();
    if (!nm || nm === state.me.name) return;
    try {
      await api(`/rooms/${code}/rename`, { method: "POST", token, body: { name: nm } });
      localStorage.setItem("table.name", nm);
    } catch (e) {
      window.alert(e instanceof ApiError ? e.message : "Rename failed");
    }
  }

  onBackRef.current = () => {
    const midTreachery = state.room.mode === "treachery" && state.room.status === "playing" && !state.me.isDisplay;
    backGuard.onBack({
      leave: () => void leaveNow(),
      warn: () =>
        pushToast(
          state.me.isDisplay
            ? "Go back again to disconnect this display"
            : midTreachery
              ? "Go back again to leave — your identity will be revealed"
              : "Go back again to leave the game",
        ),
      rearm: () => history.pushState({ tableRoom: code }, ""),
    });
  };

  if (state.me.isDisplay) {
    return (
      <DisplayView
        state={state}
        code={code}
        token={token}
        onTakeSeat={state.room.status === "lobby" ? () => void toggleDisplay(false) : undefined}
        onLeave={() => void leave("Disconnect this display?")}
      />
    );
  }

  // A player keeping score sees the same table view a dedicated display shows,
  // but they still hold their seat — so the way out is "back to my view", not
  // "take a seat", and leaving still means leaving the game.
  if (state.me.isTracker && !state.me.isDisplay) {
    return (
      <>
        {/* no onLeave: this is a player showing the table view, not a
            dedicated display. "Disconnect" belongs to a device that gave up its
            seat, and offering it here would drop them out of their own game —
            "Back to my view" below is the way out. upright: this device is in
            someone's hand, not lying flat in the middle of the table. */}
        <DisplayView state={state} code={code} token={token} upright />
        <div className="tracker-bar">
          <span>
            <Icon name="monitor" /> Keeping score for the table
          </span>
          <button onClick={() => void toggleTracking(false)}>Back to my view</button>
        </div>
      </>
    );
  }

  const leaveMsg = () =>
    state.room.mode === "treachery" && state.room.status === "playing"
      ? "Leave mid-game? Your identity will be revealed to the table."
      : "Leave and forget this game?";

  if (state.room.status === "lobby") {
    return (
      <>
        {state.tournament && <RoundClock t={state.tournament} onTurn={(d) => void countTurn(d)} />}
        <RoomBar
          code={code}
          name={state.me.name}
          onRename={() => void renameSelf()}
          onRules={() => setRulesOpen(true)}
          onTournament={state.tournament ? () => setTourneyOpen(true) : undefined}
          onDisplay={() => void toggleDisplay(true)}
          onTrack={() => void toggleTracking(true)}
          onShowQr={() => setQrOpen(true)}
          onMyGames={signedIn ? () => navigate("/account") : undefined}
          onLeave={() => void leave("Leave this room?")}
          leaveLabel="Leave room"
        />
        {rulesOpen && (
        <RulesSheet treachery={state.room.mode === "treachery"} onClose={() => setRulesOpen(false)} />
      )}
      {qrOpen && <QrSheet code={code} onClose={() => setQrOpen(false)} />}
      {tourneyOpen && state.tournament && (
        <TournamentSheet code={state.tournament.code} onClose={() => setTourneyOpen(false)} />
      )}

        <Lobby state={state} code={code} token={token} onRename={() => void renameSelf()} />
      </>
    );
  }

  const treachery = state.room.mode === "treachery";
  const ended = state.room.status === "ended";
  const activeTab: Tab = ended ? "table" : (tab ?? (treachery ? "card" : "life"));
  const zoomPlayer = zoomPid !== null ? state.players.find((p) => p.pid === zoomPid && p.card) : undefined;
  const entries = carouselEntries(state.players);
  const safeIndex = clampIndex(cardIndex, entries.length);

  // tapping a reveal toast carries you to that player's card in the carousel
  const showCardOf = (pid: number) => {
    const i = indexOfPid(carouselEntries(state.players), pid);
    if (i >= 0) {
      setCardIndex(i);
      setTab("card");
    } else {
      setZoomPid(pid);
    }
  };

  return (
    <div className="tr-room">
      {state.tournament && <RoundClock t={state.tournament} onTurn={(d) => void countTurn(d)} />}
      <RoomBar
        code={code}
        name={state.me.name}
        onRename={() => void renameSelf()}
        onNotes={() => setNotesOpen(true)}
        onRules={() => setRulesOpen(true)}
        onTournament={state.tournament ? () => setTourneyOpen(true) : undefined}
        onDisplay={() => void toggleDisplay(true)}
        onTrack={() => void toggleTracking(true)}
        onShowQr={() => setQrOpen(true)}
        onMyGames={signedIn ? () => navigate("/account") : undefined}
        onLeave={() => void leave(leaveMsg())}
      />
      {rulesOpen && (
        <RulesSheet treachery={state.room.mode === "treachery"} onClose={() => setRulesOpen(false)} />
      )}
      {qrOpen && <QrSheet code={code} onClose={() => setQrOpen(false)} />}
      {tourneyOpen && state.tournament && (
        <TournamentSheet code={state.tournament.code} onClose={() => setTourneyOpen(false)} />
      )}
      {notesOpen && (
        <NotesSheet
          code={code}
          gameNo={state.room.gameNo}
          onClose={() => setNotesOpen(false)}
          onNeedsAccount={() => {
            setNotesOpen(false);
            window.location.href = "/account";
          }}
        />
      )}
      <div className="toasts" onPointerDown={(e) => e.stopPropagation()}>
        {toasts.map((t) => (
          <button
            key={t.id}
            className="toast"
            onClick={() => {
              setToasts((all) => all.filter((x) => x.id !== t.id));
              if (t.zoomPid !== undefined) showCardOf(t.zoomPid);
            }}
          >
            {t.text}
          </button>
        ))}
      </div>
      {zoomPlayer && <CardZoom p={zoomPlayer} onClose={() => setZoomPid(null)} />}
      {stale && <div className="stale-pill">{t("status.reconnecting")}</div>}
      {countdown !== null && countdown > 0 && (
        <div className="countdown-banner">
          {t("status.gameOver", { n: countdown })}
        </div>
      )}

      {activeTab === "card" && treachery && (
        <RoleScreen
          state={state}
          entries={entries}
          index={safeIndex}
          setIndex={setCardIndex}
          onUnveil={() => act("/unveil").then(() => undefined)}
        />
      )}
      {activeTab !== "card" && (
        /* life and table are one main: on a phone the tabs pick which section
           shows; past 60rem (life mode) both render side by side and the tabs
           disappear — a desktop doesn't need to choose. treachery keeps one
           section at a time (`solo`), since the card screen still needs tabs. */
        <main className={`tr-panels active-${activeTab}${treachery ? " solo" : ""}`}>
          {(!treachery || activeTab === "life") && (
            <section className="tr-life-page">
              <header>
                <p className="tagline">
                  {state.me.name}{" "}
                  <button className="ghost rename-btn" onClick={() => void renameSelf()}>
                    <Icon name="edit" size={14} label={t("menu.rename")} />
                  </button>
                </p>
                <p className="tagline">
                  {state.room.firstPlayer && `${state.room.firstPlayer} went first · `}room {code}
                </p>
              </header>
              <LifePanel state={state} code={code} token={token} />
            </section>
          )}
          {(!treachery || activeTab === "table") && (
            <TableView
              state={state}
              onZoom={(p) => setZoomPid(p.pid)}
              onEnd={
                state.me.isHost && !ended
                  ? () => {
                      const msg = treachery
                        ? "End the game and return everyone to the room? Identities are revealed first."
                        : "End the game and return everyone to the room?";
                      if (window.confirm(msg)) void act("/end");
                    }
                  : undefined
              }
              onReopen={state.me.isHost && ended ? () => void act("/reopen") : undefined}
            />
          )}
        </main>
      )}

      {!ended && (
        <nav
          className={`bottom-nav${treachery ? "" : " no-card"}`}
          onPointerDown={(e) => e.stopPropagation()}
        >
          {treachery && (
            <button className={activeTab === "card" ? "active" : ""} onClick={() => setTab("card")}>
              <Icon name="card" /> {t("nav.card")}
            </button>
          )}
          <button className={activeTab === "life" ? "active" : ""} onClick={() => setTab("life")}>
            <Icon name="heart" /> {t("nav.life")}
          </button>
          <button className={activeTab === "table" ? "active" : ""} onClick={() => setTab("table")}>
            <Icon name="users" /> {t("nav.table")}
          </button>
        </nav>
      )}
    </div>
  );
}

function Lobby({
  state,
  code,
  token,
  onRename,
}: {
  state: RoomState;
  code: string;
  token: string;
  onRename: () => void;
}) {
  const joinUrl = `${location.origin}/table?join=${code}`;
  const treachery = state.room.mode === "treachery";
  const n = state.players.filter((p) => !p.left).length;
  const [customLife, setCustomLife] = useState("");

  async function setOptions(body: { startingLife?: number; mode?: GameMode }) {
    await api(`/rooms/${code}/options`, { method: "POST", token, body });
  }

  return (
    <main className="tr-lobby">
      <header>
        <p className="tagline">
          <Icon name={treachery ? "sword" : "heart"} />{" "}
          {treachery ? "Treachery" : "Life counter"} · room code
        </p>
        <h1 className="room-code">{code}</h1>
      </header>
      <div className="qr">
        <QRCodeSVG value={joinUrl} size={144} bgColor="#14101c" fgColor="#e8e4f0" marginSize={2} />
      </div>

      <section className="tr-players">
        <h2>Players ({n})</h2>
        <ul>
          {state.players.map((p) => (
            <li key={p.pid}>
              {p.name}
              {p.isHost && <Icon name="crown" size={13} label="Host" />}
              {p.isMe && (
                <>
                  {" (you) "}
                  <button className="ghost rename-btn" onClick={onRename}>
                    <Icon name="edit" size={14} label={t("menu.rename")} />
                  </button>
                </>
              )}
            </li>
          ))}
        </ul>
        {state.room.displays > 0 && (
          <p className="tagline">
            <Icon name="monitor" /> {state.room.displays} table display
            {state.room.displays > 1 ? "s" : ""} connected
          </p>
        )}
        {treachery && (
          <p className="dist">{n >= 4 ? distSummary(state.room.distribution) : "Best with 4+ players"}</p>
        )}
      </section>

      {state.me.isHost ? (
        <section className="tr-host">
          <h2>Game</h2>
          <div className="tr-mode">
            <button
              className={!treachery ? "active" : ""}
              onClick={() => void setOptions({ mode: "life" })}
            >
              <Icon name="heart" /> Life counter
            </button>
            <button
              className={treachery ? "active" : ""}
              onClick={() => void setOptions({ mode: "treachery" })}
            >
              <Icon name="sword" /> Treachery
            </button>
          </div>

          <h2>Starting life · {state.room.startingLife}</h2>
          <div className="life-presets">
            {[20, 30, 40].map((v) => (
              <button
                key={v}
                className={state.room.startingLife === v ? "active" : ""}
                onClick={() => void setOptions({ startingLife: v })}
              >
                {v}
              </button>
            ))}
            <input
              type="number"
              placeholder="…"
              min={1}
              max={999}
              value={customLife}
              onChange={(e) => setCustomLife(e.target.value)}
              onBlur={() => {
                const v = parseInt(customLife, 10);
                if (v >= 1 && v <= 999) void setOptions({ startingLife: v });
                setCustomLife("");
              }}
            />
          </div>

          {treachery && (
            <p className="hint">Everyone gets the same randomly-chosen card tier — power stays fair.</p>
          )}

          <button className="primary" onClick={() => void api(`/rooms/${code}/start`, { method: "POST", token })}>
            {treachery ? "Deal & start" : "Start game"}
          </button>
        </section>
      ) : (
        <p className="tagline tr-waiting">Waiting for the host to start…</p>
      )}

      {state.log.length > 0 && (
        <section className="game-log">
          <h2>Game log</h2>
          <ul>
            {state.log.slice(0, 8).map((e, i) => (
              <li key={`${e.at}-${i}`}>
                <time>
                  {new Date(e.at * 1000).toLocaleTimeString([], {
                    hour: "2-digit",
                    minute: "2-digit",
                  })}
                </time>
                {e.text}
              </li>
            ))}
          </ul>
        </section>
      )}

    </main>
  );
}

function RoleScreen({
  state,
  entries,
  index,
  setIndex,
  onUnveil,
}: {
  state: RoomState;
  entries: CarouselEntry[];
  index: number;
  setIndex: (i: number) => void;
  onUnveil: () => Promise<void>;
}) {
  const [peek, setPeek] = useState(false);
  const start = useRef<{ x: number; y: number } | null>(null);
  const swiping = useRef(false);
  const strip = useAutoHide(2500);

  const entry = entries[index] ?? entries[0];
  const me = state.me;
  // my own card stays hidden until I unveil it; other entries are public by definition
  const showFace = entry ? !entry.isMe || me.revealed || peek : false;
  const card = entry?.card;

  function onPointerDown(e: React.PointerEvent) {
    start.current = { x: e.clientX, y: e.clientY };
    swiping.current = false;
    strip.poke();
    if (entry?.isMe && !me.revealed) setPeek(true);
  }

  function onPointerMove(e: React.PointerEvent) {
    if (!start.current) return;
    const dx = e.clientX - start.current.x;
    const dy = e.clientY - start.current.y;
    if (!swiping.current && Math.abs(dx) > 12 && Math.abs(dx) > Math.abs(dy)) {
      swiping.current = true; // a swipe, not a peek
      setPeek(false);
    }
  }

  function onPointerUp(e: React.PointerEvent) {
    const s = start.current;
    start.current = null;
    setPeek(false);
    if (!s || !swiping.current || entries.length < 2) return;
    const dx = e.clientX - s.x;
    if (Math.abs(dx) > 50) {
      setIndex(step(index, dx < 0 ? 1 : -1, entries.length));
      strip.poke();
    }
  }

  return (
    <div
      className={`role-screen${entries.length > 1 ? " has-strip" : ""}`}
      onPointerDown={onPointerDown}
      onPointerMove={onPointerMove}
      onPointerUp={onPointerUp}
      onPointerCancel={() => {
        start.current = null;
        setPeek(false);
      }}
      onContextMenu={(e) => e.preventDefault()}
    >
      <div className="carousel-label">
        {entry?.isMe ? t("card.yours") : t("card.theirs", { name: entry?.name ?? "" })}
        {showFace && card?.artist && <span className="art-credit">{t("card.artBy", { artist: card.artist })}</span>}
      </div>

      {showFace && card ? (
        <img className="role-card" src={card.image} alt="" draggable={false} />
      ) : (
        <CardBack label={me.name} hint={t("card.holdToPeek")} />
      )}

      <div className="role-footer" onPointerDown={(e) => e.stopPropagation()}>
        {entries.length > 1 && (
          <div
            className={`carousel-strip${strip.visible ? "" : " hidden"}`}
            onPointerDown={() => strip.poke()}
          >
            {entries.map((e2, i) => {
              const faceUp = e2.card && (!e2.isMe || me.revealed);
              return (
                <button
                  key={e2.pid}
                  className={`thumb${i === index ? " on" : ""}`}
                  aria-label={e2.isMe ? "Your card" : `${e2.name}'s card`}
                  onClick={() => {
                    setIndex(i);
                    strip.poke();
                  }}
                >
                  {faceUp ? (
                    <img src={e2.card!.image} alt="" draggable={false} />
                  ) : (
                    <span className="thumb-back"><Icon name="card" label="face down" /></span>
                  )}
                  <span className="thumb-name">{e2.isMe ? "You" : e2.name}</span>
                </button>
              );
            })}
          </div>
        )}

        {entry && !entry.isMe ? (
          <div className="viewing-banner">
            {entry.name} — {card?.name} ({card?.role})
          </div>
        ) : me.revealed && card ? (
          <div className="unveiled-banner">
            {t("card.unveiledAs", { name: card.name, role: card.role })}
          </div>
        ) : (
          <SlideToUnveil onUnveil={onUnveil} />
        )}
      </div>
    </div>
  );
}

function CardBack({ label, hint }: { label: string; hint?: string }) {
  return (
    <div className="card-back">
      <img src="/cards/back-art.png" alt="" draggable={false} />
      <span className="back-label">{label}</span>
      {hint && <span className="back-hint">{hint}</span>}
    </div>
  );
}

function CardZoom({ p, onClose }: { p: PlayerInfo; onClose: () => void }) {
  if (!p.card) return null;
  return (
    <div className="card-zoom" onClick={onClose}>
      <div className="zoom-banner">
        This is <strong>{p.name}</strong>
        {p.isMe ? " (you)" : ""}&rsquo;s role card — {p.card.name} ({p.card.role})
        {p.card.artist && <span className="art-credit">{t("card.artBy", { artist: p.card.artist })}</span>}
      </div>
      <img src={p.card.image} alt={p.card.name} draggable={false} />
      {p.card.rulings.length > 0 && (
        <div className="card-rulings" onClick={(e) => e.stopPropagation()}>
          <h3>Rulings</h3>
          <ul>
            {p.card.rulings.map((r2, i) => (
              <li key={i}>{r2}</li>
            ))}
          </ul>
        </div>
      )}
      <span className="zoom-hint">{t("card.tapToClose")}</span>
    </div>
  );
}

function TableTile({ p, first, onZoom }: { p: PlayerInfo; first: boolean; onZoom: (p: PlayerInfo) => void }) {
  const life = p.eliminated ? "\u2020" : (p.life ?? "—");
  const label = (
    <span className="tile-label">
      {first && <Icon name="crown" size={14} />}
      {p.name}
      {p.isMe ? " (you)" : ""}
      {p.left ? " (left)" : ""} · <strong>{life}</strong>
      {p.card ? ` · ${p.card.role}` : ""}
    </span>
  );
  return (
    <div className={`table-tile${p.left ? " gone" : ""}${p.eliminated ? " dead" : ""}`}>
      {p.card ? (
        <>
          <img src={p.card.image} alt={p.card.name} draggable={false} onClick={() => onZoom(p)} />
          {label}
        </>
      ) : (
        <>
          <CardBack label={p.name} />
          {label}
        </>
      )}
    </div>
  );
}

function TableView({
  state,
  onZoom,
  onEnd,
  onReopen,
}: {
  state: RoomState;
  onZoom: (p: PlayerInfo) => void;
  onEnd?: () => void;
  onReopen?: () => void;
}) {
  const treachery = state.room.mode === "treachery";
  const ended = state.room.status === "ended";
  return (
    <section className="tr-table">
      <header>
        <h1>{ended ? "Game over" : "The table"}</h1>
        {treachery && <p className="dist">{distSummary(state.room.distribution)}</p>}
      </header>

      {treachery ? (
        <div className="table-grid">
          {state.players.map((p) => (
            <TableTile key={p.pid} p={p} first={state.room.firstPid === p.pid} onZoom={onZoom} />
          ))}
        </div>
      ) : (
        <ul className="life-roster">
          {state.players.map((p) => (
            <li key={p.pid} className={p.eliminated ? "dead" : ""}>
              <span>
                {state.room.firstPid === p.pid && <Icon name="crown" size={14} />}
                {p.name}
                {p.isMe ? " (you)" : ""}
              </span>
              <strong>
                      {p.eliminated ? (
                        <Icon name="skull" label={t("status.eliminated")} />
                      ) : (
                        (p.life ?? "—")
                      )}
                    </strong>
            </li>
          ))}
        </ul>
      )}

      <section className="game-log">
        <h2>Game log</h2>
        <ul>
          {state.log.map((e, i) => (
            <li key={`${e.at}-${i}`}>
              <time>
                {new Date(e.at * 1000).toLocaleTimeString([], {
                  hour: "2-digit",
                  minute: "2-digit",
                })}
              </time>
              {e.text}
            </li>
          ))}
        </ul>
      </section>

      <footer className="table-actions">
        {onEnd && (
          <button className="ghost" onClick={onEnd}>
            End game
          </button>
        )}
        {onReopen && (
          <button className="primary" onClick={onReopen}>
            Back to lobby
          </button>
        )}
      </footer>
    </section>
  );
}
