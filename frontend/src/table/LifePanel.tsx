import { useEffect, useState } from "react";
import { api, RoomState } from "./api";
import { t } from "../i18n";
import Icon from "../Icon";
import { useDebouncedDelta } from "./useDebouncedDelta";
import { halfDelta } from "./SeatTile";
import { useHoldRepeat } from "./useHoldRepeat";

const LETHAL_COMMANDER_DAMAGE = 21;
const LETHAL_POISON = 10;

/**
 * Seconds left before the game ends on its own, or null when nothing is
 * pending. Counted against the server's clock rather than the device's, since
 * a phone an hour out would otherwise show a countdown an hour wrong.
 */
function useCountdown(concludesAt: number | null, serverNow: number): number | null {
  const [remaining, setRemaining] = useState<number | null>(null);

  useEffect(() => {
    if (concludesAt === null) {
      setRemaining(null);
      return;
    }
    // how far this device's clock is from the server's, measured once when the
    // countdown appears and then held — re-deriving it every tick would let
    // ordinary jitter make the number jump around
    const skew = Date.now() / 1000 - serverNow;
    const tick = () => {
      const left = Math.ceil(concludesAt - (Date.now() / 1000 - skew));
      setRemaining(left > 0 ? left : 0);
    };
    tick();
    const id = setInterval(tick, 250);
    return () => clearInterval(id);
    // serverNow changes on every poll; the countdown must not restart with it
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [concludesAt]);

  return remaining;
}

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
  // holding a side runs in tens; each repeat goes through the same debounced
  // batch as a tap, so a long hold is still one request
  const hold = useHoldRepeat((delta) => bump(delta));

  const life = (me.life ?? state.room.startingLife) + pending;
  // your own commander can be turned against you, so you are on this list too
  const sources = state.players.filter((p) => !p.left);
  const worstCmd = Math.max(0, ...Object.values(me.cmdDamage));
  const countdown = useCountdown(state.room.concludesAt, state.room.now);
  // shown only to the player it is about: everyone else sees the log
  const endingOnMe = me.eliminated && countdown !== null;

  /** Why the app called it, in the player's own terms. */
  function deathReason(): string {
    if (me.poison >= LETHAL_POISON) return t("life.byPoison");
    if (worstCmd >= LETHAL_COMMANDER_DAMAGE) return t("life.byCommander");
    return t("life.byLife");
  }

  async function setCantLose(value: boolean) {
    try {
      await api(`/rooms/${code}/cantlose`, { method: "POST", token, body: { value } });
    } catch {
      /* the next state push corrects it */
    }
  }

  async function cmd(attackerPid: number, delta: number) {
    await api(`/rooms/${code}/cmddmg`, { method: "POST", token, body: { attackerPid, delta } });
  }

  async function poison(delta: number) {
    await api(`/rooms/${code}/poison`, { method: "POST", token, body: { delta } });
  }

  /**
   * "I'm not dead" — back in, and the app stops calling the counters lethal.
   *
   * Only `undo` goes over the wire: the server suppresses the thresholds
   * itself when the counters would still be lethal, so every route back in
   * behaves the same way — this button, and the table display reviving
   * someone whose phone is flat.
   */
  async function notDead() {
    await api(`/rooms/${code}/eliminate`, { method: "POST", token, body: { undo: true } });
  }

  async function lostOtherWay() {
    if (
      !window.confirm(
        state.room.mode === "treachery"
          ? "Mark yourself out? Your identity will be revealed."
          : "Mark yourself out?",
      )
    )
      return;
    await api(`/rooms/${code}/eliminate`, { method: "POST", token, body: { undo: false } });
  }

  return (
    <div className="life-panel">
      {me.eliminated ? (
        <div className={`dead-banner${endingOnMe ? " ending" : ""}`}>
          <p className="dead-title">
            <Icon name="skull" size={28} /> {t("life.autoOut")}
          </p>
          <p className="dead-why">{t("life.autoOutBy", { reason: deathReason() })}</p>

          {endingOnMe && (
            <div className="dead-countdown" role="status" aria-live="assertive">
              <span className="dead-secs">{t("life.endingIn", { n: String(countdown) })}</span>
              <p className="hint">{t("life.endingWhy")}</p>
            </div>
          )}

          {/* the primary action while dead: the whole point of not asking first */}
          <button className="primary not-dead" onClick={() => void notDead()}>
            <Icon name="heart" /> {t("life.notDead")}
          </button>
        </div>
      ) : (
        // The total is the control. Four fixed buttons meant going from 40 to
        // 12 was a spelling exercise; tapping a side moves one, holding it runs
        // in tens. Same gesture the table view uses, so a player who learns it
        // on one screen has learned it on both.
        <div
          className={`life-big${pending !== 0 ? " pending" : ""}${life <= 0 ? " zero" : ""}`}
          onPointerDown={(e) => {
            const dir = halfDelta(e.target);
            if (dir !== null) hold.begin(dir);
          }}
          onPointerUp={(e) => {
            // a hold already moved it in tens; don't add the tap on top
            if (hold.end()) return;
            const dir = halfDelta(e.target);
            if (dir !== null) bump(dir);
          }}
          onPointerCancel={() => hold.cancel()}
          onPointerLeave={() => hold.cancel()}
        >
          <button
            className="life-half dec"
            data-delta="-1"
            aria-label={t("life.minus", { name: me.name, n: 1 })}
          />
          <button
            className="life-half inc"
            data-delta="1"
            aria-label={t("life.plus", { name: me.name, n: 1 })}
          />
          <span className="life-number">{life}</span>
          {pending !== 0 && (
            <span className="pending-tag">
              {pending > 0 ? "+" : ""}
              {pending}
            </span>
          )}
        </div>
      )}

      {me.cantLose && (
        <div className="cant-lose on">
          <p>
            <Icon name="check" /> {t("life.cantLoseOn")}
          </p>
          <p className="hint">{t("life.cantLoseWhy")}</p>
          <button className="ghost" onClick={() => void setCantLose(false)}>
            {t("life.cantLoseOff")}
          </button>
        </div>
      )}

      {/* One row, always present while you're alive. Most games never see a
          poison counter, but hiding the row at zero would leave no way to add
          the first one — so it stays, compact, and only turns red at ten. It
          disappears once you're out, where the banner is the only thing worth
          reading. */}
      {(me.poison > 0 || !me.eliminated) && (
        <div className={`poison-row${me.poison >= LETHAL_POISON ? " lethal" : ""}`}>
          <span className="poison-label">
            <Icon name="skull" /> {t("life.poison")}
          </span>
          <button
            aria-label={t("life.poisonRemove")}
            onClick={() => void poison(-1)}
            disabled={me.poison === 0}
          >
            −
          </button>
          <span className="poison-amt">{me.poison}</span>
          <button aria-label={t("life.poisonAdd")} onClick={() => void poison(1)}>
            +
          </button>
          {me.poison > 0 && me.poison < LETHAL_POISON && (
            <span className="hint">{t("life.poisonLethal")}</span>
          )}
        </div>
      )}

      <button
        className="ghost cmd-toggle"
        aria-expanded={cmdOpen}
        onClick={() => setCmdOpen(!cmdOpen)}
      >
        <Icon name="chevron" className={cmdOpen ? "" : "collapsed"} />
        <Icon name="sword" /> {t("life.commanderDamage")}
      </button>
      {cmdOpen && (
        <div className="cmd-list">
          {sources.length === 0 && <p className="tagline">No players yet</p>}
          {sources.map((p) => {
            const amt = me.cmdDamage[String(p.pid)] ?? 0;
            return (
              <div
                key={p.pid}
                className={`cmd-row${amt >= LETHAL_COMMANDER_DAMAGE ? " lethal" : ""}`}
              >
                <span className="cmd-name">
                  {p.name}
                  {p.isMe && ` (${t("life.ownCommander")})`}
                </span>
                <button onClick={() => void cmd(p.pid, -1)} disabled={amt === 0}>
                  −
                </button>
                <span className="cmd-amt">{amt}</span>
                <button onClick={() => void cmd(p.pid, 1)}>+</button>
              </div>
            );
          })}
          <p className="hint">+1 here also subtracts 1 life (commander damage is damage)</p>
        </div>
      )}

      {/* Kept, and deliberately quiet. The counters can't see decking, Approach
          of the Second Sun, or anything else that just says you lose — without
          this the player has no way out and the table waits on them. */}
      {!me.eliminated && (
        <div className="other-loss">
          <button className="ghost die-btn" onClick={() => void lostOtherWay()}>
            <Icon name="skull" /> {t("life.lostOtherWay")}
          </button>
          <p className="hint">{t("life.lostOtherWayWhy")}</p>
        </div>
      )}
    </div>
  );
}
