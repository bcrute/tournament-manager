import { useEffect, useMemo, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import Icon from "../Icon";
import { saveSession } from "../table/session";
import {
  callOfficial,
  claimSeat,
  clearSeat,
  formatClock,
  getRoster,
  loadSeat,
  RosterEntry,
  saveSeat,
  secondsLeft,
  TourneyError,
} from "./api";
import { useTournament } from "./useTournament";

/**
 * The player side: scan the tournament code, tap your name, and from then on
 * the phone routes itself — when the organizer opens a round, the device drops
 * straight into that pod's room with the seat already assigned. No codes to
 * type between rounds.
 */
export default function Play() {
  const { code = "" } = useParams();
  const navigate = useNavigate();
  const [seat, setSeat] = useState(() => {
    const s = loadSeat();
    return s && s.code === code ? s : null;
  });

  if (!seat) return <ClaimSeat code={code} onClaimed={setSeat} />;
  return <SeatView code={code} seat={seat} onLeave={() => { clearSeat(); setSeat(null); }} navigate={navigate} />;
}

function ClaimSeat({
  code,
  onClaimed,
}: {
  code: string;
  onClaimed: (s: { code: string; token: string; entrantId: string; name: string }) => void;
}) {
  const [roster, setRoster] = useState<{ name: string; entrants: RosterEntry[] } | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    void getRoster(code)
      .then(setRoster)
      .catch((e) => setError(e instanceof TourneyError ? e.message : "No such tournament"));
  }, [code]);

  async function take(e: RosterEntry) {
    setBusy(true);
    setError(null);
    try {
      const res = await claimSeat(code, e.entrantId);
      const s = { code, token: res.entrantToken, entrantId: res.entrantId, name: res.name };
      saveSeat(s);
      onClaimed(s);
    } catch (err) {
      setError(err instanceof TourneyError ? err.message : "Could not claim that name");
      void getRoster(code).then(setRoster).catch(() => {});
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className="tq-play">
      <header>
        <h1>{roster?.name ?? code}</h1>
        <p className="tagline">Tap your name to check in</p>
      </header>
      {error && <p className="error">{error}</p>}
      <ul className="tq-claim">
        {roster?.entrants.map((e) => (
          <li key={e.entrantId}>
            <button
              className={e.claimed ? "ghost" : "primary"}
              disabled={busy || e.claimed || e.dropped}
              onClick={() => void take(e)}
            >
              {e.name}
              {e.claimed && <span className="seat-state">already checked in</span>}
              {e.dropped && <span className="seat-state">dropped</span>}
            </button>
          </li>
        ))}
      </ul>
      {roster && roster.entrants.length === 0 && (
        <p className="hint">The organizer hasn&rsquo;t added the roster yet — check back in a moment.</p>
      )}
    </main>
  );
}

function SeatView({
  code,
  seat,
  onLeave,
  navigate,
}: {
  code: string;
  seat: { code: string; token: string; entrantId: string; name: string };
  onLeave: () => void;
  navigate: ReturnType<typeof useNavigate>;
}) {
  const { state, error, clockOffset } = useTournament(code, seat.token);
  const [tick, setTick] = useState(0);
  const [called, setCalled] = useState(false);

  useEffect(() => {
    const id = setInterval(() => setTick((t) => t + 1), 1000);
    return () => clearInterval(id);
  }, []);

  const pod = state?.myPod ?? null;

  // the whole point of checking in: the round opens and the phone follows
  useEffect(() => {
    if (pod?.roomCode && pod.roomToken) {
      // the pod knows the room's code; Room resolves the address from the
      // session, and the code still works as a route for exactly that reason
      saveSession({ code: pod.roomCode, token: pod.roomToken });
      navigate(`/table/r/${pod.roomCode}`);
    }
  }, [pod?.roomCode, pod?.roomToken, navigate, pod]);

  const left = useMemo(
    () => secondsLeft(state?.round ?? null, Date.now(), clockOffset.current),
    [state?.round, tick, clockOffset],
  );

  const standing = state?.standings.find((s) => s.entrantId === seat.entrantId);

  return (
    <main className="tq-play">
      <header>
        <h1>{state?.tournament.name ?? code}</h1>
        <p className="tagline">Checked in as {seat.name}</p>
      </header>
      {error && <p className="error">{error}</p>}

      {state?.round && (
        <div className="tq-play-clock">
          <span className="tq-round">Round {state.round.number}</span>
          <span className={`tq-time${left !== null && left <= 300 ? " low" : ""}`}>
            {formatClock(left)}
          </span>
          {state.round.pausedAt && <span className="hint">paused</span>}
        </div>
      )}

      {pod ? (
        <p className="hint">Sending you to table {pod.table}…</p>
      ) : (
        <p className="notice">
          You&rsquo;re checked in. When the organizer starts the round this phone will open
          your table automatically — you don&rsquo;t need to do anything.
        </p>
      )}

      {standing && (
        <div className="tq-my-standing">
          <span className="tq-rank">{standing.rank}</span>
          <span className="hint">
            {standing.points} points after {standing.podsPlayed}{" "}
            {standing.podsPlayed === 1 ? "pod" : "pods"}
          </span>
        </div>
      )}

      {pod && state?.tournament.settings.allowOfficialCalls !== false && (
        <button
          className="ghost"
          disabled={called}
          onClick={() =>
            void callOfficial(code, pod.podId, seat.token)
              .then(() => setCalled(true))
              .catch(() => {})
          }
        >
          <Icon name="hand" label="Call an official" />
        </button>
      )}

      <footer>
        <button className="link" onClick={onLeave}>
          Not you? Check in as someone else
        </button>
      </footer>
    </main>
  );
}
