import type { ReactNode } from "react";
import SiteNav from "./SiteNav";

/**
 * Player chrome: one screen, one task, thumb-first. The same header the site
 * uses — arriving here from the front page shouldn't feel like leaving the
 * site — over a single narrow column. The room doesn't use this: a card fills
 * that screen, and `RoomBar` is its chrome.
 */
export default function PlayLayout({ children }: { children: ReactNode }) {
  return (
    <div className="play">
      <a className="skip-link" href="#main">Skip to content</a>
      <SiteNav />
      <main className="play-body" id="main">{children}</main>
    </div>
  );
}
