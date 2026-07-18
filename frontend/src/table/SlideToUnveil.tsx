import { useRef, useState } from "react";

const THUMB = 56;

export default function SlideToUnveil({ onUnveil }: { onUnveil: () => Promise<void> }) {
  const trackRef = useRef<HTMLDivElement>(null);
  const [x, setX] = useState(0);
  const [dragging, setDragging] = useState(false);
  const [busy, setBusy] = useState(false);
  const startX = useRef(0);

  const maxX = () => {
    const w = trackRef.current?.clientWidth ?? 280;
    return w - THUMB - 8;
  };

  function onPointerDown(e: React.PointerEvent<HTMLDivElement>) {
    e.stopPropagation();
    if (busy) return;
    (e.target as HTMLElement).setPointerCapture(e.pointerId);
    startX.current = e.clientX;
    setDragging(true);
  }

  function onPointerMove(e: React.PointerEvent<HTMLDivElement>) {
    e.stopPropagation();
    if (!dragging || busy) return;
    setX(Math.max(0, Math.min(maxX(), e.clientX - startX.current)));
  }

  async function onPointerUp(e: React.PointerEvent<HTMLDivElement>) {
    e.stopPropagation();
    if (!dragging || busy) return;
    setDragging(false);
    if (x >= maxX() * 0.9) {
      setBusy(true);
      setX(maxX());
      try {
        await onUnveil();
      } finally {
        setBusy(false);
        setX(0);
      }
    } else {
      setX(0);
    }
  }

  return (
    <div
      className="slide-track"
      ref={trackRef}
      onPointerDown={(e) => e.stopPropagation()}
      onContextMenu={(e) => e.preventDefault()}
    >
      <div className="slide-fill" style={{ width: x + THUMB }} />
      <span className="slide-label">{busy ? "Unveiling…" : "Slide to unveil to the table"}</span>
      <div
        className={`slide-thumb${dragging ? " dragging" : ""}`}
        style={{ transform: `translateX(${x}px)` }}
        onPointerDown={onPointerDown}
        onPointerMove={onPointerMove}
        onPointerUp={onPointerUp}
        onPointerCancel={onPointerUp}
      >
        ⟩⟩
      </div>
    </div>
  );
}
