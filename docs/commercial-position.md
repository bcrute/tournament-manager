# Commercial position

Where this app sits against the tools that already exist, where the real gap
is, and the rules a commercial product would have to live by. Researched July
2026, while a paid tier here was still an open question.

**It is no longer open. Decided August 2026: this app is noncommercial,
permanently.** The commercial vehicle is the separate events/social project,
not a tier of this one. That resolves the licensing question rather than
deferring it — the Wizards Fan Content Policy is noncommercial, and this app
now sits squarely inside it by construction rather than by "for now".

Two consequences worth reading §3 with in mind:

- **This app may use Scryfall and display Magic content.** The `/rulings`
  feature does. A Scryfall integration was removed in July 2026 specifically to
  drop that licence chain, at a point when a paid tier was still possible;
  going noncommercial is what makes it safe to have back. Attribution is
  mandatory and is pinned by tests.
- **§3's rules below now describe the *other* project**, not a future tier of
  this one. They are kept here because that is where the research lives, and
  because the boundary they draw — commercial core ships no Magic content —
  is the reason the split exists at all.

Kept apart from [`tournament-research.md`](./tournament-research.md) because it
answers a different question: that document asks what we can build, this one
asks whether anyone would pay for it and what changes if they do.

The licensing analysis this rests on is in
[`tournament-research.md` §2](./tournament-research.md#2-licensing). The short
version, which is the binding constraint on everything below: **the Wizards Fan
Content Policy is noncommercial.**

---

## 1. What already exists

The honest summary: **the incumbents are good**, and neither "another life
counter" nor "another pairing engine" is a business.

### Organizer side — well served

| Tool | Notes |
|---|---|
| [TopDeck.gg](https://topdeck.gg/help/running-commander-tournament) | The default for Commander. Proprietary "Swiss Pods" pairing that converts to a circular system in later rounds so top tables can't intentionally draw into the cut; deliberate re-pair avoidance. Decklists, brackets, public event pages, Discord bot, free API, event discovery. |
| [Command Tower](https://outsidetheasylum.blog/surviving-cedh/) | Polished, cEDH-focused. Online pairings, seating order (seat 1 goes first), imports, decklist submission. Closed-source algorithm; manual pairings arrived late. |
| [MTG Event](https://www.mtgevent.com/mtg-tournament-software/) | Free. Pods, pairings, results, tiebreakers. |
| Melee / EventLink | Big events and sanctioned store play. Both gated. |

### Player side — commoditized

[Draftsim lists eleven life counters](https://draftsim.com/best-mtg-life-counter-app/).
Lifetap is full-featured, free, no ads. Playgroup adds ELO via playgroup.gg.
Lifelinker rides the Command Zone audience. There is no money in life counting.

### The one weak incumbent

Wizards' own Companion app reviews poorly — [complaints](https://justuseapp.com/en/app/1455161962/magic-the-gathering-companion/reviews)
about search, being unable to drop from events, and no tournament history — but
it is free and bundled with sanctioned play. Not a distribution fight worth
picking.

## 2. Where the actual gap is

**The seam between the organizer tool and the table.** Today an organizer runs
TopDeck, players run Lifetap, and somebody retypes results into the organizer
tool afterwards. Nothing spans that boundary.

This app already owns the table half — live life totals, shared display, seat
order matched to the physical table, and **automatic last-player-standing
detection**, which is exactly the event a tournament needs reported. "The pod
reports its own result" is the differentiator; neither incumbent can do it
alone.

Worth knowing before leaning on it: that path is **test-covered but not
event-proven** — see `tournament-api-contract.md` §10. The differentiator is
the least-exercised code in the system.

Strategic consequence: **integrate rather than compete.** TopDeck has solved
multiplayer Swiss and owns event discovery; its weakness is that it stops at
the table's edge. Being the table layer that feeds it beats trying to out-pair
them. That path now exists: `POST /{code}/import` reads a TopDeck export
through an adapter and lands it as entrants, rounds and results
(`tournament-api-contract.md` §9). It is one-way by construction — their API
cannot accept results — so this feeds *from* them, and what is played here
stays here. No UI offers it yet.

Monetization shape, wherever it happens: **players free** (needed for the
network effect), **organizers or stores pay**. Same shape TopDeck uses. Not
here, though — see the top.

## 3. Rules for a commercial product

*These apply to the events/social project. This app is noncommercial and is not
bound by them — see the note at the top.*

The binding constraint is subtle and it is worth writing down:

> Scryfall grants its data **under the Wizards Fan Content Policy**, and that
> policy is **noncommercial**.

So a paid product cannot use Scryfall, and realistically cannot display Magic
card imagery or text at all without a licence Wizards does not hand out.

Fortunately nothing valuable needs it — life totals, damage-by-source, pods,
rounds, standings, seating and results require zero card content.

**The line to hold** — in the commercial product:

1. **Commercial core ships no Magic content whatsoever.** No Scryfall calls, no
   card images, no card text, no Magic branding in the product identity.
   Mechanics are unprotectable, so generic modes ("source-directed damage",
   "hidden roles") are entirely ours to sell.
2. **Treachery never ships in a paid tier.** It stays in the free fan build, or
   arrives as a pack the user imports themselves. Getting the Treachery
   maintainers' permission is still worth doing — it settles the free build and
   the artist-credit question — but it does not make the cards commercially
   shippable, because the art belongs to third-party illustrators and the text
   is Magic-derivative.
3. **A "user-generated plugin" shield does not work if we write the plugin.**
   DMCA §512 protects material stored at the direction of *users*; the operator
   uploading it defeats the knowledge requirement, and direct liability attaches
   to the person who uploads regardless of what entity owns the platform.
4. **Draw the boundary now, cheaply.** Neutral naming in schema and UI, and the
   hidden-role engine parameterized on a role pack rather than assuming
   `data/treachery-cards.json`.

**Point 4 is now largely done, and not because of this document.** The game
profile work (`games.py`, `tournament-api-contract.md` §8) made MTG a profile
over a game-agnostic core: entrants, rounds, pods, seats, placements,
standings, timers and judge calls contain nothing that knows what Magic is.
The remaining leakage is naming, not structure — `startingLife`,
`collectWizardsEmail` and the `highest_life` policy are all really
resource-shaped concepts wearing Magic names, to be renamed when a second game
lands.

If money ever actually changes hands, buy an hour of an IP attorney's time.
Everything above is reasoning from published policies, not legal advice.

---

## 4. What changes if this ships

Two consequences recorded elsewhere, noted here so they are not discovered late:

- **A data regime this project deliberately does not have.** Payment brings
  names, emails, a payment relationship and a retention requirement that
  directly contradicts "keep no identifiers". The containment approach — and
  the decision that we are never the merchant of record — is in
  [`ideas.md`](./ideas.md), "Paid registration".
- **The security scope changes.** `AGENTS.md` records that HIPAA, SOC 2 and
  vendor governance do not apply here. Paid registration is the trigger that
  reopens that, because it introduces a vendor processing data on our behalf.
