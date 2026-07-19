import { useEffect } from "react";
import { t } from "../i18n";
import Icon from "../Icon";
import { PlayerInfo } from "./api";

/**
 * Commander damage editor, opened from a seat's damage grid on the table
 * display.
 *
 * The interaction deliberately matches the seat cards behind it: tap the left
 * half of a row to take damage off, the right half to add. Someone who has
 * learned the table has already learned this.
 *
 * Everything outside the panel closes it — including the X, which is a normal
 * button but sits on the backdrop, so it would close the sheet even if its own
 * handler did nothing. It exists because "tap anywhere outside" is not
 * discoverable on a screen across the table; the affordance is the point.
 */
export default function CmdDamageSheet({
  defender,
  sources,
  onChange,
  onClose,
}: {
  defender: PlayerInfo;
  /** Every seat that could have dealt damage, in turn order. Includes the
   *  defender: a player's own commander can be turned against them. */
  sources: { pid: number; seat: number; name: string }[];
  onChange: (attackerPid: number, delta: number) => void;
  onClose: () => void;
}) {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  return (
    <div
      className="cmd-backdrop"
      onPointerDown={onClose}
      role="dialog"
      aria-modal="true"
      aria-label={t("cmd.editFor", { name: defender.name })}
    >
      <button className="cmd-close" onClick={onClose} aria-label={t("common.close")}>
        <Icon name="close" size={30} />
      </button>

      <div
        className="cmd-panel"
        onPointerDown={(e) => e.stopPropagation()}
        onClick={(e) => e.stopPropagation()}
      >
        <header>
          <h2>{defender.name}</h2>
          <p className="hint">{t("cmd.tapHint")}</p>
        </header>

        <ul className="cmd-rows">
          {sources.map((s) => {
            const amount = defender.cmdDamage[String(s.pid)] ?? 0;
            const own = s.pid === defender.pid;
            return (
              <li
                key={s.pid}
                className={`cmd-row${amount >= 21 ? " lethal" : ""}${own ? " own" : ""}`}
              >
                <button
                  className="cmd-half dec"
                  onClick={() => onChange(s.pid, -1)}
                  aria-label={t("cmd.minus", { name: s.name })}
                >
                  <Icon name="minus" />
                </button>

                <span className="cmd-row-face">
                  <span className="cmd-row-src">
                    <b>{s.seat}</b> {s.name}
                    {own && <em> {t("cmd.own")}</em>}
                  </span>
                  <span className="cmd-row-amt">{amount}</span>
                </span>

                <button
                  className="cmd-half inc"
                  onClick={() => onChange(s.pid, 1)}
                  aria-label={t("cmd.plus", { name: s.name })}
                >
                  <Icon name="plus" />
                </button>
              </li>
            );
          })}
        </ul>
      </div>
    </div>
  );
}
