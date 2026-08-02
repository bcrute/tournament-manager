import { useState } from "react";
import Icon from "../Icon";
import { Account, AccountError, forgotPassword, getAccount, login, signup } from "./api";
import { looksLikeEmail, suggestUsername } from "../username";

/**
 * Sign-in, used in two places that mean different things.
 *
 * For players an account is genuinely optional — everything works signed out —
 * but "accounts are optional" flat is wrong, because hosting a tournament
 * requires one. The player copy says *playing* never needs an account and
 * names the exception; the organizer copy drops the optional framing entirely,
 * since they are one step from being required to have one.
 *
 * Creating an account is a username and a password. A recovery email is not
 * collected here: it is account state a reset would be sent to, and taking it
 * at the one moment nobody can prove they own it had an unverified string
 * doing a credential's job. It is enrolled and confirmed from account settings.
 */
export default function SignIn({
  onDone,
  onCancel,
  purpose = "optional",
  cancelLabel = "Not now",
}: {
  onDone: (a: Account) => void;
  onCancel: () => void;
  /** "optional" — a player choosing to have one. "required" — hosting. */
  purpose?: "optional" | "required";
  cancelLabel?: string;
}) {
  const optional = purpose === "optional";
  const [mode, setMode] = useState<"login" | "signup">("login");
  // Blank, always. This used to seed itself from the name you last used at a
  // table, which quietly proposed a *table* name as an *account* name — two
  // separate things, and the table one is a spaced, capitalised label like
  // "Grumpy Platypus 42" that isn't even a legal username. Password managers
  // fill this through `autocomplete`; the app itself proposes nothing.
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [codes, setCodes] = useState<string[] | null>(null);
  const [emailWarning, setEmailWarning] = useState(false);
  const [forgot, setForgot] = useState(false);
  const [forgotSaid, setForgotSaid] = useState<string | null>(null);
  // generated lazily so the same suggestion persists while the notice is up,
  // rather than shuffling under the user's finger on every keystroke
  const [suggestion, setSuggestion] = useState<string | null>(null);

  async function go() {
    setBusy(true);
    setError(null);
    try {
      if (mode === "signup") {
        const res = await signup(username.trim(), password);
        setCodes(res.recoveryCodes); // shown once, then never again
        return;
      }
      const res = await login(username.trim(), password);
      onDone(res.account);
    } catch (e) {
      setError(e instanceof AccountError ? e.message : "Something went wrong");
    } finally {
      setBusy(false);
    }
  }

  async function askForReset() {
    setBusy(true);
    setError(null);
    try {
      const r = await forgotPassword(username.trim());
      // Whatever the server says, it says the same thing every time: whether
      // the account exists, whether it has an address, and whether that
      // address is confirmed are all things this screen must not reveal. So
      // the copy comes from the server rather than being assembled here out of
      // things this client might think it knows.
      setForgotSaid(r.message);
    } catch (e) {
      setError(e instanceof AccountError ? e.message : "Something went wrong");
    } finally {
      setBusy(false);
    }
  }

  if (forgot) {
    return (
      <div className="sheet">
        <button
          className="sheet-back"
          onClick={() => {
            setForgot(false);
            setForgotSaid(null);
          }}
          aria-label="Back to sign in"
        >
          <Icon name="back" /> Back to sign in
        </button>
        <h2>Forgotten password</h2>
        {forgotSaid ? (
          <>
            <p className="notice">{forgotSaid}</p>
            <p className="hint">
              No email? Your recovery codes still work — sign in with one from the
              account recovery screen.
            </p>
          </>
        ) : (
          <>
            <p className="hint">
              If your account has a confirmed recovery address, we'll send a link to
              it. Otherwise your recovery codes are the way back in.
            </p>
            <input
              type="text"
              placeholder="Username"
              autoCapitalize="none"
              autoComplete="username"
              value={username}
              onChange={(e) => setUsername(e.target.value)}
            />
            {error && <p className="error">{error}</p>}
            <button
              className="primary"
              disabled={busy || !username.trim()}
              onClick={() => void askForReset()}
            >
              {busy ? "…" : "Send a reset link"}
            </button>
          </>
        )}
      </div>
    );
  }

  if (codes) {
    return (
      <div className="sheet">
        {/* deliberately no way back: the account already exists and these codes
            are shown once. The only exit is acknowledging them. */}
        <h2>Save your recovery codes</h2>
        <p className="hint">
          <strong>These are the only way back into your account.</strong> Each code works
          once. Screenshot them or write them down now — they are never shown again.
        </p>
        <ul className="codes">
          {codes.map((c) => (
            <li key={c}>{c}</li>
          ))}
        </ul>
        <button
          className="primary"
          onClick={() => {
            void navigator.clipboard?.writeText(codes.join("\n")).catch(() => {});
          }}
        >
          Copy codes
        </button>
        <button
          className="ghost"
          onClick={() => void getAccountThen(onDone)}
        >
          I&rsquo;ve saved them — continue
        </button>
      </div>
    );
  }

  return (
    <div className="sheet">
      <button className="sheet-back" onClick={onCancel} aria-label={cancelLabel}>
        <Icon name="back" /> {cancelLabel}
      </button>
      <h2>{mode === "login" ? "Sign in" : "Create an account"}</h2>
      {optional && (
        <p className="notice">
          <strong>Playing never needs an account.</strong> An account keeps your game
          history and private notes. Tournament organizers need one.
        </p>
      )}
      <div className="tr-mode">
        <button className={mode === "login" ? "active" : ""} onClick={() => setMode("login")}>
          Sign in
        </button>
        <button className={mode === "signup" ? "active" : ""} onClick={() => setMode("signup")}>
          Sign up
        </button>
      </div>
      <input
        type="text"
        placeholder="Username"
        autoCapitalize="none"
        autoComplete="username"
        value={username}
        onChange={(e) => {
          setUsername(e.target.value);
          const looksEmail = looksLikeEmail(e.target.value);
          setEmailWarning(looksEmail);
          if (looksEmail && !suggestion) setSuggestion(suggestUsername());
        }}
      />
      {/* Only while creating an account. On the sign-in tab the username is
          whatever they already chose, and second-guessing it there is noise in
          front of someone who just wants to get back in. */}
      {emailWarning && mode === "signup" && (
        <div className="notice warn">
          <p>
            Using an email address as your username works, but usernames must be looked
            up when you sign in and should not be treated as private recovery
            information. We recommend using a different username.
          </p>
          {suggestion && (
            <p className="suggest-row">
              <button
                type="button"
                className="suggest"
                onClick={() => {
                  setUsername(suggestion);
                  setEmailWarning(false);
                }}
              >
                Use <strong>{suggestion}</strong>
              </button>
              <button
                type="button"
                className="link"
                onClick={() => setSuggestion(suggestUsername())}
              >
                another
              </button>
            </p>
          )}
        </div>
      )}
      <input
        type="password"
        placeholder="Password"
        autoComplete={mode === "login" ? "current-password" : "new-password"}
        value={password}
        onChange={(e) => setPassword(e.target.value)}
      />
      {error && <p className="error">{error}</p>}
      <button className="primary" disabled={busy || !username.trim() || password.length < 8} onClick={() => void go()}>
        {busy ? "…" : mode === "login" ? "Sign in" : "Create account"}
      </button>
      {/* Only on the sign-in tab: somebody creating an account has no password
          to have forgotten. */}
      {mode === "login" && (
        <button type="button" className="link forgot" onClick={() => setForgot(true)}>
          Forgotten your password?
        </button>
      )}
    </div>
  );
}

async function getAccountThen(onDone: (a: Account) => void) {
  // signup returns the codes, not the account, so this re-reads /me to hand
  // the caller the same shape a login would
  const res = await getAccount();
  if (res.account) onDone(res.account);
}
