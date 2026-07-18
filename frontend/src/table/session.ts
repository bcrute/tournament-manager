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

export function clearSession() {
  localStorage.removeItem(KEY);
}
