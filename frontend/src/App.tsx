import { useEffect, useState } from "react";

interface Card {
  name: string;
  set_name: string;
  type_line: string;
  oracle_text: string | null;
  image: string | null;
  scryfall_uri: string;
}

export default function App() {
  const [health, setHealth] = useState<"checking" | "ok" | "down">("checking");
  const [card, setCard] = useState<Card | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetch("/api/health")
      .then((r) => (r.ok ? setHealth("ok") : setHealth("down")))
      .catch(() => setHealth("down"));
  }, []);

  async function drawCard() {
    setLoading(true);
    setError(null);
    try {
      const r = await fetch("/api/random-card");
      if (!r.ok) throw new Error(`API returned ${r.status}`);
      setCard(await r.json());
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }

  return (
    <main>
      <h1>mtg.skadoosh.dev</h1>
      <p className="status">
        API: <span className={health}>{health}</span>
      </p>
      <button onClick={drawCard} disabled={loading}>
        {loading ? "Drawing…" : "Draw a random card"}
      </button>
      {error && <p className="error">{error}</p>}
      {card && (
        <div className="card">
          {card.image && <img src={card.image} alt={card.name} />}
          <div className="card-info">
            <h2>{card.name}</h2>
            <p className="type">{card.type_line}</p>
            <p className="set">{card.set_name}</p>
            {card.oracle_text && <p className="oracle">{card.oracle_text}</p>}
            <a href={card.scryfall_uri} target="_blank" rel="noreferrer">
              View on Scryfall
            </a>
          </div>
        </div>
      )}
    </main>
  );
}
