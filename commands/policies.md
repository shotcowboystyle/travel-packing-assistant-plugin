# Baggage Policies

Research the checked, cabin and personal-item allowance for every segment in `itinerary.yaml`,
and compute the binding limit for the journey.

Invoke the `baggage-policy-research` skill and follow it, including its sourcing rule: every
figure written to `allowances.yaml` carries a source URL, the sentence it came from, and a
confidence level. Save each fetched page under `research/` before extracting from it.

Report the binding limit in one sentence, then list every figure that is not `confirmed`
alongside the specific action that would confirm it.
