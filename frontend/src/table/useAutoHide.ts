import { useCallback, useEffect, useRef, useState } from "react";

/**
 * Visible after activity, hidden after `delay` ms of quiet.
 * Call `poke()` on every interaction to restart the countdown.
 */
export function useAutoHide(delay = 2500) {
  const [visible, setVisible] = useState(true);
  const timer = useRef<number | undefined>(undefined);

  const poke = useCallback(() => {
    setVisible(true);
    if (timer.current !== undefined) window.clearTimeout(timer.current);
    timer.current = window.setTimeout(() => setVisible(false), delay);
  }, [delay]);

  useEffect(() => {
    poke(); // show briefly on mount so the control is discoverable
    return () => {
      if (timer.current !== undefined) window.clearTimeout(timer.current);
    };
  }, [poke]);

  return { visible, poke };
}
