import { useEffect, useState } from "react";
import { APPS, AppStatus } from "./apps";

interface Card {
  name: string;
  set_name: string;
  type_line: string;
  oracle_text: string | null;
  image: string | null;
  scryfall_uri: string;
}

const STATUS_LABEL: Record<AppStatus, string> = {
  live: "Live",
  dev: "In development",
  planned: "Planned",
};

function RandomCard() {
  const [card, setCard] = useState<Card | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

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
    <section className="draw">
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
    </section>
  );
}

export default function App() {
  const [health, setHealth] = useState<"checking" | "ok" | "down">("checking");

  useEffect(() => {
    fetch("/api/health")
      .then((r) => (r.ok ? setHealth("ok") : setHealth("down")))
      .catch(() => setHealth("down"));
  }, []);

  return (
    <main>
      <header>
        <h1>mtg.skadoosh.dev</h1>
        <p className="tagline">Magic apps for the table</p>
      </header>

      <section className="apps">
        {APPS.map((app) => {
          const tile = (
            <div key={app.name} className={`tile ${app.status}`}>
              <div className="tile-head">
                <h2>{app.name}</h2>
                <span className={`badge ${app.status}`}>{STATUS_LABEL[app.status]}</span>
              </div>
              <p>{app.description}</p>
            </div>
          );
          return app.status === "live" && app.href ? (
            <a key={app.name} href={app.href} className="tile-link">
              {tile}
            </a>
          ) : (
            tile
          );
        })}
      </section>

      <RandomCard />

      <footer>
        <span className={`dot ${health}`} /> API {health}
      </footer>
    </main>
  );
}
