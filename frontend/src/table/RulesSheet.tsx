/**
 * Rules reference. Official documents are linked, never mirrored: partly
 * because they aren't ours to redistribute, but mostly because the
 * Comprehensive Rules changes with every set release and errata — a copy we
 * hosted would be quietly wrong within months, which is worse than no copy.
 * The Treachery summary below is written in our own words (mechanics aren't
 * copyrightable) with rule numbers so anything can be checked at the source.
 */
export default function RulesSheet({
  treachery,
  onClose,
}: {
  treachery: boolean;
  onClose: () => void;
}) {
  return (
    <div className="sheet-overlay" onClick={onClose}>
      <div className="sheet rules" onClick={(e) => e.stopPropagation()}>
        <h2>Rules</h2>

        <div className="rule-links">
          <a href="https://magic.wizards.com/en/rules" target="_blank" rel="noreferrer">
            📘 Magic Comprehensive Rules
            <span>official, always current — wizards.com</span>
          </a>
          <a href="https://mtgtreachery.net/rules/" target="_blank" rel="noreferrer">
            ⚔ Treachery rules (v6.0)
            <span>the full variant document — mtgtreachery.net</span>
          </a>
          <a href="https://mtgtreachery.net/rules/oracle/" target="_blank" rel="noreferrer">
            🎭 Identity card oracle
            <span>every card with its rulings</span>
          </a>
        </div>

        {treachery && <h2 className="rules-sub">Treachery — how it works</h2>}

        {treachery && (
          <>
        <h3>Setup</h3>
        <ul>
          <li>
            Best with 4–8 players. Everyone is dealt one identity card, kept in the command
            zone for the whole game (372.2).
          </li>
          <li>
            The mix of roles is public before the deal, but who has what is not (907.3d).
            Default splits: 4p — 1 Leader, 1 Traitor, 2 Assassins; 5p adds a Guardian; 6p —
            1/1/3/1; 7p — 1/1/3/2; 8p — 1 Leader, 2 Traitors, 3 Assassins, 2 Guardians
            (907.3c).
          </li>
          <li>
            Cards without an unveil cost start face up — that's the Leader, which is why the
            Leader is known from the start and takes the first turn (907.4a, 907.7).
          </li>
          <li>Starting life is 40 when paired with Commander, as it usually is (907.6).</li>
        </ul>

        <h3>Teams</h3>
        <ul>
          <li>Leader and Guardians are one team (907.5a).</li>
          <li>Assassins are a second team (907.5b).</li>
          <li>
            Each Traitor plays alone and wins only by outlasting everyone, including other
            Traitors (907.5c, 907.8d).
          </li>
          <li>
            While your identity is face down you count as everyone's opponent and have no
            teammates (907.5d).
          </li>
        </ul>

        <h3>Unveiling</h3>
        <ul>
          <li>
            Any time you have priority you may turn your identity face up by paying its
            unveil cost. It's a special action and doesn't use the stack (702.TR01c, 116.2tr).
          </li>
          <li>
            <strong>Undercover</strong> (mostly on Guardians) blocks that until another
            non-Leader identity has been revealed, or somebody has attacked a Leader player
            this game (702.TR02a). Putting a creature onto the battlefield isn't attacking —
            it has to be declared as an attacker.
          </li>
          <li>In this app: hold your card to peek privately, slide the bar to unveil publicly.</li>
        </ul>

        <h3>Winning and losing</h3>
        <ul>
          <li>
            The assassins win once every Leader has lost and at least one Assassin is still in
            (907.8c).
          </li>
          <li>
            The leader team loses when all Leaders are out, even if a Guardian survives —
            this overrides effects that would stop a Guardian losing (907.8b).
          </li>
          <li>A Traitor wins only when all their opponents have left the game (907.8d).</li>
          <li>
            When a player leaves, their face-down identity is revealed. At the end of the
            game, everything is revealed (907.13). The app does this automatically when
            someone is eliminated, leaves, or the game ends.
          </li>
        </ul>

        <p className="hint">
          Summarised for quick reference at the table — the linked documents above are
          authoritative, and stay current at their source.
        </p>
          </>
        )}

        <button className="ghost" onClick={onClose}>
          Close
        </button>
      </div>
    </div>
  );
}
