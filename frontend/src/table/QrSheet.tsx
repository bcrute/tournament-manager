import { QRCodeSVG } from "qrcode.react";
import { t } from "../i18n";
import Icon from "../Icon";

/**
 * The room's QR code, on demand.
 *
 * The lobby already shows one, but it disappears once the game starts — which
 * is exactly when someone arrives late, or a phone dies and needs to rejoin.
 */
export default function QrSheet({ code, onClose }: { code: string; onClose: () => void }) {
  const joinUrl = `${location.origin}/table?join=${code}`;
  return (
    <div className="sheet-overlay" onPointerDown={onClose}>
      <div className="sheet qr-sheet" onPointerDown={(e) => e.stopPropagation()}>
        <button className="sheet-back" onClick={onClose} aria-label={t("common.close")}>
          <Icon name="back" /> {t("common.close")}
        </button>
        <h2>{t("menu.showQr")}</h2>
        <div className="qr-holder">
          {/* a light quiet zone: cameras struggle with a code on a dark field */}
          <QRCodeSVG value={joinUrl} size={220} includeMargin bgColor="#ffffff" fgColor="#000000" />
        </div>
        <p className="room-code-big" aria-label={`Room code ${code.split("").join(" ")}`}>
          {code}
        </p>
        <p className="hint">{t("qr.hint")}</p>
      </div>
    </div>
  );
}
