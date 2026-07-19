import { useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import {
  Account,
  AccountError,
  deleteAccount,
  getAccount,
  getHistory,
  HistoryGame,
  logout,
  saveNote,
} from "./account";
import FanContentNotice from "../FanContentNotice";
import SignIn from "./SignIn";
import { goBack } from "../goBack";

/** Your games and notes. Signed-out visitors get the sign-in panel instead. */
export default function Dashboard() {
  const navigate = useNavigate();
  const [acct, setAcct] = useState<Account | null | undefined>(undefined);
  const [games, setGames] = useState<HistoryGame[]>([]);
  const [editing, setEditing] = useState<HistoryGame | null>(null);
  const [draft, setDraft] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [deleteText, setDeleteText] = useState("");

  useEffect(() => {
    getAccount()
      .then((r) => setAcct(r.account))
      .catch(() => setAcct(null));
  }, []);

  useEffect(() => {
    if (!acct) return;
    getHistory()
      .then((r) => setGames(r.games))
      .catch((e) => setError(e instanceof AccountError ? e.message : "Couldn't load history"));
  }, [acct]);

  if (acct === undefined) {
    return (
      <main className="tr-landing">
        <p className="tagline">Loading…</p>
      </main>
    );
  }

  if (!acct) {
    return (
      <main className="tr-landing">
        <header>
          <h1>Your games</h1>
          <p className="tagline">
            Optional — sign in to keep a history and private notes. No email needed.
          </p>
        </header>
        <SignIn onDone={setAcct} onCancel={() => goBack(navigate, "/table")} />
        <footer>
          <Link to="/table">← back to Table</Link>
        </footer>
        <FanContentNotice />
      </main>
    );
  }

  async function persistNote(g: HistoryGame, text: string) {
    await saveNote(g.roomCode, g.gameNo, text);
    setGames((list) =>
      list.map((x) =>
        x.roomCode === g.roomCode && x.gameNo === g.gameNo ? { ...x, note: text || null } : x,
      ),
    );
    setEditing(null);
  }

  return (
    <main className="tr-landing dashboard">
      <header>
        <h1>{acct.username}</h1>
        <p className="tagline">{games.length} game{games.length === 1 ? "" : "s"} recorded</p>
      </header>

      {error && <p className="error">{error}</p>}

      <ul className="history">
        {games.length === 0 && (
          <p className="hint">
            No games yet. Games you play while signed in show up here automatically.
          </p>
        )}
        {games.map((g) => (
          <li key={`${g.roomCode}-${g.gameNo}-${g.at}`}>
            <div className="history-head">
              <span className="history-room">{g.roomCode}</span>
              <span className="history-mode">{g.mode === "treachery" ? "⚔" : "♥"}</span>
              <span className="history-when">{new Date(g.at * 1000).toLocaleDateString()}</span>
            </div>
            <div className="history-detail">
              as {g.playedAs}
              {g.life !== null && ` · ended on ${g.life}`}
              {g.eliminated && " · eliminated"}
            </div>
            {editing === g ? (
              <>
                <textarea
                  className="note-input"
                  rows={4}
                  value={draft}
                  onChange={(e) => setDraft(e.target.value)}
                />
                <div className="history-actions">
                  <button className="primary" onClick={() => void persistNote(g, draft.trim())}>
                    Save note
                  </button>
                  <button className="ghost" onClick={() => setEditing(null)}>
                    Cancel
                  </button>
                </div>
              </>
            ) : (
              <>
                {g.note && <p className="history-note">{g.note}</p>}
                <button
                  className="ghost"
                  onClick={() => {
                    setEditing(g);
                    setDraft(g.note ?? "");
                  }}
                >
                  {g.note ? "Edit note" : "Add note"}
                </button>
              </>
            )}
          </li>
        ))}
      </ul>

      <section className="privacy">
        <h2>What&rsquo;s stored</h2>
        <ul>
          <li>Your username, a hashed password, and games you played while signed in.</li>
          <li>Your private notes — visible only to you.</li>
          <li>An email only if you chose to add one, used solely to recover your account.</li>
          <li>
            For abuse prevention we keep a one-way hash of connection addresses (never the
            address itself), separate from accounts, deleted after 30 days.
          </li>
        </ul>
      </section>

      <footer className="account-actions">
        <button className="ghost" onClick={() => void logout().then(() => setAcct(null))}>
          Sign out
        </button>
        <Link to="/table">← back to Table</Link>
        {!confirmDelete ? (
          <button className="ghost danger" onClick={() => setConfirmDelete(true)}>
            Delete account
          </button>
        ) : (
          <div className="delete-box">
            <p className="hint">
              This erases your account, notes and recovery codes for good. Games you played
              stay in their rooms for the other players, but are no longer linked to you.
              Type <strong>{acct.username}</strong> to confirm.
            </p>
            <input
              type="text"
              placeholder="your username"
              autoCapitalize="none"
              value={deleteText}
              onChange={(e) => setDeleteText(e.target.value)}
            />
            <div className="history-actions">
              <button
                className="ghost danger"
                disabled={deleteText.trim().toLowerCase() !== acct.username.toLowerCase()}
                onClick={() =>
                  void deleteAccount(deleteText.trim())
                    .then(() => {
                      setAcct(null);
                      setConfirmDelete(false);
                      setDeleteText("");
                    })
                    .catch((e) =>
                      setError(e instanceof AccountError ? e.message : "Couldn't delete account"),
                    )
                }
              >
                Delete my account
              </button>
              <button
                className="ghost"
                onClick={() => {
                  setConfirmDelete(false);
                  setDeleteText("");
                }}
              >
                Cancel
              </button>
            </div>
          </div>
        )}
      </footer>
    </main>
  );
}
