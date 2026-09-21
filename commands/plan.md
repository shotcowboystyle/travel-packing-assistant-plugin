---
description: Solve the pack against the binding limit and give cube-by-cube packing instructions
---

# Plan

Solve the pack and turn it into packing instructions.

Invoke the `pack-plan` skill and follow it. Check its preconditions first — an assumed
allowance, a missing tare or an incomplete inventory each make the plan provisional, and a
provisional plan must say so.

Run `scripts/pack_solver.py`, report the bag-by-bag arithmetic before any interpretation, then
give the physical instructions cube by cube.

`$ARGUMENTS` may carry solver options: `--objective consolidate`, `--overflow`.
