import { useEffect, useRef } from "react";

/** How long a press has to last before it stops being a tap. */
export const HOLD_DELAY_MS = 1000;
/** How often it fires once it is running. */
export const REPEAT_MS = 500;
/** How much each repeat is worth. Tapping is 1; holding is for the long haul. */
export const REPEAT_STEP = 10;

/**
 * Press and hold to run a counter in tens.
 *
 * Going from 40 to 12 is twenty-eight taps, which is what this replaces. After
 * a second the press stops being a tap and starts repeating, so a long press
 * covers ground and a short one still moves by one.
 *
 * The direction is fixed when the press starts, so sliding a thumb across the
 * middle of a card mid-hold can't reverse it.
 *
 * `end()` reports whether it ever repeated. That is the bit callers need: a
 * press that ran in tens must **not** also apply the single tap on release, or
 * every hold would be off by one.
 */
export function useHoldRepeat(
  fire: (delta: number) => void,
  {
    delay = HOLD_DELAY_MS,
    interval = REPEAT_MS,
    step = REPEAT_STEP,
  }: { delay?: number; interval?: number; step?: number } = {},
) {
  const startTimer = useRef<number | undefined>(undefined);
  const tick = useRef<number | undefined>(undefined);
  const repeated = useRef(false);
  // held in a ref so the timers always see the current callback without
  // restarting: a repeat that re-armed on every render would drift
  const fireRef = useRef(fire);
  fireRef.current = fire;

  const clear = () => {
    if (startTimer.current !== undefined) window.clearTimeout(startTimer.current);
    if (tick.current !== undefined) window.clearInterval(tick.current);
    startTimer.current = undefined;
    tick.current = undefined;
  };

  /** Begin a press. `sign` is -1 or 1 and is fixed for the whole hold. */
  const begin = (sign: number) => {
    clear();
    repeated.current = false;
    const dir = sign < 0 ? -1 : 1;
    startTimer.current = window.setTimeout(() => {
      repeated.current = true;
      fireRef.current(dir * step); // the first ten lands at `delay`, not after it
      tick.current = window.setInterval(() => fireRef.current(dir * step), interval);
    }, delay);
  };

  /**
   * End a press. True when it repeated, meaning the caller should skip whatever
   * it does for a tap.
   */
  const end = (): boolean => {
    clear();
    return repeated.current;
  };

  /** A press that turned into a drag: stop, and count it as neither. */
  const cancel = () => {
    clear();
    repeated.current = false;
  };

  useEffect(() => clear, []);

  return { begin, end, cancel };
}
