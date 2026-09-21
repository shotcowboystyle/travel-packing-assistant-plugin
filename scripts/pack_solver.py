#!/usr/bin/env python3
"""Allocate inventory items to bags under the binding baggage allowance, and write plan.yaml.

Reads itinerary.yaml, allowances.yaml, bags.yaml and inventory.yaml from a trip workspace
and writes plan.yaml into the same directory.

Run:
    python scripts/pack_solver.py [WORKSPACE_DIR] [--objective max-min-headroom|consolidate]
                                  [--overflow] [--dry-run] [--json]

The solver is deterministic by construction: every iteration order is a sorted list and
no random number generator is used anywhere, so the same inputs always produce the same
plan. A packing list that changes between runs is useless — you cannot check it against a
bag you already packed. The one field that varies between runs is `generated_on`, which
`--now` can pin for reproducible output.

Exit 0 on success, 1 if the workspace is unusable or a hard constraint was violated,
2 if a dependency is missing.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import math
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterator

try:
    import yaml
except ImportError:  # pragma: no cover - environment guard
    print("Missing dependencies. Install them with: uv pip install pyyaml jsonschema")
    sys.exit(2)

SOLVER_VERSION = "1.0.0"

# Proxy for an item's worth when `value` is absent. The gaps are an order of magnitude
# apart so that no quantity of nice-to-haves outranks one essential in the objective.
TIER_WEIGHT: dict[str, float] = {
    "essential": 1000.0,
    "useful": 100.0,
    "nice-to-have": 10.0,
    "expendable": 1.0,
}

# bag type -> the block under allowances.binding that caps it
BINDING_KEY: dict[str, str] = {
    "checked": "checked",
    "cabin": "cabin",
    "personal": "personal_item",
}

# Which bag types each carriage rule permits. `prohibited` maps to nothing at all.
CARRIAGE_ALLOWS: dict[str, frozenset[str]] = {
    "any": frozenset({"checked", "cabin", "personal"}),
    "cabin-only": frozenset({"cabin", "personal"}),
    "checked-only": frozenset({"checked"}),
    "prohibited": frozenset(),
}

# Airport and home scales routinely disagree by a few hundred grams, and a packed bag
# gains weight from things picked up on the way to the airport. 1.5 kg is roughly the
# error band of a hook scale plus one paperback plus a full water bottle, so anything
# inside it is reported as `tight` rather than `ok`.
TIGHT_BAND_KG = 1.5

EPS = 1e-9
LOCAL_SEARCH_BUDGET = 20000


@dataclass
class Bag:
    id: str
    type: str
    label: str
    tare_kg: float
    cube_tare_kg: float
    cubes: list[dict[str, Any]]
    allowance_kg: float | None  # None = uncapped by the binding allowance
    usable_kg: float  # allowance - tare - cube tare; math.inf when uncapped

    @property
    def capped(self) -> bool:
        return self.allowance_kg is not None


@dataclass
class Item:
    id: str
    name: str
    kg: float
    score: float
    category: str
    tier: str
    carriage: str
    pinned: bool
    preset_bag: str | None
    preset_cube: str | None
    value: float | None
    replaceable: bool
    replace_cost: float | None
    feasible_bags: list[str] = field(default_factory=list)


class SolverError(Exception):
    """Raised for conditions that make the workspace unusable rather than merely wrong."""


def stringify_dates(node: Any) -> Any:
    """PyYAML parses bare ISO dates into date objects; JSON output needs strings."""
    if isinstance(node, dict):
        return {k: stringify_dates(v) for k, v in node.items()}
    if isinstance(node, list):
        return [stringify_dates(v) for v in node]
    if isinstance(node, (dt.datetime, dt.date)):
        return node.isoformat()
    return node


def load_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise SolverError(f"{path.name} is missing from the workspace")
    try:
        with path.open("r", encoding="utf-8") as handle:
            data = yaml.safe_load(handle)
    except yaml.YAMLError as exc:
        raise SolverError(f"{path.name} is not valid YAML: {exc}") from exc
    if not isinstance(data, dict):
        raise SolverError(f"{path.name} must contain a mapping at the top level")
    return stringify_dates(data)


def rounded(value: float, places: int = 3) -> float:
    """Keep float noise out of the plan; 1 g resolution is finer than any scale here."""
    return round(value + 0.0, places)


def binding_limit(binding: dict[str, Any], bag_type: str) -> float | None:
    block = binding.get(BINDING_KEY[bag_type])
    if not isinstance(block, dict):
        return None
    limit = block.get("max_weight_kg")
    if limit is None:
        return None
    return float(limit)


def build_bags(
    bags_doc: dict[str, Any], binding: dict[str, Any], errors: list[str], warnings: list[str]
) -> list[Bag]:
    bags: list[Bag] = []
    uncapped_types: set[str] = set()
    for raw in bags_doc.get("bags") or []:
        if not isinstance(raw, dict) or not raw.get("id"):
            continue
        bag_type = raw.get("type", "checked")
        cubes = [c for c in (raw.get("cubes") or []) if isinstance(c, dict) and c.get("id")]
        cube_tare = sum(float(c.get("tare_kg") or 0.0) for c in cubes)
        tare = float(raw.get("tare_kg") or 0.0)
        if raw.get("tare_kg") is None:
            warnings.append(
                f"Bag {raw['id']} has no tare_kg; its projected gross weight assumes an "
                "empty weight of 0 kg and will read low."
            )
        allowance = binding_limit(binding, bag_type) if bag_type in BINDING_KEY else None
        if allowance is None:
            uncapped_types.add(bag_type)
            usable = math.inf
        else:
            usable = allowance - tare - cube_tare
            if usable < 0:
                errors.append(
                    f"Bag {raw['id']} weighs {rounded(tare + cube_tare)} kg empty (tare plus "
                    f"cubes) against an allowance of {allowance} kg. It cannot be used as it is."
                )
        bags.append(
            Bag(
                id=str(raw["id"]),
                type=str(bag_type),
                label=str(raw.get("label") or raw["id"]),
                tare_kg=tare,
                cube_tare_kg=cube_tare,
                cubes=cubes,
                allowance_kg=allowance,
                usable_kg=usable,
            )
        )
    for bag_type in sorted(uncapped_types):
        warnings.append(
            f"No binding weight limit for bag type '{bag_type}'; those bags are treated as "
            "uncapped and their headroom is reported as null."
        )
    return sorted(bags, key=lambda b: b.id)


def build_items(inventory: dict[str, Any], bags: list[Bag]) -> list[Item]:
    by_type: dict[str, list[str]] = {}
    for bag in bags:
        by_type.setdefault(bag.type, []).append(bag.id)

    items: list[Item] = []
    for raw in inventory.get("items") or []:
        if not isinstance(raw, dict) or not raw.get("id"):
            continue
        qty = int(raw.get("qty") or 1)
        kg = float(raw.get("weight_g") or 0.0) * qty / 1000.0
        tier = str(raw.get("tier") or "useful")
        value = raw.get("value")
        replace = raw.get("replaceable_at_destination") or {}
        if not isinstance(replace, dict):
            replace = {}
        carriage = str(raw.get("carriage") or "any")
        allowed_types = CARRIAGE_ALLOWS.get(carriage, CARRIAGE_ALLOWS["any"])
        feasible = sorted(
            bag_id for t, ids in by_type.items() if t in allowed_types for bag_id in ids
        )
        items.append(
            Item(
                id=str(raw["id"]),
                name=str(raw.get("name") or raw["id"]),
                kg=kg,
                score=float(value) if value is not None else TIER_WEIGHT.get(tier, 100.0),
                category=str(raw.get("category") or "uncategorised"),
                tier=tier,
                carriage=carriage,
                pinned=bool(raw.get("pinned")),
                preset_bag=raw.get("assigned_bag"),
                preset_cube=raw.get("cube"),
                value=float(value) if value is not None else None,
                replaceable=bool(replace.get("possible")),
                replace_cost=(
                    float(replace["cost"]) if replace.get("cost") is not None else None
                ),
                feasible_bags=feasible,
            )
        )
    return sorted(items, key=lambda i: i.id)


# --------------------------------------------------------------------------------------
# Allocation
# --------------------------------------------------------------------------------------


def bag_loads(assignment: dict[str, str | None], items: dict[str, Item], bags: list[Bag]) -> dict[str, float]:
    loads = {bag.id: 0.0 for bag in bags}
    for item_id, bag_id in assignment.items():
        if bag_id is not None:
            loads[bag_id] += items[item_id].kg
    return loads


def objective(
    assignment: dict[str, str | None],
    items: dict[str, Item],
    bags: list[Bag],
    mode: str,
) -> tuple[float, float, float]:
    """Lexicographic objective, higher is better.

    Slot 1 is always the carried value: getting a thing to the destination beats any
    tidiness of the packing. Slot 2 depends on the mode:

    - max-min-headroom lifts the *worst* bag's spare capacity. Maximising total headroom
      instead would happily leave one bag 200 g under its limit while another is half
      empty, and it is the worst bag that gets re-weighed at the desk.
    - consolidate minimises the number of bags in use, for a traveller who would rather
      leave a bag at home than carry a well-balanced extra one.
    """
    score = sum(items[i].score for i, b in assignment.items() if b is not None)
    loads = bag_loads(assignment, items, bags)
    capped = [bag for bag in bags if bag.capped]
    min_headroom = min((bag.usable_kg - loads[bag.id] for bag in capped), default=0.0)
    used = sum(1 for bag in bags if loads[bag.id] > EPS)
    if mode == "consolidate":
        return (score, -float(used), min_headroom)
    return (score, min_headroom, -float(used))


def better(a: tuple[float, ...], b: tuple[float, ...]) -> bool:
    """Strict lexicographic improvement with a tolerance, so the search cannot cycle."""
    for x, y in zip(a, b):
        if x > y + EPS:
            return True
        if x < y - EPS:
            return False
    return False


def seed_allocation(
    items: list[Item],
    bags: list[Bag],
    capacity: dict[str, float],
    mode: str,
    errors: list[str],
) -> tuple[dict[str, str | None], dict[str, str]]:
    """Greedy first pass. Returns (assignment, reasons for the items left out)."""
    by_id = {bag.id: bag for bag in bags}
    assignment: dict[str, str | None] = {item.id: None for item in items}
    reasons: dict[str, str] = {}
    loads = {bag.id: 0.0 for bag in bags}

    # Pinned items go down first and are never reconsidered. A pin is the user overriding
    # the solver, so an overweight pin is reported, not quietly relocated.
    for item in items:
        if not item.pinned:
            continue
        if item.carriage == "prohibited":
            errors.append(f"Item {item.id} is pinned to {item.preset_bag} but carriage=prohibited.")
            reasons[item.id] = "carriage=prohibited"
            continue
        target = item.preset_bag
        if target is None or target not in by_id:
            errors.append(f"Item {item.id} is pinned but assigned_bag {target!r} does not exist.")
            reasons[item.id] = f"pinned to unknown bag {target!r}"
            continue
        if by_id[target].type not in CARRIAGE_ALLOWS[item.carriage]:
            errors.append(
                f"Item {item.id} is pinned to {target} (type {by_id[target].type}) but "
                f"carriage={item.carriage} forbids it."
            )
        # Checked against the bag's true usable capacity, not the effective capacity used
        # elsewhere: that one is floored at the pinned load precisely so an over-pinned bag
        # stays a feasible state for the search, and using it here would hide the overflow.
        limit = by_id[target].usable_kg
        if loads[target] + item.kg > limit + EPS:
            errors.append(
                f"Item {item.id} is pinned to {target} and does not fit: it would take the "
                f"bag {rounded(loads[target] + item.kg - limit)} kg past its allowance. "
                "Unpin it or move it by hand — the solver will not override a pin."
            )
        assignment[item.id] = target
        loads[target] += item.kg

    # Most-constrained-first: an item that fits in only one bag has to claim its space
    # before the flexible items eat it, otherwise the greedy pass strands exactly the
    # items that have nowhere else to go. Heaviest first within the same constraint level,
    # because big items are the ones that stop fitting later.
    movable = [item for item in items if not item.pinned and item.carriage != "prohibited"]
    movable.sort(key=lambda i: (len(i.feasible_bags), -i.kg, i.id))

    for item in movable:
        candidates = [
            bag_id
            for bag_id in item.feasible_bags
            if loads[bag_id] + item.kg <= capacity[bag_id] + EPS
        ]
        if not candidates:
            reasons[item.id] = (
                f"no bag with capacity and carriage={item.carriage}"
                if item.carriage != "any"
                else "no bag with remaining capacity"
            )
            continue
        if mode == "consolidate":
            # Best fit over *open* bags only. Considering empty bags as equals would open
            # a new one for every item and strand the plan on a plateau the single-item
            # local search cannot climb off: emptying a bag takes several moves and no
            # individual move reduces the bag count. Open a fresh bag only when nothing
            # already in use can take the item, and open the largest one when it happens.
            open_bags = [b for b in candidates if loads[b] > EPS]
            if open_bags:
                chosen = min(open_bags, key=lambda b: (capacity[b] - loads[b] - item.kg, b))
            else:
                chosen = max(candidates, key=lambda b: (capacity[b], b))
        else:
            # Worst fit: spread the load, which is what lifting the minimum headroom wants.
            chosen = max(candidates, key=lambda b: (capacity[b] - loads[b], b))
        assignment[item.id] = chosen
        loads[chosen] += item.kg

    for item in items:
        if item.carriage == "prohibited":
            reasons[item.id] = "carriage=prohibited; cannot fly"

    return assignment, reasons


def unassigned_reason(item: Item) -> str:
    """Explain a leftover item in the terms the traveller has to act on.

    An item can end up unassigned either because nothing could legally hold it, or —
    more often — because the objective preferred to carry something more valuable in
    the same kilograms. Both readings matter, so say which one applies.
    """
    if item.carriage == "prohibited":
        return "carriage=prohibited; cannot fly"
    if not item.feasible_bags:
        return f"no bag of a type permitted by carriage={item.carriage}"
    if item.carriage != "any":
        return f"no bag with capacity and carriage={item.carriage}"
    return "no bag with remaining capacity; higher-value items took the space"


def candidate_moves(
    assignment: dict[str, str | None], items: list[Item]
) -> Iterator[tuple[str, str, str | None]]:
    """Single-item relocations then pairwise swaps, in a fixed order for determinism."""
    movable = [i for i in items if not i.pinned and i.carriage != "prohibited"]
    for item in movable:
        for bag_id in item.feasible_bags:
            if assignment[item.id] != bag_id:
                yield ("move", item.id, bag_id)
    for idx, first in enumerate(movable):
        for second in movable[idx + 1 :]:
            a, b = assignment[first.id], assignment[second.id]
            if a == b:
                continue
            if (b is None or b in first.feasible_bags) and (
                a is None or a in second.feasible_bags
            ):
                yield ("swap", first.id, second.id)


def fits(
    assignment: dict[str, str | None],
    items: dict[str, Item],
    bags: list[Bag],
    capacity: dict[str, float],
) -> bool:
    loads = bag_loads(assignment, items, bags)
    return all(loads[bag.id] <= capacity[bag.id] + EPS for bag in bags)


def local_search(
    assignment: dict[str, str | None],
    items: list[Item],
    bags: list[Bag],
    capacity: dict[str, float],
    mode: str,
) -> tuple[dict[str, str | None], int]:
    """First-improvement hill climb over moves and swaps, capped so it always terminates.

    Every accepted step strictly improves the lexicographic objective (with a tolerance),
    so no state can repeat; the budget is a belt-and-braces bound for pathological inputs.
    """
    by_id = {item.id: item for item in items}
    current = dict(assignment)
    best = objective(current, by_id, bags, mode)
    evaluations = 0

    while evaluations < LOCAL_SEARCH_BUDGET:
        improved = False
        for move in candidate_moves(current, items):
            if evaluations >= LOCAL_SEARCH_BUDGET:
                break
            trial = dict(current)
            if move[0] == "move":
                trial[move[1]] = move[2]
            else:
                trial[move[1]], trial[move[2]] = current[move[2]], current[move[1]]
            if not fits(trial, by_id, bags, capacity):
                continue
            evaluations += 1
            value = objective(trial, by_id, bags, mode)
            if better(value, best):
                current, best = trial, value
                improved = True
                break
        if not improved:
            break
    return current, evaluations


# --------------------------------------------------------------------------------------
# Cubes
# --------------------------------------------------------------------------------------


def assign_cubes(bag: Bag, contents: list[Item]) -> tuple[list[dict[str, Any]], list[str]]:
    """Distribute one bag's items across its cubes, one category per cube.

    Rule, kept deliberately blunt because a packing cube plan nobody can follow at 6am is
    worse than none: group the bag's items by `category`; order the categories by total
    weight descending (ties by name); fill the bag's cubes in declaration order, one
    category each. Categories left over once the cubes run out, and everything in a bag
    with no cubes, land in `loose_items`. An item that already names a cube belonging to
    this bag keeps that cube, overriding the category rule.
    """
    cube_ids = [str(c["id"]) for c in bag.cubes]
    if not cube_ids:
        return [], [item.id for item in sorted(contents, key=lambda i: i.id)]

    placement: dict[str, list[str]] = {cube_id: [] for cube_id in cube_ids}
    loose: list[str] = []

    preset = [i for i in contents if i.preset_cube in placement]
    for item in sorted(preset, key=lambda i: i.id):
        placement[str(item.preset_cube)].append(item.id)

    remaining = [i for i in contents if i.preset_cube not in placement]
    by_category: dict[str, list[Item]] = {}
    for item in remaining:
        by_category.setdefault(item.category, []).append(item)
    ordered = sorted(
        by_category.items(), key=lambda kv: (-sum(i.kg for i in kv[1]), kv[0])
    )

    for index, (_category, members) in enumerate(ordered):
        member_ids = sorted(i.id for i in members)
        if index < len(cube_ids):
            placement[cube_ids[index]].extend(member_ids)
        else:
            loose.extend(member_ids)

    cubes = [
        {"id": cube_id, "items": sorted(placement[cube_id])}
        for cube_id in cube_ids
        if placement[cube_id]
    ]
    return cubes, sorted(loose)


# --------------------------------------------------------------------------------------
# Plan assembly
# --------------------------------------------------------------------------------------


def status_for(headroom: float | None) -> str:
    if headroom is None:
        return "ok"
    if headroom < 0:
        return "over"
    if headroom <= TIGHT_BAND_KG:
        return "tight"
    return "ok"


def overflow_ranking(
    assignment: dict[str, str | None], items: list[Item]
) -> list[dict[str, Any]]:
    """Rank carried items by cost per kilogram saved, cheapest to drop first.

    Cost is the item's `value`, or its tier proxy when no value is recorded. An item that
    can be re-bought at the destination costs only that re-buy price to leave behind, which
    is what usually moves bulky cheap things to the top of the list.
    """
    rows: list[dict[str, Any]] = []
    for item in items:
        bag_id = assignment.get(item.id)
        if bag_id is None or item.kg <= 0:
            continue
        cost = item.value if item.value is not None else TIER_WEIGHT.get(item.tier, 100.0)
        if item.replaceable:
            cost = item.replace_cost if item.replace_cost is not None else 0.0
        rows.append(
            {
                "item": item.id,
                "name": item.name,
                "bag": bag_id,
                "kg_saved": rounded(item.kg),
                "cost": rounded(float(cost), 2),
                "cost_per_kg": rounded(float(cost) / item.kg, 2),
                "replaceable": item.replaceable,
                "replace_cost": item.replace_cost,
                "pinned": item.pinned,
                "tier": item.tier,
            }
        )
    # Cheapest per kilogram first; heavier items break ties, because one heavy drop beats
    # three light ones for the same cost and is far easier to actually carry out.
    rows.sort(key=lambda r: (r["cost_per_kg"], -r["kg_saved"], r["item"]))
    for position, row in enumerate(rows, start=1):
        row["rank"] = position
    return rows


def build_plan(
    workspace: Path,
    args: argparse.Namespace,
) -> tuple[dict[str, Any], list[str]]:
    itinerary = load_yaml(workspace / "itinerary.yaml")  # loaded for validation of presence
    allowances = load_yaml(workspace / "allowances.yaml")
    bags_doc = load_yaml(workspace / "bags.yaml")
    inventory = load_yaml(workspace / "inventory.yaml")
    del itinerary  # the solver needs only the binding limits, but a workspace without an
    # itinerary is not a trip and the allowances cannot be trusted.

    binding = allowances.get("binding")
    if not isinstance(binding, dict):
        raise SolverError(
            "allowances.yaml has no `binding` block. Run /travel-packing:policies first — "
            "the solver will not guess a limit."
        )

    errors: list[str] = []
    warnings: list[str] = []

    bags = build_bags(bags_doc, binding, errors, warnings)
    if not bags:
        raise SolverError("bags.yaml lists no bags")
    items = build_items(inventory, bags)
    by_id = {item.id: item for item in items}

    # Effective capacity per bag. A bag that pinned items already overfill keeps that
    # load as its floor, so the current state stays feasible and the search cannot
    # "improve" things by evicting a pin.
    pinned_load: dict[str, float] = {bag.id: 0.0 for bag in bags}
    for item in items:
        if item.pinned and item.preset_bag in pinned_load:
            pinned_load[item.preset_bag] += item.kg
    capacity = {bag.id: max(bag.usable_kg, pinned_load[bag.id]) for bag in bags}

    assignment, reasons = seed_allocation(items, bags, capacity, args.objective, errors)
    assignment, evaluations = local_search(assignment, items, bags, capacity, args.objective)

    loads = bag_loads(assignment, by_id, bags)
    plan_bags: list[dict[str, Any]] = []
    for bag in bags:
        contents = sorted(
            (by_id[i] for i, b in assignment.items() if b == bag.id), key=lambda i: i.id
        )
        cubes, loose = assign_cubes(bag, contents)
        contents_kg = loads[bag.id]
        gross = contents_kg + bag.tare_kg + bag.cube_tare_kg
        headroom = None if bag.allowance_kg is None else bag.allowance_kg - gross
        entry: dict[str, Any] = {
            "id": bag.id,
            "label": bag.label,
            "type": bag.type,
            "allowance_kg": None if bag.allowance_kg is None else rounded(bag.allowance_kg),
            "tare_kg": rounded(bag.tare_kg),
            "contents_kg": rounded(contents_kg),
            "cube_tare_kg": rounded(bag.cube_tare_kg),
            "projected_gross_kg": rounded(gross),
            "headroom_kg": None if headroom is None else rounded(headroom),
            "status": status_for(headroom),
        }
        if cubes:
            entry["cubes"] = cubes
        if loose:
            entry["loose_items"] = loose
        plan_bags.append(entry)

    unassigned = [
        {
            "item": item.id,
            "name": item.name,
            "reason": reasons.get(item.id) or unassigned_reason(item),
        }
        for item in items
        if assignment.get(item.id) is None
    ]

    # Warnings the rendered documents must carry forward.
    for entry in allowances.get("segments") or []:
        if not isinstance(entry, dict):
            continue
        source = entry.get("source") or {}
        confidence = source.get("confidence") if isinstance(source, dict) else None
        if confidence in ("inferred", "assumed"):
            warnings.append(
                f"Allowance for {entry.get('segment_id')} is confidence={confidence}; "
                "plan is provisional."
            )
    for entry in plan_bags:
        if entry["status"] == "over":
            warnings.append(
                f"{entry['id']} is {abs(entry['headroom_kg'])} kg over its allowance."
            )
        elif entry["status"] == "tight":
            warnings.append(
                f"{entry['id']} has only {entry['headroom_kg']} kg of headroom; "
                f"anything inside {TIGHT_BAND_KG} kg is treated as tight, not ok."
            )
    if unassigned:
        warnings.append(
            f"{len(unassigned)} item(s) did not fit and are listed under `unassigned`."
        )

    # Compare against the most recent weighing, if there is one: a large gap between the
    # itemised total and what the scale said means the inventory is incomplete.
    # An `empty` reading is the bag's tare, not a gross weight, so comparing it against the
    # itemised contents is meaningless — it always reports the whole load as "unaccounted".
    # Rank the remaining phases so a later stage of the trip wins over an earlier one, and
    # break ties on date.
    phase_rank = {"outbound": 1, "current": 2, "final": 3}
    latest: dict[str, dict[str, Any]] = {}
    for weighing in bags_doc.get("weighings") or []:
        if not isinstance(weighing, dict) or not weighing.get("bag"):
            continue
        rank = phase_rank.get(str(weighing.get("phase")))
        if rank is None:  # `empty`, or an unrecognised phase
            continue
        bag_id = str(weighing["bag"])
        current = latest.get(bag_id)
        key = (rank, str(weighing.get("date") or ""))
        if current is None or key >= current["_key"]:
            latest[bag_id] = {**weighing, "_key": key}
    for entry in plan_bags:
        weighing = latest.get(entry["id"])
        if not weighing or weighing.get("gross_kg") is None:
            continue
        entry["last_weighing_kg"] = rounded(float(weighing["gross_kg"]))
        gap = float(weighing["gross_kg"]) - entry["projected_gross_kg"]
        if abs(gap) >= 0.5:
            warnings.append(
                f"Unaccounted mass on {entry['id']}: {rounded(gap)} kg between itemised "
                f"total and last weighing ({weighing.get('phase')}). Run scripts/reconcile.py."
            )

    plan: dict[str, Any] = {
        "generated_on": args.now or dt.datetime.now().astimezone().isoformat(timespec="seconds"),
        "solver": f"pack_solver.py {SOLVER_VERSION}",
        "objective": args.objective,
        "binding_limits": {},
        "bags": plan_bags,
    }
    for bag_type in ("checked", "cabin", "personal"):
        block = binding.get(BINDING_KEY[bag_type])
        if isinstance(block, dict):
            plan["binding_limits"][bag_type] = {
                "pieces": block.get("included_pieces", block.get("pieces")),
                "max_weight_kg": block.get("max_weight_kg"),
            }
    if unassigned:
        plan["unassigned"] = unassigned
    if args.overflow:
        plan["overflow_ranking"] = overflow_ranking(assignment, items)
    if warnings:
        plan["warnings"] = warnings
    if errors:
        plan["errors"] = errors

    # Search statistics stay out of the plan file: they are not part of the contract in
    # docs/data-model.md and would churn the diff.
    del evaluations
    return plan, errors


def render_text(plan: dict[str, Any]) -> str:
    lines: list[str] = []
    lines.append(f"Objective: {plan['objective']}   Solver: {plan['solver']}")
    lines.append("")
    lines.append(
        f"{'BAG':<8} {'TYPE':<9} {'ALLOW':>7} {'TARE':>6} {'CONTENTS':>9} "
        f"{'GROSS':>7} {'HEADROOM':>9} STATUS"
    )
    lines.append("-" * 72)
    for bag in plan["bags"]:
        allowance = "-" if bag["allowance_kg"] is None else f"{bag['allowance_kg']:.2f}"
        headroom = "-" if bag["headroom_kg"] is None else f"{bag['headroom_kg']:.2f}"
        lines.append(
            f"{bag['id']:<8} {bag['type']:<9} {allowance:>7} {bag['tare_kg']:>6.2f} "
            f"{bag['contents_kg']:>9.2f} {bag['projected_gross_kg']:>7.2f} "
            f"{headroom:>9} {bag['status']}"
        )
        for cube in bag.get("cubes", []):
            lines.append(f"    cube {cube['id']}: {', '.join(cube['items'])}")
        if bag.get("loose_items"):
            lines.append(f"    loose: {', '.join(bag['loose_items'])}")
    lines.append("")
    if plan.get("unassigned"):
        lines.append("UNASSIGNED")
        lines.append("-" * 72)
        for entry in plan["unassigned"]:
            lines.append(f"{entry['item']:<8} {entry['name']:<32} {entry['reason']}")
        lines.append("")
    if plan.get("overflow_ranking"):
        lines.append("OVERFLOW RANKING (drop from the top: cheapest per kg saved)")
        lines.append("-" * 72)
        lines.append(
            f"{'RANK':>4} {'ITEM':<8} {'NAME':<26} {'KG':>6} {'COST':>8} {'COST/KG':>9} REPL"
        )
        for row in plan["overflow_ranking"]:
            lines.append(
                f"{row['rank']:>4} {row['item']:<8} {row['name'][:26]:<26} "
                f"{row['kg_saved']:>6.2f} {row['cost']:>8.2f} {row['cost_per_kg']:>9.2f} "
                f"{'yes' if row['replaceable'] else 'no'}"
            )
        lines.append("")
    for label in ("errors", "warnings"):
        if plan.get(label):
            lines.append(label.upper())
            lines.append("-" * 72)
            for line in plan[label]:
                lines.append(f"- {line}")
            lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Allocate inventory items to bags and write plan.yaml."
    )
    parser.add_argument(
        "workspace", nargs="?", default=".", help="trip workspace directory (default: .)"
    )
    parser.add_argument(
        "--objective",
        choices=["max-min-headroom", "consolidate"],
        default="max-min-headroom",
        help="max-min-headroom (default) spreads load; consolidate uses as few bags as possible",
    )
    parser.add_argument(
        "--overflow",
        action="store_true",
        help="include a ranked leave-behind list under overflow_ranking",
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="print the plan instead of writing plan.yaml"
    )
    parser.add_argument(
        "--json", action="store_true", dest="as_json", help="print the plan as JSON"
    )
    parser.add_argument(
        "--now",
        default=None,
        help="override generated_on with a fixed ISO timestamp (reproducible output)",
    )
    args = parser.parse_args()

    workspace = Path(args.workspace).resolve()
    if not workspace.is_dir():
        print(f"error: {workspace} is not a directory", file=sys.stderr)
        return 1

    try:
        plan, errors = build_plan(workspace, args)
    except SolverError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    if not args.dry_run:
        # The only file this script ever writes, and only inside the workspace given.
        with (workspace / "plan.yaml").open("w", encoding="utf-8") as handle:
            yaml.safe_dump(plan, handle, sort_keys=False, allow_unicode=True, default_flow_style=False)

    if args.as_json:
        print(json.dumps(plan, indent=2))
    elif args.dry_run:
        print(yaml.safe_dump(plan, sort_keys=False, allow_unicode=True, default_flow_style=False), end="")
    else:
        print(render_text(plan))
        print(f"Wrote {workspace / 'plan.yaml'}")

    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
