import { getItem, setItem } from "./storage";
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
  // two different things: `track` keeps your seat and shows the table view on
  // your own phone; `display` hands the device over as a dedicated screen
  "cmd.editFor": "Commander damage for {name}",
  "cmd.tapHint": "Left to remove, right to add",
  "cmd.own": "(own)",
  "cmd.minus": "Remove commander damage from {name}",
  "cmd.plus": "Add commander damage from {name}",
  "common.close": "Close",
  "status.eliminated": "eliminated",
  "menu.myGames": "Your games & notes",
  "menu.showQr": "Show QR code",
  "life.cantLoseAsk": "I'm alive",
  "life.cantLoseOn": "You can't lose the game",
  "life.cantLoseOff": "Can lose again",
  "life.undead": "Back in the game",
  "life.theyreDead": "{name} is out",
  "life.cantLoseWhy": "Zero life, 21 commander damage and 10 poison stop ending your game. Only \u201cI lost some other way\u201d does.",
  "life.notDead": "I'm not dead",
  "life.autoOut": "You're out",
  "life.autoOutBy": "{reason} \u2014 tap below if the board says otherwise",
  "life.byLife": "You hit 0 life",
  "life.byPoison": "You hit 10 poison",
  "life.byCommander": "You took 21 commander damage",
  "life.endingIn": "Game ends in {n}s",
  "life.endingWhy": "You were the last player still in, so this ends the game. Say you\u2019re not dead to keep it going.",
  "life.notDeadDone": "The app has stopped calling your counters lethal. Turn that off below when the board changes back.",
  "life.poison": "Poison",
  "life.poisonLethal": "10 is lethal",
  "life.poisonAdd": "Add a poison counter",
  "life.poisonRemove": "Remove a poison counter",
  "life.lostOtherWay": "I lost some other way",
  "life.lostOtherWayWhy": "Decking, Approach of the Second Sun, anything the counters can\u2019t see.",
  "qr.hint": "Scan with a phone camera, or type the code at mtg.skadoosh.dev.",
  "scan.title": "Scan a room code",
  "scan.button": "Scan QR code",
  "scan.hint": "Point the camera at the room's QR code.",
  "scan.unsupported": "This browser can't scan QR codes.",
  "scan.denied": "Camera access was declined, so scanning isn't available.",
  "scan.failed": "The camera couldn't be started.",
  "scan.useCameraApp": "Your phone's own camera app can scan it — that opens the room directly. Or type the five-character code.",
  "menu.tournament": "Tournament standings",
  "menu.track": "Show table view here",
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
  "card.winTitle": "How you win",
  "card.winLeader": "You and your Guardians lose the moment every Leader is out \u2014 even if a Guardian is still alive (907.8b).",
  "card.winGuardian": "Keep the Leader in. Your team loses the moment every Leader is out, however well you are doing (907.8b).",
  "card.winAssassin": "Your team wins once every Leader has lost and at least one Assassin is still in (907.8c).",
  "card.winTraitor": "You play alone and win only when every other player has left the game \u2014 other Traitors included (907.8d).",

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
  getItem(STORAGE_KEY) ||
  pickLocale(typeof navigator !== "undefined" ? navigator.languages ?? [navigator.language] : []);

export const getLocale = () => current;

export function setLocale(locale: string) {
  current = locale;
  try {
    setItem(STORAGE_KEY, locale);
  } catch {
    // private mode: the choice just won't persist
  }
}

/** Translate in the active locale. */
export const t = (key: string, vars?: Record<string, string | number>) =>
  translate(current, key, vars);
