import { useEffect, useRef, useState } from "react";

export default function RoomBar({
  code,
  name,
  onRename,
  onLeave,
  leaveLabel = "Leave game",
}: {
  code: string;
  name: string;
  onRename?: () => void;
  onLeave: () => void;
  leaveLabel?: string;
}) {
  const [open, setOpen] = useState(false);
  const wrap = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const onDown = (e: PointerEvent) => {
      if (!wrap.current?.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("pointerdown", onDown);
    return () => document.removeEventListener("pointerdown", onDown);
  }, [open]);

  return (
    <div className="room-bar" ref={wrap} onPointerDown={(e) => e.stopPropagation()}>
      <span className="bar-code">{code}</span>
      <span className="bar-name">{name}</span>
      <button
        className="bar-menu-btn"
        aria-label="Room menu"
        aria-expanded={open}
        onClick={() => setOpen(!open)}
      >
        ⋮
      </button>
      {open && (
        <div className="bar-menu">
          {onRename && (
            <button
              onClick={() => {
                setOpen(false);
                onRename();
              }}
            >
              Rename
            </button>
          )}
          <button
            className="danger"
            onClick={() => {
              setOpen(false);
              onLeave();
            }}
          >
            {leaveLabel}
          </button>
        </div>
      )}
    </div>
  );
}
