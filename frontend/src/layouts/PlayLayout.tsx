import type { ReactNode } from "react";
import { NavLink } from "react-router-dom";
import Icon from "../Icon";
import { PLAY_NAV } from "../nav";

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
  const listed = PLAY_NAV.filter((n) => n.listed);
  if (bare) return <>{children}</>;
  return (
    <div className="play">
      <a className="skip-link" href="#main">Skip to content</a>
      {title && (
        <header className="play-bar">
          <h1>{title}</h1>
        </header>
      )}
      <main className="play-body" id="main">{children}</main>
      {listed.length > 1 && (
      <nav className="play-nav" aria-label="Main">
        {listed.map((n) => (
          <NavLink
            key={n.to}
            to={n.to}
            end
            className={({ isActive }) => `play-tab${isActive ? " active" : ""}`}
          >
            <Icon name={n.icon} />
            <span>{n.label}</span>
          </NavLink>
        ))}
      </nav>
      )}
    </div>
  );
}
