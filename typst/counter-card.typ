// =============================================================================
// travel-packing — CHECK-IN COUNTER CARD
// =============================================================================
//
// One A4 side, printed and carried. It answers the three questions that get
// asked at a desk or a gate: what is my allowance, what does my bag actually
// weigh, and what will it cost me if the agent is right and I am wrong.
//
// Keep it to ONE page. If a change pushes it to two, cut content — a card that
// runs onto a second sheet is a card that gets read half way.
//
// -----------------------------------------------------------------------------
// COMPILE
// -----------------------------------------------------------------------------
// Typst refuses to compile a source file that lives outside `--root`, so the
// root has to contain BOTH this template and the trip workspace. Two forms
// work; both were verified with Typst 0.14.2.
//
// (a) Templates left in the plugin, root at the filesystem root. Data paths are
//     plain absolute paths — this is the form to use from a skill, because it
//     needs no copying and no assumption about where the plugin is installed:
//
//       typst compile --root / \
//         --input itinerary=/abs/trip/itinerary.yaml \
//         --input allowances=/abs/trip/allowances.yaml \
//         --input plan=/abs/trip/plan.yaml \
//         /abs/plugin/typst/counter-card.typ \
//         /abs/trip/output/counter-card.pdf
//
// (b) Templates copied into the workspace (e.g. `cp -r <plugin>/typst <trip>/.typst`),
//     root at the workspace. Data paths are then relative to the workspace:
//
//       cd /abs/trip
//       typst compile --root . \
//         --input itinerary=itinerary.yaml \
//         --input allowances=allowances.yaml \
//         --input plan=plan.yaml \
//         .typst/counter-card.typ output/counter-card.pdf
//
// All three inputs are optional; they default to the bare filenames, which
// resolve against `--root` (form (b)).
//
// itinerary.yaml is read only for the trip label, the dates and the
// origin/destination of each segment — the numbers all come from
// allowances.yaml and plan.yaml.
// =============================================================================

#import "lib.typ": *

#let itin = yaml(in-path("itinerary", "itinerary.yaml"))
#let allow = yaml(in-path("allowances", "allowances.yaml"))
#let plan = yaml(in-path("plan", "plan.yaml"))

#let trip = get(itin, "trip", default: (:))
#let binding = get(allow, "binding", default: (:))
#let alw-segments = get(allow, "segments", default: ())

// ---- lookups ---------------------------------------------------------------

#let itin-segments = get(itin, "segments", default: ())

#let seg-index = {
  let m = (:)
  for s in itin-segments { m.insert(str(get(s, "id", default: "?")), s) }
  m
}

#let alw-index = {
  let m = (:)
  for s in alw-segments { m.insert(str(get(s, "segment_id", default: "?")), s) }
  m
}

// A missing `limited_by` is a real state — an allowances.yaml whose binding
// block was hand-written, say — so every lookup takes `none` without dying.
// `str(none)` is an error in Typst, which is exactly how that dies.
#let key(id) = if id == none { "" } else { str(id) }

// "S2 · ATH→TLV"
#let seg-route(id) = {
  if id == none { return [—] }
  let s = seg-index.at(key(id), default: none)
  if s == none { return [#id] }
  [#id · #get(s, "from", default: "?")→#get(s, "to", default: "?")]
}

#let seg-carrier(id) = {
  let a = alw-index.at(key(id), default: none)
  let named = get(a, "carrier_name", default: none)
  if named != none { return named }
  let s = seg-index.at(key(id), default: none)
  get(s, "marketing_carrier", default: "")
}

#let seg-flight(id) = {
  let s = seg-index.at(key(id), default: none)
  get(s, "marketing_flight", default: "")
}

#let seg-confidence(id) = {
  let a = alw-index.at(key(id), default: none)
  get(get(a, "source", default: (:)), "confidence", default: none)
}

// The provenance of the segment that SETS a binding limit travels with that
// limit. A 7 kg cabin figure sourced by assumption is a different fact from a
// 7 kg figure read off the carrier's own page, and the card has to say which.
#let limit-note(limited-by, extra) = {
  let conf-v = seg-confidence(limited-by)
  note-line(above: 0pt, text(size: 8pt, fill: muted)[
    #if limited-by == none [
      #text(fill: over-fg)[limiting segment not recorded]
    ] else [
      set by #seg-route(limited-by) #seg-flight(limited-by)
    ]
  ])
  if conf-v != none and lower(str(conf-v)) != "confirmed" {
    note-line(above: 4pt, confidence-flag(conf-v, size: 7pt))
  }
  if extra != none {
    note-line(above: 4pt, text(size: 8pt, fill: muted)[#extra])
  }
}

#let first-date = {
  let ds = itin-segments.map(s => get(s, "date", default: none)).filter(d => d != none)
  if ds.len() == 0 { none } else { str(ds.at(0)) }
}

// `generated_on` is an ISO timestamp, but a YAML round-trip through some
// writers turns the "T" into a space. Take the date either way.
#let generated-on = {
  let g = get(plan, "generated_on", default: none)
  if g == none { none } else { str(g).replace("T", " ").split(" ").at(0) }
}

#show: doc => conf(
  title: get(trip, "label", default: "Trip"),
  subtitle: [
    Check-in counter card
    #if first-date != none [ · first flight #first-date ]
    #if generated-on != none [ · plan generated #generated-on ]
  ],
  trip: trip,
  generated: generated-on,
  margin: 1.4cm,
  body-size: 11pt,
  title-size: 20pt,
  doc,
)

// =============================================================================
// 1. BINDING LIMITS — the biggest type on the page
// =============================================================================

#let b-checked = get(binding, "checked", default: (:))
#let b-cabin = get(binding, "cabin", default: (:))
#let b-personal = get(binding, "personal_item", default: (:))

#grid(
  columns: (1fr, 1fr, 1fr),
  column-gutter: 7pt,
  big-figure(
    [#num(get(b-checked, "included_pieces", default: 1), digits: 0) × #kg(get(b-checked, "max_weight_kg", default: none))],
    "Checked",
    note: limit-note(
      get(b-checked, "limited_by", default: none),
      [max #num(get(b-checked, "max_linear_cm", default: none), digits: 0) cm linear ·
       refused above #kg(get(b-checked, "hard_max_weight_kg", default: none))],
    ),
  ),
  big-figure(
    kg(get(b-cabin, "max_weight_kg", default: none)),
    "Cabin bag",
    note: limit-note(
      get(b-cabin, "limited_by", default: none),
      dims(get(b-cabin, "dimensions_cm", default: none)),
    ),
  ),
  big-figure(
    kg(get(b-personal, "max_weight_kg", default: none)),
    "Personal item",
    note: limit-note(
      get(b-personal, "limited_by", default: none),
      dims(get(b-personal, "dimensions_cm", default: none)),
    ),
  ),
)

#let rationale = get(binding, "rationale", default: none)
#if rationale != none {
  v(4pt)
  text(size: 8.5pt, fill: muted)[*Why these govern:* #rationale]
}

// =============================================================================
// 2. THE BAGS — what they actually weigh against what is allowed
// =============================================================================

#section("Bags", note: "measured where weighed, else projected")

#let plan-bags = get(plan, "bags", default: ())

#table(
  columns: (1fr, auto, auto, auto, auto, auto, auto),
  align: (left + horizon, left + horizon, right + horizon, right + horizon, right + horizon, right + horizon, center + horizon),
  table.header(
    th("Bag"), th("Type"), th("Projected"), th("Weighed"), th("Allowance"), th("Headroom"), th("Status"),
  ),
  ..plan-bags.map(b => {
    let projected = get(b, "projected_gross_kg", default: none)
    let measured = get(b, "last_weighing_kg", default: none)
    let allowance = get(b, "allowance_kg", default: none)
    let governing = governing-kg(projected, measured)
    // Headroom is taken against whichever figure is heavier, not against the
    // projection — a bag with unaccounted mass is exactly the one that gets caught.
    let headroom = if allowance == none or governing == none { none } else { allowance - governing }
    (
      [#get(b, "label", default: get(b, "id", default: "?"))
       #text(size: 8pt, fill: faint)[#get(b, "id", default: "")]],
      text(size: 9pt)[#get(b, "type", default: "—")],
      // De-emphasised when a scale reading supersedes it.
      if measured != none and measured > projected {
        text(fill: muted)[#kg(projected)]
      } else {
        text(weight: "bold")[#kg(projected)]
      },
      if measured != none and measured >= projected {
        text(weight: "bold")[#kg(measured)]
      } else {
        kg(measured)
      },
      kg(allowance),
      kg-signed(headroom),
      status-badge(status-for(headroom)),
    )
  }).flatten(),
)

#text(size: 8pt, fill: muted)[
  Projected = bag tare + packing-cube tare + itemised contents. *Weighed* is the
  most recent scale reading that was not an empty-bag one. Headroom and status are
  taken against whichever of the two is heavier, because a gap between them is mass
  the inventory did not capture and the airport scale still will.
  *tight* is anything inside 1.5 kg of the limit: home and airport scales routinely
  disagree by a few hundred grams, so 0.2 kg of headroom is not headroom.
]

// =============================================================================
// 3. PER-SEGMENT ALLOWANCES — so a claim at the desk can be checked
// =============================================================================

#section("Allowance by segment", note: "the carrier's own published figures")

#table(
  columns: (auto, auto, 1fr, 1fr, auto),
  align: (left + horizon, left + horizon, left + horizon, left + horizon, left + horizon),
  table.header(
    th("Segment"), th("Carrier"), th("Checked"), th("Cabin"), th("Personal"),
  ),
  ..alw-segments.map(s => {
    let sid = get(s, "segment_id", default: "?")
    let c = get(s, "checked", default: (:))
    let cab = get(s, "cabin", default: (:))
    let per = get(s, "personal_item", default: (:))
    (
      [#text(weight: "bold")[#seg-route(sid)] \
       #text(size: 8pt, fill: muted)[#seg-flight(sid)]],
      text(size: 9pt)[#seg-carrier(sid)],
      text(size: 9pt)[
        #num(get(c, "included_pieces", default: 0), digits: 0) × #kg(get(c, "max_weight_kg", default: none)) \
        #text(size: 8pt, fill: muted)[#num(get(c, "max_linear_cm", default: none), digits: 0) cm linear ·
        hard max #kg(get(c, "hard_max_weight_kg", default: none))]
      ],
      text(size: 9pt)[
        #num(get(cab, "pieces", default: 1), digits: 0) × #kg(get(cab, "max_weight_kg", default: none)) \
        #text(size: 8pt, fill: muted)[#dims(get(cab, "dimensions_cm", default: none)) ·
        enforced: #get(cab, "enforced", default: "unknown")]
      ],
      text(size: 9pt)[
        #kg(get(per, "max_weight_kg", default: none)) \
        #text(size: 8pt, fill: muted)[#dims(get(per, "dimensions_cm", default: none))]
      ],
    )
  }).flatten(),
)

// =============================================================================
// 4. EXCESS BAGGAGE — the price of the decision being asked for at the desk
// =============================================================================

#section("If the bag is over", note: "excess-baggage prices, per segment")

#table(
  columns: (auto, auto, auto, auto, 1fr),
  align: (left + horizon, right + horizon, right + horizon, left + horizon, right + horizon),
  table.header(
    th("Segment"), th("Extra bag, prepaid"), th("Extra bag, at airport"),
    th("Overweight band"), th("Overweight fee"),
  ),
  ..alw-segments.map(s => {
    let sid = get(s, "segment_id", default: "?")
    let e = get(s, "excess", default: (:))
    let cur = get(e, "currency", default: none)
    (
      [#text(weight: "bold")[#sid] #text(size: 8pt, fill: muted)[#seg-carrier(sid)]],
      money(get(e, "extra_bag_prepaid", default: none), cur),
      money(get(e, "extra_bag_airport", default: none), cur),
      text(size: 9pt)[#get(e, "overweight_band", default: "—")],
      money(get(e, "overweight_fee", default: none), cur),
    )
  }).flatten(),
)

// =============================================================================
// 5. PROVENANCE — every figure carries its confidence and its date
// =============================================================================

#let unconfirmed = alw-segments.filter(s => {
  let c = get(get(s, "source", default: (:)), "confidence", default: "assumed")
  lower(str(c)) != "confirmed"
})

#if unconfirmed.len() > 0 {
  warn-box(
    title: "Not every figure above is confirmed",
    accent: over-fg,
    bg: over-bg,
    text(size: 9pt)[
      #for s in unconfirmed [
        *#get(s, "segment_id", default: "?") (#seg-carrier(get(s, "segment_id", default: "?")))* —
        #get(get(s, "source", default: (:)), "confidence", default: "unknown"). \
      ]
      Anything derived from these is provisional. Confirm with the carrier before
      the airport, and treat the tighter of the two readings as the real limit.
    ],
  )
}

#v(2pt)
#text(size: 8pt, fill: muted)[
  *Sources.*
  #for s in alw-segments [
    #let sid = get(s, "segment_id", default: "?")
    #let src = get(s, "source", default: (:))
    #sid #confidence-flag(get(src, "confidence", default: none), size: 7.5pt)
    fetched #get(src, "fetched_on", default: "date unknown")
    via #get(src, "route", default: "unknown route").#h(6pt)
  ]
  Allowances verified #get(allow, "verified_on", default: "—"). Plan generated
  #if generated-on != none [#generated-on] else [—] by
  #get(plan, "solver", default: "the packing solver").
]
