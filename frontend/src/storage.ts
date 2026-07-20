/**
 * Local storage that never throws.
 *
 * We assume people block things. A privacy extension, Safari's private mode, a
 * full quota, or a browser configured to refuse storage all make
 * `localStorage.setItem` raise — and every call site here was unguarded, so a
 * player whose browser refused storage would have their room created on the
 * server and then hit an exception before they were ever sent to it.
 *
 * Failing to remember something is a small loss. Failing to *work* is not, so
 * every operation degrades to "we didn't remember that" and the app carries on.
 * The consequence is that a locked-down browser can still play; it just gets
 * asked to rejoin after a refresh.
 */

let warned = false;

function warnOnce(action: string, e: unknown) {
  if (warned || typeof console === "undefined") return;
  warned = true;
  console.info(
    `[storage] ${action} unavailable — the app works without it, but this ` +
      `device won't remember its seat across a refresh.`,
    e,
  );
}

export function storageAvailable(): boolean {
  try {
    const probe = "__probe__";
    localStorage.setItem(probe, "1");
    localStorage.removeItem(probe);
    return true;
  } catch {
    return false;
  }
}

export function getItem(key: string): string | null {
  try {
    return localStorage.getItem(key);
  } catch (e) {
    warnOnce("read", e);
    return null;
  }
}

/** True when the value was actually persisted. */
export function setItem(key: string, value: string): boolean {
  try {
    localStorage.setItem(key, value);
    return true;
  } catch (e) {
    warnOnce("write", e);
    return false;
  }
}

export function removeItem(key: string): void {
  try {
    localStorage.removeItem(key);
  } catch (e) {
    warnOnce("remove", e);
  }
}
