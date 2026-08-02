import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import SignIn from "./SignIn";

/**
 * An account username and the name you use at a table are different things.
 *
 * This field used to initialise itself from `table.name`, so someone who had
 * played a game arrived at the sign-in form with "Grumpy Platypus 42" already
 * typed into the username box — a spaced, capitalised label that isn't even a
 * legal username, proposed as their account name. Worse on the sign-in tab,
 * where it looks like a remembered credential and isn't one.
 *
 * The app proposes nothing here now. A password manager filling it through
 * `autocomplete` is a different matter and is left alone.
 */
describe("SignIn does not borrow the table name", () => {
  beforeEach(() => {
    localStorage.clear();
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: true,
        status: 200,
        statusText: "OK",
        json: () => Promise.resolve({ account: null }),
      }),
    );
  });

  afterEach(() => {
    cleanup();
    localStorage.clear();
    vi.unstubAllGlobals();
  });

  const noop = () => {};
  const usernameBox = () =>
    screen.getByPlaceholderText(/^username$/i) as HTMLInputElement;

  it("opens blank even when a table name is remembered", () => {
    localStorage.setItem("table.name", "Grumpy Platypus 42");
    render(<SignIn onDone={noop} onCancel={noop} />);
    expect(usernameBox().value).toBe("");
  });

  it("stays blank on the sign-up tab too", () => {
    localStorage.setItem("table.name", "Sneaky Wombat 11");
    render(<SignIn onDone={noop} onCancel={noop} />);
    fireEvent.click(screen.getByRole("button", { name: /^sign up$/i }));
    expect(usernameBox().value).toBe("");
  });

  it("ignores the pre-rename key as well", () => {
    // `treachery.name` is migrated from, and was never an account name either
    localStorage.setItem("treachery.name", "Jaunty Narwhal 7");
    render(<SignIn onDone={noop} onCancel={noop} />);
    expect(usernameBox().value).toBe("");
  });

  it("keeps the autocomplete hints, which are the browser's job not ours", () => {
    render(<SignIn onDone={noop} onCancel={noop} />);
    expect(usernameBox().getAttribute("autocomplete")).toBe("username");
  });
});
