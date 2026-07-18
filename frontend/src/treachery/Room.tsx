import { useEffect, useRef, useState } from "react";
import { QRCodeSVG } from "qrcode.react";
import { useNavigate, useParams } from "react-router-dom";
import { api, CardInfo, PlayerInfo, RoomState } from "./api";
import { clearSession, loadSession } from "./session";
import SlideToUnveil from "./SlideToUnveil";
import { useRoom } from "./useRoom";

const RARITY_LABELS: Record<string, string> = {
  U: "Uncommon",
  R: "Rare",
  M: "Mythic",
  S: "Special",
};

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
    if (!session || session.code !== code.toUpperCase()) navigate("/treachery", { replace: true });
  }, [session, code, navigate]);

  if (!session || session.code !== code.toUpperCase()) return null;
  return <RoomInner code={session.code} token={session.token} />;
}

interface Toast {
  id: number;
  name: string;
}

function RoomInner({ code, token }: { code: string; token: string }) {
  const navigate = useNavigate();
  const { state, gone, error } = useRoom(code, token);
  const [view, setView] = useState<"card" | "table">("card");
  const [zoomName, setZoomName] = useState<string | null>(null);
  const [toasts, setToasts] = useState<Toast[]>([]);
  const prevRevealed = useRef<{ status: string; names: Set<string> } | null>(null);
  const toastId = useRef(0);

  useEffect(() => {
    if (gone) navigate("/treachery", { replace: true });
  }, [gone, navigate]);

  // toast newly-revealed players (mid-game only — not the deal itself or game end)
  useEffect(() => {
    if (!state) return;
    const names = new Set(
      state.players.filter((p) => p.revealed && !p.isMe).map((p) => p.name),
    );
    const prev = prevRevealed.current;
    if (prev && prev.status === "dealt" && state.room.status === "dealt") {
      for (const name of names) {
        if (!prev.names.has(name)) {
          const id = ++toastId.current;
          setToasts((t) => [...t, { id, name }]);
          window.setTimeout(() => setToasts((t) => t.filter((x) => x.id !== id)), 7000);
        }
      }
    }
    prevRevealed.current = { status: state.room.status, names };
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
    navigate("/treachery", { replace: true });
  }

  if (state.room.status === "lobby") {
    return <Lobby state={state} code={code} token={token} onLeave={() => void leave("Leave this room?")} />;
  }

  const showTable = view === "table" || state.room.status === "ended";
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
              setZoomName(t.name);
            }}
          >
            ⚔ {t.name} has revealed their identity — tap to view
          </button>
        ))}
      </div>
      {zoomPlayer && <CardZoom p={zoomPlayer} onClose={() => setZoomName(null)} />}
      {showTable ? (
        <TableView
          state={state}
          onZoom={(p) => setZoomName(p.name)}
          onBack={state.room.status === "ended" ? undefined : () => setView("card")}
          onEnd={
            state.me.isHost && state.room.status === "dealt"
              ? () => {
                  if (window.confirm("End the game and reveal everyone?")) void act("/end");
                }
              : undefined
          }
          onReopen={
            state.me.isHost && state.room.status === "ended" ? () => void act("/reopen") : undefined
          }
          onLeave={() =>
            void leave(
              state.room.status === "dealt"
                ? "Leave mid-game? Your identity will be revealed to the table."
                : "Leave and forget this game?",
            )
          }
        />
      ) : (
        <RoleScreen state={state} onUnveil={() => act("/unveil").then(() => undefined)} onTable={() => setView("table")} />
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
  const joinUrl = `${location.origin}/treachery?join=${code}`;
  const rarities = state.room.options.rarities ?? ["U", "R", "M", "S"];
  const n = state.players.filter((p) => !p.left).length;

  async function toggleRarity(r: string) {
    const next = rarities.includes(r) ? rarities.filter((x) => x !== r) : [...rarities, r];
    if (next.length === 0) return;
    await api(`/rooms/${code}/options`, { method: "POST", token, body: { rarities: next } });
  }

  return (
    <main className="tr-lobby">
      <header>
        <p className="tagline">Room code</p>
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
        <p className="dist">{n >= 4 ? distSummary(state.room.distribution) : "Best with 4+ players"}</p>
      </section>

      {state.me.isHost ? (
        <section className="tr-host">
          <h2>Card pool</h2>
          <div className="rarities">
            {Object.entries(RARITY_LABELS).map(([r, label]) => (
              <label key={r}>
                <input
                  type="checkbox"
                  checked={rarities.includes(r)}
                  onChange={() => void toggleRarity(r)}
                />
                {label}
              </label>
            ))}
          </div>
          <button className="primary" onClick={() => void api(`/rooms/${code}/deal`, { method: "POST", token })}>
            Deal identities
          </button>
        </section>
      ) : (
        <p className="tagline">Waiting for the host to deal…</p>
      )}

      <footer>
        <button className="ghost" onClick={onLeave}>
          Leave room
        </button>
      </footer>
    </main>
  );
}

function RoleScreen({
  state,
  onUnveil,
  onTable,
}: {
  state: RoomState;
  onUnveil: () => Promise<void>;
  onTable: () => void;
}) {
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

      <button className="table-btn" onPointerDown={(e) => e.stopPropagation()} onClick={onTable}>
        Table ↗
      </button>

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

function TableTile({ p, onZoom }: { p: PlayerInfo; onZoom: (p: PlayerInfo) => void }) {
  const card: CardInfo | null = p.card;
  return (
    <div className={`table-tile${p.left ? " gone" : ""}`}>
      {card ? (
        <>
          <img src={card.image} alt={card.name} draggable={false} onClick={() => onZoom(p)} />
          <span className="tile-label">
            {p.name}
            {p.left ? " (left)" : ""} — {card.role}
          </span>
        </>
      ) : (
        <>
          <CardBack label={p.name} />
          <span className="tile-label">
            {p.name}
            {p.isMe ? " (you)" : ""}
          </span>
        </>
      )}
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

function TableView({
  state,
  onZoom,
  onBack,
  onEnd,
  onReopen,
  onLeave,
}: {
  state: RoomState;
  onZoom: (p: PlayerInfo) => void;
  onBack?: () => void;
  onEnd?: () => void;
  onReopen?: () => void;
  onLeave: () => void;
}) {
  const ended = state.room.status === "ended";
  return (
    <main className="tr-table">
      <header>
        <h1>{ended ? "Game over — all revealed" : "The table"}</h1>
        <p className="dist">{distSummary(state.room.distribution)}</p>
      </header>
      <div className="table-grid">
        {state.players.map((p) => (
          <TableTile key={p.name} p={p} onZoom={onZoom} />
        ))}
      </div>
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
        {onBack && (
          <button className="primary" onClick={onBack}>
            Your card
          </button>
        )}
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
