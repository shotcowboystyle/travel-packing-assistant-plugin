# {{TRIP_NAME}}

Packing workspace for a single itinerary. Built with the
[Travel Packing Assistant](https://github.com/danielrosehill/Claude-Travel-Packing-Assistant-Plugin)
Claude Code plugin.

## What is here

`itinerary.yaml` holds the flights. `allowances.yaml` holds what each carrier permits on each
segment, with a source for every figure, and the **binding limit** that governs the journey.
`bags.yaml` and `inventory.yaml` hold the physical side — bags, packing cubes, tare weights,
scale readings, and every item being carried with its weight. `plan.yaml` is the generated
allocation of items to bags.

`output/` holds the two rendered documents: a one-page **counter card** to print and take to
the airport, and the full **packing list** with tick boxes.

## Working here

Install the plugin, then:

```
/travel-packing:status          where this trip stands
/travel-packing:itinerary       enter or amend the flights
/travel-packing:policies        research the allowances
/travel-packing:inventory       what is being carried
/travel-packing:weigh           record scale readings
/travel-packing:plan            solve the pack
/travel-packing:docs            render the PDFs
/travel-packing:overage         price the ways out of being over
/travel-packing:leave-behind    ranked drop list
```

Without the plugin, the scripts still run standalone against this directory — see the plugin's
`scripts/`.

## A caution about the allowance figures

They were researched on a date, from carriers who change them. Check `verified_on` in
`allowances.yaml` and the `confidence` on each entry before relying on any of it. Anything
marked `inferred` or `assumed` has not been confirmed against the carrier's own published
policy for this specific ticket.
