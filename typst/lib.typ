// =============================================================================
// travel-packing — shared styling and helpers
// =============================================================================
//
// Imported by counter-card.typ and packing-list.typ. Not compiled on its own.
//
//   #import "lib.typ": *
//
// -----------------------------------------------------------------------------
// TYPEFACE
// -----------------------------------------------------------------------------
// This file deliberately sets NO font family. Typst ships Libertinus Serif (and
// New Computer Modern) embedded in the binary, so the default resolves on every
// machine with no fonts installed and no `--font-path`. A template that names
// Helvetica, Inter or Source Sans renders differently — or fails — depending on
// whose laptop compiles it, and these documents are printed once, at 06:00, by
// whoever is travelling. Do not add `set text(font: ...)` without shipping the
// font file and a `--font-path` in the documented invocation.
//
// -----------------------------------------------------------------------------
// PATHS
// -----------------------------------------------------------------------------
// Typst resolves a leading `/` against `--root`, and every file read must live
// inside that root. `in-path` normalises whatever came in through `--input` so
// both of these work:
//
//   --root /path/to/trip   --input plan=plan.yaml
//   --root /               --input plan=/path/to/trip/plan.yaml
//
// See the comment block at the top of each template for full invocations.
// =============================================================================

#let in-path(key, fallback) = {
  let p = sys.inputs.at(key, default: fallback)
  if p.starts-with("/") { p } else { "/" + p }
}

// -----------------------------------------------------------------------------
// Palette — muted, high contrast, prints legibly in greyscale.
// -----------------------------------------------------------------------------

#let ink = rgb("#1a1a1a")
#let muted = rgb("#5f6368")
#let faint = rgb("#8a8f94")
#let rule = rgb("#c9ccd0")
#let hairline = rgb("#e3e5e8")

#let ok-fg = rgb("#1d6b3f")
#let ok-bg = rgb("#e6f2ea")
#let tight-fg = rgb("#8a5a00")
#let tight-bg = rgb("#fbf0d9")
#let over-fg = rgb("#9b1c1c")
#let over-bg = rgb("#fbe6e6")

// -----------------------------------------------------------------------------
// Null-safe accessors and number formatting
// -----------------------------------------------------------------------------

// Read `key` from a dictionary that may itself be missing or none.
// Returns `default` when the dictionary, the key, or the value is absent.
#let get(d, key, default: none) = {
  if type(d) != dictionary { return default }
  let v = d.at(key, default: none)
  if v == none { default } else { v }
}

// Fixed-decimal number. `none` renders as an em dash, never as "0" — a missing
// weight and a zero weight mean very different things at a check-in desk.
// `digits: 0` gives a true integer: Typst's repr() of a float keeps the ".0",
// which turns a piece count into "1.0 × 23 kg" and reads as a mistake.
// Typst also drops a trailing zero (repr(1.50) is "1.5"), which makes a column
// of weights look ragged and invites a misread of 1.5 as 1.05. Pad it back.
#let num(x, digits: 1) = {
  if x == none { return [—] }
  if type(x) == str { return [#x] }
  if digits <= 0 { return [#str(int(calc.round(x * 1.0)))] }
  let parts = repr(calc.round(x * 1.0, digits: digits)).split(".")
  let ip = parts.at(0)
  let fp = if parts.len() > 1 { parts.at(1) } else { "" }
  if fp.len() > digits { fp = fp.slice(0, digits) }
  while fp.len() < digits { fp = fp + "0" }
  [#{ip + "." + fp}]
}

// Weight in kilograms, one decimal, null-safe.
#let kg(x, digits: 1) = {
  if x == none { return [—] }
  [#num(x, digits: digits) kg]
}

// Signed weight — used for headroom, where the sign is the whole message.
#let kg-signed(x, digits: 1) = {
  if x == none { return [—] }
  if x < 0 { text(fill: over-fg, weight: "bold")[−#num(calc.abs(x), digits: digits) kg] }
  else { kg(x, digits: digits) }
}

// Grams (from inventory.yaml) shown as kilograms — the unit conversion lives
// here, in one place, because mixing g and kg is the classic way to get a
// wrong total.
#let g-as-kg(weight-g, qty: 1) = {
  if weight-g == none { return [—] }
  kg(weight-g * qty / 1000.0, digits: 2)
}

// "55 × 40 × 20 cm", null-safe.
#let dims(d) = {
  if d == none or type(d) != array or d.len() == 0 { return [—] }
  [#d.map(v => str(v)).join(" × ") cm]
}

// Money with an explicit currency code — never a bare number, because two
// segments in this document can quote fees in different currencies.
#let money(amount, currency, digits: 0) = {
  if amount == none { return [—] }
  let c = if currency == none { "" } else { currency + " " }
  [#c#num(amount, digits: digits)]
}

// -----------------------------------------------------------------------------
// Status badge
// -----------------------------------------------------------------------------
// ok / tight / over as a small pill. The wording carries the meaning on its
// own, so the card still works photocopied, faxed or printed on a mono laser:
// colour is reinforcement, not the signal.

// The figure a check-in scale will actually agree with. `plan.yaml` reports a
// projection from the itemised inventory; where a real scale reading exists and is
// heavier, that reading wins, because the difference is mass the inventory never
// captured. See docs/design-notes.md, "Measured weight beats itemised weight".
#let governing-kg(projected, measured) = {
  if measured == none { projected }
  else if projected == none { measured }
  else if measured > projected { measured }
  else { projected }
}

// Status recomputed from a headroom figure, using the same bands as
// scripts/pack_solver.py — ok above 1.5 kg, tight from 0 to 1.5, over below zero.
// The documents recompute rather than reprinting plan.yaml's `status` so that a
// measured reading can flip a bag to `over` without the plan being regenerated.
#let status-for(headroom) = {
  if headroom == none { none }
  else if headroom < 0 { "over" }
  else if headroom <= 1.5 { "tight" }
  else { "ok" }
}

#let status-badge(status, size: 8pt) = {
  let s = if status == none { "" } else { lower(str(status)) }
  let (fg, bg, label) = if s == "ok" {
    (ok-fg, ok-bg, "OK")
  } else if s == "tight" {
    (tight-fg, tight-bg, "TIGHT")
  } else if s == "over" {
    (over-fg, over-bg, "OVER")
  } else {
    (muted, white, "—")
  }
  box(
    fill: bg,
    stroke: 0.6pt + fg,
    radius: 2pt,
    inset: (x: 4pt, y: 1.5pt),
    outset: (y: 1.5pt),
    text(size: size, weight: "bold", fill: fg, tracking: 0.5pt, label),
  )
}

// -----------------------------------------------------------------------------
// Confidence flag
// -----------------------------------------------------------------------------
// `confirmed` is quiet. `inferred` and `assumed` must be visible wherever the
// figure they qualify is shown — an assumed allowance that reads like a
// confirmed one is worse than no allowance at all.

#let confidence-flag(confidence, size: 8pt) = {
  let c = if confidence == none { "unknown" } else { lower(str(confidence)) }
  if c == "confirmed" {
    text(size: size, fill: muted)[confirmed]
  } else if c == "inferred" {
    box(fill: tight-bg, stroke: 0.5pt + tight-fg, radius: 2pt, inset: (x: 3pt, y: 1pt),
      text(size: size, weight: "bold", fill: tight-fg)[INFERRED])
  } else if c == "assumed" {
    box(fill: over-bg, stroke: 0.5pt + over-fg, radius: 2pt, inset: (x: 3pt, y: 1pt),
      text(size: size, weight: "bold", fill: over-fg)[! ASSUMED])
  } else {
    box(fill: over-bg, stroke: 0.5pt + over-fg, radius: 2pt, inset: (x: 3pt, y: 1pt),
      text(size: size, weight: "bold", fill: over-fg)[! #upper(c)])
  }
}

// -----------------------------------------------------------------------------
// Blocks
// -----------------------------------------------------------------------------

#let warn-box(body, title: none, accent: tight-fg, bg: tight-bg) = {
  block(
    width: 100%,
    fill: bg,
    stroke: (left: 2.5pt + accent, rest: 0.5pt + rule),
    radius: (right: 2pt),
    inset: (x: 9pt, y: 8pt),
    above: 10pt,
    below: 10pt,
    {
      if title != none {
        text(size: 9.5pt, weight: "bold", fill: accent, tracking: 0.4pt, upper(title))
        v(3pt, weak: true)
      }
      body
    },
  )
}

// A headline figure: the number a gate agent and a traveller both look at.
// Each part is its own block. Stacking them as paragraphs inside one block
// lets a tall inline element (a confidence badge, say) overlap the line above
// it, which is how the big number ends up with text printed through it.
#let big-figure(value, label, note: none, width: 100%, size: 26pt) = {
  block(
    width: width,
    stroke: 0.8pt + rule,
    radius: 2pt,
    inset: (x: 8pt, y: 7pt),
    {
      block(above: 0pt, below: 3pt,
        text(size: 8pt, fill: muted, tracking: 0.6pt, upper(label)))
      block(above: 0pt, below: 2pt,
        text(size: size, weight: "bold")[#value])
      if note != none {
        block(above: 7pt, below: 0pt, text(size: 8pt, fill: muted)[#note])
      }
    },
  )
}

// One line of small print inside a figure box or a note stack. Kept as its own
// block so that inline badges cannot collide with neighbouring lines.
#let note-line(body, above: 3pt) = block(above: above, below: 0pt, body)

// Section heading with a hairline under it.
#let section(title, note: none) = {
  block(above: 12pt, below: 6pt, {
    grid(
      columns: (1fr, auto),
      align: (left + bottom, right + bottom),
      text(size: 11pt, weight: "bold", tracking: 0.3pt, upper(title)),
      if note != none { text(size: 8.5pt, fill: muted)[#note] } else { [] },
    )
    v(2pt, weak: true)
    line(length: 100%, stroke: 0.8pt + rule)
  })
}

// Table header cell.
#let th(body) = text(size: 8.5pt, weight: "bold", fill: muted, tracking: 0.4pt, upper(body))

// An empty box the traveller ticks with a pen while packing.
#let checkbox = box(width: 8pt, height: 8pt, stroke: 0.7pt + muted, radius: 1pt)

// Carriage markers. A power bank in the wrong bag costs more time at security
// than a heavy bag costs at the desk, so restricted items are marked in the
// row itself, not only in a footnote.
#let carriage-marker(carriage) = {
  let c = if carriage == none { "any" } else { lower(str(carriage)) }
  if c == "cabin-only" { text(fill: tight-fg, weight: "bold")[†] }
  else if c == "checked-only" { text(fill: ok-fg, weight: "bold")[‡] }
  else if c == "prohibited" { text(fill: over-fg, weight: "bold")[✖] }
  else { [] }
}

#let carriage-legend = text(size: 8.5pt, fill: muted)[
  #text(fill: tight-fg, weight: "bold")[†] cabin-only — must travel in the cabin
  (lithium batteries, medication, documents).#h(10pt)
  #text(fill: ok-fg, weight: "bold")[‡] checked-only — must not go through security
  (liquids over 100 ml, sharps, tools).#h(10pt)
  #text(fill: over-fg, weight: "bold")[✖] prohibited — cannot fly at all.
]

// -----------------------------------------------------------------------------
// Page setup
// -----------------------------------------------------------------------------
//
//   #show: doc => conf(title: "…", subtitle: "…", trip: trip-dict, doc)
//
// `trip` is the `trip:` mapping from itinerary.yaml (or anything with a
// `label`). `generated` is the date string printed in the header; pass
// plan.yaml's `generated_on` so the document dates the data, not the print run.

#let conf(
  title: none,
  subtitle: none,
  trip: (:),
  generated: none,
  margin: 1.5cm,
  body-size: 10.5pt,
  title-size: 20pt,
  footer-note: "generated by travel-packing",
  doc,
) = {
  let trip-label = get(trip, "label", default: get(trip, "id", default: ""))
  let gen = if generated == none {
    datetime.today().display("[year]-[month]-[day]")
  } else {
    str(generated)
  }

  set document(title: if title == none { trip-label } else { title })
  set page(
    paper: "a4",
    margin: (x: margin, top: margin + 0.7cm, bottom: margin + 0.6cm),
    header: {
      set text(size: 8.5pt, fill: muted)
      grid(
        columns: (1fr, auto),
        align: (left + horizon, right + horizon),
        [#trip-label],
        [generated #gen],
      )
      v(-4pt)
      line(length: 100%, stroke: 0.5pt + hairline)
    },
    footer: context {
      set text(size: 8pt, fill: faint)
      line(length: 100%, stroke: 0.5pt + hairline)
      v(-3pt)
      grid(
        columns: (1fr, auto, 1fr),
        align: (left + horizon, center + horizon, right + horizon),
        [#footer-note],
        [#counter(page).display() / #counter(page).final().first()],
        [#trip-label],
      )
    },
  )

  set text(size: body-size, fill: ink)
  set par(justify: false, leading: 0.62em)
  set list(indent: 6pt, spacing: 5pt)
  set table(
    stroke: (x, y) => (
      top: if y == 0 { 0.8pt + rule } else { 0.5pt + hairline },
      bottom: 0.5pt + hairline,
    ),
    inset: (x: 5pt, y: 4.5pt),
    align: left + horizon,
  )
  show table.cell.where(y: 0): set text(size: 8.5pt)

  // Title block. Title and subtitle are separate blocks: as paragraphs in one
  // block the 19pt line and the 10.5pt line collide on the descenders.
  if title != none {
    block(above: 0pt, below: if subtitle == none { 10pt } else { 6pt },
      text(size: title-size, weight: "bold")[#title])
    if subtitle != none {
      block(above: 0pt, below: 10pt, text(size: 10.5pt, fill: muted)[#subtitle])
    }
  }

  doc
}
