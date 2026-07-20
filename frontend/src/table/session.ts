import { getItem, removeItem, setItem, storageAvailable } from "../storage";
const KEY = "table.session";

export interface Session {
  /** Opaque id used in the address bar, so links never carry a joinable code. */
  urlId?: string;
  code: string;
  token: string;
}

export function loadSession(): Session | null {
  try {
    // migrate the pre-rename key so live sessions survive the /treachery → /table move
    const legacy = getItem("treachery.session");
    if (legacy && !getItem(KEY)) {
      setItem(KEY, legacy);
      removeItem("treachery.session");
    }
    const raw = getItem(KEY);
    if (raw) return JSON.parse(raw) as Session;
    // Empty *working* storage means there is genuinely no session — the user
    // left, or cleared it. Returning the in-memory copy here would resurrect a
    // session that was deliberately ended, which is a bug this project has
    // already shipped once. Only fall back when storage cannot answer at all.
    return storageAvailable() ? null : memory;
  } catch {
    return storageAvailable() ? null : memory;
  }
}

/**
 * Where the session lives when the browser refuses to keep it.
 *
 * Without this, a device that blocks storage can't hold a room at all: the
 * player is sent to the room, Room finds no session, and bounces them back to
 * the lobby in a loop. In memory they can play the whole game; only a refresh
 * loses it — which is what the privacy page promises.
 */
let memory: Session | null = null;

export function saveSession(s: Session) {
  memory = s;
  setItem(KEY, JSON.stringify(s));
}

export type LandingAction = "none" | "resume" | "autojoin";

/**
 * What the landing page should do:
 * - "none": no session, no join link — show the normal form
 * - "resume": stored session and no join link (or the QR is for that same room)
 * - "autojoin": a QR/join link — join that room immediately (leaving any old game first)
 */
export function landingAction(session: Session | null, joinParam: string | null): LandingAction {
  if (joinParam && joinParam.trim().toUpperCase() !== session?.code) return "autojoin";
  return session ? "resume" : "none";
}

export function clearSession() {
  memory = null;
  removeItem(KEY);
  // the pre-rename key must go too, or loadSession() resurrects the old game
  removeItem("treachery.session");
}
