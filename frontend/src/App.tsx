import { useEffect, useState } from "react";
import { APPS, AppStatus } from "./apps";
import FanContentNotice from "./FanContentNotice";

const STATUS_LABEL: Record<AppStatus, string> = {
  live: "Live",
  dev: "In development",
  planned: "Planned",
};

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

      <footer>
        <span className={`dot ${health}`} /> API {health}
      </footer>

      <FanContentNotice />
    </main>
  );
}
