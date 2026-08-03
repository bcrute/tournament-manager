import { useEffect, useRef, useState } from "react";
import Icon from "../Icon";
import SiteFooter from "../layouts/SiteFooter";
import { CardError, CardRulings, getRulings } from "./api";
import { useSuggest } from "./useSuggest";

/**
 * Card rulings, in as few taps as we can manage.
 *
 * This exists because four people are arguing at a table with a phone already
 * in someone's hand. Everything here is shaped by that: it needs no account,
 * no room and no tournament; the search box is focused on arrival; and the
 * suggestion list is keyboard- and thumb-navigable so the answer is three
 * letters and a tap away.
 *
 * The Scryfall link is not a fallback, it is part of the answer. Rulings are
 * one of several things someone might want (printings, legality, the actual
 * card image), and pretending this page replaces Scryfall would be worse than
 * pointing at it.
 */
export default function Rulings() {
  const [query, setQuery] = useState("");
  const [chosen, setChosen] = useState<string | null>(null);
  const [card, setCard] = useState<CardRulings | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [highlight, setHighlight] = useState(0);
  const box = useRef<HTMLInputElement>(null);

  // Suggestions are suppressed once a card is chosen: the query still holds
  // that card's name, so leaving them on would drop a list over the answer the
  // player just asked for.
  const { suggestions, warmingUp, failed } = useSuggest(query, chosen === null);

  useEffect(() => {
    box.current?.focus();
  }, []);

  useEffect(() => {
    setHighlight(0);
  }, [suggestions.length]);

  function choose(name: string) {
    setChosen(name);
    setQuery(name);
    setBusy(true);
    setError(null);
    setCard(null);
    void getRulings(name)
      .then(setCard)
      .catch((e: unknown) => {
        setError(e instanceof CardError ? e.message : "Could not load that card");
        // Enough to still offer a way out — the whole point is not being a
        // dead end.
        setCard(null);
      })
      .finally(() => setBusy(false));
  }

  function onKey(e: React.KeyboardEvent) {
    if (!suggestions.length) return;
    if (e.key === "ArrowDown") {
      e.preventDefault();
      setHighlight((h) => (h + 1) % suggestions.length);
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      setHighlight((h) => (h - 1 + suggestions.length) % suggestions.length);
    } else if (e.key === "Enter") {
      e.preventDefault();
      choose(suggestions[highlight]);
    } else if (e.key === "Escape") {
      setQuery("");
    }
  }

  const searching = chosen === null;

  return (
    <div className="ruling">
      <header className="ruling-head">
        <h1>Card rulings</h1>
        <p className="ruling-tagline">
          Official rulings for Magic cards. No account needed.
        </p>
      </header>

      <div className="ruling-search">
        <label className="ruling-field">
          <span className="ruling-label">Card name</span>
          <input
            ref={box}
            type="text"
            className="ruling-input"
            placeholder="Start typing a card name"
            autoCapitalize="none"
            autoCorrect="off"
            spellCheck={false}
            autoComplete="off"
            // The suggestion list is the combobox popup; announce it as one so
            // a screen reader user gets the same affordance as a sighted one.
            role="combobox"
            aria-expanded={searching && suggestions.length > 0}
            aria-controls="ruling-suggestions"
            aria-autocomplete="list"
            aria-activedescendant={
              searching && suggestions.length ? `ruling-option-${highlight}` : undefined
            }
            value={query}
            onChange={(e) => {
              setQuery(e.target.value);
              // Typing again means they are looking for something else.
              setChosen(null);
              setCard(null);
              setError(null);
            }}
            onKeyDown={onKey}
          />
        </label>

        {searching && (
          <>
            {suggestions.length > 0 && (
              <ul className="ruling-suggestions" id="ruling-suggestions" role="listbox">
                {suggestions.map((name, i) => (
                  <li key={name} role="none">
                    <button
                      type="button"
                      id={`ruling-option-${i}`}
                      role="option"
                      aria-selected={i === highlight}
                      className={`ruling-suggestion ${i === highlight ? "on" : ""}`}
                      // `onMouseDown` rather than `onClick`: a click fires
                      // after blur, and blur can tear the list down first.
                      onMouseDown={(e) => {
                        e.preventDefault();
                        choose(name);
                      }}
                    >
                      {name}
                    </button>
                  </li>
                ))}
              </ul>
            )}
            {warmingUp && (
              <p className="ruling-hint">
                Still loading the card list — try again in a moment.
              </p>
            )}
            {failed && (
              <p className="ruling-hint">
                Search is unavailable right now.{" "}
                <a
                  className="ruling-out"
                  href={`https://scryfall.com/search?q=${encodeURIComponent(query)}`}
                  target="_blank"
                  rel="noreferrer noopener"
                >
                  Look it up on Scryfall
                </a>
              </p>
            )}
            {!warmingUp && !failed && query.trim().length >= 2 && suggestions.length === 0 && (
              <p className="ruling-hint">No card matches that.</p>
            )}
          </>
        )}
      </div>

      {busy && <p className="ruling-hint">Looking that up…</p>}

      {error && (
        <div className="ruling-card">
          <p className="error">{error}</p>
          {/* Never a dead end: they have already spent the taps. */}
          <a
            className="ruling-out"
            href={`https://scryfall.com/search?q=${encodeURIComponent(chosen ?? query)}`}
            target="_blank"
            rel="noreferrer noopener"
          >
            Look it up on Scryfall <Icon name="chevron" />
          </a>
        </div>
      )}

      {card && (
        <article className="ruling-card">
          <h2 className="ruling-name">{card.name}</h2>
          <p className="ruling-type">
            {[card.typeLine, card.manaCost].filter(Boolean).join("  ")}
          </p>
          {card.oracleText && <p className="ruling-oracle">{card.oracleText}</p>}

          <h3 className="ruling-section">
            Rulings{card.rulings.length ? ` (${card.rulings.length})` : ""}
          </h3>
          {card.rulings.length === 0 ? (
            <p className="ruling-hint">
              This card has no official rulings — which is usually a good sign that
              it does what it says.
            </p>
          ) : (
            <ol className="ruling-list">
              {card.rulings.map((r, i) => (
                <li key={i} className="ruling-item">
                  <p>{r.text}</p>
                  <p className="ruling-meta">
                    {r.at}
                    {r.source && r.source !== "wotc" ? ` · ${r.source}` : ""}
                  </p>
                </li>
              ))}
            </ol>
          )}

          <a
            className="ruling-out"
            href={card.scryfallUrl}
            target="_blank"
            rel="noreferrer noopener"
          >
            Full card on Scryfall <Icon name="chevron" />
          </a>
        </article>
      )}

      <p className="ruling-credit">
        Rulings are written by Wizards of the Coast and served through{" "}
        <a
          className="ruling-out"
          href="https://scryfall.com"
          target="_blank"
          rel="noreferrer noopener"
        >
          Scryfall
        </a>
        . This app is unofficial and unaffiliated with either.
      </p>

      <SiteFooter />
    </div>
  );
}
