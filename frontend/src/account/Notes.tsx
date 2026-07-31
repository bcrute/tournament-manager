import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import Icon from "../Icon";
import { AccountError, getNotes, StoredNote } from "./api";

/**
 * Every private note, newest first, searchable.
 *
 * The Games tab answers "what did I write about *this* game"; this one answers
 * "where did I write down that combo". Same rows, opposite direction — which
 * is why the filter searches the text rather than the room code.
 *
 * These are visible to nobody but the account that wrote them. The admin
 * surface cannot read them either: it reads counts, not contents.
 */
export default function Notes() {
  const [notes, setNotes] = useState<StoredNote[] | null>(null);
  const [filter, setFilter] = useState("");
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    getNotes()
      .then((r) => setNotes(r.notes))
      .catch((e) => {
        setError(e instanceof AccountError ? e.message : "Couldn't load your notes");
        setNotes([]);
      });
  }, []);

  const shown = useMemo(() => {
    const q = filter.trim().toLowerCase();
    if (!q) return notes ?? [];
    return (notes ?? []).filter(
      (n) => n.text.toLowerCase().includes(q) || n.roomCode.toLowerCase().includes(q),
    );
  }, [notes, filter]);

  if (notes === null) return <p className="hint">Loading…</p>;

  return (
    <>
      {error && <p className="error">{error}</p>}
      {notes.length === 0 ? (
        <section className="acct-card">
          <p className="hint">
            No notes yet. Write one during a game from the room menu, or against any
            game in <Link to="/account/games">your games</Link>.
          </p>
        </section>
      ) : (
        <>
          <label className="acct-label" htmlFor="note-filter">
            Search your notes
          </label>
          <input
            id="note-filter"
            type="search"
            className="acct-input"
            placeholder="a card, a room code, a name…"
            value={filter}
            onChange={(e) => setFilter(e.target.value)}
          />
          <p className="hint">
            {shown.length} of {notes.length} note{notes.length === 1 ? "" : "s"}
          </p>
          <ul className="acct-games">
            {shown.map((n) => (
              <li key={`${n.roomCode}-${n.gameNo}`} className="acct-card">
                <div className="acct-game-head">
                  <span className="acct-game-room">{n.roomCode}</span>
                  <span className="acct-dim">game {n.gameNo}</span>
                  <span className="acct-dim">
                    {new Date(n.updatedAt * 1000).toLocaleDateString()}
                  </span>
                </div>
                <p className="acct-note">{n.text}</p>
              </li>
            ))}
          </ul>
          {shown.length === 0 && (
            <p className="hint">
              <Icon name="warn" /> Nothing matches “{filter}”.
            </p>
          )}
        </>
      )}
    </>
  );
}
