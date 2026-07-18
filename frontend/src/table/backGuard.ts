export interface BackActions {
  /** Show the "go back again" warning. */
  warn: () => void;
  /** Actually leave the room. */
  leave: () => void;
  /** Re-push the history sentinel so the next back is caught too. */
  rearm: () => void;
}

/**
 * Double-back-to-exit: the first back press arms the guard and warns;
 * a second press within `windowMs` leaves. Presses after the window
 * re-arm instead of leaving.
 */
export function createBackGuard(windowMs = 2500) {
  let armedAt = 0;
  return {
    onBack(actions: BackActions) {
      if (Date.now() - armedAt < windowMs) {
        actions.leave();
        return;
      }
      armedAt = Date.now();
      actions.warn();
      actions.rearm();
    },
  };
}
