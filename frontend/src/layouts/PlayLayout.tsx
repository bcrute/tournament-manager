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
  if (bare) return <>{children}</>;
  return (
    <div className="play">
      {title && (
        <header className="play-bar">
          <h1>{title}</h1>
        </header>
      )}
      <main className="play-body">{children}</main>
      <nav className="play-nav" aria-label="Main">
        {PLAY_NAV.filter((n) => n.listed).map((n) => (
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
    </div>
  );
}
