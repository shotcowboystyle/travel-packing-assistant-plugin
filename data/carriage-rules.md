# Carriage rules — what constrains the pack regardless of weight

Reference for setting the `carriage` field in `inventory.yaml`. These are **structural rules**
that hold broadly across carriers and jurisdictions, and they are the ones that override any
weight optimisation: a solver that puts a power bank in a checked bag has produced a plan that
fails at the security check no matter how good the arithmetic was.

**Status of this file.** Written 2026-08-16 from the long-standing international framework
(the ICAO Technical Instructions for dangerous goods, and the cabin liquids restrictions
adopted across most jurisdictions). It is a *starting point for classification*, not a source
to quote at anyone. Carriers apply stricter limits than the framework routinely, and individual
airports and states vary — particularly on liquids screening, where several jurisdictions have
been relaxing the rules unevenly as scanner technology is rolled out. Verify against the
operating carrier and the departure airport for anything that matters, and record what you
find in the trip workspace rather than editing this file.

## cabin-only

Must travel in the cabin; not permitted in checked baggage.

| Item | Why | Usual limit |
| --- | --- | --- |
| Power banks | Lithium fire risk must be where it can be dealt with | Generally up to 100 Wh freely; 100–160 Wh commonly needs carrier approval; above 160 Wh generally not carried |
| Spare/loose lithium batteries | Same | Terminals taped or individually bagged |
| E-cigarettes, vapes | Same, plus accidental activation | Cabin only, usually no in-flight charging or use |
| Medication and prescriptions | Needed in flight; a checked bag can go missing | Keep with documentation |
| Travel documents, keys, valuables | Irreplaceable or trip-ending if lost | — |
| Laptops, cameras, phones | Installed batteries; also theft and damage exposure | — |

Watt-hours are not printed on every device. Wh = (mAh ÷ 1000) × nominal voltage; a power bank
labelled only in mAh is almost always 3.7 V nominal, so a 20 000 mAh pack is about 74 Wh.
Record the calculation in `carriage_reason` when it is the reason an item is pinned to the
cabin.

Several carriers have additionally restricted power-bank *use* in flight — no charging from
them, no stowing them in the overhead bin. That affects where in the cabin bag it goes, not
whether it travels.

## checked-only

Not permitted through the cabin security check; must go in a checked bag if carried at all.

| Item | Why |
| --- | --- |
| Liquids, gels, pastes, creams in containers over 100 ml | Cabin liquids restriction. It is the **container size** that is measured, not how much is left in it — a half-empty 200 ml bottle is refused |
| Sharps: knives, scissors over the permitted blade length, razors with exposed blades, tools | Prohibited in the cabin |
| Most tools over a modest length | Prohibited in the cabin |
| Some aerosols and flammables, in limited quantity | Permitted checked within limits, barred from cabin |

A number of airports now operate scanners that lift the 100 ml rule, and some have introduced
and then re-imposed it. Treat a relaxation as true only for the specific airport you have
verified it at, on the date you verified it — the traveller passes through more than one.

## prohibited

Not carried at all, in either bag, on a normal passenger ticket: explosives and fireworks,
compressed gases beyond small personal exceptions, corrosives, oxidisers, most flammable
liquids, and damaged or recalled lithium batteries. Anything in this class is a conversation
with the carrier, not a packing decision.

## Things that are not rules but behave like them

- **The 32 kg handling ceiling.** Widely applied as the maximum weight of a single checked
  piece, as a manual-handling limit for ground staff. Above it a bag is refused outright and no
  excess fee resolves it. Some carriers set the ceiling at 23 kg in economy. Find the number
  per carrier and record it as `hard_max_weight_kg`.
- **158 cm linear.** Length + width + height, the common checked dimension cap. Measured
  including wheels and handles, which is how a case sold as "compliant" fails.
- **Worn items are not weighed.** Coats, boots and loaded jacket pockets do not go on the
  scale. This is entirely normal and is worth several kilograms on a marginal bag.
- **Duty-free bought airside** is generally exempt from the cabin liquids limit in a sealed
  tamper-evident bag, but it still has weight and it still counts against a cabin allowance
  that is actually weighed — and it can be re-screened at a connection, where the exemption
  sometimes does not survive.
