import { useEffect, useRef, useState } from "react";
import { Link, NavLink } from "react-router-dom";
import Icon from "../Icon";
import { useAccount } from "../account/useAccount";
import { t } from "../i18n";
import { accountNavItem, SITE_NAV } from "../nav";

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
  const acct = useAccount();

  // `undefined` is "we haven't asked yet". Rendering "Sign in" through that
  // gap would flash the wrong word at everyone who *is* signed in, so the
  // account entry waits one tick rather than guessing.
  const items = SITE_NAV.map((n) =>
    n.to === "/account" ? accountNavItem(acct === undefined ? null : (acct?.username ?? null)) : n,
  ).filter((n) => n.listed && !(n.to === "/account" && acct === undefined));

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
        {items.map((n) => (
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
