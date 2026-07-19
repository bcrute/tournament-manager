import { useEffect, useRef, useState } from "react";
import { t } from "../i18n";

export default function RoomBar({
  code,
  name,
  onRename,
  onDisplay,
  displayLabel,
  onNotes,
  onRules,
  onLeave,
  leaveLabel,
}: {
  code: string;
  name: string;
  onRename?: () => void;
  onDisplay?: () => void;
  displayLabel?: string;
  onNotes?: () => void;
  onRules?: () => void;
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
        aria-label={t("menu.open")}
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
              ✎ {t("menu.rename")}
            </button>
          )}
          {onNotes && (
            <button
              onClick={() => {
                setOpen(false);
                onNotes();
              }}
            >
              ✎ {t("menu.notes")}
            </button>
          )}
          {onRules && (
            <button
              onClick={() => {
                setOpen(false);
                onRules();
              }}
            >
              📘 {t("menu.rules")}
            </button>
          )}
          {onDisplay && (
            <button
              onClick={() => {
                setOpen(false);
                onDisplay();
              }}
            >
              📺 {displayLabel ?? t("menu.display")}
            </button>
          )}
          <button
            className="danger"
            onClick={() => {
              setOpen(false);
              onLeave();
            }}
          >
            {leaveLabel ?? t("menu.leaveGame")}
          </button>
        </div>
      )}
    </div>
  );
}
