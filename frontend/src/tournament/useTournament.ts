import { useCallback, useEffect, useRef, useState } from "react";
import { getState, TournamentState } from "./api";

/**
 * Polls one snapshot endpoint. Deliberately not a WebSocket: a tournament view
 * changes on organizer actions, not continuously, and a poll costs one query
 * set every few seconds instead of holding a socket per attendee all day. The
 * interval backs off when the tab is hidden so a phone in a pocket costs
 * nothing.
 */
export function useTournament(code: string, token?: string | null, activeMs = 5000) {
  const [state, setState] = useState<TournamentState | null>(null);
  const [error, setError] = useState<string | null>(null);
  // server time minus client time, so every device shows the same clock
  const offsetRef = useRef(0);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);

  const refresh = useCallback(async () => {
    try {
      const s = await getState(code, token);
      if (s.round?.now) offsetRef.current = s.round.now * 1000 - Date.now();
      setState(s);
      setError(null);
      return s;
    } catch (e) {
      setError(e instanceof Error ? e.message : "Lost contact with the server");
      return null;
    }
  }, [code, token]);

  useEffect(() => {
    let stopped = false;
    const tick = async () => {
      if (stopped) return;
      await refresh();
      if (stopped) return;
      const delay = document.hidden ? activeMs * 6 : activeMs;
      timer.current = setTimeout(() => void tick(), delay);
    };
    void tick();
    // a tab coming back to the foreground should be current immediately
    const onVisible = () => {
      if (!document.hidden) {
        if (timer.current) clearTimeout(timer.current);
        void tick();
      }
    };
    document.addEventListener("visibilitychange", onVisible);
    return () => {
      stopped = true;
      if (timer.current) clearTimeout(timer.current);
      document.removeEventListener("visibilitychange", onVisible);
    };
  }, [refresh, activeMs]);

  return { state, error, refresh, clockOffset: offsetRef };
}
