#!/usr/bin/env python3
"""Validate a trip workspace against the JSON Schemas in schema/ and cross-check references.

Schema validation alone catches typos inside one file. Most real breakage in a trip
workspace is between files: an item assigned to a bag that was renamed, an allowance for
a segment that was cancelled. Those checks live here, each with a stable `code` so the
plugin's agents can react to a specific failure rather than parsing prose.

Run:
    python scripts/validate.py [WORKSPACE_DIR] [--json]

WORKSPACE_DIR defaults to the current directory. Exit 0 when there are no errors
(warnings alone still exit 0), 1 when there are errors, 2 when a dependency is missing.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from pathlib import Path
from typing import Any, Iterable

try:
    import yaml
    from jsonschema import Draft202012Validator
except ImportError:  # pragma: no cover - environment guard
    print("Missing dependencies. Install them with: uv pip install pyyaml jsonschema")
    sys.exit(2)

# schema/ sits next to scripts/ in the plugin, not in the workspace being validated.
SCHEMA_DIR = Path(__file__).resolve().parent.parent / "schema"

# (filename, schema name, required?) — plan.yaml is generated, so its absence is normal.
FILES: list[tuple[str, str, bool]] = [
    ("itinerary.yaml", "itinerary", True),
    ("allowances.yaml", "allowances", False),
    ("bags.yaml", "bags", False),
    ("inventory.yaml", "inventory", False),
    ("plan.yaml", "plan", False),
]


class Report:
    """Collects findings. `code` is the stable identifier; `message` is for humans."""

    def __init__(self) -> None:
        self.errors: list[dict[str, Any]] = []
        self.warnings: list[dict[str, Any]] = []

    def error(self, code: str, file: str, message: str, path: str = "") -> None:
        self.errors.append(
            {"code": code, "file": file, "path": path, "message": message}
        )

    def warn(self, code: str, file: str, message: str, path: str = "") -> None:
        self.warnings.append(
            {"code": code, "file": file, "path": path, "message": message}
        )


def stringify_dates(node: Any) -> Any:
    """PyYAML turns `2026-08-27` into a datetime.date, which no JSON Schema can type.

    Convert dates and datetimes back to ISO strings before validation so the schemas can
    keep using `"type": "string", "format": "date"`.
    """
    if isinstance(node, dict):
        return {k: stringify_dates(v) for k, v in node.items()}
    if isinstance(node, list):
        return [stringify_dates(v) for v in node]
    if isinstance(node, (dt.datetime, dt.date)):
        return node.isoformat()
    return node


def load_yaml(path: Path, report: Report) -> dict[str, Any] | None:
    try:
        with path.open("r", encoding="utf-8") as handle:
            data = yaml.safe_load(handle)
    except yaml.YAMLError as exc:
        report.error("YAML_PARSE", path.name, f"could not parse YAML: {exc}")
        return None
    except OSError as exc:
        report.error("IO", path.name, f"could not read file: {exc}")
        return None
    if data is None:
        report.error("YAML_PARSE", path.name, "file is empty")
        return None
    if not isinstance(data, dict):
        report.error("YAML_PARSE", path.name, "top level must be a mapping")
        return None
    return stringify_dates(data)


def load_schema(name: str) -> dict[str, Any]:
    with (SCHEMA_DIR / f"{name}.schema.json").open("r", encoding="utf-8") as handle:
        return json.load(handle)


def json_pointer(parts: Iterable[Any]) -> str:
    return "/" + "/".join(str(p) for p in parts) if parts else "(root)"


def validate_schema(name: str, filename: str, data: dict[str, Any], report: Report) -> None:
    validator = Draft202012Validator(load_schema(name))
    for err in sorted(validator.iter_errors(data), key=lambda e: list(e.absolute_path)):
        report.error("SCHEMA", filename, err.message, json_pointer(err.absolute_path))


def as_list(container: Any, key: str) -> list[dict[str, Any]]:
    """Defensive accessor — schema errors are reported separately, so never raise here."""
    if not isinstance(container, dict):
        return []
    value = container.get(key)
    if not isinstance(value, list):
        return []
    return [entry for entry in value if isinstance(entry, dict)]


def cross_checks(
    itinerary: dict[str, Any] | None,
    allowances: dict[str, Any] | None,
    bags: dict[str, Any] | None,
    inventory: dict[str, Any] | None,
    report: Report,
) -> None:
    segment_ids = {s.get("id") for s in as_list(itinerary, "segments") if s.get("id")}
    bag_ids = {b.get("id") for b in as_list(bags, "bags") if b.get("id")}
    cubes_by_bag = {
        b.get("id"): {c.get("id") for c in as_list(b, "cubes") if c.get("id")}
        for b in as_list(bags, "bags")
        if b.get("id")
    }

    # REF_SEGMENT — allowances must point at real segments, and every segment should
    # have an allowance. The second direction is a warning: research is often partial
    # while a trip is still being built up.
    if allowances is not None:
        covered: set[str] = set()
        for idx, entry in enumerate(as_list(allowances, "segments")):
            sid = entry.get("segment_id")
            if sid is None:
                continue
            covered.add(sid)
            if itinerary is not None and sid not in segment_ids:
                report.error(
                    "REF_SEGMENT",
                    "allowances.yaml",
                    f"segment_id {sid!r} does not exist in itinerary.yaml",
                    f"/segments/{idx}/segment_id",
                )
        for sid in sorted(segment_ids - covered, key=str):
            report.warn(
                "REF_SEGMENT",
                "allowances.yaml",
                f"itinerary segment {sid!r} has no allowance entry",
            )

        binding = allowances.get("binding")
        if isinstance(binding, dict):
            for slot in ("checked", "cabin", "personal_item"):
                block = binding.get(slot)
                if not isinstance(block, dict):
                    continue
                limited_by = block.get("limited_by")
                if limited_by and itinerary is not None and limited_by not in segment_ids:
                    report.error(
                        "REF_SEGMENT",
                        "allowances.yaml",
                        f"binding.{slot}.limited_by {limited_by!r} is not an itinerary segment",
                        f"/binding/{slot}/limited_by",
                    )

    # REF_TICKET — a ticket listing a segment that was deleted silently changes which
    # carrier's allowance governs the journey, so this is an error.
    for idx, ticket in enumerate(as_list(itinerary, "tickets")):
        for pos, sid in enumerate(ticket.get("segments") or []):
            if sid not in segment_ids:
                report.error(
                    "REF_TICKET",
                    "itinerary.yaml",
                    f"ticket {ticket.get('id')!r} references unknown segment {sid!r}",
                    f"/tickets/{idx}/segments/{pos}",
                )

    # REF_BAG / REF_CUBE / CARRIAGE_REASON — inventory integrity.
    if inventory is not None:
        for idx, item in enumerate(as_list(inventory, "items")):
            iid = item.get("id")
            assigned = item.get("assigned_bag")
            if assigned and bags is not None and assigned not in bag_ids:
                report.error(
                    "REF_BAG",
                    "inventory.yaml",
                    f"item {iid!r} is assigned to unknown bag {assigned!r}",
                    f"/items/{idx}/assigned_bag",
                )
            cube = item.get("cube")
            if cube and bags is not None:
                if assigned not in cubes_by_bag:
                    report.error(
                        "REF_CUBE",
                        "inventory.yaml",
                        f"item {iid!r} names cube {cube!r} but is not assigned to a known bag",
                        f"/items/{idx}/cube",
                    )
                elif cube not in cubes_by_bag[assigned]:
                    report.error(
                        "REF_CUBE",
                        "inventory.yaml",
                        f"item {iid!r} names cube {cube!r}, which is not in bag {assigned!r}",
                        f"/items/{idx}/cube",
                    )
            carriage = item.get("carriage", "any")
            if carriage != "any" and not item.get("carriage_reason"):
                report.error(
                    "CARRIAGE_REASON",
                    "inventory.yaml",
                    f"item {iid!r} has carriage={carriage!r} but no carriage_reason; "
                    "the reason is what makes the restriction auditable at the gate",
                    f"/items/{idx}/carriage_reason",
                )

    # REF_BAG for weighings — a reading against a bag that no longer exists.
    if bags is not None:
        for idx, weighing in enumerate(as_list(bags, "weighings")):
            if weighing.get("bag") not in bag_ids:
                report.error(
                    "REF_BAG",
                    "bags.yaml",
                    f"weighing references unknown bag {weighing.get('bag')!r}",
                    f"/weighings/{idx}/bag",
                )
        scale_ids = {s.get("id") for s in as_list(bags, "scales") if s.get("id")}
        for idx, weighing in enumerate(as_list(bags, "weighings")):
            scale = weighing.get("scale")
            if scale and scale_ids and scale not in scale_ids:
                report.warn(
                    "REF_BAG",
                    "bags.yaml",
                    f"weighing names scale {scale!r}, which is not declared under scales",
                    f"/weighings/{idx}/scale",
                )

        # NO_TARE — without a tare the projected gross weight is guesswork.
        for bag in as_list(bags, "bags"):
            if bag.get("tare_kg") is None:
                report.warn(
                    "NO_TARE",
                    "bags.yaml",
                    f"bag {bag.get('id')!r} has no tare_kg; weigh it empty before trusting any total",
                )

    # UNVERIFIED_ALLOWANCE — anything not read off the carrier's own page makes the
    # whole plan provisional, so it has to surface on every run, not just the first.
    if allowances is not None:
        for entry in as_list(allowances, "segments"):
            source = entry.get("source")
            confidence = source.get("confidence") if isinstance(source, dict) else None
            if confidence in ("inferred", "assumed"):
                report.warn(
                    "UNVERIFIED_ALLOWANCE",
                    "allowances.yaml",
                    f"segment {entry.get('segment_id')!r} allowance is confidence="
                    f"{confidence}; plan is provisional until it is confirmed",
                )


def render_text(workspace: Path, checked: list[str], report: Report) -> str:
    lines: list[str] = []
    lines.append(f"Workspace: {workspace}")
    lines.append(f"Files checked: {', '.join(checked) if checked else '(none)'}")
    lines.append("")
    for label, findings in (("ERROR", report.errors), ("WARNING", report.warnings)):
        if not findings:
            continue
        lines.append(f"{label}S ({len(findings)})")
        lines.append("-" * 72)
        lines.append(f"{'CODE':<22} {'FILE':<17} MESSAGE")
        for finding in findings:
            location = finding["path"]
            message = finding["message"]
            if location and location != "(root)":
                message = f"{message} [at {location}]"
            lines.append(f"{finding['code']:<22} {finding['file']:<17} {message}")
        lines.append("")
    if not report.errors and not report.warnings:
        lines.append("No problems found.")
    else:
        lines.append(
            f"Result: {len(report.errors)} error(s), {len(report.warnings)} warning(s)."
        )
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Validate a trip workspace against the travel-packing schemas."
    )
    parser.add_argument(
        "workspace",
        nargs="?",
        default=".",
        help="trip workspace directory (default: current directory)",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        dest="as_json",
        help="emit a machine-readable report instead of text",
    )
    args = parser.parse_args()

    workspace = Path(args.workspace).resolve()
    report = Report()

    if not workspace.is_dir():
        payload = {
            "workspace": str(workspace),
            "ok": False,
            "files_checked": [],
            "errors": [
                {
                    "code": "IO",
                    "file": "",
                    "path": "",
                    "message": "workspace directory does not exist",
                }
            ],
            "warnings": [],
        }
        print(json.dumps(payload, indent=2) if args.as_json else payload["errors"][0]["message"])
        return 1

    loaded: dict[str, dict[str, Any] | None] = {}
    checked: list[str] = []
    for filename, schema_name, required in FILES:
        path = workspace / filename
        if not path.exists():
            loaded[schema_name] = None
            if required:
                report.error("MISSING_FILE", filename, "required file is missing")
            elif filename != "plan.yaml":
                # plan.yaml is generated; the others are hand-written inputs and their
                # absence just means this workspace is not finished yet.
                report.warn("MISSING_FILE", filename, "file not present; checks that need it were skipped")
            continue
        data = load_yaml(path, report)
        loaded[schema_name] = data
        checked.append(filename)
        if data is not None:
            validate_schema(schema_name, filename, data, report)

    cross_checks(
        loaded.get("itinerary"),
        loaded.get("allowances"),
        loaded.get("bags"),
        loaded.get("inventory"),
        report,
    )

    if args.as_json:
        print(
            json.dumps(
                {
                    "workspace": str(workspace),
                    "ok": not report.errors,
                    "files_checked": checked,
                    "errors": report.errors,
                    "warnings": report.warnings,
                },
                indent=2,
            )
        )
    else:
        print(render_text(workspace, checked, report))

    return 1 if report.errors else 0


if __name__ == "__main__":
    sys.exit(main())
