# Data model

Every file described here lives in a **trip workspace** (one repo per itinerary), not in
the plugin. The plugin is stateless; the workspace holds all trip data.

All files are YAML. JSON Schemas for each are in `schema/` and can be checked with
`scripts/validate.py`. Weights are **grams for items** (`weight_g`) and **kilograms for
bags and allowances** (`_kg`) — items are weighed on a kitchen scale, bags on a hook
scale, and mixing the units is the single most common source of a wrong total.

```
<trip-workspace>/
├── CLAUDE.md            directives for agents working in this trip
├── itinerary.yaml       segments, tickets, carriers          → itinerary.schema.json
├── allowances.yaml      researched policy per segment        → allowances.schema.json
├── bags.yaml            physical bags, cubes, scale readings → bags.schema.json
├── inventory.yaml       everything being carried             → inventory.schema.json
├── plan.yaml            GENERATED — do not hand-edit         → plan.schema.json
├── overage.md           excess-baggage cost research
├── research/            raw fetched policy pages, one per carrier
└── output/              rendered PDFs
```

---

## itinerary.yaml

```yaml
trip:
  id: bos-ath-tlv-0826            # kebab-case, matches workspace name
  label: "Boston → Athens → Tel Aviv, August 2026"
  travellers: 2
  direction: outbound             # outbound | return | round-trip

tickets:                          # one entry per issued ticket / PNR
  - id: T1
    booking_ref: ABC123
    validating_carrier: A3        # the airline whose stock the ticket is on
    segments: [S1, S2]            # segments sold together on this ticket

segments:
  - id: S1
    date: 2026-08-27
    marketing_carrier: A3         # IATA code on the ticket
    marketing_flight: "A3 951"
    operating_carrier: A3         # who actually flies it — differs on codeshares
    from: BOS                     # IATA airport code
    to: ATH
    cabin: economy                # economy | premium-economy | business | first
    fare_brand: "Light"           # fare family — allowances often hang off this
    loyalty:
      programme: null
      tier: null
      carried_by: null            # traveller id whose status applies
```

**Why `marketing_carrier` and `operating_carrier` are both required:** the baggage
allowance is normally set by the *marketing* carrier's fare rules, but the physical
handling at the gate — cabin bag sizers, weighing policy — is the *operating*
carrier's. Recording only one of them makes the research unreproducible.

**Why tickets are separate from segments:** whether two flights are on one ticket
decides whether bags are through-checked and which carrier's allowance governs the
whole journey. See `docs/design-notes.md`.

---

## allowances.yaml

Written by `/travel-packing:policies`. Never hand-invented — every entry carries its
source.

```yaml
verified_on: 2026-08-16           # absolute date the research was run

segments:
  - segment_id: S1
    system: piece                 # piece | weight — see design-notes.md
    source:
      url: https://en.aegeanair.com/travel-information/baggage/
      fetched_on: 2026-08-16
      route: webfetch             # webfetch | geo-egress | playwright | browser | manual
      confidence: confirmed       # confirmed | inferred | assumed
      quote: "1 piece up to 23kg"  # the sentence the numbers came from
    checked:
      included_pieces: 1
      max_weight_kg: 23
      max_linear_cm: 158          # length + width + height
      hard_max_weight_kg: 32      # above this the bag is refused, no fee will fix it
    cabin:
      pieces: 1
      max_weight_kg: 8
      dimensions_cm: [55, 40, 23]
      enforced: unknown           # always | spot-check | rarely | unknown
    personal_item:
      pieces: 1
      max_weight_kg: null         # null = published as unlimited / unstated
      dimensions_cm: [40, 30, 15]
    excess:
      currency: EUR
      extra_bag_prepaid: 75
      extra_bag_airport: 100
      overweight_band: "23–32 kg"
      overweight_fee: 60
    notes: "Light fare includes no checked bag on the transatlantic leg."

binding:                          # COMPUTED by /travel-packing:policies
  checked:
    included_pieces: 1
    max_weight_kg: 23
    limited_by: S2                # the segment that sets the constraint
  cabin:
    max_weight_kg: 8
    dimensions_cm: [55, 40, 23]
    limited_by: S1
  personal_item:
    max_weight_kg: 3            # null = uncapped; see below
    dimensions_cm: [40, 30, 15]
    limited_by: S1
  rationale: "Bags are through-checked on one ticket, so the tightest per-segment
    limit governs the whole journey."
```

`binding` is what `scripts/pack_solver.py` reads, and it is the *only* thing the solver
reads from this file besides `confidence`. Each bag in `bags.yaml` is capped by the
block matching its `type`: `checked` → `binding.checked`, `cabin` → `binding.cabin`,
`personal` → `binding.personal_item`. A `max_weight_kg` of `null`, or a missing block
altogether, means that bag type is uncapped: the solver will pack it without a weight
limit and report its headroom as `null` rather than inventing a number. The solver
refuses to run at all if `binding` is absent — it will not guess a limit.

`confidence` values mean:

- `confirmed` — the number was read on the carrier's own page, and `quote` holds the text.
- `inferred` — derived from a rule that was read (e.g. a fare-brand table) but not stated
  for this exact route.
- `assumed` — a placeholder the user must check. Any `assumed` entry makes the plan
  provisional and must be surfaced in every rendered document.

---

## bags.yaml

```yaml
bags:
  - id: CHK1
    label: "Large red Samsonite"
    type: checked                 # checked | cabin | personal
    owner: daniel
    tare_kg: 4.2                  # empty weight, on the scale, with nothing inside
    external_cm: [78, 50, 30]
    expandable: true
    cubes:
      - id: CUBE-A
        label: "Large packing cube"
        tare_kg: 0.12
        volume_l: 26
      - id: CUBE-B
        label: "Shoe cube"
        tare_kg: 0.09

weighings:                        # every scale reading, kept as history
  - bag: CHK1
    phase: outbound               # empty | outbound | current | final
    gross_kg: 22.4                # what the scale showed, bag and contents together
    date: 2026-08-27
    scale: hook

scales:
  - id: hook
    label: "Luggage hook scale"
    resolution_kg: 0.1
    bias_kg: 0.0                  # correction found by scripts/reconcile.py
```

`bias_kg` is **added to raw readings** to correct them, so a scale that reads 0.4 kg
high on every bag needs `bias_kg: -0.4`. `scripts/reconcile.py` suggests a value only
when every reconciled bag shows a residual of the same sign and similar magnitude — the
signature of a miscalibrated scale rather than of an incomplete inventory — and prints
it for you to enter. It never writes the field itself.

`phase` matters: `empty` gives tare, `outbound` is what the bag weighed leaving home,
`current` is where it stands now (after a trip has added things), `final` is the
check-in reading. `/travel-packing:weigh` appends rather than overwrites, so the
weight history of a bag across a multi-leg trip stays intact.

---

## inventory.yaml

```yaml
items:
  - id: I001
    name: "Wool jumper"
    qty: 1
    weight_g: 420                 # per unit, not for the whole qty
    weight_source: measured       # measured | estimated | vendor | catalogue
    category: clothing
    tier: useful                  # essential | useful | nice-to-have | expendable
    carriage: any                 # any | cabin-only | checked-only | prohibited
    carriage_reason: null         # required whenever carriage != any
    replaceable_at_destination:
      possible: true
      cost: 40
      currency: USD
    value: 60                     # replacement cost / sentimental proxy, same currency
    currency: USD
    fragile: false
    assigned_bag: CHK1            # written by the solver; may be pre-set to pin an item
    pinned: false                 # true = solver must not move it
    cube: CUBE-A
```

`tier` and `replaceable_at_destination` exist for one purpose: `/travel-packing:leave-behind`
ranks by cost-per-kilogram-saved, and it cannot do that without knowing what a thing is
worth and whether it can be re-bought at the other end.

`carriage` encodes the rules that override any weight optimisation:

| value | meaning | typical cause |
| --- | --- | --- |
| `cabin-only` | must be in the cabin | lithium power banks, spare batteries, medication, documents |
| `checked-only` | must not be in the cabin | liquids over 100 ml, sharps, tools |
| `prohibited` | cannot fly at all | see `data/carriage-rules.md` |

---

## plan.yaml

Generated by `scripts/pack_solver.py`. Regenerated, never edited.

```yaml
generated_on: 2026-08-16T14:02:00+03:00
solver: pack_solver.py 1.0.0
objective: max-min-headroom
binding_limits:                   # echoed from allowances.binding, one block per bag type
  checked: {pieces: 1, max_weight_kg: 23}
  cabin: {pieces: 1, max_weight_kg: 8}
  personal: {pieces: 1, max_weight_kg: 3}

bags:
  - id: CHK1
    type: checked
    allowance_kg: 23
    tare_kg: 4.2
    contents_kg: 17.9
    cube_tare_kg: 0.21
    projected_gross_kg: 22.31
    headroom_kg: 0.69
    status: tight                 # ok (>1.5 kg) | tight (0–1.5 kg) | over (<0)
    cubes:
      - id: CUBE-A
        items: [I001, I004]
    loose_items: [I009]

unassigned:                       # did not fit anywhere
  - item: I021
    name: "Power bank"            # copied from inventory so the list reads on its own
    reason: "no bag with capacity and carriage=cabin-only"

overflow_ranking:                 # only when pack_solver.py was run with --overflow
  - rank: 1
    item: I024
    name: "Adjustable dumbbell"
    bag: CHK1
    kg_saved: 6.0
    cost: 25.0                    # value, or the tier proxy, or the re-buy price
    cost_per_kg: 4.17
    replaceable: true
    replace_cost: 25
    pinned: false
    tier: expendable

warnings:
  - "Allowance for S2 is confidence=assumed; plan is provisional."
  - "Unaccounted mass on CHK1: 1.8 kg between itemised total and last weighing."

errors:                           # hard problems the solver could not resolve
  - "Bag CAB1 weighs 9.55 kg empty (tare plus cubes) against an allowance of 8.0 kg."
```

`status` thresholds are deliberately conservative: airport scales and home scales
disagree by a few hundred grams routinely, so a bag inside 1.5 kg of its limit is
reported as `tight`, not `ok`.

`allowance_kg` and `headroom_kg` are `null` together when the binding allowance does not
cap that bag type (see `binding` above). `status` is then `ok`, because there is no
limit to be close to.

`overflow_ranking` is written only when the solver is run with `--overflow`, and is
ordered ascending by `cost_per_kg` — drop from the top. `cost` is the item's `value`,
falling back to a tier proxy (essential 1000, useful 100, nice-to-have 10, expendable 1)
when no value is recorded, and reduced to `replaceable_at_destination.cost` for anything
that can simply be re-bought on arrival. `/travel-packing:leave-behind` consumes this
list.

`errors` appears only when something could not be solved rather than merely optimised —
a bag whose empty weight already exceeds its allowance, or a `pinned` item that does not
fit where it is pinned. The solver never overrides a pin: it reports the overflow and
exits non-zero, leaving the item where the traveller put it.
