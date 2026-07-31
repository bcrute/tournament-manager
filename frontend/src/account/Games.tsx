import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import Icon from "../Icon";
import { AccountError, getHistory, HistoryGame, saveNote } from "./api";

/**
 * Every game this account has sat in, with its private note.
 *
 * The note is edited here rather than in a separate place because the note is
 * *about* the game — pairing them means never having to remember which room
 * `AB123` was. `NotesSheet` (in the room) writes the same rows through the
 * same endpoint, so a note started at the table is finished here.
 */
export default function Games() {
  const [games, setGames] = useState<HistoryGame[] | null>(null);
  const [editing, setEditing] = useState<string | null>(null);
  const [draft, setDraft] = useState("");
  const [error, setError] = useState<string | null>(null);

  const key = (g: HistoryGame) => `${g.roomCode}-${g.gameNo}-${g.at}`;

  useEffect(() => {
    getHistory()
      .then((r) => setGames(r.games))
      .catch((e) => {
        setError(e instanceof AccountError ? e.message : "Couldn't load your games");
        setGames([]);
      });
  }, []);

  async function persistNote(g: HistoryGame, text: string) {
    try {
      await saveNote(g.roomCode, g.gameNo, text);
      setGames((list) =>
        (list ?? []).map((x) => (key(x) === key(g) ? { ...x, note: text || null } : x)),
      );
      setEditing(null);
    } catch (e) {
      setError(e instanceof AccountError ? e.message : "Couldn't save that note");
    }
  }

  if (games === null) return <p className="hint">Loading…</p>;

  return (
    <>
      {error && <p className="error">{error}</p>}
      {games.length === 0 ? (
        <section className="acct-card">
          <p className="hint">
            No games yet. Anything you play while signed in is recorded here
            automatically — <Link to="/table">start a game</Link>.
          </p>
        </section>
      ) : (
        <ul className="acct-games">
          {games.map((g) => (
            <li key={key(g)} className="acct-card">
              <div className="acct-game-head">
                <span className="acct-game-room">{g.roomCode}</span>
                <Icon
                  name={g.mode === "treachery" ? "sword" : "heart"}
                  label={g.mode === "treachery" ? "Hidden roles game" : "Life counter game"}
                />
                <span className="acct-dim">{new Date(g.at * 1000).toLocaleDateString()}</span>
              </div>
              <p className="acct-dim">
                as {g.playedAs}
                {g.life !== null && ` · ended on ${g.life}`}
                {g.eliminated && " · eliminated"}
              </p>
              {editing === key(g) ? (
                <>
                  <label className="acct-label" htmlFor={`note-${key(g)}`}>
                    Your private note
                  </label>
                  <textarea
                    id={`note-${key(g)}`}
                    className="acct-textarea"
                    rows={4}
                    value={draft}
                    onChange={(e) => setDraft(e.target.value)}
                  />
                  <div className="acct-actions">
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
                  {g.note && <p className="acct-note">{g.note}</p>}
                  <button
                    className="ghost"
                    onClick={() => {
                      setEditing(key(g));
                      setDraft(g.note ?? "");
                    }}
                  >
                    <Icon name="edit" /> {g.note ? "Edit note" : "Add note"}
                  </button>
                </>
              )}
            </li>
          ))}
        </ul>
      )}
    </>
  );
}
