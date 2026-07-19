/**
 * Tiny i18n layer — no dependency, because the whole surface is a lookup with
 * interpolation and a fallback chain.
 *
 * Two rules that matter more than the code:
 *  1. Prefer an icon to a string. Untranslated text is a barrier; a symbol that
 *     needs no translation is better than a string translated badly.
 *  2. Every icon-only control still needs a label for screen readers, and that
 *     label goes through here too.
 */

export type Catalog = Record<string, string>;

export const en: Catalog = {
  // room bar / menu
  "menu.open": "Menu",
  "menu.rename": "Rename",
  "menu.notes": "Notes",
  "menu.rules": "Rules",
  "menu.display": "Use as table display",
  "menu.takeSeat": "Take a seat",
  "menu.leaveGame": "Leave game",
  "menu.leaveRoom": "Leave room",
  "menu.callOfficial": "Call an official",

  // navigation
  "nav.card": "Card",
  "nav.life": "Life",
  "nav.table": "Table",

  // life
  "life.minus": "{name} minus {n}",
  "life.plus": "{name} plus {n}",
  "life.commanderDamage": "Commander damage",
  "life.ownCommander": "your own",
  "life.eliminated": "Eliminated",
  "life.undo": "undo",
  "life.imDead": "I'm dead",
  "life.lethalWarning": "21+ commander damage from one commander is lethal",

  // identity cards
  "card.yours": "Your card",
  "card.theirs": "{name}'s card",
  "card.holdToPeek": "hold to peek",
  "card.slideToUnveil": "Slide to unveil to the table",
  "card.unveiling": "Unveiling…",
  "card.unveiledAs": "Unveiled — {name} ({role})",
  "card.artBy": "art by {artist}",
  "card.tapToClose": "tap to close",

  // status
  "status.reconnecting": "reconnecting…",
  "status.gameOver": "Game over — returning to the room in {n}…",
  "status.revealed": "{name} has revealed their identity — tap to view",
  "status.goesFirst": "{name} goes first",
  "status.youGoFirst": "You go first!",
};

/** Registry. Add a locale by adding its catalog here — the parity test will
 * fail loudly if it drifts from `en`. Translations should come from someone who
 * speaks the language; a machine-translated UI is its own kind of barrier. */
export const catalogs: Record<string, Catalog> = { en };

export const FALLBACK = "en";

/**
 * Resolve a key. Falls back through: requested locale → base language
 * (`pt-BR` → `pt`) → English → the key itself, so a missing string degrades to
 * something diagnosable rather than blank.
 */
export function translate(
  locale: string,
  key: string,
  vars?: Record<string, string | number>,
  registry: Record<string, Catalog> = catalogs,
): string {
  const base = locale.split("-")[0];
  const template =
    registry[locale]?.[key] ?? registry[base]?.[key] ?? registry[FALLBACK]?.[key] ?? key;
  if (!vars) return template;
  return template.replace(/\{(\w+)\}/g, (whole, name) =>
    name in vars ? String(vars[name]) : whole,
  );
}

/** Pick the best available locale from the browser's preferences. */
export function pickLocale(
  preferred: readonly string[],
  available: readonly string[] = Object.keys(catalogs),
): string {
  for (const want of preferred) {
    if (available.includes(want)) return want;
    const base = want.split("-")[0];
    const match = available.find((a) => a === base || a.split("-")[0] === base);
    if (match) return match;
  }
  return FALLBACK;
}

const STORAGE_KEY = "table.locale";

let current =
  (typeof localStorage !== "undefined" && localStorage.getItem(STORAGE_KEY)) ||
  pickLocale(typeof navigator !== "undefined" ? navigator.languages ?? [navigator.language] : []);

export const getLocale = () => current;

export function setLocale(locale: string) {
  current = locale;
  try {
    localStorage.setItem(STORAGE_KEY, locale);
  } catch {
    // private mode: the choice just won't persist
  }
}

/** Translate in the active locale. */
export const t = (key: string, vars?: Record<string, string | number>) =>
  translate(current, key, vars);
