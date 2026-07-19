import { useEffect, useRef, useState } from "react";
import { t } from "../i18n";
import Icon from "../Icon";

export default function RoomBar({
  code,
  name,
  onRename,
  onDisplay,
  displayLabel,
  onTrack,
  onNotes,
  onRules,
  onTournament,
  onMyGames,
  onLeave,
  leaveLabel,
}: {
  code: string;
  name: string;
  onRename?: () => void;
  onDisplay?: () => void;
  displayLabel?: string;
  /** Show the table view on this phone without giving up the seat. */
  onTrack?: () => void;
  onNotes?: () => void;
  onRules?: () => void;
  /** Standings, when this room is a tournament pod. */
  onTournament?: () => void;
  /** "Your games & notes" — omitted when signed out, where it leads nowhere. */
  onMyGames?: () => void;
  onLeave: () => void;
  leaveLabel?: string;
}) {
  const [open, setOpen] = useState(false);
  const wrap = useRef<HTMLDivElement>(null);
  const trigger = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    if (!open) return;
    const onDown = (e: PointerEvent) => {
      if (!wrap.current?.contains(e.target as Node)) setOpen(false);
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== "Escape") return;
      setOpen(false);
      trigger.current?.focus();   // don't strand focus where the menu was
    };
    document.addEventListener("pointerdown", onDown);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("pointerdown", onDown);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);

  return (
    <div className="room-bar" ref={wrap} onPointerDown={(e) => e.stopPropagation()}>
      {/* leading hamburger: this menu carries navigation, not just overflow,
          so it sits where a nav menu is expected rather than as a kebab */}
      <button
        ref={trigger}
        className="bar-menu-btn"
        aria-label={t("menu.open")}
        aria-expanded={open}
        aria-haspopup="true"
        onClick={() => setOpen(!open)}
      >
        <Icon name="menu" label={t("menu.open")} />
      </button>
      <span className="bar-code">{code}</span>
      <span className="bar-name">{name}</span>
      {open && (
        <div className="bar-menu">
          {onRename && (
            <button
              onClick={() => {
                setOpen(false);
                onRename();
              }}
            >
              <Icon name="edit" /> {t("menu.rename")}
            </button>
          )}
          {onNotes && (
            <button
              onClick={() => {
                setOpen(false);
                onNotes();
              }}
            >
              <Icon name="note" /> {t("menu.notes")}
            </button>
          )}
          {onRules && (
            <button
              onClick={() => {
                setOpen(false);
                onRules();
              }}
            >
              <Icon name="book" /> {t("menu.rules")}
            </button>
          )}
          {onTournament && (
            <button
              onClick={() => {
                setOpen(false);
                onTournament();
              }}
            >
              <Icon name="crown" /> {t("menu.tournament")}
            </button>
          )}
          {onTrack && (
            <button
              onClick={() => {
                setOpen(false);
                onTrack();
              }}
            >
              <Icon name="monitor" /> {t("menu.track")}
            </button>
          )}
          {onDisplay && (
            <button
              onClick={() => {
                setOpen(false);
                onDisplay();
              }}
            >
              <Icon name="monitor" /> {displayLabel ?? t("menu.display")}
            </button>
          )}
          {onMyGames && (
            <button
              onClick={() => {
                setOpen(false);
                onMyGames();
              }}
            >
              <Icon name="note" /> {t("menu.myGames")}
            </button>
          )}
          <button
            className="danger"
            onClick={() => {
              setOpen(false);
              onLeave();
            }}
          >
            <Icon name="exit" /> {leaveLabel ?? t("menu.leaveGame")}
          </button>
        </div>
      )}
    </div>
  );
}
