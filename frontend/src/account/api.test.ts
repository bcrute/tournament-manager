import { afterEach, describe, expect, it, vi } from "vitest";
import {
  account,
  AccountError,
  changePassword,
  changeUsername,
  deleteAccount,
  getAccount,
  getHistory,
  getNote,
  getNotes,
  getStats,
  login,
  logout,
  regenerateRecoveryCodes,
  saveNote,
  setDisplayName,
  setEmail,
  signup,
} from "./api";

function mockFetch(body: unknown = { ok: true }, status = 200, headers: Record<string, string> = {}) {
  const fn = vi.fn().mockResolvedValue({
    ok: status < 400,
    status,
    statusText: "Mocked",
    headers: new Headers(headers),
    json: () => Promise.resolve(body),
  });
  vi.stubGlobal("fetch", fn);
  return fn;
}

const last = (fn: ReturnType<typeof vi.fn>) => {
  const [url, opts] = fn.mock.calls.at(-1) as [string, RequestInit];
  return { url, opts, body: opts.body ? JSON.parse(opts.body as string) : undefined };
};

afterEach(() => vi.unstubAllGlobals());

describe("account transport", () => {
  it("sends the session cookie — it is httpOnly, so the browser must attach it", async () => {
    const fn = mockFetch();
    await account("/me");
    expect(last(fn).opts.credentials).toBe("same-origin");
    expect(last(fn).url).toBe("/api/account/me");
  });

  it("sends no content-type when there is no body", async () => {
    const fn = mockFetch();
    await getAccount();
    expect(last(fn).opts.headers).toEqual({});
  });

  it("raises the server's message rather than a generic one", async () => {
    mockFetch({ detail: "that username is taken" }, 409);
    const err = await signup("ada", "a good long one").catch((e: unknown) => e);
    expect(err).toBeInstanceOf(AccountError);
    expect((err as AccountError).status).toBe(409);
    expect((err as AccountError).message).toBe("that username is taken");
  });

  it("falls back to the status text when the body isn't JSON", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: false,
        status: 500,
        statusText: "Internal Server Error",
        headers: new Headers(),
        json: () => Promise.reject(new Error("not json")),
      }),
    );
    const err = await getStats().catch((e: unknown) => e);
    expect((err as AccountError).message).toBe("Internal Server Error");
  });
});

describe("sessions", () => {
  it("sends only a username and a password", async () => {
    // A recovery email used to ride along here. It is enrolled and confirmed
    // separately now, so nothing about it belongs in account creation.
    const fn = mockFetch();
    await signup("ada", "a good long one");
    expect(last(fn).body).toEqual({ username: "ada", password: "a good long one" });
  });

  it("carries no email key at all, not even a null one", async () => {
    const fn = mockFetch();
    await signup("ada", "a good long one");
    expect("email" in last(fn).body).toBe(false);
  });

  it("logs in and out by POST", async () => {
    const fn = mockFetch();
    await login("ada", "a good long one");
    expect(last(fn).url).toBe("/api/account/login");
    await logout();
    expect(last(fn).url).toBe("/api/account/logout");
    expect(last(fn).opts.method).toBe("POST");
  });
});

describe("the two names", () => {
  it("sends the password with a rename — a session alone must not be enough", async () => {
    const fn = mockFetch();
    await changeUsername("new-name", "a good long one");
    expect(last(fn).url).toBe("/api/account/username");
    expect(last(fn).body).toEqual({ username: "new-name", password: "a good long one" });
  });

  it("sends no password with a table name, which is cosmetic", async () => {
    const fn = mockFetch();
    await setDisplayName("Grumpy Platypus 42");
    expect(last(fn).url).toBe("/api/account/display-name");
    expect(last(fn).body).toEqual({ displayName: "Grumpy Platypus 42" });
    expect(last(fn).body.password).toBeUndefined();
  });

  it("clears the table name with an empty string, not by omission", async () => {
    const fn = mockFetch();
    await setDisplayName("");
    expect(last(fn).body).toEqual({ displayName: "" });
  });
});

describe("credentials", () => {
  it("names the new password `new`, as the server's body does", async () => {
    const fn = mockFetch();
    await changePassword("old one here", "new one here");
    expect(last(fn).body).toEqual({ current: "old one here", new: "new one here" });
  });

  it("regenerates recovery codes by POST — a GET would be prefetchable", async () => {
    const fn = mockFetch({ recoveryCodes: [] });
    await regenerateRecoveryCodes();
    expect(last(fn).url).toBe("/api/account/recovery-codes");
    expect(last(fn).opts.method).toBe("POST");
  });

  it("sends the email as given, with the password it now costs", async () => {
    const fn = mockFetch();
    await setEmail("ada@example.com", "correct horse battery");
    expect(last(fn).body).toEqual({
      email: "ada@example.com",
      password: "correct horse battery",
    });
  });

  it("requires the typed username to delete", async () => {
    const fn = mockFetch();
    await deleteAccount("ada");
    expect(last(fn).url).toBe("/api/account/delete");
    expect(last(fn).body).toEqual({ confirm: "ada" });
  });
});

describe("history and notes", () => {
  it("asks for the whole history by default", async () => {
    const fn = mockFetch({ games: [] });
    await getHistory();
    expect(last(fn).url).toBe("/api/account/history");
  });

  it("passes a limit when the caller wants a preview", async () => {
    const fn = mockFetch({ games: [] });
    await getHistory(5);
    expect(last(fn).url).toBe("/api/account/history?limit=5");
  });

  it("reads totals from a separate endpoint, so they aren't the page size", async () => {
    const fn = mockFetch({ games: 12 });
    await getStats();
    expect(last(fn).url).toBe("/api/account/stats");
  });

  it("addresses a note by room and game number", async () => {
    const fn = mockFetch();
    await getNote("ab123", 2);
    expect(last(fn).url).toBe("/api/account/notes/ab123/2");
    await saveNote("ab123", 2, "went long");
    expect(last(fn).url).toBe("/api/account/notes/ab123/2");
    expect(last(fn).opts.method).toBe("PUT");
    expect(last(fn).body).toEqual({ text: "went long" });
  });

  it("lists every note from one place", async () => {
    const fn = mockFetch({ notes: [] });
    await getNotes();
    expect(last(fn).url).toBe("/api/account/notes");
  });
});
