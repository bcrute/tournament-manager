import { useEffect, useRef, useState } from "react";
import { Link, NavLink } from "react-router-dom";
import Icon from "../Icon";
import { t } from "../i18n";
import { SITE_NAV } from "../nav";

/**
 * The site's one header: logo plus `SITE_NAV`, inline links on a wide screen,
 * a hamburger on a phone. Every page outside the room renders this — the room
 * keeps `RoomBar`, whose hamburger this deliberately mirrors (leading trigger,
 * `aria-expanded`, closes on Escape or a tap outside, hands focus back) so the
 * two menus feel like one control.
 */
export default function SiteNav() {
  const [open, setOpen] = useState(false);
  const wrap = useRef<HTMLElement>(null);
  const trigger = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    if (!open) return;
    const onDown = (e: PointerEvent) => {
      if (!wrap.current?.contains(e.target as Node)) setOpen(false);
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== "Escape") return;
      setOpen(false);
      trigger.current?.focus(); // don't strand focus where the menu was
    };
    document.addEventListener("pointerdown", onDown);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("pointerdown", onDown);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);

  return (
    <header className="site-bar" ref={wrap}>
      <button
        ref={trigger}
        className="site-menu-btn"
        aria-label={t("menu.open")}
        aria-expanded={open}
        aria-haspopup="true"
        onClick={() => setOpen(!open)}
      >
        <Icon name="menu" label={t("menu.open")} />
      </button>
      <Link to="/" className="site-logo">
        mtg<span>.skadoosh.dev</span>
      </Link>
      {/* always in the DOM; a class shows it, so Escape hides rather than removes */}
      <nav className={`site-nav${open ? " open" : ""}`} aria-label="Site">
        {SITE_NAV.filter((n) => n.listed).map((n) => (
          <NavLink
            key={n.to}
            to={n.to}
            onClick={() => setOpen(false)}
            className={({ isActive }) => (isActive ? "active" : undefined)}
          >
            <Icon name={n.icon} />
            <span>{n.label}</span>
          </NavLink>
        ))}
      </nav>
    </header>
  );
}
