import { beforeEach, describe, expect, it, vi } from "vitest";
import { clearSession, landingAction, loadSession, saveSession } from "./session";

describe("session storage", () => {
  beforeEach(() => localStorage.clear());

  it("round-trips a session", () => {
    saveSession({ code: "ABCDE", token: "tok" });
    expect(loadSession()).toEqual({ code: "ABCDE", token: "tok" });
  });

  it("returns null when nothing stored", () => {
    expect(loadSession()).toBeNull();
  });

  it("migrates the legacy treachery.session key", () => {
    localStorage.setItem("treachery.session", JSON.stringify({ code: "OLDRM", token: "t" }));
    expect(loadSession()).toEqual({ code: "OLDRM", token: "t" });
    expect(localStorage.getItem("treachery.session")).toBeNull();
    expect(localStorage.getItem("table.session")).not.toBeNull();
  });

  it("does not let the legacy key override a current session", () => {
    saveSession({ code: "NEWRM", token: "new" });
    localStorage.setItem("treachery.session", JSON.stringify({ code: "OLDRM", token: "old" }));
    expect(loadSession()).toEqual({ code: "NEWRM", token: "new" });
  });

  it("clearSession removes BOTH keys (regression: leave must not resurrect old game)", () => {
    saveSession({ code: "NEWRM", token: "new" });
    localStorage.setItem("treachery.session", JSON.stringify({ code: "OLDRM", token: "old" }));
    clearSession();
    expect(loadSession()).toBeNull();
    expect(localStorage.getItem("treachery.session")).toBeNull();
  });

  it("survives corrupt stored JSON", () => {
    localStorage.setItem("table.session", "{not json");
    expect(loadSession()).toBeNull();
  });
});

describe("landingAction (QR scans)", () => {
  const session = { code: "OLDRM", token: "t" };

  it("no session, no join link -> none", () => {
    expect(landingAction(null, null)).toBe("none");
  });

  it("scanning a QR with no session -> autojoin immediately", () => {
    expect(landingAction(null, "NEWRM")).toBe("autojoin");
  });

  it("session without a join param -> resume old room", () => {
    expect(landingAction(session, null)).toBe("resume");
  });

  it("QR for the SAME room -> resume, not rejoin", () => {
    expect(landingAction(session, "OLDRM")).toBe("resume");
    expect(landingAction(session, "oldrm")).toBe("resume");
  });

  it("QR for a DIFFERENT room -> autojoin (regression: must not bounce back to old game)", () => {
    expect(landingAction(session, "NEWRM")).toBe("autojoin");
  });
});

describe("when the browser refuses storage", () => {
  const deny = () => {
    throw new DOMException("denied");
  };

  it("holds the session in memory so the player can still play", async () => {
    const { saveSession, loadSession } = await import("./session");
    vi.stubGlobal("localStorage", {
      getItem: deny,
      setItem: deny,
      removeItem: deny,
      clear: deny,
    });
    saveSession({ code: "ABCDE", token: "tok" });
    expect(loadSession()).toEqual({ code: "ABCDE", token: "tok" });
    vi.unstubAllGlobals();
  });

  it("does not resurrect a session that working storage says is gone", async () => {
    // this project shipped exactly that bug once: leaving a game didn't stick
    // because a stale copy was read back afterwards
    const { saveSession, clearSession, loadSession } = await import("./session");
    saveSession({ code: "ABCDE", token: "tok" });
    clearSession();
    expect(loadSession()).toBeNull();
  });

  it("treats storage cleared behind our back as no session", async () => {
    const { saveSession, loadSession } = await import("./session");
    saveSession({ code: "ABCDE", token: "tok" });
    localStorage.clear();
    expect(loadSession()).toBeNull();
  });
});
