import type React from "react";

/**
 * Single-colour outline icons.
 *
 * Everything is stroked in `currentColor` on a 24×24 grid, so an icon inherits
 * whatever colour its context sets — which is what makes themes possible. No
 * emoji: those can't be recoloured, render differently on every platform, and
 * several carry skin-tone or gender variants we'd be choosing for the user.
 *
 * These glyphs are deliberately plain. Every icon in the app resolves through
 * this one component, so swapping in a polished set later (Lucide, MIT; or
 * Material Symbols, Apache-2.0) is a change to this file and nothing else.
 */

export type IconName =
  | "menu"
  | "edit"
  | "note"
  | "book"
  | "monitor"
  | "card"
  | "heart"
  | "users"
  | "user"
  | "shield"
  | "chart"
  | "sword"
  | "skull"
  | "crown"
  | "dice"
  | "clock"
  | "hand"
  | "seat"
  | "exit"
  | "back"
  | "plus"
  | "minus"
  | "check"
  | "close"
  | "warn"
  | "chevron";

const paths: Record<IconName, React.ReactElement> = {
  menu: <path d="M4 7h16M4 12h16M4 17h16" />,
  edit: (
    <>
      <path d="M4 20h4L19 9a2.1 2.1 0 0 0-3-3L5 17v3z" />
      <path d="M14.5 6.5l3 3" />
    </>
  ),
  note: (
    <>
      <rect x="5" y="3.5" width="14" height="17" rx="2" />
      <path d="M8.5 8.5h7M8.5 12h7M8.5 15.5h4" />
    </>
  ),
  book: (
    <>
      <path d="M5 4.5A1.5 1.5 0 0 1 6.5 3H18v18H6.5A1.5 1.5 0 0 1 5 19.5z" />
      <path d="M8.5 3v18" />
    </>
  ),
  monitor: (
    <>
      <rect x="3" y="4" width="18" height="12" rx="2" />
      <path d="M9 20h6M12 16v4" />
    </>
  ),
  card: (
    <>
      <rect x="6" y="3" width="12" height="18" rx="2" />
      <path d="M9 8h6M9 12h6" />
    </>
  ),
  heart: <path d="M12 20.5C6.5 16.2 3.5 13.2 3.5 9.6A4.1 4.1 0 0 1 12 7.3a4.1 4.1 0 0 1 8.5 2.3c0 3.6-3 6.6-8.5 10.9z" />,
  users: (
    <>
      <circle cx="9" cy="8.5" r="3" />
      <path d="M3.5 20a5.5 5.5 0 0 1 11 0" />
      <path d="M16 6.2a3 3 0 0 1 0 5.6M17.5 14.5a5.5 5.5 0 0 1 3 5" />
    </>
  ),
  // one figure, where `users` is the group. The account area is about the one
  // person holding it, and the two glyphs are never a substitute for each other.
  user: (
    <>
      <circle cx="12" cy="8" r="3.5" />
      <path d="M5 20a7 7 0 0 1 14 0" />
    </>
  ),
  shield: <path d="M12 3l7 3v5.5c0 4.2-2.8 7.4-7 8.5-4.2-1.1-7-4.3-7-8.5V6z" />,
  chart: (
    <>
      <path d="M4 20V4M4 20h16" />
      <path d="M8 20v-6M12.5 20v-9M17 20v-4" />
    </>
  ),
  sword: (
    <>
      <path d="M19.5 3.5L10 13l1.5 1.5L21 5V3.5z" />
      <path d="M6.5 15.5l3 3M5 21l2.5-2.5M4.5 17.5L7 20" />
    </>
  ),
  skull: (
    <>
      <path d="M6 11a6 6 0 1 1 12 0v3.5l-1.5 1.5v3h-9v-3L6 14.5z" />
      <circle cx="9.5" cy="11" r="1.3" />
      <circle cx="14.5" cy="11" r="1.3" />
    </>
  ),
  crown: (
    <>
      <path d="M4 8l3.5 4L12 5.5 16.5 12 20 8v9.5H4z" />
      <path d="M4 20.5h16" />
    </>
  ),
  dice: (
    <>
      <rect x="4" y="4" width="16" height="16" rx="3" />
      <circle cx="9" cy="9" r="1.2" />
      <circle cx="15" cy="15" r="1.2" />
      <circle cx="12" cy="12" r="1.2" />
    </>
  ),
  clock: (
    <>
      <circle cx="12" cy="12" r="8.5" />
      <path d="M12 7v5.3l3.2 2" />
    </>
  ),
  // raised hand: calling an official mirrors what a player physically does
  hand: (
    <>
      <path d="M9 11V5.5a1.5 1.5 0 0 1 3 0V11" />
      <path d="M12 11V4.5a1.5 1.5 0 0 1 3 0V11" />
      <path d="M15 11V6.5a1.5 1.5 0 0 1 3 0V14a7 7 0 0 1-7 7h-.5a6 6 0 0 1-4.6-2.2L4 15.5a1.6 1.6 0 0 1 2.4-2.1L9 16" />
    </>
  ),
  seat: (
    <>
      <path d="M6 4v7a2 2 0 0 0 2 2h8a2 2 0 0 0 2-2V4" />
      <path d="M5 13h14v3a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2z" />
      <path d="M7.5 18v2.5M16.5 18v2.5" />
    </>
  ),
  exit: (
    <>
      <path d="M14 4.5H6.5A1.5 1.5 0 0 0 5 6v12a1.5 1.5 0 0 0 1.5 1.5H14" />
      <path d="M17 8.5L20.5 12 17 15.5M10 12h10.5" />
    </>
  ),
  back: <path d="M15 5l-7 7 7 7" />,
  chevron: <path d="M6 9l6 6 6-6" />,
  plus: <path d="M12 6v12M6 12h12" />,
  minus: <path d="M6 12h12" />,
  check: <path d="M5 12.5l4.5 4.5L19 7.5" />,
  close: <path d="M6 6l12 12M18 6L6 18" />,
  warn: (
    <>
      <path d="M12 4.5L21 19.5H3z" />
      <path d="M12 10v4.2" />
      <circle cx="12" cy="17" r="0.9" />
    </>
  ),
};

export default function Icon({
  name,
  size = 20,
  label,
  className,
}: {
  name: IconName;
  size?: number;
  /** Set when the icon stands alone; omit when adjacent text already says it. */
  label?: string;
  className?: string;
}) {
  return (
    <svg
      className={`icon${className ? ` ${className}` : ""}`}
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.75"
      strokeLinecap="round"
      strokeLinejoin="round"
      role={label ? "img" : undefined}
      aria-label={label}
      aria-hidden={label ? undefined : true}
      focusable="false"
    >
      {paths[name]}
    </svg>
  );
}

export const ICON_NAMES = Object.keys(paths) as IconName[];
