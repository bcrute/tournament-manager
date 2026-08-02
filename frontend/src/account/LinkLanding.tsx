import { useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import Icon from "../Icon";
import { Account, AccountError, resetPassword, verifyEmail } from "./api";
import { publishAccount } from "./useAccount";

/**
 * Where a link in an email lands: confirming an address, or choosing a new
 * password after forgetting one.
 *
 * The token arrives in the **fragment** (`/account/reset#<token>`), not the
 * query string, for the same reason a room invitation does — a fragment is
 * never transmitted to a server, so a credential in an emailed link cannot end
 * up in an access log, ours or a corporate mail gateway's link-rewriter. The
 * first thing this does is take the token out of the address bar with
 * `replaceState`, so it does not survive in history or in a screenshot of the
 * tab either.
 */
function takeToken(): string {
  const hash = window.location.hash;
  if (!hash || hash.length < 2) return "";
  const token = decodeURIComponent(hash.slice(1));
  window.history.replaceState(null, "", window.location.pathname);
  return token;
}

export default function LinkLanding({ purpose }: { purpose: "verify" | "reset" }) {
  // Read on mount, before anything can navigate and lose it.
  const [token, setToken] = useState(takeToken);
  // Bumped on every arrival, and part of the child's key. The token alone is
  // not enough: clicking the *same* link twice leaves it unchanged, so nothing
  // would re-render and the page would keep showing the first attempt's result
  // rather than telling the user the link is spent.
  const [arrival, setArrival] = useState(0);

  // A second link arriving at a tab that is already here. The address bar is
  // wiped on arrival, so clicking another link for the same page differs only
  // by fragment — which the browser treats as a same-document navigation, and
  // this component never remounts. The table's invitation handling had exactly
  // this bug; without the listener the page would sit there showing the result
  // of the *previous* link.
  useEffect(() => {
    const onHash = () => {
      const next = takeToken();
      if (!next) return;
      setToken(next);
      setArrival((n) => n + 1);
    };
    window.addEventListener("hashchange", onHash);
    return () => window.removeEventListener("hashchange", onHash);
  }, []);

  const key = `${arrival}:${token}`;
  return purpose === "verify" ? (
    <Verify key={key} token={token} />
  ) : (
    <Reset key={key} token={token} />
  );
}

function Shell({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="acct">
      <div className="acct-card">
        <h2>{title}</h2>
        {children}
      </div>
    </div>
  );
}

/** Every failure reads the same, deliberately: expired, already used, and
 *  never-existed are one message on the server too, so that somebody holding a
 *  stolen token learns nothing about which of their guesses was once real. */
const DEAD_LINK = "That link is no longer valid — ask for a new one from your account settings.";

function Verify({ token }: { token: string }) {
  const [state, setState] = useState<"working" | "done" | "failed">("working");
  const [error, setError] = useState(DEAD_LINK);

  useEffect(() => {
    if (!token) {
      setState("failed");
      return;
    }
    let live = true;
    void verifyEmail(token)
      .then((r) => {
        if (!live) return;
        // The account object in memory is stale the moment this succeeds, and
        // the thing it is stale about is whether you may host a tournament.
        publishAccount({
          username: r.username,
          displayName: r.displayName,
          hasEmail: r.hasEmail,
          emailPending: r.emailPending,
          mailConfigured: r.mailConfigured,
          createdAt: r.createdAt,
        } as Account);
        setState("done");
      })
      .catch((e: unknown) => {
        if (!live) return;
        setError(e instanceof AccountError ? e.message : DEAD_LINK);
        setState("failed");
      });
    return () => {
      live = false;
    };
  }, [token]);

  if (state === "working") {
    return (
      <Shell title="Confirming your address">
        <p className="hint">One moment…</p>
      </Shell>
    );
  }
  if (state === "failed") {
    return (
      <Shell title="That didn't work">
        <p className="error">{error}</p>
        <Link className="primary" to="/account/settings">
          Account settings
        </Link>
      </Shell>
    );
  }
  return (
    <Shell title="Address confirmed">
      <p className="acct-done">
        <Icon name="check" /> Your recovery address is confirmed. You can reset your
        password with it, and you can host a tournament.
      </p>
      <Link className="primary" to="/account">
        Your account
      </Link>
    </Shell>
  );
}

function Reset({ token }: { token: string }) {
  const navigate = useNavigate();
  const [password, setPassword] = useState("");
  const [again, setAgain] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(token ? null : DEAD_LINK);

  // Checked here as well as on the server: burning the one link they have on a
  // typo is a bad way to find out the two boxes disagreed.
  const tooShort = password.length > 0 && password.length < 8;
  const mismatch = again.length > 0 && again !== password;
  const ready = !!token && password.length >= 8 && again === password && !busy;

  async function go() {
    setBusy(true);
    setError(null);
    try {
      const r = await resetPassword(token, password);
      publishAccount(r.account);
      navigate("/account");
    } catch (e) {
      setError(e instanceof AccountError ? e.message : DEAD_LINK);
    } finally {
      setBusy(false);
    }
  }

  return (
    <Shell title="Choose a new password">
      <p className="hint">
        This signs you in and signs out every other device — which is usually the
        reason someone is here.
      </p>
      <label className="acct-label" htmlFor="new-password">
        New password
      </label>
      <input
        id="new-password"
        className="acct-input"
        type="password"
        autoComplete="new-password"
        value={password}
        onChange={(e) => setPassword(e.target.value)}
      />
      <label className="acct-label" htmlFor="new-password-again">
        And again
      </label>
      <input
        id="new-password-again"
        className="acct-input"
        type="password"
        autoComplete="new-password"
        value={again}
        onChange={(e) => setAgain(e.target.value)}
      />
      {tooShort && <p className="hint">At least 8 characters.</p>}
      {mismatch && <p className="hint">Those two don't match.</p>}
      {error && <p className="error">{error}</p>}
      <button className="primary" disabled={!ready} onClick={() => void go()}>
        {busy ? "…" : "Set new password"}
      </button>
    </Shell>
  );
}
