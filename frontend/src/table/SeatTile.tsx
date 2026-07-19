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
  seatOrder,
  onCmdOpen,
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
  /** Every seat in turn order, so the damage grid reads positionally. */
  seatOrder: { pid: number; seat: number }[];
  /** Opens the editor for this seat. Omitted on devices that may not edit. */
  onCmdOpen?: (pid: number) => void;
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

  const turned = slot.rotate !== 0;
  const inner = turned ? { width: size.h, height: size.w } : { width: size.w, height: size.h };
  const font = seatFonts(inner.width, inner.height);
  // A diagram, not a list: one cell per opponent in seat order, so a total is
  // found by position rather than by reading names in a rotated card.
  const cells = seatOrder.map((src) => ({
    pid: src.pid,
    seat: src.seat,
    amount: p.cmdDamage[String(src.pid)] ?? 0,
    own: src.pid === p.pid,
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
      onPointerDown={onDragStart}
      onPointerMove={onDragMove}
      onPointerUp={onDragEnd}
      onPointerCancel={onDragEnd}
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
            {p.eliminated ? "☠" : (p.life ?? "—")}
          </span>
        </div>

        <button
          className="seat-cmd-grid"
          style={{ fontSize: font.cmd, maxHeight: font.cmdBar }}
          onPointerDown={(e) => e.stopPropagation()}
          onClick={(e) => {
            e.stopPropagation();
            onCmdOpen?.(p.pid);
          }}
          aria-label={t("cmd.editFor", { name: p.name })}
          disabled={!onCmdOpen}
        >
          {cells.map((c) => (
            <span
              key={c.pid}
              className={`cmd-cell${c.amount >= 21 ? " lethal" : ""}${c.amount === 0 ? " zero" : ""}${c.own ? " own" : ""}`}
            >
              <b className="cmd-src">{c.seat}</b>
              <b className="cmd-amt">{c.amount || "·"}</b>
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
