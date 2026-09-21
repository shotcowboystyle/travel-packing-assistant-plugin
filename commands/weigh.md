# Weigh

Record scale readings and reconcile them against the inventory.

Invoke the `weigh-bags` skill and follow it. Readings append — never overwrite an earlier
weighing. Record the phase (`empty`, `outbound`, `current`, `final`), the date and the scale.

Run `scripts/reconcile.py` afterwards and lead the report with the arithmetic: gross, allowance,
headroom, then the unaccounted mass.

`$ARGUMENTS` may contain the readings directly, e.g. `CHK1 22.4 current`.
