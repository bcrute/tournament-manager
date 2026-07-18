import { useEffect, useRef, useState } from "react";

/** Optimistic taps accumulate locally, committed as one net delta after a pause. */
export function useDebouncedDelta(commit: (delta: number) => Promise<void>, ms = 1400) {
  const [pending, setPending] = useState(0);
  const pendingRef = useRef(0);
  const timer = useRef<number | undefined>(undefined);

  const bump = (d: number) => {
    pendingRef.current += d;
    setPending(pendingRef.current);
    if (timer.current !== undefined) window.clearTimeout(timer.current);
    timer.current = window.setTimeout(() => {
      const delta = pendingRef.current;
      pendingRef.current = 0;
      setPending(0);
      if (delta !== 0) void commit(delta);
    }, ms);
  };

  useEffect(
    () => () => {
      if (timer.current !== undefined) window.clearTimeout(timer.current);
      const delta = pendingRef.current;
      pendingRef.current = 0;
      if (delta !== 0) void commit(delta);
    },
    // commit only on unmount
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [],
  );

  return { pending, bump };
}
