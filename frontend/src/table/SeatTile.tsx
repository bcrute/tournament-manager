import { useEffect, useRef, useState } from "react";
import { PlayerInfo } from "./api";
import { t } from "../i18n";
import Icon from "../Icon";
import { SeatSlot, seatFonts } from "./seats";

/**
 * One player's seat on the table display, rotated to face them.
 * Tapping the left half of the card takes a life, the right half gives one;
 * dragging moves the seat. Commander damage from every player (including the
 * player themselves — their own commander can be turned against them) is
 * listed along the bottom edge of the card.
 */
export default function SeatTile({
  p,
  slot,
  first,
  turn,
  nameOf,
  cmdLayout,
  onCmdOpen,
  onHold,
  dragging,
  dropTarget,
  flash,
  onDragStart,
  onDragMove,
  onDragEnd,
}: {
  p: PlayerInfo;
  slot: SeatSlot;
  first: boolean;
  turn?: number;
  nameOf: Map<string, string>;
  /**
   * The table's own arrangement, reused for the damage grid: same rows, same
   * columns, same positions. A total is then read by *where* someone sits
   * rather than by matching a name or a number — and because it comes from the
   * same seat assignment the table uses, dragging a player moves their square
   * here too, with nothing to keep in sync.
   */
  cmdLayout: { rows: number; cols: number; cells: { pid: number; row: number; col: number; colSpan: number }[] };
  /** Opens the editor for this seat. Omitted on devices that may not edit. */
  onCmdOpen?: (pid: number) => void;
  /** Press and hold: reaches a player whose phone is across the table or dead. */
  onHold?: (pid: number) => void;
  dragging: boolean;
  dropTarget?: boolean;
  flash?: number;
  onDragStart: (e: React.PointerEvent) => void;
  onDragMove: (e: React.PointerEvent) => void;
  onDragEnd: (e: React.PointerEvent) => void;
}) {
  const cell = useRef<HTMLDivElement>(null);
  const [size, setSize] = useState({ w: 0, h: 0 });

  // a rotated card swaps width and height, so measure the cell it sits in
  useEffect(() => {
    const el = cell.current;
    if (!el) return;
    const ro = new ResizeObserver(([entry]) => {
      const { width, height } = entry.contentRect;
      setSize({ w: width, h: height });
    });
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  const holdTimer = useRef<number | null>(null);
  const held = useRef(false);
  const cancelHold = () => {
    if (holdTimer.current !== null) {
      window.clearTimeout(holdTimer.current);
      holdTimer.current = null;
    }
  };

  const turned = slot.rotate !== 0;
  const inner = turned ? { width: size.h, height: size.w } : { width: size.w, height: size.h };
  const font = seatFonts(inner.width, inner.height);
  // Sized so the squares stay square: the block takes about a third of the
  // card's shorter side, whatever the table's shape.
  // Fit first, then size: the block is placed inside a card that is rotated
  // and clips its overflow, so deriving from one axis let it spill and get cut
  // off. Cap the whole block to a fraction of the card's *shorter* side and
  // divide by the larger of rows/cols, so it always lands inside.
  const block = Math.min(inner.width, inner.height) * 0.4;
  const miniCell = Math.max(12, block / Math.max(cmdLayout.rows, cmdLayout.cols));
  const mini = {
    w: miniCell * cmdLayout.cols,
    h: miniCell * cmdLayout.rows,
    font: Math.max(11, miniCell * 0.55),
  };

  // A miniature of the table, not a list. No names, no seat numbers — the
  // position is the label.
  const cells = cmdLayout.cells.map((c) => ({
    ...c,
    amount: p.cmdDamage[String(c.pid)] ?? 0,
    own: c.pid === p.pid,
  }));

  return (
    <div
      ref={cell}
      className="seat"
      data-pid={p.pid}
      style={{
        gridRow: slot.row,
        gridColumn: `${slot.col} / span ${slot.colSpan}`,
      }}
      onPointerDown={(e) => {
        // a hold opens the seat's own menu; a drag still rearranges, because the
        // timer is cancelled as soon as the pointer moves or lifts
        if (onHold) {
          holdTimer.current = window.setTimeout(() => {
            held.current = true;
            onHold(p.pid);
          }, 550);
        }
        onDragStart(e);
      }}
      onPointerMove={(e) => {
        cancelHold();
        onDragMove(e);
      }}
      onPointerUp={(e) => {
        cancelHold();
        onDragEnd(e);
      }}
      onPointerCancel={(e) => {
        cancelHold();
        onDragEnd(e);
      }}
    >
      <div
        className={`seat-card${p.eliminated ? " dead" : ""}${p.left ? " gone" : ""}${dragging ? " dragging" : ""}${dropTarget ? " drop-target" : ""}`}
        style={{ ...inner, transform: `rotate(${slot.rotate}deg)` }}
      >
        <button
          className={`seat-half dec${flash === -1 ? " flash" : ""}`}
          data-delta="-1"
          aria-label={t("life.minus", { name: p.name, n: 1 })}
        />
        <button
          className={`seat-half inc${flash === 1 ? " flash" : ""}`}
          data-delta="1"
          aria-label={t("life.plus", { name: p.name, n: 1 })}
        />

        {turn !== undefined && (
          <span className={`seat-turn${first ? " first" : ""}`} title="turn order">
            {turn}
          </span>
        )}

        <div className="seat-face" style={{ bottom: font.cmdBar }}>
          <span className="seat-name" style={{ fontSize: font.name }}>
            {first && <Icon name="crown" size={13} />}
            {p.name}
            {p.card ? ` · ${p.card.role}` : ""}
          </span>
          <span className="seat-life" style={{ fontSize: font.life }}>
            {p.eliminated ? <Icon name="skull" label={t("status.eliminated")} /> : (p.life ?? "—")}
          </span>
        </div>

        <button
          className="seat-cmd-grid"
          onPointerDown={(e) => e.stopPropagation()}
          onClick={(e) => {
            e.stopPropagation();
            onCmdOpen?.(p.pid);
          }}
          aria-label={t("cmd.editFor", { name: p.name })}
          disabled={!onCmdOpen}
          style={{
            width: mini.w,
            height: mini.h,
            fontSize: mini.font,
            gridTemplateRows: `repeat(${cmdLayout.rows}, 1fr)`,
            gridTemplateColumns: `repeat(${cmdLayout.cols}, 1fr)`,
          }}
        >
          {cells.map((c) => (
            <span
              key={c.pid}
              className={`cmd-cell${c.amount >= 21 ? " lethal" : ""}${c.amount === 0 ? " zero" : ""}${c.own ? " own" : ""}`}
              style={{ gridRow: c.row, gridColumn: `${c.col} / span ${c.colSpan}` }}
            >
              {c.amount || ""}
            </span>
          ))}
        </button>
      </div>
    </div>
  );
}

/** Which half of a seat card a pointer event landed on, if any. */
export function halfDelta(target: EventTarget | null): number | null {
  const el = (target as HTMLElement | null)?.closest?.("[data-delta]") as HTMLElement | null;
  if (!el) return null;
  const n = Number(el.dataset.delta);
  return Number.isFinite(n) ? n : null;
}
