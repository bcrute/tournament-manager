import type { ReactNode } from "react";
import { Link, NavLink } from "react-router-dom";
import FanContentNotice from "../FanContentNotice";
import { SITE_NAV } from "../nav";

/** Public website chrome. One page today; the nav is here so adding a second
 *  is a line in `SITE_NAV` rather than another bespoke header. */
export default function SiteLayout({ children }: { children: ReactNode }) {
  return (
    <div className="site">
      <a className="skip-link" href="#main">Skip to content</a>
      <header className="site-bar">
        <Link to="/" className="site-logo">
          mtg<span>.skadoosh.dev</span>
        </Link>
        <nav aria-label="Site">
          {SITE_NAV.filter((n) => n.listed).map((n) => (
            <NavLink
              key={n.to}
              to={n.to}
              className={({ isActive }) => (isActive ? "active" : undefined)}
            >
              {n.label}
            </NavLink>
          ))}
        </nav>
      </header>
      <main className="site-body" id="main">{children}</main>
      <footer className="site-footer">
        <p className="site-footer-links">
          <Link to="/privacy">Privacy</Link>
          <span className="dot-sep">·</span>
          <span className="hint">No tracking, no cookie banner</span>
        </p>
        <FanContentNotice />
      </footer>
    </div>
  );
}
