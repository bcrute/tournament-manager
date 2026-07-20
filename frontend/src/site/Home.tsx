import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import Icon from "../Icon";

/**
 * The public front page.
 *
 * One page for now, but structured as a website rather than a launcher: what
 * this is, what you can do, and two clear ways in. Sections are separate blocks
 * so adding a page later means moving one out, not unpicking a tile grid.
 */
export default function Home() {
  const [health, setHealth] = useState<"checking" | "ok" | "down">("checking");

  useEffect(() => {
    fetch("/api/health")
      .then((r) => (r.ok ? setHealth("ok") : setHealth("down")))
      .catch(() => setHealth("down"));
  }, []);

  return (
    <>
      <section className="hero">
        <h1>Everything at the table, on the phones already there.</h1>
        <p className="lede">
          Life totals, commander damage, hidden roles and full tournaments — shared
          across every device at the table. No app to install, and no account needed
          to play.
        </p>
        <div className="hero-actions">
          <Link className="cta" to="/table">
            <Icon name="heart" /> Start a game
          </Link>
          <Link className="cta ghost" to="/tournament">
            <Icon name="crown" /> Run a tournament
          </Link>
        </div>
      </section>

      <section className="features">
        <article>
          <h2>
            <Icon name="heart" /> Shared life tracker
          </h2>
          <p>
            Every player adjusts their own total from their own phone, and the table
            display keeps everyone honest. Commander damage included — including from
            your own commander.
          </p>
        </article>
        <article>
          <h2>
            <Icon name="card" /> Hidden roles
          </h2>
          <p>
            Deal secret identities to the table, peek privately, and unveil when you
            choose. Your role survives a refresh, a dropped connection, and a dead
            battery.
          </p>
        </article>
        <article>
          <h2>
            <Icon name="crown" /> Tournaments
          </h2>
          <p>
            Swiss pairings over pods, seating, round timers and standings. Players scan
            one code and their phone follows them from table to table for the rest of
            the event.
          </p>
        </article>
        <article>
          <h2>
            <Icon name="users" /> No sign-up wall
          </h2>
          <p>
            Playing never needs an account. Make one only if you want your game history
            and private notes kept — hosting a tournament is the one exception.
          </p>
        </article>
      </section>

      <section className="stance">
        <h2>
          <Icon name="check" /> Built privacy-first, and checkable
        </h2>
        <ul>
          <li>
            <strong>No accounts to play.</strong> No email, no password, no name beyond
            the one you type at the table.
          </li>
          <li>
            <strong>No tracking, no analytics, no ads.</strong> Nothing about you is
            measured, profiled, sold or shared.
          </li>
          <li>
            <strong>No third-party requests at all.</strong> No CDN, no hosted fonts, no
            embedded widgets — the page loads from this server and nowhere else, and the
            browser is told to enforce it.
          </li>
          <li>
            <strong>No cookie banner</strong>, because there is nothing to consent to.
            Everything stored is what makes your game work.
          </li>
          <li>
            <strong>Your address is never stored.</strong> Rate limiting uses a salted
            hash, kept thirty days.
          </li>
        </ul>
        <p>
          <Link className="cta ghost" to="/privacy">
            Read exactly what is stored
          </Link>
        </p>
      </section>

      <section className="shots">
        <h2>What it looks like</h2>
        <p className="lede">
          Real screens, captured from the running app — not mockups.
        </p>
        <div className="shot-strip">
          {[
            ["table-player", "Your own phone: life, commander damage, and nothing else in the way."],
            ["table-display", "One phone showing the whole table, without giving up its seat."],
            ["table-commander", "Commander damage as a grid — left to remove, right to add."],
            ["tournament-console", "Running an event: pods, pairings, timer and judge calls."],
            ["tournament-standings", "Standings players can read from inside their game."],
          ].map(([file, caption]) => (
            <figure key={file}>
              <img
                src={`/shots/${file}.png`}
                alt={caption}
                loading="lazy"
                width={390}
                height={844}
              />
              <figcaption>{caption}</figcaption>
            </figure>
          ))}
        </div>
      </section>

      <section className="site-status">
        <span className={`dot ${health}`} /> Service {health}
      </section>
    </>
  );
}
