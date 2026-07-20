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
    const legacy = localStorage.getItem("treachery.session");
    if (legacy && !localStorage.getItem(KEY)) {
      localStorage.setItem(KEY, legacy);
      localStorage.removeItem("treachery.session");
    }
    const raw = localStorage.getItem(KEY);
    return raw ? (JSON.parse(raw) as Session) : null;
  } catch {
    return null;
  }
}

export function saveSession(s: Session) {
  localStorage.setItem(KEY, JSON.stringify(s));
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
  localStorage.removeItem(KEY);
  // the pre-rename key must go too, or loadSession() resurrects the old game
  localStorage.removeItem("treachery.session");
}
