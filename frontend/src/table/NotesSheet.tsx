import { useEffect, useState } from "react";
import { AccountError, getNote, saveNote } from "./account";
import Icon from "../Icon";

/**
 * Private notes for one game. Reachable mid-game from the ⋮ menu and later from
 * the dashboard. Saves on close and on demand; notes are visible only to their
 * author.
 */
export default function NotesSheet({
  code,
  gameNo,
  onClose,
  onNeedsAccount,
}: {
  code: string;
  gameNo: number;
  onClose: () => void;
  onNeedsAccount: () => void;
}) {
  const [text, setText] = useState("");
  const [loaded, setLoaded] = useState(false);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    getNote(code, gameNo)
      .then((n) => {
        setText(n.text);
        setLoaded(true);
      })
      .catch((e) => {
        if (e instanceof AccountError && e.status === 401) onNeedsAccount();
        else setError("Couldn't load your note");
      });
  }, [code, gameNo, onNeedsAccount]);

  async function persist() {
    setSaving(true);
    setError(null);
    try {
      await saveNote(code, gameNo, text);
      setSaved(true);
      window.setTimeout(() => setSaved(false), 1500);
    } catch (e) {
      setError(e instanceof AccountError ? e.message : "Couldn't save");
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="sheet-overlay" onClick={onClose}>
      <div className="sheet" onClick={(e) => e.stopPropagation()}>
        <h2>Notes · game {gameNo}</h2>
        <p className="hint">Private to you. Nobody else at the table can see this.</p>
        <textarea
          className="note-input"
          rows={8}
          placeholder="Who did what, what to remember for next time…"
          value={text}
          disabled={!loaded}
          onChange={(e) => setText(e.target.value)}
        />
        {error && <p className="error">{error}</p>}
        <button className="primary" disabled={saving || !loaded} onClick={() => void persist()}>
          {saving ? "Saving…" : saved ? <><Icon name="check" /> Saved</> : "Save"}
        </button>
        <button
          className="ghost"
          onClick={() => {
            if (loaded) void persist().then(onClose);
            else onClose();
          }}
        >
          Close
        </button>
      </div>
    </div>
  );
}
