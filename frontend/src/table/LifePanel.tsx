import { useState } from "react";
import { api, RoomState } from "./api";
import { useDebouncedDelta } from "./useDebouncedDelta";

export default function LifePanel({
  state,
  code,
  token,
}: {
  state: RoomState;
  code: string;
  token: string;
}) {
  const me = state.me;
  const { pending, bump } = useDebouncedDelta((delta) =>
    api(`/rooms/${code}/life`, { method: "POST", token, body: { delta } }).then(() => undefined),
  );
  const [cmdOpen, setCmdOpen] = useState(false);

  const life = (me.life ?? state.room.startingLife) + pending;
  const opponents = state.players.filter((p) => !p.isMe && !p.left);
  const lethal = Object.values(me.cmdDamage).some((v) => v >= 21);

  async function cmd(attacker: string, delta: number) {
    await api(`/rooms/${code}/cmddmg`, { method: "POST", token, body: { attacker, delta } });
  }

  async function eliminate(undo: boolean) {
    if (!undo && !window.confirm(
      state.room.mode === "treachery"
        ? "Mark yourself eliminated? Your identity will be revealed."
        : "Mark yourself eliminated?",
    ))
      return;
    await api(`/rooms/${code}/eliminate`, { method: "POST", token, body: { undo } });
  }

  return (
    <div className="life-panel">
      {me.eliminated ? (
        <div className="dead-banner">
          ☠ Eliminated
          <button className="ghost" onClick={() => void eliminate(true)}>
            undo
          </button>
        </div>
      ) : (
        <>
          <div className={`life-big${pending !== 0 ? " pending" : ""}${life <= 0 ? " zero" : ""}`}>
            {life}
            {pending !== 0 && (
              <span className="pending-tag">
                {pending > 0 ? "+" : ""}
                {pending}
              </span>
            )}
          </div>
          <div className="life-buttons">
            <button onClick={() => bump(-5)}>−5</button>
            <button onClick={() => bump(-1)}>−1</button>
            <button onClick={() => bump(1)}>+1</button>
            <button onClick={() => bump(5)}>+5</button>
          </div>
        </>
      )}

      {lethal && <p className="error">⚠ 21+ commander damage from one commander is lethal</p>}

      <button className="ghost cmd-toggle" onClick={() => setCmdOpen(!cmdOpen)}>
        {cmdOpen ? "▾ " : "▸ "}Commander damage
      </button>
      {cmdOpen && (
        <div className="cmd-list">
          {opponents.length === 0 && <p className="tagline">No opponents yet</p>}
          {opponents.map((p) => {
            const amt = me.cmdDamage[p.name] ?? 0;
            return (
              <div key={p.name} className={`cmd-row${amt >= 21 ? " lethal" : ""}`}>
                <span className="cmd-name">{p.name}</span>
                <button onClick={() => void cmd(p.name, -1)} disabled={amt === 0}>
                  −
                </button>
                <span className="cmd-amt">{amt}</span>
                <button onClick={() => void cmd(p.name, 1)}>+</button>
              </div>
            );
          })}
          <p className="hint">+1 here also subtracts 1 life (commander damage is damage)</p>
        </div>
      )}

      {!me.eliminated && (
        <button className="ghost die-btn" onClick={() => void eliminate(false)}>
          ☠ I&rsquo;m dead
        </button>
      )}
    </div>
  );
}
