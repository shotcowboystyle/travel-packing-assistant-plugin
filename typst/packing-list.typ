// =============================================================================
// travel-packing — PACKING LIST
// =============================================================================
//
// The working document: what goes in which bag, in which cube, in what
// quantity, with a box to tick as each thing goes in. Multi-page by design —
// this one is read at home with the bags open, not at the desk. The one-page
// card the traveller carries is counter-card.typ.
//
// Numbers are read straight out of the YAML at compile time. Nothing is
// transcribed into this file, because transcription is where totals go wrong.
//
// -----------------------------------------------------------------------------
// COMPILE
// -----------------------------------------------------------------------------
// Typst refuses to compile a source file outside `--root`, so the root must
// contain BOTH this template and the trip workspace. Two forms work; both were
// verified with Typst 0.14.2.
//
// (a) Templates left in the plugin, root at the filesystem root. Data paths are
//     plain absolute paths — the form to use from a skill:
//
//       typst compile --root / \
//         --input itinerary=/abs/trip/itinerary.yaml \
//         --input plan=/abs/trip/plan.yaml \
//         --input bags=/abs/trip/bags.yaml \
//         --input inventory=/abs/trip/inventory.yaml \
//         /abs/plugin/typst/packing-list.typ \
//         /abs/trip/output/packing-list.pdf
//
// (b) Templates copied into the workspace (`cp -r <plugin>/typst <trip>/.typst`),
//     root at the workspace:
//
//       cd /abs/trip
//       typst compile --root . \
//         --input itinerary=itinerary.yaml \
//         --input plan=plan.yaml \
//         --input bags=bags.yaml \
//         --input inventory=inventory.yaml \
//         .typst/packing-list.typ output/packing-list.pdf
//
// All four inputs are optional and default to the bare filenames.
// itinerary.yaml supplies the trip label only; every number comes from
// plan.yaml, bags.yaml and inventory.yaml.
// =============================================================================

#import "lib.typ": *

#let itin = yaml(in-path("itinerary", "itinerary.yaml"))
#let plan = yaml(in-path("plan", "plan.yaml"))
#let bagfile = yaml(in-path("bags", "bags.yaml"))
#let inventory = yaml(in-path("inventory", "inventory.yaml"))

#let trip = get(itin, "trip", default: (:))
#let plan-bags = get(plan, "bags", default: ())
#let all-items = get(inventory, "items", default: ())

// ---- lookups ---------------------------------------------------------------

#let item-index = {
  let m = (:)
  for it in all-items { m.insert(str(get(it, "id", default: "?")), it) }
  m
}

#let bag-index = {
  let m = (:)
  for b in get(bagfile, "bags", default: ()) { m.insert(str(get(b, "id", default: "?")), b) }
  m
}

// Cube metadata (label, tare) lives in bags.yaml; the plan only lists which
// item ids went into which cube.
#let cube-meta(bag-id, cube-id) = {
  let b = bag-index.at(str(bag-id), default: none)
  if b == none { return (:) }
  for c in get(b, "cubes", default: ()) {
    if str(get(c, "id", default: "")) == str(cube-id) { return c }
  }
  (:)
}

#let item-total-g(it) = {
  let w = get(it, "weight_g", default: none)
  if w == none { return none }
  w * get(it, "qty", default: 1)
}

#let generated-on = {
  let g = get(plan, "generated_on", default: none)
  if g == none { none } else { str(g).replace("T", " ") }
}

#show: doc => conf(
  title: "Packing list",
  subtitle: get(trip, "label", default: none),
  trip: trip,
  generated: if generated-on == none { none } else { generated-on.split(" ").at(0) },
  margin: 1.6cm,
  body-size: 10.5pt,
  title-size: 20pt,
  doc,
)

// =============================================================================
// SUMMARY
// =============================================================================

#section("Summary", note: "one line per bag, as the plan stands")

#table(
  columns: (1fr, auto, auto, auto, auto, auto, auto),
  align: (left + horizon, left + horizon, right + horizon, right + horizon,
          right + horizon, right + horizon, center + horizon),
  table.header(
    th("Bag"), th("Type"), th("Tare"), th("Contents"),
    th("Gross"), th("Headroom"), th("Status"),
  ),
  ..plan-bags.map(b => {
    // Same rule as the counter card: a scale reading heavier than the projection
    // supersedes it, and headroom and status are taken against the heavier figure.
    // The two documents must not disagree about whether a bag is over.
    let projected = get(b, "projected_gross_kg", default: none)
    let measured = get(b, "last_weighing_kg", default: none)
    let allowance = get(b, "allowance_kg", default: none)
    let governing = governing-kg(projected, measured)
    let headroom = if allowance == none or governing == none { none } else { allowance - governing }
    (
      [#get(b, "label", default: get(b, "id", default: "?"))
       #text(size: 8pt, fill: faint)[#get(b, "id", default: "")]],
      text(size: 9.5pt)[#get(b, "type", default: "—")],
      kg(get(b, "tare_kg", default: none) + get(b, "cube_tare_kg", default: 0)),
      kg(get(b, "contents_kg", default: none)),
      [#text(weight: "bold")[#kg(governing)] \
       #text(size: 8pt, fill: muted)[of #kg(allowance)#if measured != none and measured > projected [ · weighed]]],
      kg-signed(headroom),
      status-badge(status-for(headroom)),
    )
  }).flatten(),
)

#let bag-item-ids(b) = {
  let in-cubes = get(b, "cubes", default: ()).map(c => get(c, "items", default: ())).flatten()
  in-cubes + get(b, "loose_items", default: ())
}

#let packed-ids = plan-bags.map(b => bag-item-ids(b)).flatten()

#let packed-units = packed-ids.map(id => {
  get(item-index.at(str(id), default: (:)), "qty", default: 1)
}).sum(default: 0)

// Totals use the same governing figure as the table, so the summary line cannot
// disagree with the rows above it.
#let total-gross = plan-bags.map(b => {
  let g = governing-kg(get(b, "projected_gross_kg", default: none), get(b, "last_weighing_kg", default: none))
  if g == none { 0 } else { g }
}).sum(default: 0)

#text(size: 9pt, fill: muted)[
  #packed-ids.len() inventory lines / #packed-units physical units packed across
  #plan-bags.len() bags · #kg(total-gross) total mass leaving the house ·
  #get(plan, "unassigned", default: ()).len() lines not packed.
  Weights come from inventory.yaml in grams and are converted here; bag and cube
  tares come from bags.yaml in kilograms.
]

// ---- warnings --------------------------------------------------------------

#let warnings = get(plan, "warnings", default: ())
#if warnings.len() > 0 {
  warn-box(
    title: "Warnings from the solver",
    accent: over-fg,
    bg: over-bg,
    {
      set text(size: 9.5pt)
      for w in warnings [
        - #w
      ]
    },
  )
}

#v(2pt)
#carriage-legend

// =============================================================================
// ONE SECTION PER BAG
// =============================================================================

// A single item row: tick box, marker, name, quantity, unit weight, line total.
#let item-row(id) = {
  let it = item-index.at(str(id), default: none)
  if it == none {
    return (
      checkbox,
      text(fill: over-fg)[#id — *not found in inventory.yaml*],
      [—], [—], [—], [—],
    )
  }
  let carriage = get(it, "carriage", default: "any")
  let reason = get(it, "carriage_reason", default: none)
  let qty = get(it, "qty", default: 1)
  (
    checkbox,
    {
      [#carriage-marker(carriage) #get(it, "name", default: "(unnamed)")
       #text(size: 8pt, fill: faint)[#get(it, "id", default: "")]]
      if lower(str(carriage)) != "any" and reason != none {
        linebreak()
        text(size: 8pt, fill: muted)[#lower(str(carriage)): #reason]
      }
    },
    text(size: 9.5pt)[#qty],
    text(size: 9.5pt)[#num(get(it, "weight_g", default: none), digits: 0) g],
    text(size: 9.5pt, weight: "bold")[#g-as-kg(get(it, "weight_g", default: none), qty: qty)],
    text(size: 9pt, fill: muted)[#get(it, "category", default: "—")],
  )
}

#let items-table(ids, subtotal-label: none, subtotal-extra-kg: 0) = {
  let total-g = ids.map(id => {
    let it = item-index.at(str(id), default: none)
    if it == none { 0 } else {
      let t = item-total-g(it)
      if t == none { 0 } else { t }
    }
  }).sum(default: 0)

  table(
    columns: (auto, 1fr, auto, auto, auto, auto),
    align: (center + horizon, left + horizon, right + horizon, right + horizon,
            right + horizon, left + horizon),
    table.header(
      th("✓"), th("Item"), th("Qty"), th("Each"), th("Line"), th("Category"),
    ),
    ..ids.map(id => item-row(id)).flatten(),
    ..if subtotal-label == none { () } else {
      (
        table.cell(colspan: 4, align: right,
          text(size: 9pt, weight: "bold", fill: muted)[#subtotal-label]),
        text(size: 9.5pt, weight: "bold")[#kg(total-g / 1000.0 + subtotal-extra-kg, digits: 2)],
        [],
      )
    },
  )
}

#for b in plan-bags {
  pagebreak(weak: true)

  let bid = get(b, "id", default: "?")
  section(
    get(b, "label", default: bid),
    note: [#bid · #get(b, "type", default: "")],
  )

  // Facts strip: the four numbers that decide whether this bag is a problem.
  grid(
    columns: (1fr, 1fr, 1fr, 1fr),
    column-gutter: 6pt,
    big-figure(kg(get(b, "tare_kg", default: none)), "Tare (empty bag)",
      note: [plus #kg(get(b, "cube_tare_kg", default: 0), digits: 2) of cubes], size: 15pt),
    big-figure(kg(get(b, "contents_kg", default: none)), "Contents", size: 15pt,
      note: [itemised from inventory.yaml]),
    big-figure(kg(get(b, "projected_gross_kg", default: none)), "Projected gross", size: 15pt,
      note: [allowance #kg(get(b, "allowance_kg", default: none))]),
    big-figure(kg-signed(get(b, "headroom_kg", default: none)), "Headroom", size: 15pt,
      note: status-badge(get(b, "status", default: none))),
  )

  let last-weighing = get(b, "last_weighing_kg", default: none)
  if last-weighing != none {
    v(4pt)
    let delta = last-weighing - get(b, "projected_gross_kg", default: last-weighing)
    text(size: 9pt, fill: muted)[
      Last scale reading #kg(last-weighing) — #kg(calc.abs(delta), digits: 2)
      #if delta >= 0 [more] else [less] than the itemised projection. A gap this
      way usually means something in the bag is not in inventory.yaml.
    ]
  }

  // ---- cubes, then loose items --------------------------------------------
  for c in get(b, "cubes", default: ()) {
    let cid = get(c, "id", default: "?")
    let meta = cube-meta(bid, cid)
    v(8pt)
    block(above: 6pt, below: 4pt, {
      text(size: 10pt, weight: "bold")[#get(meta, "label", default: cid)]
      text(size: 9pt, fill: muted)[
        #h(4pt) #cid · cube tare #kg(get(meta, "tare_kg", default: 0), digits: 2)
        #if get(meta, "volume_l", default: none) != none [ · #get(meta, "volume_l", default: "") L]
      ]
    })
    items-table(
      get(c, "items", default: ()),
      subtotal-label: "Cube total, including cube tare",
      subtotal-extra-kg: get(meta, "tare_kg", default: 0),
    )
  }

  let loose = get(b, "loose_items", default: ())
  if loose.len() > 0 {
    v(8pt)
    block(above: 6pt, below: 4pt, {
      text(size: 10pt, weight: "bold")[Loose in the bag]
      text(size: 9pt, fill: muted)[#h(4pt) not in a packing cube]
    })
    items-table(loose, subtotal-label: "Loose total")
  }

  v(6pt)
  carriage-legend
}

// =============================================================================
// NOT PACKED
// =============================================================================

#pagebreak(weak: true)

#let unassigned = get(plan, "unassigned", default: ())

#section("Not packed", note: "items the solver could not place")

#if unassigned.len() == 0 {
  text(size: 10pt, fill: muted)[Everything in inventory.yaml was assigned to a bag.]
} else {
  table(
    columns: (1fr, auto, auto, 1.4fr),
    align: (left + horizon, right + horizon, left + horizon, left + horizon),
    table.header(th("Item"), th("Weight"), th("Carriage"), th("Why it is not packed")),
    ..unassigned.map(u => {
      let id = get(u, "item", default: "?")
      let it = item-index.at(str(id), default: none)
      let qty = get(it, "qty", default: 1)
      (
        [#carriage-marker(get(it, "carriage", default: "any"))
         #get(it, "name", default: id)
         #text(size: 8pt, fill: faint)[#id]],
        text(size: 9.5pt)[#g-as-kg(get(it, "weight_g", default: none), qty: qty)],
        text(size: 9pt)[#get(it, "carriage", default: "any")],
        text(size: 9pt)[#get(u, "reason", default: "no reason recorded")],
      )
    }).flatten(),
  )
  v(4pt)
  carriage-legend
}

// ---- leave-behind ranking --------------------------------------------------

#let ranking = get(plan, "overflow_ranking", default: ())

#if ranking.len() > 0 {
  section("If weight has to come out", note: "ranked by cost per kilogram saved")

  text(size: 9pt, fill: muted)[
    Cheapest sacrifice first. The ranking is money-per-kilogram, not weight: a
    heavy thing that can be re-bought at the far end is a better thing to leave
    than a light thing that cannot.
  ]
  v(5pt)

  table(
    columns: (auto, 1.1fr, auto, auto, auto, auto, 1.2fr),
    align: (center + horizon, left + horizon, left + horizon, right + horizon,
            right + horizon, right + horizon, left + horizon),
    table.header(
      th("#"), th("Item"), th("Bag"), th("Saves"), th("Re-buy"), th("Per kg"), th("Note"),
    ),
    ..ranking.enumerate().map(pair => {
      let (i, r) = pair
      let id = get(r, "item", default: "?")
      let it = item-index.at(str(id), default: none)
      let cur = get(r, "currency", default: none)
      (
        text(weight: "bold")[#get(r, "rank", default: i + 1)],
        {
          [#get(it, "name", default: id) #text(size: 8pt, fill: faint)[#id]]
          let tier = get(r, "tier", default: get(it, "tier", default: none))
          if tier != none {
            linebreak()
            text(size: 8pt, fill: muted)[#tier]
          }
        },
        text(size: 9pt)[#get(r, "bag", default: "—")],
        text(size: 9.5pt, weight: "bold")[#kg(get(r, "kg_saved", default: none), digits: 2)],
        text(size: 9.5pt)[#if get(r, "replaceable", default: false) {
          money(get(r, "replace_cost", default: none), cur)
        } else {
          text(fill: over-fg)[not re-buyable]
        }],
        text(size: 9.5pt)[#if get(r, "cost_per_kg", default: none) != none {
          money(get(r, "cost_per_kg", default: none), cur, digits: 1)
        } else { [—] }],
        text(size: 9pt, fill: muted)[#get(r, "note", default: "")],
      )
    }).flatten(),
  )
}
