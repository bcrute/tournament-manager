import { useCallback, useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import SignIn from "../table/SignIn";
import { goBack } from "../goBack";
import {
  ago,
  AdminError,
  AdminRoom,
  AdminTournament,
  Ban,
  closeRoom,
  endTournament,
  getBans,
  getLog,
  getOverview,
  getRooms,
  getSecurity,
  getTournaments,
  liftBan,
  LogEntry,
  Overview,
  SecurityEntry,
} from "./api";

/**
 * Admin console. Unlisted — nothing in the app links here.
 *
 * A non-admin gets 404 from every endpoint, so this page cannot tell the
 * difference between "you are not an admin" and "this does not exist", and it
 * deliberately doesn't try. It offers a sign-in and says nothing more.
 */
export default function Admin() {
  const navigate = useNavigate();
  const [overview, setOverview] = useState<Overview | null>(null);
  const [denied, setDenied] = useState(false);
  const [rooms, setRooms] = useState<AdminRoom[]>([]);
  const [tournaments, setTournaments] = useState<AdminTournament[]>([]);
  const [bans, setBans] = useState<Ban[]>([]);
  const [log, setLog] = useState<LogEntry[]>([]);
  // kept separate from the admin log on purpose — see backend/app/audit.py
  const [security, setSecurity] = useState<SecurityEntry[]>([]);
  const [counts, setCounts] = useState<{ kind: string; n: number }[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const o = await getOverview();
      setOverview(o);
      setDenied(false);
      const [r, t, b, l, s] = await Promise.all([
        getRooms(),
        getTournaments(),
        getBans(),
        getLog(),
        getSecurity(),
      ]);
      setRooms(r.rooms);
      setTournaments(t.tournaments);
      setBans(b.bans);
      setLog(l.entries);
      setSecurity(s.entries);
      setCounts(s.last24h);
    } catch (e) {
      if (e instanceof AdminError && e.status === 404) setDenied(true);
      else setError(e instanceof Error ? e.message : "Something went wrong");
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  async function act(fn: () => Promise<unknown>, confirmText: string) {
    if (!window.confirm(confirmText)) return;
    const reason = window.prompt("Reason (recorded in the audit log):") ?? undefined;
    setBusy(true);
    setError(null);
    try {
      await fn();
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "That didn't go through");
    } finally {
      setBusy(false);
    }
  }

  if (denied || !overview) {
    return (
      <main className="adm">
        <header>
          <h1>Admin</h1>
        </header>
        {denied && (
          <SignIn
            purpose="required"
            cancelLabel="Back"
            onDone={() => void load()}
            onCancel={() => goBack(navigate, "/")}
          />
        )}
      </main>
    );
  }

  return (
    <main className="adm">
      <header className="adm-bar">
        <h1>Admin</h1>
        <span className="hint">signed in as {overview.admin}</span>
        <button disabled={busy} onClick={() => void load()}>
          Refresh
        </button>
      </header>

      {error && <p className="error">{error}</p>}

      <section className="adm-stats">
        {[
          ["Rooms", `${overview.rooms.active} playing / ${overview.rooms.total}`],
          ["Tournaments", `${overview.tournaments.running} running / ${overview.tournaments.total}`],
          ["Players seated", String(overview.players)],
          ["Accounts", String(overview.accounts)],
          ["Active bans", String(overview.bans)],
        ].map(([label, value]) => (
          <div key={label} className="adm-stat">
            <span className="adm-stat-value">{value}</span>
            <span className="adm-stat-label">{label}</span>
          </div>
        ))}
      </section>

      <section className="adm-panel">
        <h2>Tournaments</h2>
        <table>
          <thead>
            <tr>
              <th>Code</th><th>Name</th><th>Status</th><th>Entrants</th><th>Idle</th><th />
            </tr>
          </thead>
          <tbody>
            {tournaments.map((t) => (
              <tr key={t.code}>
                <td className="mono">{t.code}</td>
                <td>{t.name}</td>
                <td>{t.status}</td>
                <td>{t.entrants}</td>
                <td>{ago(t.last_active ?? t.created_at)}</td>
                <td>
                  {t.status !== "ended" && (
                    <button
                      disabled={busy}
                      onClick={() =>
                        void act(
                          () => endTournament(t.code),
                          `End tournament ${t.code}? Standings are kept.`,
                        )
                      }
                    >
                      End
                    </button>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>

      <section className="adm-panel">
        <h2>Rooms</h2>
        <table>
          <thead>
            <tr>
              <th>Code</th><th>Mode</th><th>Status</th><th>Players</th><th>Idle</th><th />
            </tr>
          </thead>
          <tbody>
            {rooms.map((r) => (
              <tr key={r.code}>
                <td className="mono">{r.code}</td>
                <td>{r.mode}</td>
                <td>{r.status}</td>
                <td>{r.players}</td>
                <td>{ago(r.last_active ?? r.created_at)}</td>
                <td>
                  {r.status !== "ended" && (
                    <button
                      disabled={busy}
                      onClick={() =>
                        void act(
                          () => closeRoom(r.code),
                          `Close room ${r.code}? History is kept.`,
                        )
                      }
                    >
                      Close
                    </button>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>

      <section className="adm-panel">
        <h2>Bans</h2>
        <p className="hint">
          Subjects are salted hashes of a client address. The address itself is never
          stored, so it cannot be shown here.
        </p>
        <table>
          <thead>
            <tr><th>Subject</th><th>Strikes</th><th>Expires</th><th /></tr>
          </thead>
          <tbody>
            {bans.map((b) => (
              <tr key={b.subject}>
                <td className="mono trunc">{b.subject}</td>
                <td>{b.strikes}</td>
                <td>{new Date(b.until * 1000).toLocaleString()}</td>
                <td>
                  <button
                    disabled={busy}
                    onClick={() =>
                      void act(() => liftBan(b.subject), "Lift this ban and clear its strikes?")
                    }
                  >
                    Lift
                  </button>
                </td>
              </tr>
            ))}
            {bans.length === 0 && (
              <tr>
                <td colSpan={4} className="hint">No bans</td>
              </tr>
            )}
          </tbody>
        </table>
      </section>

      <section className="adm-panel">
        <h2>Security events</h2>
        <p className="hint">
          Failures and probes — noisy by nature, which is why they are kept apart from
          the admin log. Subjects are salted hashes or usernames, never addresses.
          {counts.length > 0 && (
            <> Last 24h: {counts.map((c) => `${c.kind} ${c.n}`).join(" · ")}.</>
          )}
        </p>
        <table>
          <thead>
            <tr><th>When</th><th>Kind</th><th>Subject</th><th>Detail</th></tr>
          </thead>
          <tbody>
            {security.slice(0, 50).map((e, i) => (
              <tr key={`${e.at}-${i}`}>
                <td>{new Date(e.at * 1000).toLocaleString()}</td>
                <td className="mono">{e.kind}</td>
                <td className="mono trunc">{e.subject ?? "—"}</td>
                <td className="trunc">{e.detail ?? "—"}</td>
              </tr>
            ))}
            {security.length === 0 && (
              <tr><td colSpan={4} className="hint">Nothing recorded</td></tr>
            )}
          </tbody>
        </table>
      </section>

      <section className="adm-panel">
        <h2>Admin actions</h2>
        <table>
          <thead>
            <tr><th>When</th><th>Who</th><th>Action</th><th>Target</th><th>Reason</th></tr>
          </thead>
          <tbody>
            {log.map((e, i) => (
              <tr key={`${e.at}-${i}`}>
                <td>{new Date(e.at * 1000).toLocaleString()}</td>
                <td>{e.actor}</td>
                <td className="mono">{e.action}</td>
                <td className="mono">{e.target ?? "—"}</td>
                <td>{e.detail ?? "—"}</td>
              </tr>
            ))}
            {log.length === 0 && (
              <tr>
                <td colSpan={5} className="hint">Nothing yet</td>
              </tr>
            )}
          </tbody>
        </table>
      </section>
    </main>
  );
}
