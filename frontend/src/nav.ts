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

/** The places someone goes to do something. Privacy lives in the footer —
 *  nav is for destinations, not small print. */
export const SITE_NAV: NavItem[] = [
  { label: "Play", to: "/table", icon: "heart", listed: true },
  { label: "Rulings", to: "/rulings", icon: "note", listed: true },
  { label: "Tournaments", to: "/tournament", icon: "crown", listed: true },
  { label: "Account", to: "/account", icon: "user", listed: true },
];

/**
 * Where the account entry points, and what it is called, depends on whether
 * anyone is signed in — a signed-out visitor is not going to "Account", they
 * are going to a form, and labelling it otherwise is a dead end.
 *
 * It names **both** actions on purpose. "Sign in" alone is the conventional
 * label and it was the wrong one here: this app has never had a sign-up link
 * anywhere, so a visitor reading "Sign in" has no reason to think an account
 * is something they could make. Creating one is the action that needs
 * advertising, so it goes first.
 */
export const accountNavItem = (username: string | null): NavItem =>
  username
    ? { label: username, to: "/account", icon: "user", listed: true }
    : { label: "Sign up / Sign in", to: "/account", icon: "user", listed: true };

export type AccountSection = "overview" | "games" | "notes" | "settings";

/**
 * Sections of the account area.
 *
 * The same axis as the console's tabs — movement *within* one thing rather
 * than around the app — so they render as their own strip rather than folding
 * into `SITE_NAV`, which would put four near-identical entries in the site
 * menu for a signed-out visitor who has no account at all.
 */
export const ACCOUNT_SECTIONS: { id: AccountSection; label: string; icon: IconName }[] = [
  { id: "overview", label: "Overview", icon: "chart" },
  { id: "games", label: "Games", icon: "heart" },
  { id: "notes", label: "Notes", icon: "note" },
  { id: "settings", label: "Settings", icon: "shield" },
];

export const accountPath = (section: AccountSection) =>
  section === "overview" ? "/account" : `/account/${section}`;

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
