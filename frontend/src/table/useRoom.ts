import { useCallback, useEffect, useState } from "react";
import { api, ApiError, RoomState } from "./api";
import { clearSession } from "./session";

/** Live room state: fetch + WebSocket refresh + refetch on tab focus. */
export function useRoom(code: string, token: string) {
  const [state, setState] = useState<RoomState | null>(null);
  const [gone, setGone] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const refetch = useCallback(async () => {
    try {
      setState(await api<RoomState>(`/rooms/${code}/me`, { token }));
      setError(null);
    } catch (e) {
      if (e instanceof ApiError && (e.status === 404 || e.status === 403)) {
        clearSession();
        setGone(true);
      } else {
        setError(e instanceof Error ? e.message : String(e));
      }
    }
  }, [code, token]);

  useEffect(() => {
    void refetch();
  }, [refetch]);

  useEffect(() => {
    let ws: WebSocket | null = null;
    let closed = false;
    let timer: number | undefined;

    const connect = () => {
      const proto = location.protocol === "https:" ? "wss" : "ws";
      ws = new WebSocket(`${proto}://${location.host}/api/table/ws/${code}`);
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

  return { state, gone, error, refetch };
}
