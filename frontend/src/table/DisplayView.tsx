import { useState } from "react";
import { QRCodeSVG } from "qrcode.react";
import { api, PlayerInfo, RoomState } from "./api";

export default function DisplayView({
  state,
  code,
  token,
  onLeave,
}: {
  state: RoomState;
  code: string;
  token: string;
  onLeave: () => void;
}) {
  const [editing, setEditing] = useState<{ pid: number; name: string } | null>(null);
  const lobby = state.room.status === "lobby";
  const ended = state.room.status === "ended";
  const joinUrl = `${location.origin}/table?join=${code}`;
  const nameOf = new Map(state.players.map((p) => [String(p.pid), p.name]));

  async function adjust(playerPid: number, delta: number) {
    await api(`/rooms/${code}/life`, { method: "POST", token, body: { playerPid, delta } });
  }

  return (
    <main className="display-view">
      <header className="display-head">
        <span className="display-code">{code}</span>
        <span className="display-mode">
          {state.room.mode === "treachery" ? "⚔ Treachery" : "♥ Life"}
          {ended && " — game over"}
        </span>
        <button className="ghost" onClick={onLeave}>
          Disconnect
        </button>
      </header>

      {lobby ? (
        <div className="display-lobby">
          <div className="qr big">
            <QRCodeSVG value={joinUrl} size={220} bgColor="#14101c" fgColor="#e8e4f0" marginSize={2} />
          </div>
          <p className="tagline">Scan to join · room {code}</p>
          <ul className="display-roster">
            {state.players.map((p) => (
              <li key={p.pid}>
                {p.name}
                {p.isHost ? " ♛" : ""}
              </li>
            ))}
          </ul>
        </div>
      ) : (
        <div className="display-grid">
          {state.players.map((p) => (
            <DisplayTile
              key={p.pid}
              p={p}
              first={state.room.firstPid === p.pid}
              nameOf={nameOf}
              onTap={() => setEditing({ pid: p.pid, name: p.name })}
            />
          ))}
        </div>
      )}

      <div className="display-log">
        {state.log.slice(0, 4).map((e, i) => (
          <div key={`${e.at}-${i}`} className="display-log-line">
            {e.text}
          </div>
        ))}
      </div>

      {editing && (
        <div className="edit-overlay" onClick={() => setEditing(null)}>
          <div className="edit-box" onClick={(e) => e.stopPropagation()}>
            <h2>{editing.name}</h2>
            <div className="life-buttons">
              <button onClick={() => void adjust(editing.pid, -5)}>−5</button>
              <button onClick={() => void adjust(editing.pid, -1)}>−1</button>
              <button onClick={() => void adjust(editing.pid, 1)}>+1</button>
              <button onClick={() => void adjust(editing.pid, 5)}>+5</button>
            </div>
            <button className="ghost" onClick={() => setEditing(null)}>
              done
            </button>
          </div>
        </div>
      )}
    </main>
  );
}

function DisplayTile({
  p,
  first,
  nameOf,
  onTap,
}: {
  p: PlayerInfo;
  first: boolean;
  nameOf: Map<string, string>;
  onTap: () => void;
}) {
  return (
    <button className={`display-tile${p.eliminated ? " dead" : ""}${p.left ? " gone" : ""}`} onClick={onTap}>
      <span className="display-name">
        {first && "👑 "}
        {p.name}
        {p.card ? ` · ${p.card.role}` : ""}
      </span>
      <span className="display-life">{p.eliminated ? "☠" : (p.life ?? "—")}</span>
      {Object.keys(p.cmdDamage).length > 0 && (
        <span className="display-cmd">
          {Object.entries(p.cmdDamage)
            .map(([fromPid, amt]) => `${amt}⚔${nameOf.get(fromPid) ?? "?"}`)
            .join("  ")}
        </span>
      )}
    </button>
  );
}
