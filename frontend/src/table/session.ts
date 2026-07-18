const KEY = "table.session";

export interface Session {
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

export type LandingAction = "none" | "resume" | "switch";

/**
 * What the landing page should do with a stored session:
 * - "none": no session, show the normal form
 * - "resume": go back to the stored room (also when the QR is for that same room)
 * - "switch": a QR/join link for a DIFFERENT room — leave the old game, stay on the form
 */
export function landingAction(session: Session | null, joinParam: string | null): LandingAction {
  if (!session) return "none";
  if (joinParam && joinParam.trim().toUpperCase() !== session.code) return "switch";
  return "resume";
}

export function clearSession() {
  localStorage.removeItem(KEY);
  // the pre-rename key must go too, or loadSession() resurrects the old game
  localStorage.removeItem("treachery.session");
}
