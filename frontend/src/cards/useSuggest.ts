import { useEffect, useRef, useState } from "react";
import { CardError, Suggestions, suggestCards } from "./api";

/**
 * Debounced autocomplete, with the two failure modes that make a suggestion
 * box feel broken handled explicitly.
 *
 * **Out-of-order responses.** Type "bolt" quickly and four requests are in
 * flight; they can come back in any order, and the last one to land wins the
 * render. Without a sequence check the list settles on the answer for "bol"
 * while the box says "bolt" — which reads as the search being wrong rather
 * than late. Each request carries a number and a stale one is dropped.
 *
 * **The gap before the first keystroke resolves.** The list is left alone
 * while a new request is in flight rather than being cleared, because
 * blanking it on every keystroke produces a flicker that makes the whole
 * feature feel slower than it is.
 */

/** Long enough to skip most intermediate keystrokes, short enough that the
 *  list feels attached to the typing. */
export const DEBOUNCE_MS = 140;

export interface SuggestState {
  suggestions: string[];
  /** The index is still being built server-side; say so rather than "no
   *  results", which blames the person typing. */
  warmingUp: boolean;
  failed: boolean;
}

export function useSuggest(query: string, enabled = true): SuggestState {
  const [state, setState] = useState<SuggestState>({
    suggestions: [],
    warmingUp: false,
    failed: false,
  });
  const seq = useRef(0);

  useEffect(() => {
    const text = query.trim();
    if (!enabled || text.length < 2) {
      // One character matches thousands of cards, which is a list nobody
      // reads and a query nobody needs.
      setState({ suggestions: [], warmingUp: false, failed: false });
      return;
    }

    const mine = ++seq.current;
    const timer = setTimeout(() => {
      void suggestCards(text)
        .then((r: Suggestions) => {
          if (mine !== seq.current) return; // a newer keystroke has overtaken this
          setState({ suggestions: r.suggestions, warmingUp: !r.ready, failed: false });
        })
        .catch((e: unknown) => {
          if (mine !== seq.current) return;
          setState({
            suggestions: [],
            warmingUp: false,
            // A rate-limited or offline suggest box should not look like "that
            // card does not exist".
            failed: e instanceof CardError || e instanceof Error,
          });
        });
    }, DEBOUNCE_MS);

    return () => clearTimeout(timer);
  }, [query, enabled]);

  return state;
}
