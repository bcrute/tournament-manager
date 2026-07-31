import { useEffect, useRef } from "react";
import { NavLink, useNavigate } from "react-router-dom";
import Icon from "../Icon";
import SiteFooter from "../layouts/SiteFooter";
import { ACCOUNT_SECTIONS, accountPath, AccountSection } from "../nav";
import { goBack } from "../goBack";
import Games from "./Games";
import Notes from "./Notes";
import Overview from "./Overview";
import Settings from "./Settings";
import SignIn from "./SignIn";
import { publishAccount, useAccount } from "./useAccount";

/**
 * The account area's shell: one sign-in gate, one tab strip, four sections.
 *
 * The gate lives here rather than in each section so there is exactly one
 * answer to "what does a signed-out visitor see" — before this the dashboard
 * had its own copy and nothing else had any, so `/account/settings` would have
 * rendered an empty settings form to nobody in particular.
 *
 * This is a client-side convenience, not access control: every endpoint behind
 * these screens checks the session itself and returns 401 regardless of what
 * this component decides to draw.
 */
export default function AccountArea({ section }: { section: AccountSection }) {
  const navigate = useNavigate();
  const acct = useAccount();
  const tabs = useRef<HTMLElement>(null);

  // On a phone the strip scrolls, and "Settings" sits off the right edge — so
  // opening /account/settings directly showed a tab bar with every section
  // visible except the one you were on. Only the strip moves, never the page.
  useEffect(() => {
    tabs.current
      ?.querySelector(".acct-tab.active")
      ?.scrollIntoView({ block: "nearest", inline: "nearest" });
  }, [section, acct]);

  if (acct === undefined) {
    return (
      <div className="acct">
        <p className="hint">Loading…</p>
      </div>
    );
  }

  if (!acct) {
    return (
      <div className="acct">
        <header className="acct-head">
          <h1>Your account</h1>
          <p className="tagline">
            Keep your game history, your private notes and the name you play under —
            on every device you sign in from.
          </p>
        </header>
        <SignIn onDone={publishAccount} onCancel={() => goBack(navigate, "/table")} />
        <SiteFooter />
      </div>
    );
  }

  return (
    <div className="acct">
      <header className="acct-head">
        <h1>
          <Icon name="user" /> {acct.displayName || acct.username}
        </h1>
        {acct.displayName && <p className="tagline">signed in as {acct.username}</p>}
      </header>

      {/* the same axis as the console's tabs: movement within one thing */}
      <nav className="acct-tabs" aria-label="Account" ref={tabs}>
        {ACCOUNT_SECTIONS.map((s) => (
          <NavLink
            key={s.id}
            to={accountPath(s.id)}
            end={s.id === "overview"}
            className={({ isActive }) => (isActive ? "acct-tab active" : "acct-tab")}
          >
            <Icon name={s.icon} />
            <span>{s.label}</span>
          </NavLink>
        ))}
      </nav>

      {section === "overview" && <Overview account={acct} />}
      {section === "games" && <Games />}
      {section === "notes" && <Notes />}
      {section === "settings" && <Settings account={acct} />}
    </div>
  );
}
