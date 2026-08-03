import { useState } from "react";
import { QRCodeSVG } from "qrcode.react";
import { t } from "../i18n";
import Icon from "../Icon";
import { invitationLink } from "./qrPayload";

/**
 * The room's QR code, on demand.
 *
 * The lobby already shows one, but it disappears once the game starts — which
 * is exactly when someone arrives late, or a phone dies and needs to rejoin.
 */
export default function QrSheet({
  roomId,
  onClose,
}: {
  /** The room's public identifier — the thing that actually lets someone in. */
  roomId: string;
  onClose: () => void;
}) {
  const joinUrl = invitationLink(location.origin, roomId);
  const [copied, setCopied] = useState(false);
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
        {/* The identifier is 128 bits — nobody is reading it across a table,
            so the useful action is copying the link rather than displaying a
            value to retype. The five-character code is no longer shown here at
            all: it opens nothing, and putting it beside a QR that does would
            say otherwise. */}
        <button
          className="primary copy-invite"
          onClick={() => {
            void navigator.clipboard
              ?.writeText(joinUrl)
              .then(() => setCopied(true))
              .catch(() => {});
          }}
        >
          <Icon name="note" /> {copied ? t("qr.copied") : t("qr.copy")}
        </button>
        <p className="hint">{t("qr.hint")}</p>
      </div>
    </div>
  );
}
