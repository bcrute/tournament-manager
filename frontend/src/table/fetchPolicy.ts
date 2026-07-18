import { ApiError } from "./api";

export type FetchOutcome = "gone" | "transient" | "fatal";

/**
 * How to treat a failed room poll.
 * - "gone": the room or our seat no longer exists — clear the session
 * - "transient": a blip (deploy, wifi drop). Keep showing the last known state
 *   and let the next poll recover; never blank a live game for this.
 * - "fatal": we have nothing to show, so surface the error
 */
export function classifyFetchError(error: unknown, hasState: boolean): FetchOutcome {
  if (error instanceof ApiError) {
    if (error.status === 404 || error.status === 403 || error.status === 410) return "gone";
    // 5xx and 0 are server restarts/proxy blips
    if (error.status >= 500 || error.status === 0) return hasState ? "transient" : "fatal";
    return hasState ? "transient" : "fatal";
  }
  // network-level failure (fetch threw) — the API is briefly unreachable
  return hasState ? "transient" : "fatal";
}
