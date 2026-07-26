import type { ReactNode } from "react";
import { Link } from "react-router-dom";
import FanContentNotice from "../FanContentNotice";
import SiteNav from "./SiteNav";

/** Public website chrome: the shared header plus a footer. */
export default function SiteLayout({ children }: { children: ReactNode }) {
  return (
    <div className="site">
      <a className="skip-link" href="#main">Skip to content</a>
      <SiteNav />
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
