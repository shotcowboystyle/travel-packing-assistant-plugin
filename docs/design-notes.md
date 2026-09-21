# Design notes

Why this plugin is shaped the way it is. Written 2026-08-16 alongside v1.0.0.

## One workspace per itinerary

Allowances, bag tares and the pack that actually worked are facts about a specific journey.
A workspace accumulating several trips loses the ability to answer "what did this bag weigh
leaving home", which is the question the return leg turns on. The cost is a repo per trip; the
benefit is that every number in the workspace has an unambiguous referent.

The workspaces are private by default. A packing workspace names the dates a home is empty and
lists what is worth taking from it.

## Everything is sourced, and confidence is a first-class field

Baggage allowances are among the most-copied and least-maintained numbers on the web. Aggregator
sites, travel blogs and forum posts return confident, well-formatted, years-out-of-date tables
that are indistinguishable from current policy — until the desk. An allowance with no source is
therefore not a weaker allowance, it is a different kind of object, and the schema refuses to
store it as if it were the same thing.

Hence `source.url`, `source.fetched_on`, `source.quote` and `confidence` on every entry, and
hence the rule that `inferred` and `assumed` figures stay visibly flagged all the way through to
the rendered PDF. The counter card exists partly so a traveller can check a gate agent's claim
against the carrier's own published sentence — that only works if the provenance survives.

The best available source is not the airline's public baggage page at all. It is the
manage-booking page for the specific booking, which states the allowance for the actual ticket
including fare brand and status. Reaching it usually means asking the user to open it and paste
what it says, and the skill treats that as the highest-quality outcome rather than a fallback.

## Piece concept vs weight concept, decided before any arithmetic

Under a **piece** concept (N bags each under a cap), splitting a load across two bags doubles
the allowance. Under a **weight** concept (a pooled total in kg), it buys nothing at all. The
same 30 kg of belongings is either fine or expensive depending purely on which system the
carrier uses, and every downstream recommendation — redistribute, buy a bag, pay overweight —
inverts with it. So `system` is a required field, established during research, and both the
solver and the overage skill branch on it.

## Pack to the tightest limit

On an interline itinerary, the industry has rules for resolving whose baggage policy governs.
In practice their application is uneven, and the agent at the first counter frequently applies
their own employer's policy regardless. The plugin therefore computes `binding` as the tightest
per-segment limit across the ticket and records which segment set it and what the looser limits
were.

This deliberately costs capacity. It removes an entire category of failure — the one where the
bag is legal for the leg the traveller researched and illegal for the leg they did not. Where
the difference is large enough to matter, the skill surfaces it and lets the user take the risk
knowingly rather than deciding on their behalf.

## Measured weight beats itemised weight

Nobody weighs every item. The realistic input is a bag on a hook scale plus a partial inventory,
and the honest thing to do with the discrepancy is to name it. `reconcile.py` reports
unaccounted mass rather than silently distributing it across estimates, and the planning number
is the scale reading — because that is the number the airport will agree with.

The corollary is that `weight_source` has to be recorded per item. Without it there is no way to
tell "the inventory is missing things" from "the estimates are drifting", and those have
opposite fixes.

## Max-min headroom as the default objective

The solver could minimise the number of bags, or balance them evenly, or fill greedily. It
maximises the *minimum* headroom across capped bags, because the dominant real-world error is
not allocation, it is measurement: home scales and airport scales routinely disagree by a few
hundred grams, and the disagreement is not symmetric in consequence. Headroom is what absorbs
that. `--objective consolidate` exists for the traveller who would rather carry fewer bags and
accept the tighter margin.

For the same reason the `tight` status band is 1.5 kg wide. A bag 400 g under its limit is not
a pass; reporting it as one is exactly the kind of proxy signal that produces a confident wrong
answer.

## Determinism

The solver is seeded and its local search is bounded, so identical inputs produce an identical
plan. A packing list that reshuffles between runs cannot be followed — the traveller has already
put things in cubes. Any change in the allocation should mean an input changed, and that is
worth finding before the new plan is shown.

## Cost per kilogram, not weight, for the leave-behind ranking

Ranking by weight alone recommends abandoning the heaviest thing, which is frequently the most
expensive and least replaceable. The ranking divides an *effective* cost — replacement cost at
the destination where that is possible, full value where it is not, infinite for essentials —
by the kilograms saved. This is why `replaceable_at_destination` is captured during inventory
rather than reconstructed under pressure later: a 900 g bottle of shampoo replaceable for $4
should rank above a 200 g charger worth $60, and no weight-only ordering can reach that.

## Grams for items, kilograms for bags

Items get weighed on a kitchen scale, bags on a hook scale, allowances are published in
kilograms. Carrying one unit throughout would mean either 0.042 kg entries or 23000 g
allowances, and both invite the decimal-place error that this whole exercise exists to avoid.
The split matches the instruments.

## What the plugin deliberately does not do

- **No volume or 3D packing model.** Volume matters, but the constraint that gets people
  charged is weight, and a credible volumetric model would need per-item dimensions that nobody
  is going to enter.
- **No cached allowance database.** A local table of airline allowances would go stale silently
  and would then be worse than no table — it would look like a source. The plugin ships the
  method for finding current figures, and the structural facts that do not change, and nothing
  in between.
- **No booking or purchasing.** It prices the excess-baggage options and names a
  recommendation. Buying the bag is the user's action.
