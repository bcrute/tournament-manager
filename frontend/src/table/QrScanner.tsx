import { useEffect, useRef, useState } from "react";
import { t } from "../i18n";
import Icon from "../Icon";
import { codeFromScan } from "./qrPayload";

/**
 * Scan a room's QR code with the device camera.
 *
 * Uses the built-in `BarcodeDetector`, which is available in Chrome and
 * Android browsers but **not in Safari or Firefox**. Rather than pull in a
 * decoder library for the gap, the fallback points at the thing that already
 * works everywhere: the phone's own camera app, which opens the room link
 * directly. That path predates this component and stays the primary one.
 *
 * The camera is requested only when this opens, and the track is stopped on
 * every exit — including an error or an unmount mid-scan. A camera left
 * running behind a closed sheet is the kind of thing people rightly notice.
 */

interface BarcodeLike {
  rawValue: string;
}

type DetectorCtor = new (opts: { formats: string[] }) => {
  detect: (source: CanvasImageSource) => Promise<BarcodeLike[]>;
};

export function scanSupported(): boolean {
  return typeof window !== "undefined" && "BarcodeDetector" in window;
}

export default function QrScanner({
  onCode,
  onClose,
}: {
  onCode: (code: string) => void;
  onClose: () => void;
}) {
  const video = useRef<HTMLVideoElement>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!scanSupported()) {
      setError(t("scan.unsupported"));
      return;
    }
    let stream: MediaStream | null = null;
    let raf = 0;
    let stopped = false;

    const stop = () => {
      stopped = true;
      cancelAnimationFrame(raf);
      stream?.getTracks().forEach((track) => track.stop());
      stream = null;
    };

    void (async () => {
      try {
        // the rear camera is the one pointed at the table
        stream = await navigator.mediaDevices.getUserMedia({
          video: { facingMode: "environment" },
        });
        if (stopped) {
          stream.getTracks().forEach((tr) => tr.stop());
          return;
        }
        if (video.current) {
          video.current.srcObject = stream;
          await video.current.play();
        }
        const Detector = (window as unknown as { BarcodeDetector: DetectorCtor })
          .BarcodeDetector;
        const detector = new Detector({ formats: ["qr_code"] });

        const tick = async () => {
          if (stopped || !video.current) return;
          try {
            const found = await detector.detect(video.current);
            for (const b of found) {
              const code = codeFromScan(b.rawValue);
              if (code) {
                stop();
                onCode(code);
                return;
              }
            }
          } catch {
            /* a frame that couldn't be decoded is normal; keep looking */
          }
          raf = requestAnimationFrame(() => void tick());
        };
        raf = requestAnimationFrame(() => void tick());
      } catch (e) {
        // a refused permission is a choice, not a failure — say so plainly
        const denied = e instanceof DOMException && e.name === "NotAllowedError";
        setError(denied ? t("scan.denied") : t("scan.failed"));
        stop();
      }
    })();

    return stop;
  }, [onCode]);

  return (
    <div className="sheet-overlay" onPointerDown={onClose}>
      <div className="sheet scan-sheet" onPointerDown={(e) => e.stopPropagation()}>
        <button className="sheet-back" onClick={onClose} aria-label={t("common.close")}>
          <Icon name="back" /> {t("common.close")}
        </button>
        <h2>{t("scan.title")}</h2>

        {error ? (
          <>
            <p className="notice warn">{error}</p>
            <p className="hint">{t("scan.useCameraApp")}</p>
          </>
        ) : (
          <>
            {/* muted + playsInline: iOS refuses to autoplay otherwise */}
            <video ref={video} className="scan-video" muted playsInline aria-label={t("scan.title")} />
            <p className="hint">{t("scan.hint")}</p>
          </>
        )}
      </div>
    </div>
  );
}
