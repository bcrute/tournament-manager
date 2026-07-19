import { useEffect, useRef, useState } from "react";
import { QRCodeSVG } from "qrcode.react";
import { api, PlayerInfo, RoomState } from "./api";
import SeatTile, { halfDelta } from "./SeatTile";
import { assignSeats, seatGrid, turnPositions } from "./seats";

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
  const lobby = state.room.status === "lobby";
  const ended = state.room.status === "ended";
  const joinUrl = `${location.origin}/table?join=${code}`;
  const nameOf = new Map(state.players.map((p) => [String(p.pid), p.name]));

  // drag to rearrange seats: local order while dragging, committed on release
  const [localOrder, setLocalOrder] = useState<number[] | null>(null);
  const [dragPid, setDragPid] = useState<number | null>(null);
  const moved = useRef(false);
  // brief tap feedback; :active can't be used because the seat captures the pointer
  const [flash, setFlash] = useState<{ pid: number; delta: number } | null>(null);
  const flashTimer = useRef<number | undefined>(undefined);

  useEffect(() => () => window.clearTimeout(flashTimer.current), []);

  function flashHalf(pid: number, delta: number) {
    setFlash({ pid, delta });
    window.clearTimeout(flashTimer.current);
    flashTimer.current = window.setTimeout(() => setFlash(null), 180);
  }

  const serverOrder = state.players.map((p) => p.pid);
  const order = localOrder ?? serverOrder;
  const byPid = new Map(state.players.map((p) => [p.pid, p]));
  const ordered = order.map((pid) => byPid.get(pid)).filter(Boolean) as PlayerInfo[];
  for (const p of state.players) if (!order.includes(p.pid)) ordered.push(p);

  useEffect(() => {
    if (dragPid === null) setLocalOrder(null);
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

  async function onDragEnd(e: React.PointerEvent, pid: number) {
    const wasDragging = dragPid !== null;
    setDragPid(null);
    if (!wasDragging) return;
    if (!moved.current) {
      // a tap, not a drag: which half of the card was hit?
      const delta = halfDelta(document.elementFromPoint(e.clientX, e.clientY));
      if (delta !== null) {
        flashHalf(pid, delta);
        await adjust(pid, delta);
      }
      return;
    }
    const pids = (localOrder ?? serverOrder).filter((p) => byPid.has(p));
    try {
      await api(`/rooms/${code}/order`, { method: "POST", token, body: { pids } });
    } catch {
      setLocalOrder(null);
    }
  }

  async function adjust(playerPid: number, delta: number) {
    await api(`/rooms/${code}/life`, { method: "POST", token, body: { playerPid, delta } });
  }

  const grid = seatGrid(ordered.length);
  const seated = assignSeats(ordered);
  // turn order follows the seating: rearranging the tiles rearranges play order
  const turns = turnPositions(ordered, state.room.firstPid);

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
        <div
          className="seat-grid"
          style={{
            gridTemplateRows: `repeat(${grid.rows}, 1fr)`,
            gridTemplateColumns: `repeat(${grid.cols}, 1fr)`,
          }}
        >
          {seated.map(({ player, slot }) => (
            <SeatTile
              key={player.pid}
              p={player}
              slot={slot}
              first={state.room.firstPid === player.pid}
              turn={state.room.firstPid !== null ? turns.get(player.pid) : undefined}
              nameOf={nameOf}
              dragging={dragPid === player.pid}
              flash={flash?.pid === player.pid ? flash.delta : undefined}
              onDragStart={(e) => onDragStart(e, player.pid)}
              onDragMove={onDragMove}
              onDragEnd={(e) => void onDragEnd(e, player.pid)}
            />
          ))}
        </div>
      )}

      <div className="display-log">
        {state.log.slice(0, 2).map((e, i) => (
          <div key={`${e.at}-${i}`} className="display-log-line">
            {e.text}
          </div>
        ))}
      </div>
    </main>
  );
}
