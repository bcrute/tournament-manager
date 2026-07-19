import { useEffect, useMemo, useState } from "react";
import Icon from "../Icon";
import { RoomTournament } from "./api";

/**
 * The round clock, shown inside the pod's room — which is where players are
 * actually looking, not the tournament page they passed through once.
 *
 * Nothing here syncs a clock. The server sends one absolute deadline and its
 * own `now`; this counts down locally against that, using the difference only
 * to correct a device whose clock is wrong.
 *
 * When time is called the countdown is replaced by the additional-turns
 * counter (MTR 2.4: finish the turn, then play five more). The app can't see a
 * turn pass, so the table taps it through — which is what players already do
 * by hand.
 */
export default function RoundClock({
  t,
  onTurn,
}: {
  t: RoomTournament;
  onTurn: (delta: number) => void;
}) {
  const [, setTick] = useState(0);
  const offset = useMemo(() => t.now * 1000 - Date.now(), [t.now]);

  useEffect(() => {
    const id = setInterval(() => setTick((n) => n + 1), 1000);
    return () => clearInterval(id);
  }, []);

  if (t.turnsRemaining !== null) {
    return (
      <div className="round-clock turns">
        <div className="rc-turns-count">{t.turnsRemaining}</div>
        <div className="rc-turns-label">
          {t.turnsRemaining === 1 ? "final turn" : "turns left"}
        </div>
        <div className="rc-turn-buttons">
          <button className="ghost" onClick={() => onTurn(1)} title="Undo — or add a turn">
            <Icon name="plus" label="Add a turn" />
          </button>
          <button className="primary" onClick={() => onTurn(-1)}>
            <Icon name="check" /> Turn ended
          </button>
        </div>
      </div>
    );
  }

  const left = t.endsAt
    ? t.pausedAt
      ? Math.max(0, t.endsAt - t.pausedAt)
      : Math.max(0, Math.round(t.endsAt - (Date.now() + offset) / 1000))
    : null;

  return (
    <div className={`round-clock${left !== null && left <= 300 ? " low" : ""}`}>
      <span className="rc-round">
        R{t.round} · T{t.table}
      </span>
      <span className="rc-time">
        {left === null ? "—" : `${Math.floor(left / 60)}:${String(left % 60).padStart(2, "0")}`}
      </span>
      {t.pausedAt && (
        <span className="rc-paused">
          <Icon name="clock" /> paused
        </span>
      )}
    </div>
  );
}
