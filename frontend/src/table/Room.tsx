import { useEffect, useRef, useState } from "react";
import { QRCodeSVG } from "qrcode.react";
import { useNavigate, useParams } from "react-router-dom";
import { api, PlayerInfo, RoomState } from "./api";
import { clearSession, loadSession } from "./session";
import DisplayView from "./DisplayView";
import LifePanel from "./LifePanel";
import SlideToUnveil from "./SlideToUnveil";
import { useRoom } from "./useRoom";

const ROLE_ORDER = ["Leader", "Guardian", "Assassin", "Traitor"];

function distSummary(dist: Record<string, number>) {
  return ROLE_ORDER.filter((r) => dist[r] > 0)
    .map((r) => `${dist[r]} ${r}${dist[r] > 1 ? "s" : ""}`)
    .join(" · ");
}

export default function Room() {
  const { code = "" } = useParams();
  const navigate = useNavigate();
  const session = loadSession();

  useEffect(() => {
    if (!session || session.code !== code.toUpperCase()) navigate("/table", { replace: true });
  }, [session, code, navigate]);

  if (!session || session.code !== code.toUpperCase()) return null;
  return <RoomInner code={session.code} token={session.token} />;
}

interface Toast {
  id: number;
  text: string;
  zoomName?: string;
}

type Tab = "card" | "life" | "table";

function RoomInner({ code, token }: { code: string; token: string }) {
  const navigate = useNavigate();
  const { state, gone, error } = useRoom(code, token);
  const [tab, setTab] = useState<Tab | null>(null);
  const [zoomName, setZoomName] = useState<string | null>(null);
  const [toasts, setToasts] = useState<Toast[]>([]);
  const prev = useRef<{ status: string; names: Set<string>; first: string | null } | null>(null);
  const toastId = useRef(0);

  useEffect(() => {
    if (gone) navigate("/table", { replace: true });
  }, [gone, navigate]);

  const pushToast = (text: string, zoomName?: string) => {
    const id = ++toastId.current;
    setToasts((t) => [...t, { id, text, zoomName }]);
    window.setTimeout(() => setToasts((t) => t.filter((x) => x.id !== id)), 7000);
  };

  // toasts for mid-game reveals and the first-turn announcement
  useEffect(() => {
    if (!state) return;
    const names = new Set(
      state.players.filter((p) => p.revealed && !p.isMe).map((p) => p.name),
    );
    const p = prev.current;
    if (p && p.status === "playing" && state.room.status === "playing") {
      for (const name of names) {
        if (!p.names.has(name)) pushToast(`⚔ ${name} has revealed their identity — tap to view`, name);
      }
    }
    if (p && state.room.firstPlayer && p.first !== state.room.firstPlayer && state.room.status === "playing") {
      const who = state.room.firstPlayer;
      const isLeader = state.room.mode === "treachery";
      pushToast(
        who === state.me.name
          ? `🎲 You go first!`
          : `🎲 ${who}${isLeader ? " (Leader)" : ""} goes first`,
      );
    }
    prev.current = { status: state.room.status, names, first: state.room.firstPlayer };
  }, [state]);

  if (error) return <main className="tr-landing"><p className="error">{error}</p></main>;
  if (!state) return <main className="tr-landing"><p className="tagline">Loading…</p></main>;

  const act = (path: string) => api(`/rooms/${code}${path}`, { method: "POST", token });

  async function leave(confirmMsg: string) {
    if (!window.confirm(confirmMsg)) return;
    try {
      await act("/leave");
    } catch {
      // leaving a dead room is fine
    }
    clearSession();
    navigate("/table", { replace: true });
  }

  if (state.me.isDisplay) {
    return (
      <DisplayView
        state={state}
        code={code}
        token={token}
        onLeave={() => void leave("Disconnect this display?")}
      />
    );
  }

  if (state.room.status === "lobby") {
    return <Lobby state={state} code={code} token={token} onLeave={() => void leave("Leave this room?")} />;
  }

  const treachery = state.room.mode === "treachery";
  const ended = state.room.status === "ended";
  const activeTab: Tab = ended ? "table" : (tab ?? (treachery ? "card" : "life"));
  const zoomPlayer = zoomName ? state.players.find((p) => p.name === zoomName && p.card) : undefined;

  return (
    <div className="tr-room">
      <div className="toasts" onPointerDown={(e) => e.stopPropagation()}>
        {toasts.map((t) => (
          <button
            key={t.id}
            className="toast"
            onClick={() => {
              setToasts((all) => all.filter((x) => x.id !== t.id));
              if (t.zoomName) setZoomName(t.zoomName);
            }}
          >
            {t.text}
          </button>
        ))}
      </div>
      {zoomPlayer && <CardZoom p={zoomPlayer} onClose={() => setZoomName(null)} />}

      {activeTab === "card" && treachery && (
        <RoleScreen state={state} onUnveil={() => act("/unveil").then(() => undefined)} />
      )}
      {activeTab === "life" && (
        <main className="tr-life-page">
          <header>
            <p className="tagline">
              {state.room.firstPlayer && `👑 ${state.room.firstPlayer} went first · `}room {code}
            </p>
          </header>
          <LifePanel state={state} code={code} token={token} />
        </main>
      )}
      {activeTab === "table" && (
        <TableView
          state={state}
          onZoom={(p) => setZoomName(p.name)}
          onEnd={
            state.me.isHost && !ended
              ? () => {
                  if (window.confirm("End the game" + (treachery ? " and reveal everyone?" : "?")))
                    void act("/end");
                }
              : undefined
          }
          onReopen={state.me.isHost && ended ? () => void act("/reopen") : undefined}
          onLeave={() =>
            void leave(
              !ended && treachery
                ? "Leave mid-game? Your identity will be revealed to the table."
                : "Leave and forget this game?",
            )
          }
        />
      )}

      {!ended && (
        <nav className="bottom-nav" onPointerDown={(e) => e.stopPropagation()}>
          {treachery && (
            <button className={activeTab === "card" ? "active" : ""} onClick={() => setTab("card")}>
              🎭 Card
            </button>
          )}
          <button className={activeTab === "life" ? "active" : ""} onClick={() => setTab("life")}>
            ♥ Life
          </button>
          <button className={activeTab === "table" ? "active" : ""} onClick={() => setTab("table")}>
            👥 Table
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
  onLeave,
}: {
  state: RoomState;
  code: string;
  token: string;
  onLeave: () => void;
}) {
  const joinUrl = `${location.origin}/table?join=${code}`;
  const treachery = state.room.mode === "treachery";
  const n = state.players.filter((p) => !p.left).length;
  const [customLife, setCustomLife] = useState("");

  async function setOptions(body: { startingLife?: number }) {
    await api(`/rooms/${code}/options`, { method: "POST", token, body });
  }

  return (
    <main className="tr-lobby">
      <header>
        <p className="tagline">{treachery ? "⚔ Treachery" : "♥ Life counter"} · room code</p>
        <h1 className="room-code">{code}</h1>
      </header>
      <div className="qr">
        <QRCodeSVG value={joinUrl} size={144} bgColor="#14101c" fgColor="#e8e4f0" marginSize={2} />
      </div>

      <section className="tr-players">
        <h2>Players ({n})</h2>
        <ul>
          {state.players.map((p) => (
            <li key={p.name}>
              {p.name}
              {p.isHost ? " ♛" : ""}
              {p.isMe ? " (you)" : ""}
            </li>
          ))}
        </ul>
        {state.room.displays > 0 && (
          <p className="tagline">
            📺 {state.room.displays} table display{state.room.displays > 1 ? "s" : ""} connected
          </p>
        )}
        {treachery && (
          <p className="dist">{n >= 4 ? distSummary(state.room.distribution) : "Best with 4+ players"}</p>
        )}
      </section>

      {state.me.isHost ? (
        <section className="tr-host">
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
        <p className="tagline">Waiting for the host to start…</p>
      )}

      <footer>
        <button className="ghost" onClick={onLeave}>
          Leave room
        </button>
      </footer>
    </main>
  );
}

function RoleScreen({ state, onUnveil }: { state: RoomState; onUnveil: () => Promise<void> }) {
  const [peek, setPeek] = useState(false);
  const me = state.me;
  const card = me.card;
  const show = me.revealed || peek;

  return (
    <div
      className="role-screen"
      onPointerDown={() => setPeek(true)}
      onPointerUp={() => setPeek(false)}
      onPointerCancel={() => setPeek(false)}
      onPointerLeave={() => setPeek(false)}
      onContextMenu={(e) => e.preventDefault()}
    >
      {show && card ? (
        <img className="role-card" src={card.image} alt="" draggable={false} />
      ) : (
        <CardBack label={me.name} hint="hold to peek" />
      )}

      <div className="role-footer" onPointerDown={(e) => e.stopPropagation()}>
        {me.revealed && card ? (
          <div className="unveiled-banner">
            Unveiled — {card.name} ({card.role})
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
      </div>
      <img src={p.card.image} alt={p.card.name} draggable={false} />
      <span className="zoom-hint">tap to close</span>
    </div>
  );
}

function TableTile({ p, first, onZoom }: { p: PlayerInfo; first: boolean; onZoom: (p: PlayerInfo) => void }) {
  const life = p.eliminated ? "☠" : (p.life ?? "—");
  const label = (
    <span className="tile-label">
      {first && "👑 "}
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
  onLeave,
}: {
  state: RoomState;
  onZoom: (p: PlayerInfo) => void;
  onEnd?: () => void;
  onReopen?: () => void;
  onLeave: () => void;
}) {
  const treachery = state.room.mode === "treachery";
  const ended = state.room.status === "ended";
  return (
    <main className="tr-table">
      <header>
        <h1>{ended ? "Game over" : "The table"}</h1>
        {treachery && <p className="dist">{distSummary(state.room.distribution)}</p>}
      </header>

      {treachery ? (
        <div className="table-grid">
          {state.players.map((p) => (
            <TableTile key={p.name} p={p} first={state.room.firstPlayer === p.name} onZoom={onZoom} />
          ))}
        </div>
      ) : (
        <ul className="life-roster">
          {state.players.map((p) => (
            <li key={p.name} className={p.eliminated ? "dead" : ""}>
              <span>
                {state.room.firstPlayer === p.name && "👑 "}
                {p.name}
                {p.isMe ? " (you)" : ""}
              </span>
              <strong>{p.eliminated ? "☠" : (p.life ?? "—")}</strong>
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
        <button className="ghost" onClick={onLeave}>
          Leave
        </button>
      </footer>
    </main>
  );
}
