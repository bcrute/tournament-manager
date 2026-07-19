import type { IconName } from "./Icon";

/**
 * Navigation, as data.
 *
 * Every surface previously hand-rolled its own header, which is why the app had
 * nine `<header>` elements, five unrelated page wrappers, and a back button that
 * behaved three different ways. Routes were flat, so there was nowhere for
 * shared chrome to live.
 *
 * Declaring navigation here means a layout renders it rather than each page
 * inventing it, and adding a section is a line in a list instead of a new
 * bespoke header.
 */

export interface NavItem {
  label: string;
  to: string;
  icon: IconName;
  /** Shown in the layout's nav; false for routes reachable but not advertised. */
  listed?: boolean;
}

/** The public website. One page today; the shape is what matters. */
export const SITE_NAV: NavItem[] = [
  { label: "Play", to: "/table", icon: "heart", listed: true },
  { label: "Tournaments", to: "/tournament", icon: "crown", listed: true },
];

/**
 * The player's bottom navigation.
 *
 * "Your games" used to sit here and led to a sign-in wall for the many players
 * who never make an account. It now lives in the menu, and only appears when
 * there is an account behind it.
 */
export const PLAY_NAV: NavItem[] = [
  { label: "Table", to: "/table", icon: "heart", listed: true },
];

export type ConsoleSection = "pods" | "roster" | "standings" | "calls" | "settings";

/**
 * Sections of the organizer console.
 *
 * This is the piece the old layout could not express: running an event means
 * moving between roster, pairings, standings and judge calls while a round is
 * live. As one scrolling page that is unusable; as sections it is a console.
 */
export const CONSOLE_SECTIONS: { id: ConsoleSection; label: string; icon: IconName }[] = [
  { id: "pods", label: "Pods", icon: "seat" },
  { id: "roster", label: "Roster", icon: "users" },
  { id: "standings", label: "Standings", icon: "crown" },
  { id: "calls", label: "Calls", icon: "hand" },
];

export const ADMIN_SECTIONS: { id: string; label: string; icon: IconName }[] = [
  { id: "overview", label: "Overview", icon: "monitor" },
  { id: "tournaments", label: "Tournaments", icon: "crown" },
  { id: "rooms", label: "Rooms", icon: "seat" },
  { id: "bans", label: "Bans", icon: "close" },
  { id: "logs", label: "Logs", icon: "note" },
];

export const consolePath = (code: string, section: ConsoleSection) =>
  `/tournament/${code}/organize/${section}`;
