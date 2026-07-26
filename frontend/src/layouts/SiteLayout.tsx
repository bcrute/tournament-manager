import type { ReactNode } from "react";
import SiteFooter from "./SiteFooter";
import SiteNav from "./SiteNav";

/** Public website chrome: the shared header plus the shared footer. */
export default function SiteLayout({ children }: { children: ReactNode }) {
  return (
    <div className="site">
      <a className="skip-link" href="#main">Skip to content</a>
      <SiteNav />
      <main className="site-body" id="main">{children}</main>
      <SiteFooter />
    </div>
  );
}
