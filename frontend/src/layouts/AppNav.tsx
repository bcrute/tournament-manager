import { useEffect, useRef, useState } from "react";
import { Link, NavLink, useLocation } from "react-router-dom";
import Icon from "../Icon";
import { SITE_NAV } from "../nav";

/**
 * The app's one navigation bar.
 *
 * There used to be three answers to "where does navigation live": the site had a
 * top bar, the player shell duplicated that markup and also carried a bottom tab
 * strip, and the organizer console had no app navigation at all — once you were
 * running an event there was no way back to anything. Same question, three
 * answers, and the console's answer was "none".
 *
 * One bar now, in every layout. Links sit across the top where there is room and
 * collapse behind a hamburger where there is not, which is the same trade the
 * room bar already makes: a hamburger buys screen space a phone doesn't have and
 * a laptop does. The breakpoint (60rem) is deliberately the room bar's, so the
 * two never disagree about which mode a given screen is in.
 *
 * Interaction is the room bar's contract, for the same reason: Escape closes and
 * hands focus back, a pointer outside closes, and the trigger reports
 * `aria-expanded`. Deliberately *not* `role="menu"` — this project shipped that
 * once without arrow-key handling, which lies to a screen reader and breaks
 * every `getByRole("button")` query. A nav full of links is what this is.
 */
export default function AppNav() {
  const [open, setOpen] = useState(false);
  const wrap = useRef<HTMLDivElement>(null);
  const trigger = useRef<HTMLButtonElement>(null);
  const { pathname } = useLocation();

  // a link inside the panel navigates without unmounting this bar, so nothing
  // else would close it
  useEffect(() => setOpen(false), [pathname]);

  useEffect(() => {
    if (!open) return;
    const onDown = (e: PointerEvent) => {
      if (!wrap.current?.contains(e.target as Node)) setOpen(false);
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== "Escape") return;
      setOpen(false);
      trigger.current?.focus();
    };
    document.addEventListener("pointerdown", onDown);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("pointerdown", onDown);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);

  const listed = SITE_NAV.filter((n) => n.listed);

  return (
    <div className="app-bar" ref={wrap}>
      <Link to="/" className="site-logo">
        mtg<span>.skadoosh.dev</span>
      </Link>
      <button
        ref={trigger}
        className="app-menu-btn"
        aria-label="Site menu"
        aria-expanded={open}
        aria-haspopup="true"
        onClick={() => setOpen(!open)}
      >
        {/* the button already carries the name; a second one here would only
            give the same control two of them */}
        <Icon name="menu" />
      </button>
      <nav className={`app-nav${open ? " open" : ""}`} aria-label="Site">
        {listed.map((n) => (
          <NavLink
            key={n.to}
            to={n.to}
            className={({ isActive }) => (isActive ? "active" : undefined)}
          >
            <Icon name={n.icon} />
            <span>{n.label}</span>
          </NavLink>
        ))}
      </nav>
    </div>
  );
}
