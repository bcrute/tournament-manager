import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import Icon from "../Icon";
import { listMine, MyTournament } from "../tournament/api";
import { Account, AccountError, AccountStats, getHistory, getStats, HistoryGame } from "./api";

/** A date, or a dash. Every timestamp here can legitimately be absent. */
function when(at: number | null): string {
  return at ? new Date(at * 1000).toLocaleDateString() : "—";
}

const MODE_LABEL: Record<string, string> = {
  life: "Life counter",
  treachery: "Hidden roles",
};

/**
 * The account's front page: what you have played, what you last played, and
 * the events you are running.
 *
 * Every number here is one the data can actually support. There is deliberately
 * no win rate: the life counter records who was eliminated, not who won, and a
 * "78% win rate" derived from that would be a confident fiction. See the
 * server's `/stats` docstring.
 */
export default function Overview({ account }: { account: Account }) {
  const [stats, setStats] = useState<AccountStats | null>(null);
  const [recent, setRecent] = useState<HistoryGame[]>([]);
  const [events, setEvents] = useState<MyTournament[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    getStats()
      .then(setStats)
      .catch((e) => setError(e instanceof AccountError ? e.message : "Couldn't load your stats"));
    getHistory(5)
      .then((r) => setRecent(r.games))
      .catch(() => setRecent([]));
    // an account with no events is the normal case, not an error
    listMine()
      .then((r) => setEvents(r.tournaments))
      .catch(() => setEvents([]));
  }, []);

  return (
    <>
      {error && <p className="error">{error}</p>}

      <section className="acct-card">
        <h2>
          <Icon name="chart" /> Your play
        </h2>
        {stats ? (
          <>
            <ul className="acct-stats">
              <li>
                <span className="acct-stat-n">{stats.games}</span>
                <span className="acct-stat-l">times you sat down</span>
              </li>
              <li>
                <span className="acct-stat-n">{stats.tables}</span>
                <span className="acct-stat-l">tables joined</span>
              </li>
              <li>
                <span className="acct-stat-n">{stats.notes}</span>
                <span className="acct-stat-l">notes written</span>
              </li>
            </ul>
            <p className="hint">
              {Object.entries(stats.byMode).length > 0 && (
                <>
                  {Object.entries(stats.byMode)
                    .map(([m, n]) => `${MODE_LABEL[m] ?? m}: ${n}`)
                    .join(" · ")}
                  {" — "}
                </>
              )}
              last played {when(stats.lastAt)}, member since {when(stats.memberSince)}.
            </p>
          </>
        ) : (
          <p className="hint">Counting…</p>
        )}
      </section>

      <section className="acct-card">
        <h2>
          <Icon name="heart" /> Recent games
        </h2>
        {recent.length === 0 ? (
          <p className="hint">
            Nothing yet. Games you play while signed in show up here on their own —{" "}
            <Link to="/table">start one</Link>.
          </p>
        ) : (
          <>
            <ul className="acct-list">
              {recent.map((g) => (
                <li key={`${g.roomCode}-${g.gameNo}-${g.at}`}>
                  <span className="acct-list-main">
                    <Icon
                      name={g.mode === "treachery" ? "sword" : "heart"}
                      label={MODE_LABEL[g.mode] ?? g.mode}
                    />{" "}
                    {g.roomCode} <span className="acct-dim">as {g.playedAs}</span>
                  </span>
                  <span className="acct-dim">{when(g.at)}</span>
                  {g.note && <p className="acct-note">{g.note}</p>}
                </li>
              ))}
            </ul>
            <Link className="acct-more" to="/account/games">
              All your games <Icon name="chevron" />
            </Link>
          </>
        )}
      </section>

      <section className="acct-card">
        <h2>
          <Icon name="crown" /> Events you run
        </h2>
        {events === null ? (
          <p className="hint">Loading…</p>
        ) : events.length === 0 ? (
          <p className="hint">
            You aren&rsquo;t running any events. <Link to="/tournament">Host one</Link> — it
            needs an account with a confirmed recovery email, which is what this page is for.
          </p>
        ) : (
          <ul className="acct-list">
            {events.slice(0, 5).map((t) => (
              <li key={t.code}>
                <span className="acct-list-main">
                  <Link to={`/tournament/${t.code}/organize`}>{t.name}</Link>{" "}
                  <span className="acct-dim">{t.code}</span>
                </span>
                <span className="acct-dim">
                  {t.status} · {t.entrants} entrant{t.entrants === 1 ? "" : "s"}
                  {t.openCalls > 0 && ` · ${t.openCalls} open call${t.openCalls === 1 ? "" : "s"}`}
                </span>
              </li>
            ))}
          </ul>
        )}
        {/* Deliberately absent: tournaments you *played* in. Claiming a seat
            never links it to an account, which is a boundary this project
            pins with a test — so there is nothing to list, by design. */}
        <p className="hint">
          Only events you organize appear here. Entering a tournament never links your
          seat to your account, so there is nothing for us to show — that separation is
          the point.
        </p>
      </section>

      <section className="acct-card">
        <h2>
          <Icon name="shield" /> Account
        </h2>
        <p className="hint">
          You sign in as <strong>{account.username}</strong>
          {account.displayName ? (
            <>
              {" "}
              and sit down at tables as <strong>{account.displayName}</strong>.
            </>
          ) : (
            <> and have no default table name set, so each device uses its own.</>
          )}
          {/* Pending is not "on file" for any purpose that matters, so it gets
              its own sentence rather than being folded in with confirmed. */}
          {account.emailPending
            ? " A recovery email is waiting to be confirmed — until the link is used, your recovery codes are your only way back in."
            : !account.hasEmail &&
              " No recovery email is on file — recovery codes are your only way back in."}
        </p>
        <Link className="acct-more" to="/account/settings">
          Manage your account <Icon name="chevron" />
        </Link>
      </section>
    </>
  );
}
