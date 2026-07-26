import type { ReactNode } from "react";
import AppNav from "./AppNav";

/**
 * Player chrome: one screen, one task, thumb-first.
 *
 * `bare` exists for surfaces that own the whole viewport — the room, where a
 * card fills the screen and the app's own navigation would be in the way. Those
 * pages keep their own controls rather than being forced into this shell.
 */
export default function PlayLayout({
  title,
  children,
  bare = false,
}: {
  title?: string;
  children: ReactNode;
  bare?: boolean;
}) {
  if (bare) return <>{children}</>;
  return (
    <div className="play">
      <a className="skip-link" href="#main">Skip to content</a>
      {/* the same bar the site and the console use: arriving here from the front
          page shouldn't feel like leaving the site */}
      <header className="play-masthead">
        <AppNav />
      </header>
      {title && (
        <header className="play-bar">
          <h1>{title}</h1>
        </header>
      )}
      <main className="play-body" id="main">{children}</main>
    </div>
  );
}
