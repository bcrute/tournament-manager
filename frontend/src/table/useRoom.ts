import { useCallback, useEffect, useRef, useState } from "react";
import { api, RoomState } from "./api";
import { classifyFetchError } from "./fetchPolicy";
import { clearSession } from "./session";

/**
 * Live room state: fetch + WebSocket refresh + refetch on tab focus.
 * Survives server restarts (deploys) without disturbing a game in progress:
 * transient failures keep the last known state and retry quietly.
 */
export function useRoom(code: string, token: string) {
  const [state, setState] = useState<RoomState | null>(null);
  const [gone, setGone] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [stale, setStale] = useState(false);
  const hasState = useRef(false);

  const refetch = useCallback(async () => {
    try {
      const next = await api<RoomState>(`/rooms/${code}/me`, { token });
      hasState.current = true;
      setState(next);
      setError(null);
      setStale(false);
    } catch (e) {
      switch (classifyFetchError(e, hasState.current)) {
        case "gone":
          clearSession();
          setGone(true);
          break;
        case "transient":
          setStale(true); // keep the game on screen; the retry loop will recover
          break;
        default:
          setError(e instanceof Error ? e.message : String(e));
      }
    }
  }, [code, token]);

  useEffect(() => {
    void refetch();
  }, [refetch]);

  // while stale (server restarting), poll until it answers again
  useEffect(() => {
    if (!stale) return;
    const iv = window.setInterval(() => void refetch(), 1500);
    return () => window.clearInterval(iv);
  }, [stale, refetch]);

  useEffect(() => {
    let ws: WebSocket | null = null;
    let closed = false;
    let timer: number | undefined;

    const connect = () => {
      const proto = location.protocol === "https:" ? "wss" : "ws";
      ws = new WebSocket(`${proto}://${location.host}/api/table/ws/${code}`);
      // a fresh socket means we may have missed updates (e.g. across a deploy)
      ws.onopen = () => void refetch();
      ws.onmessage = () => void refetch();
      ws.onclose = () => {
        if (!closed) timer = window.setTimeout(connect, 2000);
      };
    };
    connect();

    const onVisible = () => {
      if (document.visibilityState === "visible") void refetch();
    };
    document.addEventListener("visibilitychange", onVisible);

    return () => {
      closed = true;
      ws?.close();
      if (timer !== undefined) window.clearTimeout(timer);
      document.removeEventListener("visibilitychange", onVisible);
    };
  }, [code, refetch]);

  return { state, gone, error, stale, refetch };
}
