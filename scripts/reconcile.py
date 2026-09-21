#!/usr/bin/env python3
"""Reconcile scale readings against the itemised inventory, bag by bag.

The normal state of a real trip is a bag that has been weighed but only half itemised.
This script quantifies that gap: what the scale says, what the inventory accounts for, and
how much mass is unexplained. It never edits anything — it prints what it found and, where
the evidence points at a miscalibrated scale rather than missing items, the `bias_kg` value
to enter by hand in bags.yaml.

Run:
    python scripts/reconcile.py [WORKSPACE_DIR] [--phase empty|outbound|current|final] [--json]

Exit 0 whatever it finds; exit 1 only when a required file is missing or malformed,
2 if a dependency is missing.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from pathlib import Path
from typing import Any

try:
    import yaml
except ImportError:  # pragma: no cover - environment guard
    print("Missing dependencies. Install them with: uv pip install pyyaml jsonschema")
    sys.exit(2)

# Chronological order of the packing phases, used to pick "the most recent phase present".
PHASE_ORDER: list[str] = ["empty", "outbound", "current", "final"]

# A residual smaller than either of these is inside the noise of a hook scale plus the
# rounding on item weights, so it is not evidence of anything.
CONSISTENT_ABS_KG = 0.3
CONSISTENT_PCT = 3.0
PARTIAL_PCT = 15.0

# Weight sources that were never actually put on a scale.
SOFT_SOURCES = frozenset({"estimated", "vendor"})
SOFT_DOMINANT_FRACTION = 0.5

# Thresholds for calling a uniform residual a scale bias rather than missing items.
BIAS_MIN_ABS_KG = 0.1
BIAS_MAX_SPREAD_KG = 0.3


class ReconcileError(Exception):
    """A missing or malformed input file — the only condition that exits non-zero."""


def stringify_dates(node: Any) -> Any:
    if isinstance(node, dict):
        return {k: stringify_dates(v) for k, v in node.items()}
    if isinstance(node, list):
        return [stringify_dates(v) for v in node]
    if isinstance(node, (dt.datetime, dt.date)):
        return node.isoformat()
    return node


def load_yaml(path: Path, required: bool = True) -> dict[str, Any] | None:
    if not path.exists():
        if required:
            raise ReconcileError(f"{path.name} is missing from the workspace")
        return None
    try:
        with path.open("r", encoding="utf-8") as handle:
            data = yaml.safe_load(handle)
    except yaml.YAMLError as exc:
        raise ReconcileError(f"{path.name} is not valid YAML: {exc}") from exc
    if not isinstance(data, dict):
        raise ReconcileError(f"{path.name} must contain a mapping at the top level")
    return stringify_dates(data)


def rounded(value: float, places: int = 3) -> float:
    return round(value + 0.0, places)


def item_kg(item: dict[str, Any]) -> float:
    return float(item.get("weight_g") or 0.0) * int(item.get("qty") or 1) / 1000.0


def assignments_from(plan: dict[str, Any] | None, inventory: dict[str, Any]) -> dict[str, str]:
    """Where each item currently lives.

    plan.yaml wins when it exists: it is the solver's output and is regenerated, whereas
    inventory.assigned_bag may still hold a stale hand-entered value.
    """
    if plan:
        mapping: dict[str, str] = {}
        for bag in plan.get("bags") or []:
            if not isinstance(bag, dict) or not bag.get("id"):
                continue
            for cube in bag.get("cubes") or []:
                for item_id in cube.get("items") or []:
                    mapping[str(item_id)] = str(bag["id"])
            for item_id in bag.get("loose_items") or []:
                mapping[str(item_id)] = str(bag["id"])
        if mapping:
            return mapping
    return {
        str(item["id"]): str(item["assigned_bag"])
        for item in inventory.get("items") or []
        if isinstance(item, dict) and item.get("id") and item.get("assigned_bag")
    }


def choose_phase(weighings: list[dict[str, Any]], requested: str | None) -> str | None:
    present = {str(w.get("phase")) for w in weighings if w.get("phase")}
    if requested:
        return requested
    for phase in reversed(PHASE_ORDER):
        if phase in present:
            return phase
    return None


def classify(unaccounted: float, net_kg: float) -> str:
    pct = abs(unaccounted) / net_kg * 100.0 if net_kg > 0 else 0.0
    if abs(unaccounted) < CONSISTENT_ABS_KG or pct < CONSISTENT_PCT:
        return "consistent"
    if pct <= PARTIAL_PCT:
        return "partial inventory"
    return "inventory incomplete"


def reconcile(
    bags_doc: dict[str, Any],
    inventory: dict[str, Any],
    plan: dict[str, Any] | None,
    requested_phase: str | None,
) -> dict[str, Any]:
    bags = [b for b in (bags_doc.get("bags") or []) if isinstance(b, dict) and b.get("id")]
    weighings = [
        w for w in (bags_doc.get("weighings") or []) if isinstance(w, dict) and w.get("bag")
    ]
    scales = {
        str(s["id"]): s
        for s in (bags_doc.get("scales") or [])
        if isinstance(s, dict) and s.get("id")
    }
    items = {
        str(i["id"]): i
        for i in (inventory.get("items") or [])
        if isinstance(i, dict) and i.get("id")
    }
    assigned = assignments_from(plan, inventory)

    phase = choose_phase(weighings, requested_phase)
    notes: list[str] = []
    rows: list[dict[str, Any]] = []

    if phase is None:
        notes.append("No weighings recorded; nothing to reconcile.")
        return {"phase": None, "bags": [], "notes": notes, "suggested_bias_kg": None}

    # Later entries win: weighings are appended, so the last one for a bag at a phase is
    # the current reading for that phase.
    reading: dict[str, dict[str, Any]] = {}
    for weighing in weighings:
        if str(weighing.get("phase")) == phase:
            reading[str(weighing["bag"])] = weighing

    for bag in sorted(bags, key=lambda b: str(b["id"])):
        bag_id = str(bag["id"])
        weighing = reading.get(bag_id)
        if weighing is None:
            continue
        gross = float(weighing.get("gross_kg") or 0.0)
        scale_id = weighing.get("scale")
        bias = 0.0
        if scale_id and scale_id in scales and scales[scale_id].get("bias_kg") is not None:
            bias = float(scales[scale_id]["bias_kg"])
            if bias:
                notes.append(
                    f"{bag_id}: applied bias_kg {bias:+.3f} from scale '{scale_id}' to the "
                    f"raw reading {gross:.3f}."
                )
        gross += bias

        tare = float(bag.get("tare_kg") or 0.0)
        if bag.get("tare_kg") is None:
            notes.append(
                f"{bag_id}: no tare_kg recorded, so the whole empty weight of the bag shows "
                "up as unaccounted mass. Weigh it empty first."
            )
        cube_tare = sum(
            float(c.get("tare_kg") or 0.0)
            for c in (bag.get("cubes") or [])
            if isinstance(c, dict)
        )

        contents = [items[i] for i, b in sorted(assigned.items()) if b == bag_id and i in items]
        itemised = sum(item_kg(item) for item in contents)
        soft_kg = sum(
            item_kg(item)
            for item in contents
            if str(item.get("weight_source")) in SOFT_SOURCES
        )

        net = gross - tare - cube_tare
        unaccounted = net - itemised
        pct = (unaccounted / net * 100.0) if net > 0 else 0.0
        verdict = classify(unaccounted, net)

        soft_fraction = soft_kg / itemised if itemised > 0 else 0.0
        if verdict != "consistent" and soft_fraction > SOFT_DOMINANT_FRACTION:
            notes.append(
                f"{bag_id}: {soft_fraction * 100:.0f}% of the itemised weight comes from "
                "estimated or vendor figures, and the residual is large. The fix is to put "
                "the items on a scale, not to refine the estimates."
            )

        rows.append(
            {
                "bag": bag_id,
                "label": bag.get("label"),
                "phase": phase,
                "gross_kg": rounded(gross),
                "tare_kg": rounded(tare),
                "cube_tare_kg": rounded(cube_tare),
                "itemised_kg": rounded(itemised),
                "net_contents_kg": rounded(net),
                "unaccounted_kg": rounded(unaccounted),
                "unaccounted_pct": rounded(pct, 1),
                "items_counted": len(contents),
                "soft_weight_fraction": rounded(soft_fraction, 3),
                "classification": verdict,
            }
        )

    # A miscalibrated scale offsets every bag by the same amount in the same direction.
    # Missing items do not: they pile up in whichever bag was itemised least. So only
    # suggest a bias when the residuals agree in sign and magnitude across every bag.
    suggested: float | None = None
    residuals = [row["unaccounted_kg"] for row in rows]
    if len(residuals) >= 2:
        same_sign = all(r > 0 for r in residuals) or all(r < 0 for r in residuals)
        magnitudes = [abs(r) for r in residuals]
        if (
            same_sign
            and min(magnitudes) >= BIAS_MIN_ABS_KG
            and (max(magnitudes) - min(magnitudes)) <= BIAS_MAX_SPREAD_KG
        ):
            mean_residual = sum(residuals) / len(residuals)
            # bias_kg is added to raw readings, so it cancels the residual: a scale reading
            # 0.4 kg high on every bag needs bias_kg = -0.4.
            suggested = rounded(-mean_residual, 2)
            notes.append(
                f"Every bag shows a residual of the same sign within "
                f"{BIAS_MAX_SPREAD_KG} kg of the others. That is the signature of a "
                f"miscalibrated scale, not missing items. Suggested bias_kg {suggested:+.2f} "
                "— set it by hand in bags.yaml under scales; this script never writes it."
            )

    return {
        "phase": phase,
        "bags": rows,
        "notes": notes,
        "suggested_bias_kg": suggested,
    }


def render_text(workspace: Path, result: dict[str, Any]) -> str:
    lines: list[str] = []
    lines.append(f"Workspace: {workspace}")
    lines.append(f"Phase: {result['phase'] or '(none)'}")
    lines.append("")
    if result["bags"]:
        lines.append(
            f"{'BAG':<8} {'GROSS':>7} {'TARE':>6} {'CUBES':>6} {'ITEMISED':>9} "
            f"{'NET':>7} {'UNACCT':>8} {'PCT':>7}  CLASSIFICATION"
        )
        lines.append("-" * 78)
        for row in result["bags"]:
            lines.append(
                f"{row['bag']:<8} {row['gross_kg']:>7.2f} {row['tare_kg']:>6.2f} "
                f"{row['cube_tare_kg']:>6.2f} {row['itemised_kg']:>9.2f} "
                f"{row['net_contents_kg']:>7.2f} {row['unaccounted_kg']:>8.2f} "
                f"{row['unaccounted_pct']:>6.1f}%  {row['classification']}"
            )
        lines.append("")
    else:
        lines.append("No bag has a weighing at this phase.")
        lines.append("")
    if result["notes"]:
        lines.append("NOTES")
        lines.append("-" * 78)
        for note in result["notes"]:
            lines.append(f"- {note}")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Reconcile scale readings against the itemised inventory."
    )
    parser.add_argument(
        "workspace", nargs="?", default=".", help="trip workspace directory (default: .)"
    )
    parser.add_argument(
        "--phase",
        choices=PHASE_ORDER,
        default=None,
        help="which weighing phase to reconcile (default: the most recent phase present)",
    )
    parser.add_argument(
        "--json", action="store_true", dest="as_json", help="emit a machine-readable report"
    )
    args = parser.parse_args()

    workspace = Path(args.workspace).resolve()
    if not workspace.is_dir():
        print(f"error: {workspace} is not a directory", file=sys.stderr)
        return 1

    try:
        bags_doc = load_yaml(workspace / "bags.yaml")
        inventory = load_yaml(workspace / "inventory.yaml")
        plan = load_yaml(workspace / "plan.yaml", required=False)
    except ReconcileError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    assert bags_doc is not None and inventory is not None
    result = reconcile(bags_doc, inventory, plan, args.phase)
    result["workspace"] = str(workspace)

    if args.as_json:
        print(json.dumps(result, indent=2))
    else:
        print(render_text(workspace, result), end="")
    return 0


if __name__ == "__main__":
    sys.exit(main())
