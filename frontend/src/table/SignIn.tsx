import { useState } from "react";
import Icon from "../Icon";
import { Account, AccountError, login, signup } from "./account";
import { looksLikeEmail, suggestUsername } from "../username";
import { getItem } from "../storage";

/**
 * Sign-in, used in two places that mean different things.
 *
 * For players an account is genuinely optional — everything works signed out —
 * but "accounts are optional" flat is wrong, because hosting a tournament
 * requires one. The player copy says *playing* never needs an account and
 * names the exception; the organizer copy drops the optional framing entirely,
 * since they are one step from being required to have both an account and a
 * recovery email.
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
  const [username, setUsername] = useState(getItem("table.name") ?? "");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [codes, setCodes] = useState<string[] | null>(null);
  const [emailWarning, setEmailWarning] = useState(false);
  // generated lazily so the same suggestion persists while the notice is up,
  // rather than shuffling under the user's finger on every keystroke
  const [suggestion, setSuggestion] = useState<string | null>(null);
  const [email, setEmail] = useState("");
  // only offer to reuse what they typed once; after they touch the field it is
  // theirs, and re-filling it would fight them
  const [emailTouched, setEmailTouched] = useState(false);

  async function go() {
    setBusy(true);
    setError(null);
    try {
      if (mode === "signup") {
        const res = await signup(username.trim(), password, email.trim() || undefined);
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

  if (codes) {
    return (
      <div className="sheet">
        {/* deliberately no way back: the account already exists and these codes
            are shown once. The only exit is acknowledging them. */}
        <h2>Save your recovery codes</h2>
        <p className="hint">
          <strong>These are the only way back into your account.</strong> Each code works
          once. Screenshot them or write them down now — they are never shown again, and
          an email on file does not replace them.
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
          <strong>Playing never needs an account.</strong> One only keeps your game
          history and private notes, and signing up is a username and a password —
          an email is optional, used for nothing but account recovery.{" "}
          <em>Hosting</em> a tournament is the one exception: organizers need a way
          back into their event.
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
          // hand what they typed to the field it actually belongs in
          if (looksEmail && !emailTouched) setEmail(e.target.value.trim());
        }}
      />
      {emailWarning && (
        <div className="notice warn">
          <p>
            <strong>Using your email as a username works, but we&rsquo;d suggest not
            to.</strong> A username is looked up every time you sign in, so it can&rsquo;t
            be stored encrypted — the optional email field below can be treated as
            private in a way a username can&rsquo;t. We&rsquo;ve copied your address there
            for you. You can absolutely carry on with it as your username if you prefer.
          </p>
          {mode === "signup" && suggestion && (
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
      {mode === "signup" && (
        <>
          <input
            type="email"
            placeholder="Email (optional)"
            autoComplete="email"
            value={email}
            onChange={(e) => {
              setEmail(e.target.value);
              setEmailTouched(true);
            }}
          />
          <p className="hint">
            <strong>Email is optional.</strong> It stays private, is never shown to
            anyone, and is only ever used to help you back into your account.{" "}
            <strong>
              Either way, save the recovery codes on the next screen — right now they are
              the only way back in if you forget your password.
            </strong>
          </p>
        </>
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
    </div>
  );
}

async function getAccountThen(onDone: (a: Account) => void) {
  const { getAccount } = await import("./account");
  const res = await getAccount();
  if (res.account) onDone(res.account);
}
