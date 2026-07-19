import { useEffect, useState } from "react";
import Icon from "../Icon";
import { getState, StandingRow } from "../tournament/api";
import { loadSeat } from "../tournament/api";

/**
 * Standings, read from inside the room.
 *
 * A player in a pod should never have to navigate a tournament interface — the
 * round finds them, the clock is on their screen, and the next pairing opens
 * itself. The one thing they do want is how everyone is doing, and that belongs
 * behind the menu rather than in the way.
 */
export default function TournamentSheet({
  code,
  onClose,
}: {
  code: string;
  onClose: () => void;
}) {
  const [rows, setRows] = useState<StandingRow[] | null>(null);
  const [name, setName] = useState("");
  const [error, setError] = useState<string | null>(null);
  const mine = loadSeat();

  useEffect(() => {
    const token = mine && mine.code === code ? mine.token : undefined;
    void getState(code, token)
      .then((s) => {
        setRows(s.standings);
        setName(s.tournament.name);
      })
      .catch(() => setError("Couldn't load the standings"));
  }, [code, mine]);

  return (
    <div className="sheet-overlay" onPointerDown={onClose}>
      <div className="sheet" onPointerDown={(e) => e.stopPropagation()}>
        <button className="sheet-back" onClick={onClose} aria-label="Close">
          <Icon name="back" /> Back to the game
        </button>
        <h2>{name || "Standings"}</h2>

        {error && <p className="error">{error}</p>}
        {!rows && !error && <p className="hint">Loading…</p>}

        {rows && (
          <ol className="ts-rows">
            {rows.map((r) => {
              const isMe = mine?.entrantId === r.entrantId;
              return (
                <li key={r.entrantId} className={`ts-row${isMe ? " me" : ""}${r.dropped ? " dropped" : ""}`}>
                  <span className="ts-rank">{r.rank}</span>
                  <span className="ts-name">
                    {r.name}
                    {isMe && <em> · you</em>}
                  </span>
                  <span className="ts-record" title="won · drew · lost">
                    {r.wins}–{r.draws}–{r.losses}
                  </span>
                  <span className="ts-points" title="points · opponents' points">
                    {r.points}
                    <span className="hint"> / {r.opponentPoints}</span>
                  </span>
                </li>
              );
            })}
          </ol>
        )}

        {rows && rows.length > 0 && (
          <p className="hint">
            Record is won–drew–lost. The second number after points is your opponents&rsquo;
            total, the standard tiebreaker.
          </p>
        )}
      </div>
    </div>
  );
}
