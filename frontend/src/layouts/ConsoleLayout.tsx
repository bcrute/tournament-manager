import type { ReactNode } from "react";
import { NavLink } from "react-router-dom";
import AppNav from "./AppNav";
import Icon, { IconName } from "../Icon";

/**
 * Management chrome: a console, not a page.
 *
 * Mobile-first per the same rule as the rest of the app — an organizer is
 * usually holding a phone and walking between tables, not sitting at a laptop.
 * Sections are a scrolling tab strip on a phone and a sidebar once there's room,
 * from the same markup.
 *
 * The status slot is for whatever must stay visible while moving between
 * sections — the round clock, for a tournament. That is the thing a single
 * scrolling page could never do.
 */
export default function ConsoleLayout({
  title,
  subtitle,
  status,
  sections,
  pathFor,
  children,
}: {
  title: string;
  subtitle?: ReactNode;
  status?: ReactNode;
  sections: { id: string; label: string; icon: IconName }[];
  pathFor: (id: string) => string;
  children: ReactNode;
}) {
  return (
    <div className="console">
      <a className="skip-link" href="#main">Skip to content</a>
      {/* app navigation first, then the event's own chrome. Running an event
          used to be a dead end: no logo, no way back to the rest of the app
          without editing the URL. The section tabs below are a different axis —
          they move within this console, not around the app — so they stay
          visible rather than folding into the same menu. */}
      <header className="console-masthead">
        <AppNav />
      </header>
      <header className="console-bar">
        <div className="console-title">
          <h1>{title}</h1>
          {subtitle && <p className="console-sub">{subtitle}</p>}
        </div>
        {status && <div className="console-status">{status}</div>}
      </header>

      <nav className="console-nav" aria-label="Sections">
        {sections.map((s) => (
          <NavLink
            key={s.id}
            to={pathFor(s.id)}
            className={({ isActive }) => `console-tab${isActive ? " active" : ""}`}
          >
            <Icon name={s.icon} />
            <span>{s.label}</span>
          </NavLink>
        ))}
      </nav>

      <main className="console-body" id="main">{children}</main>
    </div>
  );
}
