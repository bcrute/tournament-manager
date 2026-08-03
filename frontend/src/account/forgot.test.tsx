import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import SignIn from "./SignIn";

/**
 * The way back in for someone who cannot get in.
 *
 * The one property worth defending here is that this screen reveals nothing.
 * Whether the account exists, whether it has a recovery address, and whether
 * that address was ever confirmed are all answered identically by the server —
 * so the client must not undo that by assembling its own copy out of things it
 * thinks it knows.
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

const BLIND = "If that account exists and has a confirmed recovery address, a reset link is on its way.";

describe("forgotten password", () => {
  beforeEach(() => {
    localStorage.clear();
    mockFetch({ ok: true, message: BLIND });
  });

  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
  });

  const noop = () => {};
  const open = () => {
    render(<SignIn onDone={noop} onCancel={noop} />);
    fireEvent.click(screen.getByRole("button", { name: /forgotten your password/i }));
  };

  it("is offered on the sign-in tab", () => {
    render(<SignIn onDone={noop} onCancel={noop} />);
    expect(screen.getByRole("button", { name: /forgotten your password/i })).toBeTruthy();
  });

  it("is not offered while creating an account", () => {
    // there is no password yet to have forgotten
    render(<SignIn onDone={noop} onCancel={noop} />);
    fireEvent.click(screen.getByRole("button", { name: /^sign up$/i }));
    expect(screen.queryByRole("button", { name: /forgotten your password/i })).toBeNull();
  });

  it("asks for a username and nothing else", () => {
    open();
    expect(screen.getByPlaceholderText(/^username$/i)).toBeTruthy();
    // notably not an email box: the address is not something this screen knows
    expect(screen.queryByPlaceholderText(/you@example.com/i)).toBeNull();
  });

  it("sends the username to /forgot", async () => {
    const fn = mockFetch({ ok: true, message: BLIND });
    open();
    fireEvent.change(screen.getByPlaceholderText(/^username$/i), {
      target: { value: "ada" },
    });
    fireEvent.click(screen.getByRole("button", { name: /send a reset link/i }));
    await waitFor(() => expect(fn).toHaveBeenCalled());
    const [url, opts] = fn.mock.calls.at(-1) as [string, RequestInit];
    expect(url).toBe("/api/account/forgot");
    expect(JSON.parse(opts.body as string)).toEqual({ username: "ada" });
  });

  it("shows the server's sentence rather than one of its own", async () => {
    open();
    fireEvent.change(screen.getByPlaceholderText(/^username$/i), {
      target: { value: "ada" },
    });
    fireEvent.click(screen.getByRole("button", { name: /send a reset link/i }));
    // A client that said "check your inbox" would be claiming the account
    // exists — the exact thing the endpoint refuses to say.
    await waitFor(() => expect(screen.getByText(BLIND)).toBeTruthy());
  });

  it("says the same thing for a name that does not exist", async () => {
    // there is no other thing to say: the response is identical either way
    open();
    fireEvent.change(screen.getByPlaceholderText(/^username$/i), {
      target: { value: "nobody-at-all" },
    });
    fireEvent.click(screen.getByRole("button", { name: /send a reset link/i }));
    await waitFor(() => expect(screen.getByText(BLIND)).toBeTruthy());
  });

  it("points at the recovery codes, which work without any address", async () => {
    open();
    fireEvent.change(screen.getByPlaceholderText(/^username$/i), {
      target: { value: "ada" },
    });
    fireEvent.click(screen.getByRole("button", { name: /send a reset link/i }));
    await waitFor(() => expect(screen.getByText(/recovery codes still work/i)).toBeTruthy());
  });

  it("can be backed out of", () => {
    open();
    fireEvent.click(screen.getByRole("button", { name: /back to sign in/i }));
    // back on the sign-in form: two "Sign in" buttons, the tab and the submit
    expect(screen.getAllByRole("button", { name: /^sign in$/i }).length).toBe(2);
    expect(screen.getByRole("button", { name: /forgotten your password/i })).toBeTruthy();
  });
});
