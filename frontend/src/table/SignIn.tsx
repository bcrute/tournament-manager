import { useState } from "react";
import { Account, AccountError, login, signup } from "./account";

/**
 * Optional sign-in. No email is asked for anywhere; recovery codes are shown
 * once on signup and are the whole recovery story unless the user later adds
 * an address themselves.
 */
export default function SignIn({
  onDone,
  onCancel,
}: {
  onDone: (a: Account) => void;
  onCancel: () => void;
}) {
  const [mode, setMode] = useState<"login" | "signup">("login");
  const [username, setUsername] = useState(localStorage.getItem("table.name") ?? "");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [codes, setCodes] = useState<string[] | null>(null);

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
          Because we don&rsquo;t ask for an email, these codes are how you get back in if
          you forget your password. Each one works once. Screenshot or write them down
          now — they aren&rsquo;t shown again. (You can add an email later as a second
          route back in, but it&rsquo;s optional.)
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
      <p className="notice">
        <strong>Accounts are completely optional.</strong> Everything in the app works
        signed out — an account only keeps a history of your games and your private notes.
      </p>
      <p className="hint">
        <strong>No email required.</strong> Sign up with just a username and a password.
        You can add an email later if you want, and it is used for one thing only:
        recovering your account. It is never required, never shown to anyone, and never
        used to contact you.
      </p>
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
        onChange={(e) => setUsername(e.target.value)}
      />
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
        Not now
      </button>
    </div>
  );
}

async function getAccountThen(onDone: (a: Account) => void) {
  const { getAccount } = await import("./account");
  const res = await getAccount();
  if (res.account) onDone(res.account);
}
