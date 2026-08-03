import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import LinkLanding from "./LinkLanding";

/**
 * Where an emailed link lands.
 *
 * The token is a credential — a reset token *is* a password — so the shape of
 * the link matters as much as what the page does with it. It arrives in the
 * fragment, which browsers never transmit, and the first thing this page does
 * is take it out of the address bar so it does not survive in history or in a
 * screenshot of the tab.
 */

function mockFetch(body: unknown, status = 200) {
  const fn = vi.fn().mockResolvedValue({
    ok: status < 400,
    status,
    statusText: "Mocked",
    headers: new Headers(),
    json: () => Promise.resolve(body),
  });
  vi.stubGlobal("fetch", fn);
  return fn;
}

const ACCOUNT = {
  ok: true,
  username: "ada",
  displayName: null,
  hasEmail: true,
  emailPending: false,
  mailConfigured: true,
  createdAt: 1,
};

/** Put a token in the address bar the way an emailed link would. */
function arriveWith(path: string, token: string) {
  window.history.replaceState(null, "", `${path}#${token}`);
}

const draw = (purpose: "verify" | "reset") =>
  render(
    <MemoryRouter>
      <LinkLanding purpose={purpose} />
    </MemoryRouter>,
  );

describe("arriving from a link", () => {
  beforeEach(() => {
    mockFetch(ACCOUNT);
  });

  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
    window.history.replaceState(null, "", "/");
  });

  it("takes the token out of the address bar immediately", () => {
    arriveWith("/account/verify", "a-secret-token");
    draw("verify");
    // history, back button, screenshots, a bookmark — none of them keep it
    expect(window.location.hash).toBe("");
    expect(window.location.href).not.toContain("a-secret-token");
  });

  it("reads a token that was percent-encoded on the way through a mail client", () => {
    const fn = mockFetch(ACCOUNT);
    arriveWith("/account/verify", encodeURIComponent("tok+en/with=chars"));
    draw("verify");
    return waitFor(() => {
      const [, opts] = fn.mock.calls.at(-1) as [string, RequestInit];
      expect(JSON.parse(opts.body as string).token).toBe("tok+en/with=chars");
    });
  });

  it("does not put the token in a query string of its own", async () => {
    const fn = mockFetch(ACCOUNT);
    arriveWith("/account/verify", "a-secret-token");
    draw("verify");
    await waitFor(() => expect(fn).toHaveBeenCalled());
    const [url] = fn.mock.calls.at(-1) as [string, RequestInit];
    expect(url).toBe("/api/account/email/verify");
    expect(url).not.toContain("a-secret-token");
  });
});

describe("confirming an address", () => {
  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
    window.history.replaceState(null, "", "/");
  });

  it("confirms it and says what that unlocked", async () => {
    mockFetch(ACCOUNT);
    arriveWith("/account/verify", "good-token");
    draw("verify");
    await waitFor(() =>
      expect(screen.getByRole("heading", { name: /address confirmed/i })).toBeTruthy(),
    );
    // the two things confirmation is *for*
    expect(screen.getByText(/host a tournament/i)).toBeTruthy();
  });

  it("shows the server's refusal for a dead link", async () => {
    mockFetch({ detail: "that link is no longer valid — ask for a new one" }, 400);
    arriveWith("/account/verify", "stale-token");
    draw("verify");
    await waitFor(() => expect(screen.getByText(/no longer valid/i)).toBeTruthy());
  });

  it("does not call the server at all with no token", async () => {
    const fn = mockFetch(ACCOUNT);
    window.history.replaceState(null, "", "/account/verify");
    draw("verify");
    await waitFor(() => expect(screen.getByText(/didn't work/i)).toBeTruthy());
    expect(fn).not.toHaveBeenCalled();
  });
});

describe("choosing a new password", () => {
  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
    window.history.replaceState(null, "", "/");
  });

  const fill = (label: RegExp, value: string) =>
    fireEvent.change(screen.getByLabelText(label), { target: { value } });

  it("will not submit until the two boxes agree", () => {
    mockFetch({ account: ACCOUNT });
    arriveWith("/account/reset", "good-token");
    draw("reset");
    const submit = screen.getByRole("button", { name: /set new password/i }) as HTMLButtonElement;
    expect(submit.disabled).toBe(true);

    fill(/new password/i, "a whole new one");
    expect(submit.disabled).toBe(true); // second box still empty
    fill(/and again/i, "a whole different one");
    expect(submit.disabled).toBe(true);
    fill(/and again/i, "a whole new one");
    expect(submit.disabled).toBe(false);
  });

  it("will not submit a password the server would reject", () => {
    // burning the one link they have on a too-short password is a bad way to
    // find out it was too short
    mockFetch({ account: ACCOUNT });
    arriveWith("/account/reset", "good-token");
    draw("reset");
    fill(/new password/i, "short");
    fill(/and again/i, "short");
    expect(
      (screen.getByRole("button", { name: /set new password/i }) as HTMLButtonElement).disabled,
    ).toBe(true);
    expect(screen.getByText(/at least 8 characters/i)).toBeTruthy();
  });

  it("sends the token and the new password together", async () => {
    const fn = mockFetch({ account: ACCOUNT });
    arriveWith("/account/reset", "good-token");
    draw("reset");
    fill(/new password/i, "a whole new one");
    fill(/and again/i, "a whole new one");
    fireEvent.click(screen.getByRole("button", { name: /set new password/i }));
    await waitFor(() => expect(fn).toHaveBeenCalled());
    const [url, opts] = fn.mock.calls.at(-1) as [string, RequestInit];
    expect(url).toBe("/api/account/reset");
    expect(JSON.parse(opts.body as string)).toEqual({
      token: "good-token",
      password: "a whole new one",
    });
  });

  it("warns that every other device is signed out", () => {
    mockFetch({ account: ACCOUNT });
    arriveWith("/account/reset", "good-token");
    draw("reset");
    expect(screen.getByText(/signs out every other device/i)).toBeTruthy();
  });

  it("surfaces a refused token instead of pretending it worked", async () => {
    mockFetch({ detail: "that link is no longer valid — ask for a new one" }, 400);
    arriveWith("/account/reset", "stale-token");
    draw("reset");
    fill(/new password/i, "a whole new one");
    fill(/and again/i, "a whole new one");
    fireEvent.click(screen.getByRole("button", { name: /set new password/i }));
    await waitFor(() => expect(screen.getByText(/no longer valid/i)).toBeTruthy());
  });

  it("refuses to submit with no token at all", () => {
    mockFetch({ account: ACCOUNT });
    window.history.replaceState(null, "", "/account/reset");
    draw("reset");
    fill(/new password/i, "a whole new one");
    fill(/and again/i, "a whole new one");
    expect(
      (screen.getByRole("button", { name: /set new password/i }) as HTMLButtonElement).disabled,
    ).toBe(true);
  });
});
