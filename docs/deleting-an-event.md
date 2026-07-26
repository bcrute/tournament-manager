# Deleting an event — a decision that needs taking

*Written 2026-07-26, after "there's no obvious way to end/delete a tournament".
Ending is now fixed. Deleting is not, and shouldn't be until this is settled.*

## What prompted it

Two separate problems arrived wearing one sentence.

**Ending** was a UI defect: the organizer console only offered "End tournament"
when a round existed *and* was closed, so an event created by mistake — or one
that dissolved mid-round and could therefore never satisfy `close_round`'s
"every pod has a result" — had no way out at all. That is fixed: the button is
offered whenever the event is live, and force-ends an open round the way
`admin.py` always could.

**Deleting** is not a defect. It has never existed, for anyone, at any surface —
there is no `DELETE` route in the codebase. The dashboard (`GET /mine`) selects
with `LIMIT 100` and no status filter, so every ended and expired event stays on
an organizer's list forever. Now that events also expire on their own after 12h,
that list only grows.

The real complaint is probably the dashboard, not the data. That distinction is
the whole decision.

## What an event actually owns

Delete has to mean something specific, so: `tournaments` plus `entrants`,
`trounds`, `pods`, `pod_seats`, `pod_results`, and `official_calls`.

And then it stops. **A pod's room is not the tournament's to delete.** A pod is
backed by an ordinary room in the table layer, and `AGENTS.md` is explicit that
the tournament surface may use the table surface and never the reverse —
`table.py` has to keep working with no tournament in sight. Rooms already expire
on their own 3h sweep. A delete that cascaded into `rooms` and `players` would
be the tournament layer reaching down into a layer it doesn't own.

There is a second reason, and it is the stronger one. `players` rows carry
`account_id` for signed-in players, and personal game history reads it. Deleting
an event's rooms would punch holes in the game history of everyone who played in
it — people who are not the organizer and never agreed to anything. `ideas.md`
already settles the mirror case: deleting an *account* drops the pointer without
touching the entrant row or its results, "so an event's standings can't develop
holes because someone deleted their account on the train home." The same
principle run the other way says: **one organizer tidying their dashboard must
not edit other people's history.**

## The options

**A — Hard delete.** Cascade the seven tournament-layer tables, leave rooms
alone. Honest and simple, and the only option that genuinely erases a
sanctioning id (which is an email address, and the most identifying thing the
app holds). But it destroys standings irreversibly, and standings are the
artefact the whole app exists to produce. An organizer clearing "old" events in
February deletes the league table someone asks for in March.

**B — Archive.** An `archived_at` column; `/mine` filters it out; the code still
resolves and the standings still load for anyone holding it. Nothing is lost and
the dashboard problem goes away. Does not answer "delete my data".

**C — Dashboard filter only.** No schema change at all: `/mine` returns live
events by default and past ones behind a flag or a second key. The smallest
thing that fixes the actual complaint.

**D — Archive by default, delete as a separate deliberate act.** C or B for the
everyday case, and a genuine hard delete kept as its own rarely-used path with a
confirmation that names what it destroys.

## Recommendation

**Do C now; hold A behind D.**

C is a query change and solves what was actually complained about. B is worth
doing at the same time only if you want an organizer to hide a *live* event,
which nobody has asked for.

Hard delete should wait, because it needs answers this document can't supply on
its own:

- **Does an entrant have a say?** Their name and result live in an event the
  organizer owns. Today the organizer can already drop them; deletion is a
  bigger version of that and it is not obvious it should be unilateral.
- **What happens to a sanctioning id?** If the honest reason to delete is "erase
  the email addresses", then the right feature might be narrower and better:
  clear collected sanctioning ids after the event reports, automatically,
  without deleting anything else. That is a retention rule, not a delete button,
  and it is probably the more defensible design.
- **Does an expired event differ from an ended one?** An event that idled out
  after 12h without ever running a round is genuinely junk. One that ran six
  rounds and crowned a winner is a record. The same button should probably not
  do both.

## If A is built anyway

- Organizer-only, on their own event, through `require_organizer`.
- Never touches `rooms` or `players`. Rooms expire on their own.
- Never touches `admin_log` or `security_log` — an audit trail an actor can
  delete is not an audit trail.
- Confirmation names the loss in numbers ("42 entrants, 5 rounds, final
  standings"), not "are you sure?".
- It is a state change on other people's records, which is the one thing
  `AGENTS.md` says the admin surface logs and the other two don't. Worth asking
  whether organizer deletion is the exception that should be logged too.
