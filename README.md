# Travel Packing Assistant

A Claude Code plugin for making optimal use of a baggage allowance on an international
itinerary — and for knowing, before the airport, exactly what that allowance is.

The problem it solves is not "what should I bring". It is the narrower and more expensive one:
you have several flights on different carriers, each publishing a different allowance for a
fare brand you probably cannot name, and the number that actually governs your bags is the
tightest one on the route. Nobody works that out at 05:00 on the day. This works it out in
advance, then packs to it.

```
/travel-packing:itinerary       enter the flights
/travel-packing:policies        research every carrier's real allowance
/travel-packing:inventory       what you're carrying, by weight
/travel-packing:weigh           scale readings, reconciled against the inventory
/travel-packing:plan            solve the pack, bag by bag and cube by cube
/travel-packing:docs            counter card + packing list, as PDFs
```

And when it does not fit:

```
/travel-packing:overage         price every way out, recommend one
/travel-packing:leave-behind    ranked drop list, with a stop line
```

## What makes the answers trustworthy

**Every allowance figure carries its source.** A URL, the sentence it was read in, the date it
was fetched, and a confidence level. Anything not read on the carrier's own page for your
actual ticket stays flagged as `inferred` or `assumed` all the way through to the printed
document. Baggage allowances are the most-copied, least-maintained numbers on the web — an
out-of-date table from an aggregator looks exactly like current policy right up until the desk.

**It packs to the binding limit, not the average one.** The tightest per-segment limit across
the ticket, with the segment that set it named. Costs a little capacity; removes the failure
where your bag is legal for the leg you researched and illegal for the leg you didn't.

**Measured weight beats itemised weight.** Nobody weighs every sock. So the reconciler compares
the scale reading against the sum of what you listed and reports the gap in kilograms rather
than quietly pretending the inventory is complete.

**The solver is deterministic.** Same inputs, same plan, every run. A packing list that
reshuffles between readings cannot be followed — you have already put things in cubes.

## The two documents

**The counter card** — one A4 page, printed, in your hand at check-in. Binding limits in large
type, each bag's weight against its allowance, the per-segment allowance table, and the
excess-baggage prices so you know the cost of the decision you are being asked to make. Every
number shows its confidence and the date it was verified, so you can check a claim at the desk
against the carrier's own published figure.

**The packing list** — the working document. Bag by bag, cube by cube, with tick boxes,
markers on the cabin-only and checked-only items, and the not-packed list at the end.

Both render from the workspace YAML directly, so no number is transcribed by hand — as PDFs via
[Typst](https://typst.app), and as Markdown for publishing to a static site. Both media apply
the same measured-beats-projected rule, so a bag cannot read `OVER` in one and `TIGHT` in the
other. They can be saved locally, emailed, pushed to cloud storage, or committed into a site
repo — see [`docs/delivery.md`](docs/delivery.md).

## How it is organised

One **trip workspace** per itinerary, created by `/travel-packing:new-trip`. The plugin is
stateless; the workspace holds the flights, the researched allowances, the bags, the inventory
and the generated plan, as YAML files with published schemas. Workspaces are private by
default — a packing workspace names the dates your home is empty.

```
<trip-workspace>/
├── itinerary.yaml    segments, tickets, carriers
├── allowances.yaml   researched policy per segment + the binding limit
├── bags.yaml         bags, cubes, tare weights, every scale reading
├── inventory.yaml    everything being carried
├── plan.yaml         generated allocation
├── research/         saved carrier policy pages — the evidence
└── output/           rendered PDFs
```

## Contents

| | |
| --- | --- |
| **Skills** | `new-workspace`, `itinerary-intake`, `baggage-policy-research`, `packing-inventory`, `weigh-bags`, `pack-plan`, `overage-options`, `leave-behind`, `packing-docs` |
| **Scripts** | `pack_solver.py` (allocation), `reconcile.py` (scale vs inventory), `validate.py` (schema + cross-file checks), `render_markdown.py` (documents as Markdown) |
| **Templates** | `typst/counter-card.typ`, `typst/packing-list.typ` |
| **Reference** | [`data/carriage-rules.md`](data/carriage-rules.md), [`data/typical-weights.md`](data/typical-weights.md), [`data/packing-categories.md`](data/packing-categories.md) |
| **Docs** | [`docs/data-model.md`](docs/data-model.md), [`docs/design-notes.md`](docs/design-notes.md), [`docs/delivery.md`](docs/delivery.md) |

The scripts have no solver dependency and run standalone against a workspace directory; they
need `PyYAML` and `jsonschema` only.

## Installation

```
/plugin marketplace add danielrosehill/Claude-Code-Plugins
/plugin install travel-packing@danielrosehill
```

Typst is required only for the PDF output: [install instructions](https://github.com/typst/typst#installation).

## What it deliberately does not do

No volumetric packing model — volume matters, but weight is what gets charged, and per-item
dimensions are not data anyone will enter. No bundled airline allowance database — a cached
table would go stale silently and then be worse than nothing, because it would look like a
source. No booking: it prices the options and makes a recommendation; buying the bag is yours.

Reasoning for these and the other design decisions is in
[`docs/design-notes.md`](docs/design-notes.md).

## Caution

The allowance figures in any workspace were researched on a date, from carriers who change
them without notice, and the plugin's reference files describe general patterns rather than any
specific airline's current policy. Check `verified_on` and the per-entry `confidence` before
relying on any of it. Nothing here is a substitute for the allowance shown on your own booking.

MIT licensed.

---

## Attribution

Fork of [danielrosehill/Claude-Travel-Packing-Assistant-Plugin](https://github.com/danielrosehill/Claude-Travel-Packing-Assistant-Plugin),
MIT-licensed, maintained here for local modification.
