import { useEffect, useMemo, useState } from "react";
import { useParams } from "react-router-dom";
import Icon from "../Icon";
import {
  ackCall,
  addEntrants,
  closeRound,
  dropEntrant,
  formatClock,
  openRound,
  PodView,
  releaseEntrant,
  reportResult,
  resolveCall,
  secondsLeft,
  timerAction,
  TourneyError,
} from "./api";
import { useTournament } from "./useTournament";

/**
 * The organizer console. Desktop-first — this is the one screen in the app
 * meant for a laptop at the front table, so it lays out wide: roster on the
 * left, pods in the middle, standings and the call queue on the right.
 */
export default function Organize() {
  const { code = "" } = useParams();
  const { state, error, refresh, clockOffset } = useTournament(code);
  const [names, setNames] = useState("");
  const [busy, setBusy] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);
  const [tick, setTick] = useState(0);

  // one interval for the whole page rather than one per pod
  useEffect(() => {
    const id = setInterval(() => setTick((t) => t + 1), 1000);
    return () => clearInterval(id);
  }, []);

  // `tick` is the dependency that matters: it re-reads the wall clock each second
  const left = useMemo(
    () => secondsLeft(state?.round ?? null, Date.now(), clockOffset.current),
    [state?.round, tick, clockOffset],
  );

  async function run(fn: () => Promise<unknown>) {
    setBusy(true);
    setActionError(null);
    try {
      await fn();
      await refresh();
    } catch (e) {
      setActionError(e instanceof TourneyError ? e.message : "That didn't go through");
    } finally {
      setBusy(false);
    }
  }

  if (!state) {
    return (
      <main className="tq-console">
        <p className="hint">{error ?? "Loading…"}</p>
      </main>
    );
  }

  const { tournament, round, pods, standings, calls } = state;
  const joinUrl = `${location.origin}/tournament/${tournament.code}`;
  const roundOpen = round?.status === "active";
  const allReported = pods.length > 0 && pods.every((p) => p.status === "complete");

  return (
    <main className="tq-console">
      <header className="tq-bar">
        <div>
          <h1>{tournament.name}</h1>
          <p className="tagline">
            Join code <strong className="tq-code">{tournament.code}</strong>
            <span className="dot-sep">·</span>
            <span className="hint">{joinUrl}</span>
          </p>
        </div>
        <div className="tq-clock">
          {round ? (
            <>
              <span className="tq-round">Round {round.number}</span>
              <span className={`tq-time${left !== null && left <= 300 ? " low" : ""}`}>
                {formatClock(left)}
              </span>
              <div className="tq-timer-controls">
                {round.pausedAt ? (
                  <button disabled={busy} onClick={() => void run(() => timerAction(code, "resume"))}>
                    Resume
                  </button>
                ) : (
                  <button disabled={busy} onClick={() => void run(() => timerAction(code, "pause"))}>
                    Pause
                  </button>
                )}
                <button
                  disabled={busy}
                  onClick={() => void run(() => timerAction(code, "extend", { minutes: 5 }))}
                >
                  +5 min
                </button>
              </div>
            </>
          ) : (
            <span className="hint">No round yet</span>
          )}
        </div>
      </header>

      {actionError && <p className="error">{actionError}</p>}

      <div className="tq-grid">
        <section className="tq-panel">
          <h2>
            <Icon name="users" /> Roster ({standings.length})
          </h2>
          <textarea
            rows={4}
            placeholder="One name per line"
            value={names}
            onChange={(e) => setNames(e.target.value)}
          />
          <button
            disabled={busy || !names.trim()}
            onClick={() =>
              void run(async () => {
                await addEntrants(
                  code,
                  names.split("\n").map((n) => n.trim()).filter(Boolean),
                );
                setNames("");
              })
            }
          >
            Add players
          </button>
          <ul className="tq-roster">
            {standings.map((s) => (
              <li key={s.entrantId} className={s.dropped ? "dropped" : ""}>
                <span className="tq-name">{s.name}</span>
                <span className="tq-tags">
                  {s.claimed && <span className="tq-tag on">on device</span>}
                  {s.dropped && <span className="tq-tag">dropped</span>}
                </span>
                <span className="tq-row-actions">
                  {s.claimed && (
                    <button
                      className="link"
                      disabled={busy}
                      title="Free this name so it can be claimed again"
                      onClick={() => void run(() => releaseEntrant(code, s.entrantId))}
                    >
                      release
                    </button>
                  )}
                  {!s.dropped && (
                    <button
                      className="link"
                      disabled={busy}
                      onClick={() => void run(() => dropEntrant(code, s.entrantId))}
                    >
                      drop
                    </button>
                  )}
                </span>
              </li>
            ))}
          </ul>
        </section>

        <section className="tq-panel wide">
          <h2>
            <Icon name="seat" /> {round ? `Round ${round.number} pods` : "Pods"}
          </h2>
          <div className="tq-round-actions">
            <button
              className="primary"
              disabled={busy || roundOpen}
              onClick={() => void run(() => openRound(code))}
            >
              {round ? "Start next round" : "Start round 1"}
            </button>
            {roundOpen && (
              <>
                <button
                  disabled={busy}
                  title="Discard these pairings and pair again"
                  onClick={() => void run(() => openRound(code, true))}
                >
                  Re-pair
                </button>
                <button
                  disabled={busy || !allReported}
                  title={allReported ? "" : "Every pod needs a result first"}
                  onClick={() => void run(() => closeRound(code))}
                >
                  Close round
                </button>
              </>
            )}
          </div>
          <div className="tq-pods">
            {pods.map((p) => (
              <PodCard key={p.podId} code={code} pod={p} busy={busy} run={run} />
            ))}
            {pods.length === 0 && (
              <p className="hint">
                Add the roster, then start round 1 — pairings and seating are generated for
                you, and each pod gets its own room the players drop straight into.
              </p>
            )}
          </div>
        </section>

        <section className="tq-panel">
          <h2>
            <Icon name="hand" /> Calls
          </h2>
          {calls.length === 0 && <p className="hint">No open calls</p>}
          <ul className="tq-calls">
            {calls.map((c) => (
              <li key={c.id} className={c.status}>
                <strong>Table {pods.find((p) => p.podId === c.podId)?.table ?? "?"}</strong>
                {c.note && <span className="tq-note">{c.note}</span>}
                <span className="tq-row-actions">
                  {c.status === "open" && (
                    <button disabled={busy} onClick={() => void run(() => ackCall(code, c.id))}>
                      On my way
                    </button>
                  )}
                  <button disabled={busy} onClick={() => void run(() => resolveCall(code, c.id))}>
                    Resolved
                  </button>
                </span>
              </li>
            ))}
          </ul>

          <h2>
            <Icon name="crown" /> Standings
          </h2>
          <ol className="tq-standings">
            {standings.map((s) => (
              <li key={s.entrantId}>
                <span className="tq-rank">{s.rank}</span>
                <span className="tq-name">{s.name}</span>
                <span className="tq-pts" title="points · opponents' points">
                  {s.points} <span className="hint">/ {s.opponentPoints}</span>
                </span>
              </li>
            ))}
          </ol>
        </section>
      </div>
    </main>
  );
}

/** One table: seating, live result, and the organizer's override. */
function PodCard({
  code,
  pod,
  busy,
  run,
}: {
  code: string;
  pod: PodView;
  busy: boolean;
  run: (fn: () => Promise<unknown>) => Promise<void>;
}) {
  const [editing, setEditing] = useState(false);
  const [places, setPlaces] = useState<Record<number, number>>({});

  const submitPlacement = () =>
    void run(async () => {
      await reportResult(code, pod.podId, {
        kind: "placement",
        places: pod.seats.map((s) => ({
          entrantId: s.entrantId,
          place: places[s.entrantId] ?? s.place ?? pod.seats.length,
        })),
      });
      setEditing(false);
    });

  return (
    <article className={`tq-pod ${pod.status}`}>
      <header>
        <h3>Table {pod.table}</h3>
        <span className="tq-pod-status">{pod.status.replace("_", " ")}</span>
      </header>
      <ol className="tq-seats">
        {pod.seats.map((s) => (
          <li key={s.entrantId}>
            <span className="tq-seat-no">{s.seat}</span>
            <span className="tq-name">{s.name}</span>
            {editing ? (
              <input
                type="number"
                min={1}
                max={pod.seats.length}
                value={places[s.entrantId] ?? s.place ?? ""}
                onChange={(e) =>
                  setPlaces((p) => ({ ...p, [s.entrantId]: Number(e.target.value) }))
                }
              />
            ) : (
              s.place != null && <span className="tq-place">#{s.place}</span>
            )}
          </li>
        ))}
      </ol>
      <footer>
        {pod.roomCode && <span className="hint">room {pod.roomCode}</span>}
        {editing ? (
          <>
            <button className="primary" disabled={busy} onClick={submitPlacement}>
              Save result
            </button>
            <button disabled={busy} onClick={() => setEditing(false)}>
              Cancel
            </button>
          </>
        ) : (
          <>
            <button disabled={busy} onClick={() => setEditing(true)}>
              {pod.status === "complete" ? "Override" : "Enter result"}
            </button>
            <button
              disabled={busy}
              title="Time was called with no winner"
              onClick={() => void run(() => reportResult(code, pod.podId, { kind: "draw" }))}
            >
              Draw
            </button>
          </>
        )}
      </footer>
    </article>
  );
}
