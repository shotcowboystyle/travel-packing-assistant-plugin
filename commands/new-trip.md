---
description: Provision a new trip workspace for one itinerary
---

# New Trip Workspace

Provision a packing workspace for a specific itinerary.

Invoke the `new-workspace` skill from this plugin and follow it exactly. Pass `$ARGUMENTS`
through as the trip name, optional target parent path, and flags (`--local-only`, `--public`).

If no trip name was given, ask for one before touching the filesystem. Prefer a
route-and-date name: `bos-ath-tlv-0826`.
