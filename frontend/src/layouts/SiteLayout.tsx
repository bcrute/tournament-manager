import type { ReactNode } from "react";
import { Link } from "react-router-dom";
import AppNav from "./AppNav";
import FanContentNotice from "../FanContentNotice";

/** Public website chrome. The bar itself is `AppNav`, shared with every other
 *  layout — adding a section is a line in `SITE_NAV`, and it appears everywhere
 *  at once rather than in whichever header happened to be copied. */
export default function SiteLayout({ children }: { children: ReactNode }) {
  return (
    <div className="site">
      <a className="skip-link" href="#main">Skip to content</a>
      <header className="site-bar">
        <AppNav />
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
