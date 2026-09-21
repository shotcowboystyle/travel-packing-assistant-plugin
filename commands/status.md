---
description: Show where this trip stands — validation, reconciliation and what to do next
---

# Status

Where this trip stands, in one screen.

Read whichever of `itinerary.yaml`, `allowances.yaml`, `bags.yaml`, `inventory.yaml` and
`plan.yaml` exist in the current workspace, then run:

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/validate.py . --json
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/reconcile.py . --json
```

Report, in this order:

1. Days to departure, and any deadline from `overage.md` that has not passed.
2. Binding limits, and how many allowance figures are not `confirmed`.
3. Per bag: projected or measured gross, allowance, headroom, status.
4. What is missing — the next unrun step in
   `itinerary → policies → inventory → weigh → plan → docs`.

Arithmetic first, interpretation second. Do not change any file.
