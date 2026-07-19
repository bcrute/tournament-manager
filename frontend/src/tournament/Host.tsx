import { useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { Account, account, AccountError, getAccount } from "../table/account";
import SignIn from "../table/SignIn";
import { createTournament, TourneyError } from "./api";

/**
 * The organizer's front door: sign in, then create a tournament.
 *
 * Hosting is the one place an email is required. Everywhere else in the app an
 * email stays optional — but an organizer who loses their account mid-event
 * leaves a room full of people with no way to run the rest of the rounds.
 */
export default function Host() {
  const navigate = useNavigate();
  const [acct, setAcct] = useState<Account | null | undefined>(undefined);
  const [email, setEmail] = useState("");
  const [name, setName] = useState("");
  const [mode, setMode] = useState<"life" | "treachery">("life");
  const [podSize, setPodSize] = useState(4);
  const [roundMinutes, setRoundMinutes] = useState(60);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    void getAccount()
      .then((r) => setAcct(r.account))
      .catch(() => setAcct(null));
  }, []);

  async function addEmail() {
    setBusy(true);
    setError(null);
    try {
      await account("/email", { method: "POST", body: { email: email.trim() } });
      const r = await getAccount();
      setAcct(r.account);
    } catch (e) {
      setError(e instanceof AccountError ? e.message : "Could not save that address");
    } finally {
      setBusy(false);
    }
  }

  async function create() {
    setBusy(true);
    setError(null);
    try {
      const res = await createTournament(name.trim(), mode, { podSize, roundMinutes });
      navigate(`/tournament/${res.code}/organize`);
    } catch (e) {
      setError(e instanceof TourneyError ? e.message : "Could not create the tournament");
    } finally {
      setBusy(false);
    }
  }

  if (acct === undefined) return <main className="tq-host" />;

  if (!acct) {
    return (
      <main className="tq-host">
        <header>
          <h1>Host a tournament</h1>
          <p className="tagline">
            Organizers need an account — it&rsquo;s how you get back into your event
          </p>
        </header>
        <SignIn
          purpose="required"
          cancelLabel="Back"
          onDone={(a) => setAcct(a)}
          onCancel={() => navigate("/table")}
        />
      </main>
    );
  }

  if (!acct.hasEmail) {
    return (
      <main className="tq-host">
        <header>
          <h1>One thing first</h1>
        </header>
        <div className="sheet">
          <p className="notice">
            Hosting is the only part of the app that needs an email address. If you lose
            access to your account partway through an event, everyone at the tables is
            stuck — recovery codes don&rsquo;t help much when they&rsquo;re at home in a
            drawer. It stays private, is never shown to players, and is used for nothing
            but getting you back in.
          </p>
          <input
            type="email"
            placeholder="you@example.com"
            autoComplete="email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
          />
          {error && <p className="error">{error}</p>}
          <button className="primary" disabled={busy || !email.includes("@")} onClick={() => void addEmail()}>
            {busy ? "…" : "Save and continue"}
          </button>
          <Link className="ghost-link" to="/table">
            Not now
          </Link>
        </div>
      </main>
    );
  }

  return (
    <main className="tq-host">
      <header>
        <h1>Create a tournament</h1>
        <p className="tagline">Signed in as {acct.username}</p>
      </header>
      <div className="sheet">
        <label>
          Event name
          <input
            type="text"
            placeholder="Friday Night Commander"
            maxLength={80}
            value={name}
            onChange={(e) => setName(e.target.value)}
          />
        </label>
        <label>
          Format
          <div className="tr-mode">
            <button className={mode === "life" ? "active" : ""} onClick={() => setMode("life")}>
              Life counter
            </button>
            <button
              className={mode === "treachery" ? "active" : ""}
              onClick={() => setMode("treachery")}
            >
              Hidden roles
            </button>
          </div>
        </label>
        <label>
          Players per pod
          <input
            type="number"
            min={3}
            max={6}
            value={podSize}
            onChange={(e) => setPodSize(Number(e.target.value))}
          />
        </label>
        <label>
          Round length (minutes)
          <input
            type="number"
            min={10}
            max={240}
            value={roundMinutes}
            onChange={(e) => setRoundMinutes(Number(e.target.value))}
          />
        </label>
        {error && <p className="error">{error}</p>}
        <button className="primary" disabled={busy || !name.trim()} onClick={() => void create()}>
          {busy ? "…" : "Create tournament"}
        </button>
      </div>
    </main>
  );
}
