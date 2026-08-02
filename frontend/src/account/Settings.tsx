import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import Icon from "../Icon";
import { setItem } from "../storage";
import { suggestTableName } from "../username";
import {
  Account,
  AccountError,
  changePassword,
  changeUsername,
  deleteAccount,
  logout,
  regenerateRecoveryCodes,
  removeEmail,
  resendVerification,
  setDisplayName,
  setEmail,
} from "./api";
import { publishAccount } from "./useAccount";

/** Errors and confirmations are per-card: one shared banner at the top of a
 *  page this long is out of sight by the time it matters. */
function useCardState() {
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function run(action: () => Promise<string>) {
    setBusy(true);
    setError(null);
    setDone(null);
    try {
      setDone(await action());
    } catch (e) {
      setError(e instanceof AccountError ? e.message : "Something went wrong");
    } finally {
      setBusy(false);
    }
  }

  const feedback = (
    <>
      {error && <p className="error">{error}</p>}
      {done && (
        <p className="acct-done">
          <Icon name="check" /> {done}
        </p>
      )}
    </>
  );

  return { busy, run, feedback };
}

/**
 * Account management.
 *
 * The two names are the thing this screen exists to keep apart. A **username**
 * is typed to sign in, so it is unique and changing it costs a password. A
 * **default table name** is read aloud by the other players, so it is
 * cosmetic, duplicable and free. Presenting them as one field — which is what
 * "change your name" would do — is how someone ends up unable to sign in
 * because they wanted to be called Grumpy Platypus at the table.
 */
export default function Settings({ account }: { account: Account }) {
  return (
    <>
      <UsernameCard account={account} />
      <DisplayNameCard account={account} />
      <EmailCard account={account} />
      <PasswordCard />
      <RecoveryCodesCard />
      <StoredCard />
      <DangerCard account={account} />
    </>
  );
}

function UsernameCard({ account }: { account: Account }) {
  const [name, setName] = useState(account.username);
  const [password, setPassword] = useState("");
  const { busy, run, feedback } = useCardState();

  return (
    <section className="acct-card">
      <h2>
        <Icon name="user" /> Username
      </h2>
      <p className="hint">
        What you type to sign in. It has to be unique, and it is the one thing you
        can&rsquo;t change back without knowing what you changed it to — so your password
        is required.
      </p>
      <label className="acct-label" htmlFor="username">
        Username
      </label>
      <input
        id="username"
        className="acct-input"
        type="text"
        autoCapitalize="none"
        autoComplete="username"
        value={name}
        onChange={(e) => setName(e.target.value)}
      />
      <label className="acct-label" htmlFor="username-password">
        Your current password
      </label>
      <input
        id="username-password"
        className="acct-input"
        type="password"
        autoComplete="current-password"
        value={password}
        onChange={(e) => setPassword(e.target.value)}
      />
      {feedback}
      <button
        className="primary"
        disabled={busy || !password || !name.trim() || name.trim() === account.username}
        onClick={() =>
          void run(async () => {
            const r = await changeUsername(name.trim(), password);
            publishAccount(r.account); // or the nav keeps showing the old name
            setPassword("");
            return `You now sign in as ${r.account.username}.`;
          })
        }
      >
        {busy ? "…" : "Change username"}
      </button>
    </section>
  );
}

function DisplayNameCard({ account }: { account: Account }) {
  const [name, setName] = useState(account.displayName ?? "");
  const { busy, run, feedback } = useCardState();

  return (
    <section className="acct-card">
      <h2>
        <Icon name="users" /> Default table name
      </h2>
      <p className="hint">
        The name filled in for you when you sit down at a table, on any device you sign
        in from. The other players see this one. It doesn&rsquo;t have to be unique — two
        Grumpy Platypuses at one table is a joke, not a problem, because seats are never
        identified by name. Leave it empty and each device keeps using its own last name.
      </p>
      <label className="acct-label" htmlFor="display-name">
        Table name
      </label>
      <div className="acct-row">
        <input
          id="display-name"
          className="acct-input"
          type="text"
          maxLength={24}
          placeholder="No preference"
          value={name}
          onChange={(e) => setName(e.target.value)}
        />
        <button className="ghost" type="button" onClick={() => setName(suggestTableName())}>
          <Icon name="dice" /> Suggest
        </button>
      </div>
      {feedback}
      <button
        className="primary"
        disabled={busy || name.trim() === (account.displayName ?? "")}
        onClick={() =>
          void run(async () => {
            const r = await setDisplayName(name.trim());
            publishAccount({ ...account, displayName: r.displayName });
            // keep this device's own prefill in step, so the next table join
            // agrees with what this page just said
            if (r.displayName) setItem("table.name", r.displayName);
            return r.displayName
              ? `You'll sit down as ${r.displayName}.`
              : "Cleared — each device will use its own name.";
          })
        }
      >
        {busy ? "…" : "Save table name"}
      </button>
    </section>
  );
}

function EmailCard({ account }: { account: Account }) {
  const [email, setEmailValue] = useState("");
  const [password, setPassword] = useState("");
  /* What the client itself just submitted. The server never returns the
     address — a deliberate boundary older than this feature — so the only way
     to tell someone which inbox to check is to remember what they typed. */
  const [sentTo, setSentTo] = useState<string | null>(null);
  const { busy, run, feedback } = useCardState();
  /** Saving nothing over an address on file deletes it — a different act from
   *  saving a new one, so it gets a different button. */
  const onFile = account.hasEmail || account.emailPending;
  const removing = onFile && !email.trim();

  if (!account.mailConfigured) {
    return (
      <section className="acct-card">
        <h2>
          <Icon name="note" /> Recovery email
        </h2>
        {/* Rather than a form that would 503. A settings control that cannot
            do what it says is worse than one that isn't there. */}
        <p className="hint">
          This server can't send email, so a recovery address can't be confirmed
          here. Your recovery codes are your way back in, and hosting a
          tournament isn't available until the server is configured to send mail.
        </p>
      </section>
    );
  }

  return (
    <section className="acct-card">
      <h2>
        <Icon name="note" /> Recovery email
      </h2>
      <p className="hint">
        Optional, and used for nothing else — never shown to anyone, never mailed
        anything but a recovery.{" "}
        {account.hasEmail
          ? "One is on file and confirmed. Saving an empty field removes it."
          : account.emailPending
            ? "One is on file but not confirmed yet, which counts as none until the link in it is used."
            : "None on file, so your recovery codes are your only way back in."}{" "}
        <strong>Hosting a tournament requires a confirmed one</strong>, because an
        organizer locked out mid-event strands everyone at the table.
      </p>

      {account.emailPending && (
        <p className="acct-pending">
          <Icon name="clock" /> Waiting for confirmation
          {sentTo ? ` — check ${sentTo}.` : " — check your inbox for the link."}{" "}
          <button
            className="link"
            disabled={busy}
            onClick={() =>
              void run(async () => {
                await resendVerification();
                return "Sent again. The previous link no longer works.";
              })
            }
          >
            Send it again
          </button>
        </p>
      )}

      <label className="acct-label" htmlFor="email">
        Email address
      </label>
      <input
        id="email"
        className="acct-input"
        type="email"
        autoComplete="email"
        placeholder={onFile ? "•••••••• (on file)" : "you@example.com"}
        value={email}
        onChange={(e) => setEmailValue(e.target.value)}
      />
      {/* Required for both adding and removing. The recovery address is what
          can hand this account to whoever holds it, so a session cookie alone
          must not be able to move it — same rule as the username. */}
      <label className="acct-label" htmlFor="email-password">
        Your password
      </label>
      <input
        id="email-password"
        className="acct-input"
        type="password"
        autoComplete="current-password"
        value={password}
        onChange={(e) => setPassword(e.target.value)}
      />
      {feedback}
      {/* An empty field means "remove", so the button has to say so. Leaving
          it reading "Update email" made an empty save look like a no-op and
          quietly delete the address hosting depends on. */}
      <button
        className={removing ? "ghost danger" : "primary"}
        disabled={busy || !password || (!email.trim() && !onFile)}
        onClick={() =>
          void run(async () => {
            const address = email.trim();
            const r = address ? await setEmail(address, password) : await removeEmail(password);
            publishAccount({
              ...account,
              hasEmail: r.hasEmail,
              emailPending: r.emailPending,
            });
            setEmailValue("");
            setPassword("");
            setSentTo(address || null);
            return address
              ? `Check ${address} for a confirmation link. Until it's used, this account still has no recovery address.`
              : "Recovery email removed. You can no longer host a tournament.";
          })
        }
      >
        {busy ? "…" : removing ? "Remove email" : onFile ? "Change email" : "Add email"}
      </button>
    </section>
  );
}

function PasswordCard() {
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const { busy, run, feedback } = useCardState();

  return (
    <section className="acct-card">
      <h2>
        <Icon name="shield" /> Password
      </h2>
      <p className="hint">
        Changing this ends every session on every device — <strong>including this
        one</strong>, so you will be asked to sign in again with the new password. That
        is the point: if you are changing it because someone else might know it, leaving
        any session alive would defeat the exercise. At least 8 characters.
      </p>
      <label className="acct-label" htmlFor="current-password">
        Current password
      </label>
      <input
        id="current-password"
        className="acct-input"
        type="password"
        autoComplete="current-password"
        value={current}
        onChange={(e) => setCurrent(e.target.value)}
      />
      <label className="acct-label" htmlFor="new-password">
        New password
      </label>
      <input
        id="new-password"
        className="acct-input"
        type="password"
        autoComplete="new-password"
        value={next}
        onChange={(e) => setNext(e.target.value)}
      />
      {feedback}
      <button
        className="primary"
        disabled={busy || !current || next.length < 8}
        onClick={() =>
          void run(async () => {
            await changePassword(current, next);
            setCurrent("");
            setNext("");
            // the session that made this request no longer exists, so leaving
            // the signed-in UI up would 401 on the user's next click
            publishAccount(null);
            return "Password changed. Sign in again with your new password.";
          })
        }
      >
        {busy ? "…" : "Change password"}
      </button>
    </section>
  );
}

function RecoveryCodesCard() {
  const [codes, setCodes] = useState<string[] | null>(null);
  const { busy, run, feedback } = useCardState();

  return (
    <section className="acct-card">
      <h2>
        <Icon name="book" /> Recovery codes
      </h2>
      <p className="hint">
        Eight one-time codes, each usable once, and the way back in when you forget your
        password. Generating a new set <strong>invalidates every code you already
        have</strong> — do it if you have lost them or used most of them, not casually.
      </p>
      {codes && (
        <>
          <p className="notice warn">
            <strong>These are shown once.</strong> Screenshot them or write them down
            now. Your previous codes no longer work.
          </p>
          <ul className="codes">
            {codes.map((c) => (
              <li key={c}>{c}</li>
            ))}
          </ul>
          <button
            className="ghost"
            onClick={() => void navigator.clipboard?.writeText(codes.join("\n")).catch(() => {})}
          >
            Copy codes
          </button>
        </>
      )}
      {feedback}
      <button
        className="ghost"
        disabled={busy}
        onClick={() =>
          void run(async () => {
            const r = await regenerateRecoveryCodes();
            setCodes(r.recoveryCodes);
            return "New codes issued. The old ones stopped working.";
          })
        }
      >
        {busy ? "…" : "Generate new codes"}
      </button>
    </section>
  );
}

/** Kept on this screen deliberately: the place you manage the data is the
 *  place to say what it is. It used to live at the bottom of the dashboard. */
function StoredCard() {
  return (
    <section className="acct-card">
      <h2>
        <Icon name="check" /> What&rsquo;s stored
      </h2>
      <ul className="acct-bullets">
        <li>Your username, a hashed password, and games you played while signed in.</li>
        <li>Your default table name, if you set one.</li>
        <li>Your private notes — visible only to you.</li>
        <li>An email only if you chose to add one, used solely to recover your account.</li>
        <li>
          For abuse prevention we keep a one-way hash of connection addresses (never the
          address itself), separate from accounts, deleted after 30 days.
        </li>
      </ul>
      <Link className="acct-more" to="/privacy">
        Read exactly what is stored <Icon name="chevron" />
      </Link>
    </section>
  );
}

function DangerCard({ account }: { account: Account }) {
  const navigate = useNavigate();
  const [confirming, setConfirming] = useState(false);
  const [typed, setTyped] = useState("");
  const { busy, run, feedback } = useCardState();

  return (
    <section className="acct-card acct-danger">
      <h2>
        <Icon name="warn" /> Sign out, or leave
      </h2>
      <div className="acct-actions">
        <button
          className="ghost"
          onClick={() =>
            void logout().then(() => {
              publishAccount(null);
              navigate("/table");
            })
          }
        >
          <Icon name="exit" /> Sign out
        </button>
        {!confirming && (
          <button className="ghost danger" onClick={() => setConfirming(true)}>
            Delete account
          </button>
        )}
      </div>
      {confirming && (
        <div className="acct-delete">
          <p className="hint">
            This erases your account, your notes and your recovery codes for good. Games
            you played stay in their rooms for the other players, but are no longer
            linked to you. Type <strong>{account.username}</strong> to confirm.
          </p>
          <input
            className="acct-input"
            type="text"
            placeholder="your username"
            autoCapitalize="none"
            value={typed}
            onChange={(e) => setTyped(e.target.value)}
          />
          {feedback}
          <div className="acct-actions">
            <button
              className="ghost danger"
              disabled={busy || typed.trim().toLowerCase() !== account.username.toLowerCase()}
              onClick={() =>
                void run(async () => {
                  await deleteAccount(typed.trim());
                  publishAccount(null);
                  navigate("/table");
                  return "Account deleted.";
                })
              }
            >
              Delete my account
            </button>
            <button
              className="ghost"
              onClick={() => {
                setConfirming(false);
                setTyped("");
              }}
            >
              Cancel
            </button>
          </div>
        </div>
      )}
    </section>
  );
}
