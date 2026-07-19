import type { NavigateFunction } from "react-router-dom";

/**
 * Go back to wherever the user actually came from.
 *
 * Sending them to a fixed route instead is wrong in the common case: someone
 * who opened sign-in from the tournament page, the dashboard, or a deep link
 * expects to land back there, not on the table lobby.
 *
 * `history.length > 1` distinguishes "there is somewhere to go back to" from a
 * tab opened directly on this URL, where `navigate(-1)` would do nothing at all
 * and leave the button looking broken.
 */
export function goBack(navigate: NavigateFunction, fallback = "/") {
  if (typeof window !== "undefined" && window.history.length > 1) {
    navigate(-1);
    return;
  }
  navigate(fallback, { replace: true });
}
