import { useEffect, useRef, useState } from "react";
import { QRCodeSVG } from "qrcode.react";
import { api, PlayerInfo, RoomState } from "./api";

export default function DisplayView({
  state,
  code,
  token,
  onTakeSeat,
  onLeave,
}: {
  state: RoomState;
  code: string;
  token: string;
  onTakeSeat?: () => void;
  onLeave: () => void;
}) {
  const [editing, setEditing] = useState<{ pid: number; name: string } | null>(null);
  const lobby = state.room.status === "lobby";
  const ended = state.room.status === "ended";
  const joinUrl = `${location.origin}/table?join=${code}`;
  const nameOf = new Map(state.players.map((p) => [String(p.pid), p.name]));

  // drag to rearrange seats: keep a local order while dragging, commit on release
  const [localOrder, setLocalOrder] = useState<number[] | null>(null);
  const [dragPid, setDragPid] = useState<number | null>(null);
  const moved = useRef(false);

  const serverOrder = state.players.map((p) => p.pid);
  const order = localOrder ?? serverOrder;
  const byPid = new Map(state.players.map((p) => [p.pid, p]));
  const ordered = order.map((pid) => byPid.get(pid)).filter(Boolean) as PlayerInfo[];
  // players who joined mid-drag still show up
  for (const p of state.players) if (!order.includes(p.pid)) ordered.push(p);

  useEffect(() => {
    if (dragPid === null) setLocalOrder(null); // resync with the server between drags
  }, [dragPid, state.players.length]);

  function onDragStart(e: React.PointerEvent, pid: number) {
    (e.currentTarget as HTMLElement).setPointerCapture(e.pointerId);
    setDragPid(pid);
    moved.current = false;
  }

  function onDragMove(e: React.PointerEvent) {
    if (dragPid === null) return;
    const el = document
      .elementFromPoint(e.clientX, e.clientY)
      ?.closest("[data-pid]") as HTMLElement | null;
    const overPid = el ? Number(el.dataset.pid) : null;
    if (!overPid || overPid === dragPid) return;
    moved.current = true;
    setLocalOrder((cur) => {
      const list = [...(cur ?? serverOrder)];
      const from = list.indexOf(dragPid);
      const to = list.indexOf(overPid);
      if (from < 0 || to < 0) return cur;
      list.splice(to, 0, ...list.splice(from, 1));
      return list;
    });
  }

  async function onDragEnd() {
    const pid = dragPid;
    setDragPid(null);
    if (pid === null || !moved.current) return;
    const pids = (localOrder ?? serverOrder).filter((p) => byPid.has(p));
    try {
      await api(`/rooms/${code}/order`, { method: "POST", token, body: { pids } });
    } catch {
      setLocalOrder(null); // fall back to the server's order
    }
  }

  async function adjust(playerPid: number, delta: number) {
    await api(`/rooms/${code}/life`, { method: "POST", token, body: { playerPid, delta } });
  }

  return (
    <main className="display-view">
      <header className="display-head">
        <span className="display-code">{code}</span>
        <span className="display-mode">
          {state.room.mode === "treachery" ? "⚔ Treachery" : "♥ Life"}
          {ended && " — game over"}
        </span>
        {onTakeSeat && (
          <button className="ghost" onClick={onTakeSeat}>
            Take a seat
          </button>
        )}
        <button className="ghost" onClick={onLeave}>
          Disconnect
        </button>
      </header>

      {lobby ? (
        <div className="display-lobby">
          <div className="qr big">
            <QRCodeSVG value={joinUrl} size={220} bgColor="#14101c" fgColor="#e8e4f0" marginSize={2} />
          </div>
          <p className="tagline">Scan to join · room {code}</p>
          <ul className="display-roster">
            {state.players.map((p) => (
              <li key={p.pid}>
                {p.name}
                {p.isHost ? " ♛" : ""}
              </li>
            ))}
          </ul>
        </div>
      ) : (
        <div className="display-grid">
          {ordered.map((p) => (
            <DisplayTile
              key={p.pid}
              p={p}
              first={state.room.firstPid === p.pid}
              nameOf={nameOf}
              dragging={dragPid === p.pid}
              onTap={() => {
                if (!moved.current) setEditing({ pid: p.pid, name: p.name });
              }}
              onDragStart={(e) => onDragStart(e, p.pid)}
              onDragMove={onDragMove}
              onDragEnd={() => void onDragEnd()}
            />
          ))}
        </div>
      )}

      <div className="display-log">
        {state.log.slice(0, 4).map((e, i) => (
          <div key={`${e.at}-${i}`} className="display-log-line">
            {e.text}
          </div>
        ))}
      </div>

      {editing && (
        <div className="edit-overlay" onClick={() => setEditing(null)}>
          <div className="edit-box" onClick={(e) => e.stopPropagation()}>
            <h2>{editing.name}</h2>
            <div className="life-buttons">
              <button onClick={() => void adjust(editing.pid, -5)}>−5</button>
              <button onClick={() => void adjust(editing.pid, -1)}>−1</button>
              <button onClick={() => void adjust(editing.pid, 1)}>+1</button>
              <button onClick={() => void adjust(editing.pid, 5)}>+5</button>
            </div>
            <button className="ghost" onClick={() => setEditing(null)}>
              done
            </button>
          </div>
        </div>
      )}
    </main>
  );
}

function DisplayTile({
  p,
  first,
  nameOf,
  dragging,
  onTap,
  onDragStart,
  onDragMove,
  onDragEnd,
}: {
  p: PlayerInfo;
  first: boolean;
  nameOf: Map<string, string>;
  dragging: boolean;
  onTap: () => void;
  onDragStart: (e: React.PointerEvent) => void;
  onDragMove: (e: React.PointerEvent) => void;
  onDragEnd: () => void;
}) {
  return (
    <button
      data-pid={p.pid}
      className={`display-tile${p.eliminated ? " dead" : ""}${p.left ? " gone" : ""}${dragging ? " dragging" : ""}`}
      onClick={onTap}
      onPointerDown={onDragStart}
      onPointerMove={onDragMove}
      onPointerUp={onDragEnd}
      onPointerCancel={onDragEnd}
    >
      <span className="display-name">
        {first && "👑 "}
        {p.name}
        {p.card ? ` · ${p.card.role}` : ""}
      </span>
      <span className="display-life">{p.eliminated ? "☠" : (p.life ?? "—")}</span>
      {Object.keys(p.cmdDamage).length > 0 && (
        <span className="display-cmd">
          {Object.entries(p.cmdDamage)
            .map(([fromPid, amt]) => `${amt}⚔${nameOf.get(fromPid) ?? "?"}`)
            .join("  ")}
        </span>
      )}
    </button>
  );
}
