import { useEffect } from "react";

/**
 * Keep the screen awake while `active` — and only then, to spare battery.
 * The OS auto-releases wake locks when the app is backgrounded (so there is
 * no background battery cost); we re-acquire when the tab becomes visible.
 * No-ops gracefully where the API is unsupported or denied (e.g. low battery).
 */
export function useWakeLock(active: boolean) {
  useEffect(() => {
    if (!active || !("wakeLock" in navigator)) return;
    let lock: WakeLockSentinel | null = null;
    let stopped = false;

    const acquire = async () => {
      try {
        const l = await navigator.wakeLock.request("screen");
        if (stopped) {
          void l.release();
        } else {
          lock = l;
        }
      } catch {
        // denied (battery saver, etc.) — the game works fine without it
      }
    };

    const onVisible = () => {
      if (document.visibilityState === "visible") void acquire();
    };

    void acquire();
    document.addEventListener("visibilitychange", onVisible);
    return () => {
      stopped = true;
      document.removeEventListener("visibilitychange", onVisible);
      void lock?.release();
    };
  }, [active]);
}
