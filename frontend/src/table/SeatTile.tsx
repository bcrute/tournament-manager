import { useEffect, useRef, useState } from "react";
import { PlayerInfo } from "./api";
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
  const cmd = Object.entries(p.cmdDamage);

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
          aria-label={`${p.name} minus 1`}
        />
        <button
          className={`seat-half inc${flash === 1 ? " flash" : ""}`}
          data-delta="1"
          aria-label={`${p.name} plus 1`}
        />

        {turn !== undefined && (
          <span className={`seat-turn${first ? " first" : ""}`} title="turn order">
            {turn}
          </span>
        )}

        <div className="seat-face" style={{ bottom: font.cmdBar }}>
          <span className="seat-name" style={{ fontSize: font.name }}>
            {first && "👑 "}
            {p.name}
            {p.card ? ` · ${p.card.role}` : ""}
          </span>
          <span className="seat-life" style={{ fontSize: font.life }}>
            {p.eliminated ? "☠" : (p.life ?? "—")}
          </span>
        </div>

        <div
          className="seat-cmd"
          style={{ fontSize: font.cmd, maxHeight: font.cmdBar }}
          onPointerDown={(e) => e.stopPropagation()}
        >
          {cmd.length === 0 ? (
            <span className="cmd-none">no commander damage</span>
          ) : (
            cmd.map(([fromPid, amt]) => (
              <span key={fromPid} className={`cmd-chip${amt >= 21 ? " lethal" : ""}`}>
                <b>{amt}</b> {nameOf.get(fromPid) ?? "?"}
                {String(p.pid) === fromPid ? " (own)" : ""}
              </span>
            ))
          )}
        </div>
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
