import { t } from "../i18n";
import Icon from "../Icon";
import { PlayerInfo } from "./api";

/**
 * The per-seat menu, opened by pressing and holding a card on the table view.
 *
 * It exists for the player whose phone is across the table, out of battery, or
 * simply not in their hand — the shared screen has to be able to act for them.
 */
export default function SeatMenu({
  player,
  onCantLose,
  onEliminate,
  onClose,
}: {
  player: PlayerInfo;
  onCantLose: (value: boolean) => void;
  onEliminate: (dead: boolean) => void;
  onClose: () => void;
}) {
  return (
    <div className="sheet-overlay" onPointerDown={onClose}>
      <div className="sheet seat-menu" onPointerDown={(e) => e.stopPropagation()}>
        <h2>{player.name}</h2>

        {player.cantLose ? (
          <button className="ghost" onClick={() => { onCantLose(false); onClose(); }}>
            <Icon name="warn" /> {t("life.cantLoseOff")}
          </button>
        ) : (
          <button className="ghost" onClick={() => { onCantLose(true); onClose(); }}>
            <Icon name="heart" /> {t("life.cantLoseAsk")}
          </button>
        )}

        {player.eliminated ? (
          <button className="ghost" onClick={() => { onEliminate(false); onClose(); }}>
            <Icon name="check" /> {t("life.undead")}
          </button>
        ) : (
          <button className="danger" onClick={() => { onEliminate(true); onClose(); }}>
            <Icon name="skull" /> {t("life.theyreDead", { name: player.name })}
          </button>
        )}

        <button className="ghost" onClick={onClose}>
          {t("common.close")}
        </button>
      </div>
    </div>
  );
}
