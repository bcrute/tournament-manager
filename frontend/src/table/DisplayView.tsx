import { useEffect, useRef, useState } from "react";
import { QRCodeSVG } from "qrcode.react";
import { api, PlayerInfo, RoomState } from "./api";
import Icon from "../Icon";
import SeatTile, { halfDelta } from "./SeatTile";
import { assignSeats, MAX_TABLE_VIEW, seatGrid, swapSeats, turnPositions } from "./seats";
import CmdDamageSheet from "./CmdDamageSheet";
import SeatMenu from "./SeatMenu";

export default function DisplayView({
  state,
  code,
  token,
  onTakeSeat,
  onLeave,
  upright = false,
}: {
  state: RoomState;
  code: string;
  token: string;
  onTakeSeat?: () => void;
  /** Only a dedicated display disconnects. A player showing the table view
   *  keeps their seat and leaves via "Back to my view". */
  onLeave?: () => void;
  /** Rotation faces each card at its player — the arrangement for a device
   *  lying flat in the table's middle. A device someone is holding (or a
   *  desktop) reads everything upright, seats kept in table positions. */
  upright?: boolean;
}) {
  const lobby = state.room.status === "lobby";
  const ended = state.room.status === "ended";
  const joinUrl = `${location.origin}/table?join=${code}`;
  const nameOf = new Map(state.players.map((p) => [String(p.pid), p.name]));
  const [cmdFor, setCmdFor] = useState<number | null>(null);
  const [menuFor, setMenuFor] = useState<number | null>(null);

  // drag to rearrange seats: local order while dragging, committed on release
  const [localOrder, setLocalOrder] = useState<number[] | null>(null);
  const [dragPid, setDragPid] = useState<number | null>(null);
  const [overPid, setOverPid] = useState<number | null>(null);
  const moved = useRef(false);
  const origin = useRef<{ x: number; y: number } | null>(null);
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
    setOverPid(null);
    origin.current = { x: e.clientX, y: e.clientY };
    moved.current = false;
  }

  function onDragMove(e: React.PointerEvent) {
    if (dragPid === null || !origin.current) return;
    const dx = e.clientX - origin.current.x;
    const dy = e.clientY - origin.current.y;
    if (!moved.current && Math.hypot(dx, dy) < 10) return; // still a tap
    moved.current = true;
    // highlight the seat under the finger; the swap happens on release so the
    // grid stays still while you aim
    const el = document
      .elementFromPoint(e.clientX, e.clientY)
      ?.closest("[data-pid]") as HTMLElement | null;
    const over = el ? Number(el.dataset.pid) : null;
    setOverPid(over && over !== dragPid ? over : null);
  }

  async function onDragEnd(e: React.PointerEvent, pid: number) {
    const dragged = dragPid;
    const target = overPid;
    const wasDrag = moved.current;
    setDragPid(null);
    setOverPid(null);
    origin.current = null;
    if (dragged === null) return;

    if (!wasDrag) {
      // a tap, not a drag: which half of the card was hit?
      const delta = halfDelta(document.elementFromPoint(e.clientX, e.clientY));
      if (delta !== null) {
        flashHalf(pid, delta);
        await adjust(pid, delta);
      }
      return;
    }
    if (target === null) return; // dropped on empty space: leave the seats be

    const next = swapSeats(localOrder ?? serverOrder, dragged, target);
    setLocalOrder(next);
    try {
      await api(`/rooms/${code}/order`, {
        method: "POST",
        token,
        body: { pids: next.filter((p) => byPid.has(p)) },
      });
    } catch {
      setLocalOrder(null);
    }
  }

  async function adjust(playerPid: number, delta: number) {
    await api(`/rooms/${code}/life`, { method: "POST", token, body: { playerPid, delta } });
  }

  const grid = seatGrid(ordered.length);
  const seated = assignSeats(ordered).map((s) =>
    upright ? { ...s, slot: { ...s.slot, rotate: 0 } } : s,
  );
  // turn order follows the seating: rearranging the tiles rearranges play order
  const turns = turnPositions(ordered, state.room.firstPid);
  // the grid and the sheet both read positionally, so they must agree on order
  const seatOrder = ordered.map((p, i) => ({
    pid: p.pid,
    seat: turns.get(p.pid) ?? i + 1,
    name: p.name,
  }));
  // the damage grid is a miniature of this exact arrangement, so a seat moved
  // by dragging moves in every card's grid too, with nothing to keep in sync
  const cmdLayout = {
    rows: grid.rows,
    cols: grid.cols,
    cells: seated.map(({ player, slot }) => ({
      pid: player.pid,
      row: slot.row,
      col: slot.col,
      colSpan: slot.colSpan,
    })),
  };

  async function changeCmd(defenderPid: number, attackerPid: number, delta: number) {
    try {
      await api(`/rooms/${code}/cmddmg`, {
        method: "POST",
        token,
        body: { attackerPid, delta, defenderPid },
      });
    } catch {
      /* the next state push corrects anything that didn't take */
    }
  }

  const cmdTarget = cmdFor === null ? null : ordered.find((p) => p.pid === cmdFor) ?? null;

  // Past the limit the cards are too short to read from across a table. Say so
  // plainly rather than rendering a grid nobody can use; every player still has
  // their own phone, which is the better answer at this size anyway.
  if (ordered.length > MAX_TABLE_VIEW) {
    return (
      <main className="display-root">
        <div className="display-toomany">
          <h1>{ordered.length} players is too many for one screen</h1>
          <p>
            The shared table view shows up to {MAX_TABLE_VIEW}. Above that the cards are
            too small to read from across a table, so everyone should track their own
            life on their own phone — which works exactly as it always does.
          </p>
          <ul className="display-compact">
            {ordered.map((pl) => (
              <li key={pl.pid}>
                <span>{pl.name}</span>
                <strong>{pl.eliminated ? <Icon name="skull" label="eliminated" /> : (pl.life ?? "—")}</strong>
              </li>
            ))}
          </ul>
          <p className="hint">Room {state.room.code}</p>
        </div>
      </main>
    );
  }

  return (
    <main className={`display-view${upright ? " upright" : ""}`}>
      <header className="display-head">
        <span className="display-code">{code}</span>
        <span className="display-mode">
          <>{state.room.mode === "treachery" ? <Icon name="sword" /> : <Icon name="heart" />}{" "}{state.room.mode === "treachery" ? "Treachery" : "Life"}</>
          {ended && " — game over"}
        </span>
        {onTakeSeat && (
          <button className="ghost" onClick={onTakeSeat}>
            Take a seat
          </button>
        )}
        {onLeave && (
          <button className="ghost" onClick={onLeave}>
            Disconnect
          </button>
        )}
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
                {p.isHost && <Icon name="crown" size={13} label="Host" />}
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
              cmdLayout={cmdLayout}
              onCmdOpen={state.room.status === "playing" ? setCmdFor : undefined}
              onHold={state.room.status === "playing" ? setMenuFor : undefined}
              dragging={dragPid === player.pid}
              dropTarget={overPid === player.pid}
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

      {menuFor !== null && (() => {
        const target = ordered.find((pl) => pl.pid === menuFor);
        return target ? (
          <SeatMenu
            player={target}
            onClose={() => setMenuFor(null)}
            onCantLose={(value) =>
              void api(`/rooms/${code}/cantlose`, {
                method: "POST",
                token,
                body: { value, playerPid: target.pid },
              }).catch(() => {})
            }
            onEliminate={(dead) =>
              void api(`/rooms/${code}/eliminate`, {
                method: "POST",
                token,
                body: { undo: !dead, playerPid: target.pid },
              }).catch(() => {})
            }
          />
        ) : null;
      })()}

      {cmdTarget && (
        <CmdDamageSheet
          defender={cmdTarget}
          sources={seatOrder}
          onChange={(attackerPid, delta) => void changeCmd(cmdTarget.pid, attackerPid, delta)}
          onClose={() => setCmdFor(null)}
        />
      )}
    </main>
  );
}
