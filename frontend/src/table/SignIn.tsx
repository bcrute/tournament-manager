import { useState } from "react";
import { Account, AccountError, login, signup } from "./account";

/**
 * Sign-in, used in two places that mean different things.
 *
 * For players an account is genuinely optional, and the copy says so loudly —
 * everything works signed out. For organizers it isn't: hosting needs an
 * account with a recovery email, so telling them accounts are optional is at
 * best noise and at worst a lie about what they're about to do.
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
  const [username, setUsername] = useState(localStorage.getItem("table.name") ?? "");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [codes, setCodes] = useState<string[] | null>(null);
  const [emailWarning, setEmailWarning] = useState(false);

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

  if (codes) {
    return (
      <div className="sheet">
        <h2>Save your recovery codes</h2>
        <p className="hint">
          {optional
            ? "These codes are how you get back in if you forget your password, because we don’t ask for an email. Each one works once. Screenshot or write them down now — they aren’t shown again."
            : "Each code works once and gets you back in if you forget your password. Screenshot or write them down now — they aren’t shown again. You’ll add a recovery email next, but keep these too."}
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
      <h2>{mode === "login" ? "Sign in" : "Create an account"}</h2>
      {optional && (
        <>
          <p className="notice">
            <strong>Accounts are completely optional.</strong> Everything in the app works
            signed out — an account only keeps a history of your games and your private
            notes.
          </p>
          <p className="hint">
            <strong>No email required.</strong> Sign up with just a username and a
            password. You can add an email later if you want, and it is used for one thing
            only: recovering your account. It is never required, never shown to anyone,
            and never used to contact you.
          </p>
        </>
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
          setEmailWarning(e.target.value.includes("@"));
        }}
      />
      {emailWarning && (
        <p className="notice warn">
          We discourage using an email address as a username — usernames are shown to other
          players and can&rsquo;t be stored encrypted, because we have to look them up on
          every sign-in. You can add an email privately in your account settings after
          logging in if you want one for recovery. You&rsquo;re free to continue either way.
        </p>
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
      <button className="ghost" onClick={onCancel}>
        {cancelLabel}
      </button>
    </div>
  );
}

async function getAccountThen(onDone: (a: Account) => void) {
  const { getAccount } = await import("./account");
  const res = await getAccount();
  if (res.account) onDone(res.account);
}
