import { readFileSync } from "node:fs";

/**
 * Reading what the app under test "sent".
 *
 * The server runs with `TABLE_MAIL_FILE` pointing at a JSONL file (see
 * `playwright.config.ts`), which is a real transport rather than a test hook —
 * the same thing a developer would point at a local mail catcher. That matters:
 * the alternative was a test-only way to skip confirming an address, which
 * would have left the one flow most in need of end-to-end coverage covered
 * only by unit tests.
 */
export interface SentMail {
  to: string;
  subject: string;
  body: string;
}

function all(): SentMail[] {
  const path = process.env.E2E_MAILBOX;
  if (!path) throw new Error("E2E_MAILBOX is not set — check playwright.config.ts");
  let text = "";
  try {
    text = readFileSync(path, "utf-8");
  } catch {
    return []; // nothing sent yet, so the file does not exist
  }
  return text
    .split("\n")
    .filter(Boolean)
    .map((line) => JSON.parse(line) as SentMail);
}

/** The most recent message to an address, waiting briefly for it to arrive —
 *  sends are queued on the server so the response can beat the delivery. */
export async function waitForMail(to: string, timeoutMs = 10_000): Promise<SentMail> {
  const deadline = Date.now() + timeoutMs;
  for (;;) {
    const match = all()
      .reverse()
      .find((m) => m.to.toLowerCase() === to.toLowerCase());
    if (match) return match;
    if (Date.now() > deadline) throw new Error(`no mail to ${to} within ${timeoutMs}ms`);
    await new Promise((r) => setTimeout(r, 100));
  }
}

/** The link out of a message. It is the only http line in the body, and the
 *  token lives in its fragment. */
export function linkIn(mail: SentMail): string {
  const line = mail.body.split("\n").find((l) => l.startsWith("http"));
  if (!line) throw new Error(`no link in message: ${mail.body}`);
  return line.trim();
}
