import { useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import Icon from "../Icon";
import { goBack } from "../goBack";
import { Account, account, AccountError, getAccount } from "../table/account";
import SignIn from "../table/SignIn";
import { ago } from "../admin/api";
import { suggestEventName } from "../username";
import {
  createTournament,
  deleteTournament,
  GameProfile,
  listGames,
  listMine,
  MyTournament,
  TourneyError,
} from "./api";

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
  // pre-filled rather than blank: naming the event is the only thing standing
  // between an organizer and their tournament, and most of them don't care
  const [name, setName] = useState(suggestEventName);
  const [mode, setMode] = useState("life");
  const [podSize, setPodSize] = useState(4);
  const [roundMinutes, setRoundMinutes] = useState(60);
  const [games, setGames] = useState<GameProfile[]>([]);
  const [game, setGame] = useState("mtg");
  const [structure, setStructure] = useState<string>("");
  const [mine, setMine] = useState<MyTournament[] | null>(null);
  const [creating, setCreating] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    void getAccount()
      .then((r) => setAcct(r.account))
      .catch(() => setAcct(null));
    void listGames().then((r) => setGames(r.games)).catch(() => {});
  }, []);

  // an organizer's own events, so closing the tab doesn't lose the tournament
  useEffect(() => {
    if (!acct?.hasEmail) return;
    void listMine().then((r) => setMine(r.tournaments)).catch(() => setMine([]));
  }, [acct]);

  const profile = games.find((g) => g.key === game);

  // Table size and round length belong to the game, not to the form. Left
  // alone, switching to a duel game kept Magic's four-to-a-pod and quietly
  // seated four duelists at one table. Only the untouched fields follow the
  // profile: an organizer who typed a number meant it.
  const [touched, setTouched] = useState<{ pod?: boolean; minutes?: boolean }>({});
  useEffect(() => {
    if (!profile) return;
    if (!touched.pod) setPodSize(profile.defaultPodSize);
    if (!touched.minutes) setRoundMinutes(profile.defaultRoundMinutes);
    if (profile.modes.length && !profile.modes.includes(mode)) setMode(profile.modes[0]);
    setStructure("");
  }, [profile, touched.pod, touched.minutes, mode]);

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

  async function remove(t: MyTournament) {
    // naming the event in the prompt: these codes look alike in a list, and
    // this is the one action here that cannot be undone
    if (!window.confirm(`Delete "${t.name}"? Its roster, rounds and standings go with it.`))
      return;
    setBusy(true);
    setError(null);
    try {
      await deleteTournament(t.code);
      setMine((all) => (all ?? []).filter((x) => x.code !== t.code));
    } catch (e) {
      setError(e instanceof TourneyError ? e.message : "Could not delete that tournament");
    } finally {
      setBusy(false);
    }
  }

  async function create() {
    setBusy(true);
    setError(null);
    try {
      const res = await createTournament(
        name.trim(),
        mode,
        { podSize, roundMinutes, ...(structure ? { structure } : {}) },
        game,
      );
      navigate(`/tournament/${res.code}/organize`);
    } catch (e) {
      setError(e instanceof TourneyError ? e.message : "Could not create the tournament");
    } finally {
      setBusy(false);
    }
  }

  if (acct === undefined) return <div className="tq-host" />;

  if (!acct) {
    return (
      <div className="tq-host">
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
          onCancel={() => goBack(navigate, "/table")}
        />
      </div>
    );
  }

  if (!acct.hasEmail) {
    return (
      <div className="tq-host">
        <header>
          <h1>One thing first</h1>
        </header>
        <div className="sheet">
          <button className="sheet-back" onClick={() => goBack(navigate, "/table")} aria-label="Back">
            <Icon name="back" /> Back
          </button>
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
        </div>
      </div>
    );
  }

  // The organizer's home: their events first. Creating is one of the things you
  // can do here, not the only thing — an event you already started matters more
  // than a new one.
  if (!creating && mine !== null) {
    return (
      <div className="tq-host">
        <header>
          <h1>Your tournaments</h1>
          <p className="tagline">Signed in as {acct.username}</p>
        </header>

        {mine.length > 0 && (
          <ul className="tq-mine">
            {mine.map((t) => (
              /* The card is the container, not the link. The link stretches
                 across it so the whole card still opens the event, and delete
                 sits above that overlay — inside the card, but its own target
                 rather than a button nested in a navigation element. */
              <li key={t.code} className={`tq-mine-card ${t.status}`}>
                <Link to={`/tournament/${t.code}/organize/pods`} className="tq-mine-link">
                  <span className="tq-mine-head">
                    <strong>{t.name}</strong>
                    <span className="tq-code">{t.code}</span>
                  </span>
                  <span className="tq-mine-meta">
                    {t.status === "ended"
                      ? "ended"
                      : t.rounds === 0
                        ? "not started"
                        : `round ${t.rounds}`}
                    <span className="dot-sep">·</span>
                    {t.entrants} {t.entrants === 1 ? "player" : "players"}
                    <span className="dot-sep">·</span>
                    {ago(t.last_active ?? t.created_at)} ago
                    {t.openCalls > 0 && (
                      <strong className="tq-mine-calls">
                        {" "}
                        {t.openCalls} call{t.openCalls === 1 ? "" : "s"} waiting
                      </strong>
                    )}
                  </span>
                </Link>
                <button
                  className="tq-mine-delete"
                  disabled={busy}
                  aria-label={`Delete ${t.name}`}
                  title="Delete this tournament"
                  onClick={() => void remove(t)}
                >
                  <Icon name="close" size={16} />
                </button>
              </li>
            ))}
          </ul>
        )}

        {mine.length === 0 && (
          <p className="hint">
            No tournaments yet. Creating one takes a name and about ten seconds — players
            join by scanning a code, with no account of their own.
          </p>
        )}

        {error && <p className="error">{error}</p>}

        <button className="primary" onClick={() => setCreating(true)}>
          <Icon name="plus" /> New tournament
        </button>
      </div>
    );
  }

  return (
    <div className="tq-host">
      <header>
        <h1>Create a tournament</h1>
      </header>
      <div className="sheet">
        <button className="sheet-back" onClick={() => setCreating(false)} aria-label="Back">
          <Icon name="back" /> Back
        </button>
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

        {games.length > 1 && (
          <label>
            Game
            <select value={game} onChange={(e) => setGame(e.target.value)}>
              {games.map((g) => (
                <option key={g.key} value={g.key}>
                  {g.name}
                </option>
              ))}
            </select>
          </label>
        )}

        {/* one format needs no picker — the same rule the game selector uses */}
        {(profile?.modes?.length ?? 0) > 1 && (
          <label>
            Format
            <div className="tr-mode">
              {profile!.modes.map((m) => (
                <button
                  key={m}
                  className={mode === m ? "active" : ""}
                  onClick={() => setMode(m)}
                >
                  {m === "life" ? "Life counter" : m === "treachery" ? "Hidden roles" : m}
                </button>
              ))}
            </div>
          </label>
        )}

        {profile && profile.structures?.length > 0 && (
          <label>
            Structure
            <select value={structure} onChange={(e) => setStructure(e.target.value)}>
              {profile.structures.map((s) => (
                <option key={s.key} value={s.key}>
                  {s.name}
                </option>
              ))}
            </select>
            <span className="hint">
              {(() => {
                const s = profile.structures.find((x) => x.key === (structure || profile.structures[0].key));
                if (!s) return null;
                return s.official
                  ? `Official — ${s.source}`
                  : `House convention. ${s.source}`;
              })()}
            </span>
          </label>
        )}

        <label>
          Players per table
          <input
            type="number"
            min={2}
            max={6}
            value={podSize}
            onChange={(e) => {
              setTouched((s) => ({ ...s, pod: true }));
              setPodSize(Number(e.target.value));
            }}
          />
        </label>
        <label>
          Round length (minutes)
          <input
            type="number"
            min={10}
            max={240}
            value={roundMinutes}
            onChange={(e) => {
              setTouched((s) => ({ ...s, minutes: true }));
              setRoundMinutes(Number(e.target.value));
            }}
          />
        </label>
        {error && <p className="error">{error}</p>}
        <button className="primary" disabled={busy || !name.trim()} onClick={() => void create()}>
          {busy ? "…" : "Create tournament"}
        </button>
      </div>
    </div>
  );
}
