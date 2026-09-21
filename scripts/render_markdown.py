#!/usr/bin/env python3
"""Render the counter card and the packing list as Markdown, straight from the workspace YAML.

These are the same two documents `typst/counter-card.typ` and `typst/packing-list.typ`
produce, in a different medium: same content, same section order, same rules about what
must be visible. The reason for a second renderer is publication — a PDF is a blob on a
static site, and the immediate consumer here is an Astro wiki that wants readable pages.
Nothing is transcribed by hand; every figure comes out of the YAML.

Run:
    python scripts/render_markdown.py [WORKSPACE_DIR] --doc counter-card [--out FILE]
    python scripts/render_markdown.py [WORKSPACE_DIR] --doc packing-list [--out FILE]
    python scripts/render_markdown.py [WORKSPACE_DIR] --doc both --out-dir DIR

A single document goes to stdout unless `--out`/`--out-dir` is given; `--doc both`
defaults to `<workspace>/output/`.

OUTPUT CONTRACT
---------------
The output is CommonMark that also has to survive an MDX-adjacent pipeline, which is a
stricter target than plain Markdown:

- No raw HTML at all. Where the Typst templates use a line break inside a table cell,
  this renderer puts the same text inline after an em dash instead — `<br>` is permitted
  by the brief but was never needed, and a file with no HTML in it cannot be mangled by
  a sanitiser.
- `|` inside a table cell is escaped, so a carrier note containing a pipe cannot shear
  the table in half.
- `{` and `}` are escaped wherever they come out of the YAML, and any line that would
  still begin with one gets a backslash. MDX reads a leading brace as the start of a
  JavaScript expression and fails the whole page build over it.
- Deterministic: the same inputs plus `--now` give byte-identical output. Every list is
  emitted in file order, no dictionary is iterated without a fixed order, and the only
  clock reading in the file is the one `--now` replaces (matching `pack_solver.py`).

DEGRADATION
-----------
`allowances.yaml` is required for the counter card — a counter card without the
allowance is not a document, it is a decoration. `plan.yaml` is not: without it the card
still renders the allowances and says, in place of the bag table, that there is no plan.
The packing list is the other way round; it is a rendering of `plan.yaml` and cannot
stand in without one.

Exit 0 on success, 1 on missing or malformed input, 2 if a dependency is missing.
"""

from __future__ import annotations

import argparse
import datetime as dt
import sys
from pathlib import Path
from typing import Any, Sequence

try:
    import yaml
except ImportError:  # pragma: no cover - environment guard
    print("Missing dependencies. Install them with: uv pip install pyyaml jsonschema")
    sys.exit(2)

RENDERER_VERSION = "1.0.0"

DOC_TITLES: dict[str, str] = {
    "counter-card": "Check-in counter card",
    "packing-list": "Packing list",
}

DEFAULT_FILENAMES: dict[str, str] = {
    "counter-card": "counter-card.md",
    "packing-list": "packing-list.md",
}

# Same three markers the Typst templates use, so a traveller who has seen the PDF reads
# the web page without relearning anything.
CARRIAGE_MARKERS: dict[str, str] = {
    "cabin-only": "†",
    "checked-only": "‡",
    "prohibited": "✖",
}

CARRIAGE_LEGEND = (
    "† cabin-only — must travel in the cabin (lithium batteries, medication, documents). "
    "‡ checked-only — must not go through security (liquids over 100 ml, sharps, tools). "
    "✖ prohibited — cannot fly at all."
)

TIGHT_BAND_KG = 1.5


class RenderError(Exception):
    """A missing or malformed input file, or an impossible combination of options."""


# --------------------------------------------------------------------------------------
# Loading
# --------------------------------------------------------------------------------------


def stringify_dates(node: Any) -> Any:
    """PyYAML parses bare ISO dates into date objects; Markdown needs strings."""
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
            raise RenderError(f"{path.name} is missing from the workspace")
        return None
    try:
        with path.open("r", encoding="utf-8") as handle:
            data = yaml.safe_load(handle)
    except yaml.YAMLError as exc:
        raise RenderError(f"{path.name} is not valid YAML: {exc}") from exc
    if data is None:
        data = {}
    if not isinstance(data, dict):
        raise RenderError(f"{path.name} must contain a mapping at the top level")
    return stringify_dates(data)


def get(source: Any, key: str, default: Any = None) -> Any:
    """Null-safe read, mirroring `get` in typst/lib.typ.

    Returns `default` when the container is missing, is not a mapping, lacks the key, or
    holds an explicit null. `max_weight_kg: null` is a real and meaningful value in
    allowances.yaml, so the three cases have to collapse to the same answer.
    """
    if not isinstance(source, dict):
        return default
    value = source.get(key)
    return default if value is None else value


def as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


# --------------------------------------------------------------------------------------
# Markdown-safe text
# --------------------------------------------------------------------------------------

# `\` first or the escapes escape each other. `{` and `}` are here for MDX; `|` for
# tables; the rest are Markdown's own inline syntax leaking out of free-text YAML fields.
_ESCAPES: tuple[tuple[str, str], ...] = (
    ("\\", "\\\\"),
    ("`", "\\`"),
    ("|", "\\|"),
    ("{", "\\{"),
    ("}", "\\}"),
    ("<", "\\<"),
    (">", "\\>"),
    ("*", "\\*"),
    ("[", "\\["),
    ("]", "\\]"),
)


def esc(value: Any) -> str:
    """Escape a value for inline use anywhere, table cell included."""
    if value is None:
        return "—"
    text = str(value)
    for needle, replacement in _ESCAPES:
        text = text.replace(needle, replacement)
    # A cell cannot contain a newline, and a stray one would end the table row.
    return " ".join(text.split())


def esc_url(url: Any) -> str:
    """Escape a link destination. Parentheses and spaces are what break `[t](u)`."""
    text = str(url)
    return text.replace("\\", "%5C").replace(" ", "%20").replace("(", "%28").replace(")", "%29")


def link(url: Any, label: Any = None) -> str:
    if url is None:
        return "—"
    return f"[{esc(label if label is not None else url)}]({esc_url(url)})"


def guard_braces(text: str) -> str:
    """Backslash any line that still starts with a brace.

    Everything drawn from the YAML is escaped already, so this only ever fires on a line
    this file built itself — but MDX fails the entire page build on one leading `{`, and
    the failure surfaces as a broken site rather than as a broken document.
    """
    out: list[str] = []
    for line in text.split("\n"):
        stripped = line.lstrip()
        if stripped[:1] in ("{", "}"):
            indent = line[: len(line) - len(stripped)]
            out.append(f"{indent}\\{stripped}")
        else:
            out.append(line)
    return "\n".join(out)


# --------------------------------------------------------------------------------------
# Number and unit formatting — the same rules as typst/lib.typ
# --------------------------------------------------------------------------------------


def num(value: Any, digits: int = 1) -> str:
    """Fixed-decimal number. `None` is an em dash, never `0`.

    A missing weight and a zero weight mean very different things at a check-in desk, and
    the trailing zero is padded back because a column of `1.5` and `1.05` invites a
    misread.
    """
    if value is None:
        return "—"
    if isinstance(value, str):
        return esc(value)
    if isinstance(value, bool):
        return esc(str(value))
    try:
        number = float(value)
    except (TypeError, ValueError):
        return esc(value)
    if digits <= 0:
        return str(int(round(number)))
    return f"{number:.{digits}f}"


def kg(value: Any, digits: int = 1) -> str:
    if value is None:
        return "—"
    return f"{num(value, digits)} kg"


def kg_signed(value: Any, digits: int = 1) -> str:
    """Headroom, where the sign is the whole message."""
    if value is None:
        return "—"
    try:
        number = float(value)
    except (TypeError, ValueError):
        return esc(value)
    if number < 0:
        return f"**-{num(abs(number), digits)} kg**"
    return kg(number, digits)


def g_as_kg(weight_g: Any, qty: Any = 1) -> str:
    """Grams from inventory.yaml shown as kilograms. The one place the unit changes."""
    if weight_g is None:
        return "—"
    try:
        grams = float(weight_g) * float(qty or 1)
    except (TypeError, ValueError):
        return "—"
    return kg(grams / 1000.0, 2)


def dims(value: Any) -> str:
    if not isinstance(value, list) or not value:
        return "—"
    return " × ".join(str(v) for v in value) + " cm"


def money(amount: Any, currency: Any, digits: int = 0) -> str:
    """Never a bare number: two segments in one document can quote different currencies."""
    if amount is None:
        return "—"
    prefix = "" if currency is None else f"{esc(currency)} "
    return f"{prefix}{num(amount, digits)}"


def status_label(status: Any) -> str:
    """`ok` / `tight` / `over`. The word carries the meaning; no colour to lean on here."""
    value = "" if status is None else str(status).lower()
    if value == "ok":
        return "OK"
    if value == "tight":
        return "TIGHT"
    if value == "over":
        return "**OVER**"
    return "—"


TIGHT_BAND_KG = 1.5


def governing_figures(
    bag: dict[str, Any], measured_kg: float | None
) -> tuple[float | None, float | None, str | None]:
    """Return (governing gross, headroom, status) for a bag.

    `plan.yaml` reports a projection from the itemised inventory. Where a real scale
    reading exists and is heavier, that reading governs, because the difference is mass
    the inventory never captured and the airport scale still weighs. Headroom and status
    are recomputed against the heavier of the two rather than reprinted from the plan —
    the same rule the Typst templates apply, so the PDF and the Markdown page cannot
    disagree about whether a bag is over. Bands match scripts/pack_solver.py.
    """
    projected = get(bag, "projected_gross_kg")
    projected_f = None if projected is None else float(projected)
    if measured_kg is None:
        governing = projected_f
    elif projected_f is None or measured_kg > projected_f:
        governing = float(measured_kg)
    else:
        governing = projected_f

    allowance = get(bag, "allowance_kg")
    if allowance is None or governing is None:
        return governing, None, None

    headroom = float(allowance) - governing
    if headroom < 0:
        status = "over"
    elif headroom <= TIGHT_BAND_KG:
        status = "tight"
    else:
        status = "ok"
    return governing, headroom, status


def confidence_flag(confidence: Any) -> str:
    """`confirmed` is quiet; anything else is loud, in the table itself.

    An assumed allowance that reads like a confirmed one is worse than no allowance at
    all, so this string is placed next to every figure it qualifies rather than only in
    the provenance footer.
    """
    value = "unknown" if confidence is None else str(confidence).lower()
    if value == "confirmed":
        return "confirmed"
    if value == "inferred":
        return "**INFERRED**"
    if value == "assumed":
        return "**! ASSUMED**"
    return f"**! {esc(value.upper())}**"


def carriage_marker(carriage: Any) -> str:
    value = "any" if carriage is None else str(carriage).lower()
    return CARRIAGE_MARKERS.get(value, "")


# --------------------------------------------------------------------------------------
# Table building
# --------------------------------------------------------------------------------------

ALIGN_TOKENS: dict[str, str] = {"l": "---", "r": "---:", "c": ":---:"}


def md_table(headers: Sequence[str], aligns: str, rows: Sequence[Sequence[str]]) -> list[str]:
    """Build a GitHub-style table. Cells must already be escaped."""
    if len(aligns) != len(headers):
        raise RenderError("internal: table alignment string does not match the header count")
    lines = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join(ALIGN_TOKENS[a] for a in aligns) + " |",
    ]
    for row in rows:
        cells = [cell if cell != "" else " " for cell in row]
        lines.append("| " + " | ".join(cells) + " |")
    return lines


def blockquote(lines: Sequence[str]) -> list[str]:
    return [f"> {line}" if line else ">" for line in lines]


# --------------------------------------------------------------------------------------
# Workspace view
# --------------------------------------------------------------------------------------


class Workspace:
    """Everything the two documents read, loaded once and indexed.

    Which files are required depends on the document, so loading is per-document rather
    than eager: the counter card must not fail because a workspace has no inventory.
    """

    def __init__(self, root: Path) -> None:
        self.root = root
        self.itinerary: dict[str, Any] = {}
        self.allowances: dict[str, Any] = {}
        self.plan: dict[str, Any] | None = None
        self.bags: dict[str, Any] = {}
        self.inventory: dict[str, Any] = {}

    # -- loading ------------------------------------------------------------------

    def load(self, *, require: Sequence[str], optional: Sequence[str]) -> None:
        for name in require:
            setattr(self, name, load_yaml(self.root / f"{self._file(name)}", required=True))
        for name in optional:
            loaded = load_yaml(self.root / f"{self._file(name)}", required=False)
            if name == "plan":
                self.plan = loaded
            elif loaded is not None:
                setattr(self, name, loaded)

    @staticmethod
    def _file(name: str) -> str:
        return {
            "itinerary": "itinerary.yaml",
            "allowances": "allowances.yaml",
            "plan": "plan.yaml",
            "bags": "bags.yaml",
            "inventory": "inventory.yaml",
        }[name]

    # -- indexes ------------------------------------------------------------------

    @property
    def trip(self) -> dict[str, Any]:
        return get(self.itinerary, "trip", {})

    @property
    def itinerary_segments(self) -> list[dict[str, Any]]:
        return [s for s in as_list(get(self.itinerary, "segments", [])) if isinstance(s, dict)]

    @property
    def allowance_segments(self) -> list[dict[str, Any]]:
        return [s for s in as_list(get(self.allowances, "segments", [])) if isinstance(s, dict)]

    @property
    def plan_bags(self) -> list[dict[str, Any]]:
        return [b for b in as_list(get(self.plan, "bags", [])) if isinstance(b, dict)]

    @property
    def warnings(self) -> list[Any]:
        return as_list(get(self.plan, "warnings", []))

    @property
    def errors(self) -> list[Any]:
        return as_list(get(self.plan, "errors", []))

    def segment(self, segment_id: Any) -> dict[str, Any]:
        if segment_id is None:
            return {}
        for entry in self.itinerary_segments:
            if str(get(entry, "id", "")) == str(segment_id):
                return entry
        return {}

    def allowance(self, segment_id: Any) -> dict[str, Any]:
        if segment_id is None:
            return {}
        for entry in self.allowance_segments:
            if str(get(entry, "segment_id", "")) == str(segment_id):
                return entry
        return {}

    def bag_meta(self, bag_id: Any) -> dict[str, Any]:
        for entry in as_list(get(self.bags, "bags", [])):
            if isinstance(entry, dict) and str(get(entry, "id", "")) == str(bag_id):
                return entry
        return {}

    def cube_meta(self, bag_id: Any, cube_id: Any) -> dict[str, Any]:
        """Cube label and tare live in bags.yaml; the plan only records item ids."""
        for cube in as_list(get(self.bag_meta(bag_id), "cubes", [])):
            if isinstance(cube, dict) and str(get(cube, "id", "")) == str(cube_id):
                return cube
        return {}

    def last_weighing(self, bag_id: Any) -> tuple[float, str | None] | None:
        """The most recent scale reading for a bag, as (kilograms, phase).

        `plan.yaml` carries `last_weighing_kg` in the worked example but the solver does
        not write it, so the reading is taken from bags.yaml when the plan has none.
        Weighings are appended rather than overwritten, so the last entry for a bag is the
        current one — the same rule `pack_solver.py` uses when it looks for unaccounted
        mass. A `tare_kg` and an `empty` weighing are the same measurement, so `empty` is
        skipped: reporting it as "last measured" would put an empty bag's weight in a
        column the reader is comparing against a packed projection.
        """
        found: tuple[float, str | None] | None = None
        for entry in as_list(get(self.bags, "weighings", [])):
            if not isinstance(entry, dict) or str(get(entry, "bag", "")) != str(bag_id):
                continue
            phase = get(entry, "phase")
            gross = get(entry, "gross_kg")
            if gross is None or str(phase) == "empty":
                continue
            try:
                found = (float(gross), None if phase is None else str(phase))
            except (TypeError, ValueError):
                continue
        return found

    def measured_gross(self, bag: dict[str, Any]) -> tuple[float, str | None] | None:
        """The bag's last scale reading, from the plan if it carries one, else bags.yaml.

        The phase is only reported when it is known. `plan.yaml` in the worked example has
        a bare `last_weighing_kg` with no phase attached, so the phase is recovered from
        the bags.yaml entry with the same reading — and left off rather than guessed when
        the two do not line up.
        """
        recorded = get(bag, "last_weighing_kg")
        if recorded is None:
            return self.last_weighing(get(bag, "id"))
        try:
            value = float(recorded)
        except (TypeError, ValueError):
            return None
        from_bags = self.last_weighing(get(bag, "id"))
        if from_bags is not None and abs(from_bags[0] - value) < 1e-9:
            return (value, from_bags[1])
        return (value, None)

    def item(self, item_id: Any) -> dict[str, Any]:
        for entry in as_list(get(self.inventory, "items", [])):
            if isinstance(entry, dict) and str(get(entry, "id", "")) == str(item_id):
                return entry
        return {}

    # -- derived ------------------------------------------------------------------

    def binding_block(self, kind: str) -> dict[str, Any]:
        """Read a block out of `allowances.binding`.

        `personal` is spelled `personal_item` in docs/data-model.md and `personal` in the
        worked example and in counter-card.typ. Both are in the wild, so both are read;
        silently rendering an em dash because the key was the other spelling would look
        exactly like a workspace with no personal-item allowance.
        """
        binding = get(self.allowances, "binding", {})
        if kind == "personal":
            block = get(binding, "personal_item", None)
            if not isinstance(block, dict):
                block = get(binding, "personal", {})
            return block if isinstance(block, dict) else {}
        block = get(binding, kind, {})
        return block if isinstance(block, dict) else {}

    def segment_route(self, segment_id: Any) -> str:
        if segment_id is None:
            return "—"
        segment = self.segment(segment_id)
        if not segment:
            return esc(segment_id)
        return (
            f"{esc(segment_id)} · {esc(get(segment, 'from', '?'))}"
            f"→{esc(get(segment, 'to', '?'))}"
        )

    def segment_carrier(self, segment_id: Any) -> str:
        named = get(self.allowance(segment_id), "carrier_name")
        if named is not None:
            return esc(named)
        return esc(get(self.segment(segment_id), "marketing_carrier", ""))

    def segment_flight(self, segment_id: Any) -> str:
        return esc(get(self.segment(segment_id), "marketing_flight", ""))

    def segment_confidence(self, segment_id: Any) -> Any:
        return get(get(self.allowance(segment_id), "source", {}), "confidence")

    def unconfirmed_segments(self) -> list[dict[str, Any]]:
        """Every allowance whose research did not come back `confirmed`."""
        out: list[dict[str, Any]] = []
        for entry in self.allowance_segments:
            confidence = get(get(entry, "source", {}), "confidence", "assumed")
            if str(confidence).lower() != "confirmed":
                out.append(entry)
        return out

    def is_provisional(self) -> bool:
        """The same rule the Typst templates apply, in one place.

        A plan with warnings, or any allowance figure that is not confirmed, makes both
        documents provisional. Nothing else does — a `tight` bag is a fact, not a doubt.
        """
        return bool(self.warnings) or bool(self.unconfirmed_segments())

    def first_date(self) -> str | None:
        for segment in self.itinerary_segments:
            date = get(segment, "date")
            if date is not None:
                return str(date)
        return None

    def plan_generated_on(self) -> str | None:
        """`generated_on` as written; some YAML writers turn the `T` into a space."""
        value = get(self.plan, "generated_on")
        return None if value is None else str(value).replace("T", " ")

    def plan_generated_date(self) -> str | None:
        value = self.plan_generated_on()
        return None if value is None else value.split(" ")[0]


# --------------------------------------------------------------------------------------
# Shared document parts
# --------------------------------------------------------------------------------------


def frontmatter_block(
    title: str, generated_date: str, user_pairs: Sequence[tuple[str, str]]
) -> list[str]:
    """YAML frontmatter. `title` and `generated` are automatic; user keys override them.

    Values are emitted double-quoted with the JSON escaping rules, which are a subset of
    YAML's — that way a title containing a colon, a `#` or a quote cannot produce a
    frontmatter block the site generator refuses to parse.
    """
    ordered: list[str] = ["title", "generated"]
    values: dict[str, str] = {"title": title, "generated": generated_date}
    for key, value in user_pairs:
        if key not in values:
            ordered.append(key)
        values[key] = value
    lines = ["---"]
    for key in ordered:
        lines.append(f"{key}: {_yaml_scalar(values[key])}")
    lines.append("---")
    return lines


def _yaml_scalar(value: str) -> str:
    """Quote a frontmatter value, unless it is already a valid non-string YAML literal.

    `--frontmatter tags=[travel, packing]` and `--frontmatter draft=true` have to reach
    the site generator as a list and a boolean; quoting everything would turn both into
    strings and quietly break the collection schema. Anything that does not round-trip
    through the YAML parser as a non-string is quoted, which covers every title, date and
    free-text value — including the ones containing a colon or a `#` that would otherwise
    produce frontmatter the generator refuses to parse.
    """
    stripped = value.strip()
    if stripped:
        try:
            parsed = yaml.safe_load(stripped)
        except yaml.YAMLError:
            parsed = None
        if isinstance(parsed, (list, dict, bool, int, float)):
            return stripped
    body = value.replace("\\", "\\\\").replace('"', '\\"')
    body = body.replace("\n", "\\n").replace("\r", "\\r").replace("\t", "\\t")
    return f'"{body}"'


def provisional_banner(ws: Workspace) -> list[str]:
    """The banner both documents carry when anything about the plan is unsettled."""
    if not ws.is_provisional():
        return []
    reasons: list[str] = []
    for entry in ws.unconfirmed_segments():
        sid = get(entry, "segment_id", "?")
        confidence = get(get(entry, "source", {}), "confidence", "unknown")
        carrier = ws.segment_carrier(sid)
        suffix = f" ({carrier})" if carrier and carrier != "—" else ""
        reasons.append(
            f"Allowance for {esc(sid)}{suffix} is {confidence_flag(confidence)} — "
            "confirm it with the carrier before the airport."
        )
    if ws.warnings:
        reasons.append(
            f"The solver recorded {_plural(len(ws.warnings), 'warning')} against this plan."
        )
    if ws.errors:
        reasons.append(
            f"The solver recorded {_plural(len(ws.errors), 'unresolved error')} "
            "against this plan."
        )
    body = ["**PROVISIONAL — not every figure here is confirmed.**", ""]
    body += [f"- {reason}" for reason in reasons]
    body += [
        "",
        "Anything derived from these figures is provisional. Where two readings "
        "disagree, treat the tighter one as the real limit.",
    ]
    return blockquote(body) + [""]


def footer(ws: Workspace, rendered_at: str) -> list[str]:
    plan_generated = ws.plan_generated_on()
    parts = [
        f"Rendered {esc(rendered_at)} by `render_markdown.py` {RENDERER_VERSION} "
        f"from `{esc(ws.root.name)}`."
    ]
    if plan_generated is not None:
        parts.append(
            f"Plan generated {esc(plan_generated)} by "
            f"{esc(get(ws.plan, 'solver', 'the packing solver'))}."
        )
    return ["---", "", " ".join(parts), ""]


# --------------------------------------------------------------------------------------
# Document: counter card
# --------------------------------------------------------------------------------------


def render_counter_card(ws: Workspace, title: str, rendered_at: str) -> list[str]:
    """Section order follows typst/counter-card.typ exactly.

    Binding limits, bags, per-segment allowances, excess baggage, provenance. The Typst
    version is constrained to one A4 side and cuts content to stay there; this one is not,
    so it also carries each segment's `notes` in the provenance list — the same facts, in
    the place a reader looking for the source of a number would look.
    """
    lines: list[str] = [f"# {esc(title)}", ""]

    subtitle_bits = ["Check-in counter card"]
    trip_label = get(ws.trip, "label", get(ws.trip, "id"))
    if trip_label is not None and esc(trip_label) != esc(title):
        subtitle_bits.append(esc(trip_label))
    first_date = ws.first_date()
    if first_date is not None:
        subtitle_bits.append(f"first flight {esc(first_date)}")
    plan_date = ws.plan_generated_date()
    if plan_date is not None:
        subtitle_bits.append(f"plan generated {esc(plan_date)}")
    lines += [" · ".join(subtitle_bits), ""]

    lines += provisional_banner(ws)

    # ---- 1. Binding limits ---------------------------------------------------------
    lines += ["## Binding limits", "", "These govern the whole journey.", ""]

    checked = ws.binding_block("checked")
    cabin = ws.binding_block("cabin")
    personal = ws.binding_block("personal")

    if not (checked or cabin or personal):
        lines += [
            "_No `binding` block in allowances.yaml — run `/travel-packing:policies` "
            "before relying on this card._",
            "",
        ]
    else:
        rows: list[list[str]] = []
        pieces = get(checked, "included_pieces", get(checked, "pieces"))
        rows.append(
            _binding_row(
                ws,
                "Checked",
                f"{num(pieces, 0) if pieces is not None else '—'} × {kg(get(checked, 'max_weight_kg'))}",
                checked,
                " · ".join(
                    part
                    for part in (
                        f"max {num(get(checked, 'max_linear_cm'), 0)} cm linear"
                        if get(checked, "max_linear_cm") is not None
                        else "",
                        f"refused above {kg(get(checked, 'hard_max_weight_kg'))}"
                        if get(checked, "hard_max_weight_kg") is not None
                        else "",
                    )
                    if part
                )
                or "—",
            )
        )
        rows.append(
            _binding_row(ws, "Cabin bag", kg(get(cabin, "max_weight_kg")), cabin,
                         dims(get(cabin, "dimensions_cm")))
        )
        rows.append(
            _binding_row(ws, "Personal item", kg(get(personal, "max_weight_kg")), personal,
                         dims(get(personal, "dimensions_cm")))
        )
        lines += md_table(
            ["Limit", "Allowance", "Set by", "Confidence", "Detail"],
            "lrlll",
            rows,
        )
        lines.append("")
        lines += [
            "A blank allowance is not zero: it means the carriers publish no cap for that "
            "bag type, and the solver reports its headroom as unknown rather than "
            "inventing a number.",
            "",
        ]

    rationale = get(get(ws.allowances, "binding", {}), "rationale")
    if rationale is not None:
        lines += [f"**Why these govern:** {esc(rationale)}", ""]

    # ---- 2. Bags -------------------------------------------------------------------
    lines += ["## Bags", "", "_Measured where weighed, else projected from the itemised inventory._", ""]
    if ws.plan is None:
        lines += [
            "No `plan.yaml` in this workspace, so there is no bag table: this card shows "
            "the allowance only. Run `scripts/pack_solver.py` to project what each bag "
            "will actually weigh.",
            "",
        ]
    elif not ws.plan_bags:
        lines += ["_plan.yaml lists no bags._", ""]
    else:
        rows = []
        for bag in ws.plan_bags:
            bag_id = get(bag, "id", "?")
            label = get(bag, "label", get(ws.bag_meta(bag_id), "label", bag_id))
            measured = ws.measured_gross(bag)
            measured_kg = None if measured is None else float(measured[0])
            governing, headroom, status = governing_figures(bag, measured_kg)
            gross = kg(governing)
            if measured is not None:
                phase = f", {esc(measured[1])}" if measured[1] is not None else ""
                gross = f"{gross} (weighed{phase})" if governing == measured_kg else (
                    f"{gross} (last measured {kg(measured_kg)}{phase})"
                )
            rows.append(
                [
                    f"{esc(label)} ({esc(bag_id)})",
                    esc(get(bag, "type", "—")),
                    gross,
                    kg(get(bag, "allowance_kg")),
                    kg_signed(headroom),
                    status_label(status),
                ]
            )
        lines += md_table(
            ["Bag", "Type", "Gross", "Allowance", "Headroom", "Status"],
            "llrrrc",
            rows,
        )
        lines += [
            "",
            "Projected = bag tare + packing-cube tare + itemised contents. **TIGHT** is "
            f"anything inside {num(TIGHT_BAND_KG)} kg of the limit: home and airport "
            "scales routinely disagree by a few hundred grams, so 0.2 kg of headroom is "
            "not headroom.",
            "",
        ]

    # ---- 3. Allowance by segment ---------------------------------------------------
    lines += ["## Allowance by segment", "", "_The carrier's own published figures._", ""]
    if not ws.allowance_segments:
        lines += ["_allowances.yaml lists no segments._", ""]
    else:
        rows = []
        for entry in ws.allowance_segments:
            sid = get(entry, "segment_id", "?")
            chk = get(entry, "checked", {})
            cab = get(entry, "cabin", {})
            per = get(entry, "personal_item", {})
            carrier = ws.segment_carrier(sid)
            flight = ws.segment_flight(sid)
            rows.append(
                [
                    ws.segment_route(sid),
                    f"{carrier} ({flight})" if flight and flight != "—" else carrier,
                    " · ".join(
                        [
                            f"{num(get(chk, 'included_pieces', 0), 0)} × "
                            f"{kg(get(chk, 'max_weight_kg'))}",
                            f"{num(get(chk, 'max_linear_cm'), 0)} cm linear",
                            f"hard max {kg(get(chk, 'hard_max_weight_kg'))}",
                        ]
                    ),
                    " · ".join(
                        [
                            f"{num(get(cab, 'pieces', 1), 0)} × {kg(get(cab, 'max_weight_kg'))}",
                            dims(get(cab, "dimensions_cm")),
                            f"enforced: {esc(get(cab, 'enforced', 'unknown'))}",
                        ]
                    ),
                    " · ".join(
                        [kg(get(per, "max_weight_kg")), dims(get(per, "dimensions_cm"))]
                    ),
                    confidence_flag(ws.segment_confidence(sid)),
                ]
            )
        lines += md_table(
            ["Segment", "Carrier", "Checked", "Cabin", "Personal", "Confidence"],
            "llllll",
            rows,
        )
        lines.append("")

    # ---- 4. Excess baggage ---------------------------------------------------------
    lines += [
        "## If the bag is over",
        "",
        "_Excess-baggage prices, per segment. This is the price of the decision being "
        "asked for at the desk._",
        "",
    ]
    if not ws.allowance_segments:
        lines += ["_No segments to price._", ""]
    else:
        rows = []
        for entry in ws.allowance_segments:
            sid = get(entry, "segment_id", "?")
            excess = get(entry, "excess", {})
            currency = get(excess, "currency")
            rows.append(
                [
                    f"{esc(sid)} — {ws.segment_carrier(sid)}",
                    money(get(excess, "extra_bag_prepaid"), currency),
                    money(get(excess, "extra_bag_airport"), currency),
                    esc(get(excess, "overweight_band", "—")),
                    money(get(excess, "overweight_fee"), currency),
                ]
            )
        lines += md_table(
            [
                "Segment",
                "Extra bag, prepaid",
                "Extra bag, at airport",
                "Overweight band",
                "Overweight fee",
            ],
            "lrrlr",
            rows,
        )
        lines.append("")

    # ---- 5. Provenance -------------------------------------------------------------
    lines += [
        "## Provenance",
        "",
        "_Every figure above carries its confidence and the date it was fetched._",
        "",
    ]
    if not ws.allowance_segments:
        lines += ["_No sources recorded._", ""]
    else:
        for entry in ws.allowance_segments:
            sid = get(entry, "segment_id", "?")
            source = get(entry, "source", {})
            bits = [
                ws.segment_carrier(sid),
                confidence_flag(get(source, "confidence")),
                f"fetched {esc(get(source, 'fetched_on', 'date unknown'))}",
                f"via {esc(get(source, 'route', 'unknown route'))}",
            ]
            url = get(source, "url")
            if url is not None:
                bits.append(link(url, "source"))
            lines.append(f"- **{esc(sid)}** — " + " · ".join(bit for bit in bits if bit))
            quote = get(source, "quote")
            if quote is not None:
                lines.append(f"  - Quote: {esc(quote)}")
            note = get(entry, "notes")
            if note is not None:
                lines.append(f"  - Note: {esc(note)}")
        lines.append("")
        lines += [
            f"Allowances verified {esc(get(ws.allowances, 'verified_on', '—'))}.",
            "",
        ]

    lines += footer(ws, rendered_at)
    return lines


def _binding_row(
    ws: Workspace, label: str, value: str, block: dict[str, Any], detail: str
) -> list[str]:
    """One row of the binding-limits table.

    The provenance of the segment that *sets* a limit travels with that limit. A 7 kg
    cabin figure sourced by assumption is a different fact from a 7 kg figure read off
    the carrier's own page, and the card has to say which — in the row, not in a footnote.
    """
    limited_by = get(block, "limited_by")
    if limited_by is None:
        set_by = "**limiting segment not recorded**"
        confidence = "—"
    else:
        route = ws.segment_route(limited_by)
        flight = ws.segment_flight(limited_by)
        set_by = f"{route} ({flight})" if flight and flight != "—" else route
        confidence = confidence_flag(ws.segment_confidence(limited_by))
    return [label, value, set_by, confidence, detail or "—"]


# --------------------------------------------------------------------------------------
# Document: packing list
# --------------------------------------------------------------------------------------


def render_packing_list(ws: Workspace, title: str, rendered_at: str) -> list[str]:
    """Section order follows typst/packing-list.typ.

    Summary, warnings, then one section per bag (cubes first, loose items last), then the
    not-packed list and the leave-behind ranking. Each bag gets its contents twice: as a
    table with the weights, and as a `- [ ]` checklist, because the table is what you read
    at the desk and the checklist is what you tick on a phone with the bag open.
    """
    lines: list[str] = [f"# {esc(title)}", ""]

    subtitle_bits: list[str] = []
    trip_label = get(ws.trip, "label", get(ws.trip, "id"))
    if trip_label is not None and esc(trip_label) != esc(title):
        subtitle_bits.append(esc(trip_label))
    plan_generated = ws.plan_generated_on()
    if plan_generated is not None:
        subtitle_bits.append(f"plan generated {esc(plan_generated)}")
    objective = get(ws.plan, "objective")
    if objective is not None:
        subtitle_bits.append(f"objective {esc(objective)}")
    if subtitle_bits:
        lines += [" · ".join(subtitle_bits), ""]

    lines += provisional_banner(ws)

    # ---- Summary -------------------------------------------------------------------
    lines += ["## Summary", "", "_One line per bag, as the plan stands._", ""]
    if not ws.plan_bags:
        lines += ["_plan.yaml lists no bags._", ""]
    else:
        rows: list[list[str]] = []
        for bag in ws.plan_bags:
            bag_id = get(bag, "id", "?")
            label = get(bag, "label", get(ws.bag_meta(bag_id), "label", bag_id))
            tare = get(bag, "tare_kg")
            cube_tare = get(bag, "cube_tare_kg", 0)
            total_tare = None if tare is None else float(tare) + float(cube_tare or 0)
            measured = ws.measured_gross(bag)
            governing, headroom, status = governing_figures(
                bag, None if measured is None else float(measured[0])
            )
            rows.append(
                [
                    f"{esc(label)} ({esc(bag_id)})",
                    esc(get(bag, "type", "—")),
                    kg(total_tare, 2),
                    kg(get(bag, "contents_kg"), 2),
                    kg(governing, 2),
                    kg(get(bag, "allowance_kg")),
                    kg_signed(headroom, 2),
                    status_label(status),
                ]
            )
        lines += md_table(
            [
                "Bag",
                "Type",
                "Tare (bag + cubes)",
                "Contents",
                "Gross",
                "Allowance",
                "Headroom",
                "Status",
            ],
            "llrrrrrc",
            rows,
        )
        lines.append("")
        lines += _summary_totals(ws)

    # ---- Warnings ------------------------------------------------------------------
    if ws.errors:
        lines += blockquote(
            ["**Errors the solver could not resolve.**", ""]
            + [f"- {esc(entry)}" for entry in ws.errors]
        )
        lines.append("")
    if ws.warnings:
        lines += blockquote(
            ["**Warnings from the solver.**", ""]
            + [f"- {esc(entry)}" for entry in ws.warnings]
        )
        lines.append("")

    lines += [CARRIAGE_LEGEND, ""]

    # ---- One section per bag -------------------------------------------------------
    for bag in ws.plan_bags:
        lines += _render_bag(ws, bag)

    # ---- Not packed ----------------------------------------------------------------
    lines += ["## Not packed", "", "_Items the solver could not place._", ""]
    unassigned = as_list(get(ws.plan, "unassigned", []))
    if not unassigned:
        lines += ["Everything in inventory.yaml was assigned to a bag.", ""]
    else:
        rows = []
        marked = False
        for entry in unassigned:
            if not isinstance(entry, dict):
                continue
            item_id = get(entry, "item", "?")
            item = ws.item(item_id)
            name = get(entry, "name", get(item, "name", item_id))
            carriage = get(item, "carriage", "any")
            marker = carriage_marker(carriage)
            marked = marked or bool(marker)
            qty = get(item, "qty", 1)
            rows.append(
                [
                    f"{marker + ' ' if marker else ''}{esc(name)} ({esc(item_id)})",
                    esc(qty),
                    g_as_kg(get(item, "weight_g"), qty),
                    esc(carriage),
                    esc(get(entry, "reason", "no reason recorded")),
                ]
            )
        lines += md_table(
            ["Item", "Qty", "Weight", "Carriage", "Why it is not packed"],
            "lrrll",
            rows,
        )
        lines.append("")
        if marked:
            lines += [CARRIAGE_LEGEND, ""]

    # ---- Leave-behind ranking ------------------------------------------------------
    ranking = [r for r in as_list(get(ws.plan, "overflow_ranking", [])) if isinstance(r, dict)]
    if ranking:
        lines += [
            "## If weight has to come out",
            "",
            "_Ranked by cost per kilogram saved — cheapest sacrifice first. The ranking is "
            "money-per-kilogram, not weight: a heavy thing that can be re-bought at the far "
            "end is a better thing to leave than a light thing that cannot._",
            "",
        ]
        # `note` is in the worked example but the solver does not write one, so the column
        # only appears when at least one row would have something to put in it: a table of
        # empty cells reads as missing data rather than as an absent field.
        has_notes = any(get(row, "note") is not None for row in ranking)
        rows = []
        for index, row in enumerate(ranking, start=1):
            item_id = get(row, "item", "?")
            item = ws.item(item_id)
            name = get(row, "name", get(item, "name", item_id))
            tier = get(row, "tier", get(item, "tier"))
            currency = get(row, "currency", get(item, "currency"))
            if get(row, "replaceable", False):
                rebuy = money(get(row, "replace_cost"), currency)
            else:
                rebuy = "**not re-buyable**"
            cells = [
                esc(get(row, "rank", index)),
                f"{esc(name)} ({esc(item_id)})",
                esc(tier) if tier is not None else "—",
                esc(get(row, "bag", "—")),
                kg(get(row, "kg_saved"), 2),
                rebuy,
                money(get(row, "cost_per_kg"), currency, 1),
            ]
            if has_notes:
                cells.append(esc(get(row, "note", "")) if get(row, "note") else "")
            rows.append(cells)
        headers = ["#", "Item", "Tier", "Bag", "Saves", "Re-buy", "Per kg"]
        aligns = "clllrrr"
        if has_notes:
            headers.append("Note")
            aligns += "l"
        lines += md_table(headers, aligns, rows)
        lines.append("")

    lines += footer(ws, rendered_at)
    return lines


def _summary_totals(ws: Workspace) -> list[str]:
    packed_ids: list[Any] = []
    for bag in ws.plan_bags:
        packed_ids += _bag_item_ids(bag)
    units = 0
    for item_id in packed_ids:
        try:
            units += int(get(ws.item(item_id), "qty", 1))
        except (TypeError, ValueError):
            units += 1
    total_gross = 0.0
    for bag in ws.plan_bags:
        try:
            _m = ws.measured_gross(bag)
            _g, _, _ = governing_figures(bag, None if _m is None else float(_m[0]))
            total_gross += float(_g or 0)
        except (TypeError, ValueError):
            pass
    not_packed = len(as_list(get(ws.plan, "unassigned", [])))
    return [
        f"{_plural(len(packed_ids), 'inventory line')} / "
        f"{_plural(units, 'physical unit')} packed across "
        f"{_plural(len(ws.plan_bags), 'bag')} · {kg(total_gross, 2)} total mass leaving "
        f"the house · {_plural(not_packed, 'line')} not packed. Weights come from "
        "inventory.yaml in grams and are converted here; bag and cube tares come from "
        "bags.yaml in kilograms.",
        "",
    ]


def _plural(count: int, noun: str) -> str:
    return f"{count} {noun}" if count == 1 else f"{count} {noun}s"


def _bag_item_ids(bag: dict[str, Any]) -> list[Any]:
    ids: list[Any] = []
    for cube in as_list(get(bag, "cubes", [])):
        if isinstance(cube, dict):
            ids += as_list(get(cube, "items", []))
    ids += as_list(get(bag, "loose_items", []))
    return ids


def _render_bag(ws: Workspace, bag: dict[str, Any]) -> list[str]:
    bag_id = get(bag, "id", "?")
    label = get(bag, "label", get(ws.bag_meta(bag_id), "label", bag_id))
    lines: list[str] = [
        f"## {esc(label)}",
        "",
        f"_{esc(bag_id)} · {esc(get(bag, 'type', ''))}_",
        "",
    ]

    # The numbers that decide whether this bag is a problem. Gross is the governing
    # figure — the projection, or a heavier scale reading where one exists.
    _measured = ws.measured_gross(bag)
    _governing, _headroom, _status = governing_figures(
        bag, None if _measured is None else float(_measured[0])
    )
    lines += md_table(
        ["Tare (empty bag)", "Cubes", "Contents", "Gross", "Allowance",
         "Headroom", "Status"],
        "rrrrrrc",
        [
            [
                kg(get(bag, "tare_kg"), 2),
                kg(get(bag, "cube_tare_kg", 0), 2),
                kg(get(bag, "contents_kg"), 2),
                kg(_governing, 2),
                kg(get(bag, "allowance_kg")),
                kg_signed(_headroom, 2),
                status_label(_status),
            ]
        ],
    )
    lines.append("")

    measured = ws.measured_gross(bag)
    if measured is not None:
        last, phase = measured
        projected = get(bag, "projected_gross_kg", last)
        try:
            delta = float(last) - float(projected)
        except (TypeError, ValueError):
            delta = 0.0
        direction = "more" if delta >= 0 else "less"
        phase_note = f" ({esc(phase)})" if phase is not None else ""
        lines += [
            f"Last scale reading {kg(last)}{phase_note} — {kg(abs(delta), 2)} "
            f"{direction} than the itemised projection. A gap this way usually means "
            "something in the bag is not in inventory.yaml.",
            "",
        ]

    marked = False

    for cube in as_list(get(bag, "cubes", [])):
        if not isinstance(cube, dict):
            continue
        cube_id = get(cube, "id", "?")
        meta = ws.cube_meta(bag_id, cube_id)
        heading_bits = [f"{esc(cube_id)} · cube tare {kg(get(meta, 'tare_kg', 0), 2)}"]
        if get(meta, "volume_l") is not None:
            heading_bits.append(f"{esc(get(meta, 'volume_l'))} L")
        lines += [
            f"### {esc(get(meta, 'label', cube_id))}",
            "",
            f"_{' · '.join(heading_bits)}_",
            "",
        ]
        table_lines, cube_marked = _items_table(
            ws,
            as_list(get(cube, "items", [])),
            subtotal_label="Cube total, including cube tare",
            subtotal_extra_kg=float(get(meta, "tare_kg", 0) or 0),
        )
        marked = marked or cube_marked
        lines += table_lines + [""]

    loose = as_list(get(bag, "loose_items", []))
    if loose:
        lines += ["### Loose in the bag", "", "_Not in a packing cube._", ""]
        table_lines, loose_marked = _items_table(ws, loose, subtotal_label="Loose total")
        marked = marked or loose_marked
        lines += table_lines + [""]

    checklist = _checklist(ws, bag)
    if checklist:
        lines += [f"### Checklist — {esc(bag_id)}", ""] + checklist + [""]

    if marked:
        lines += [CARRIAGE_LEGEND, ""]

    return lines


def _items_table(
    ws: Workspace,
    item_ids: Sequence[Any],
    subtotal_label: str | None = None,
    subtotal_extra_kg: float = 0.0,
) -> tuple[list[str], bool]:
    """Returns the table lines and whether any row carried a carriage marker."""
    rows: list[list[str]] = []
    total_g = 0.0
    marked = False
    for item_id in item_ids:
        item = ws.item(item_id)
        if not item:
            rows.append(
                [" ", f"**{esc(item_id)} — not found in inventory.yaml**", "—", "—", "—", "—"]
            )
            continue
        qty = get(item, "qty", 1)
        weight_g = get(item, "weight_g")
        try:
            total_g += float(weight_g or 0) * float(qty or 1)
        except (TypeError, ValueError):
            pass
        carriage = get(item, "carriage", "any")
        marker = carriage_marker(carriage)
        marked = marked or bool(marker)
        name = f"{marker + ' ' if marker else ''}{esc(get(item, 'name', '(unnamed)'))} " \
               f"({esc(item_id)})"
        reason = get(item, "carriage_reason")
        if marker and reason is not None:
            name = f"{name} — {esc(carriage)}: {esc(reason)}"
        elif marker:
            name = f"{name} — {esc(carriage)}"
        rows.append(
            [
                " ",
                name,
                esc(qty),
                f"{num(weight_g, 0)} g" if weight_g is not None else "—",
                g_as_kg(weight_g, qty),
                esc(get(item, "category", "—")),
            ]
        )
    if subtotal_label is not None:
        rows.append(
            [
                " ",
                f"**{esc(subtotal_label)}**",
                " ",
                " ",
                f"**{kg(total_g / 1000.0 + subtotal_extra_kg, 2)}**",
                " ",
            ]
        )
    return (
        md_table(["✓", "Item", "Qty", "Each", "Line", "Category"], "clrrrl", rows),
        marked,
    )


def _checklist(ws: Workspace, bag: dict[str, Any]) -> list[str]:
    """The same contents as the tables, as `- [ ]` boxes.

    A Markdown table cannot hold a working checkbox, and the packing list is used with
    the bag open and a phone in the other hand. The tables carry the arithmetic; this
    carries the ticking.
    """
    lines: list[str] = []
    bag_id = get(bag, "id", "?")
    for cube in as_list(get(bag, "cubes", [])):
        if not isinstance(cube, dict):
            continue
        cube_id = get(cube, "id", "?")
        meta = ws.cube_meta(bag_id, cube_id)
        entries = as_list(get(cube, "items", []))
        if not entries:
            continue
        lines.append(f"- [ ] **{esc(get(meta, 'label', cube_id))}** ({esc(cube_id)})")
        for item_id in entries:
            lines.append("  " + _checklist_line(ws, item_id))
    for item_id in as_list(get(bag, "loose_items", [])):
        lines.append(_checklist_line(ws, item_id))
    return lines


def _checklist_line(ws: Workspace, item_id: Any) -> str:
    item = ws.item(item_id)
    if not item:
        return f"- [ ] **{esc(item_id)} — not found in inventory.yaml**"
    qty = get(item, "qty", 1)
    marker = carriage_marker(get(item, "carriage", "any"))
    prefix = f"{marker} " if marker else ""
    bits = [f"- [ ] {prefix}{esc(get(item, 'name', '(unnamed)'))}"]
    tail = [f"×{esc(qty)}", g_as_kg(get(item, "weight_g"), qty), esc(item_id)]
    if marker:
        tail.append(esc(get(item, "carriage", "any")))
    return bits[0] + " — " + " · ".join(tail)


# --------------------------------------------------------------------------------------
# Driver
# --------------------------------------------------------------------------------------


def build_document(
    workspace: Path,
    doc: str,
    title_override: str | None,
    frontmatter_pairs: list[tuple[str, str]] | None,
    rendered_at: str,
) -> str:
    ws = Workspace(workspace)
    if doc == "counter-card":
        # allowances.yaml is the document; plan.yaml is an enrichment of it.
        ws.load(
            require=["allowances"],
            optional=["itinerary", "plan", "bags", "inventory"],
        )
        title = title_override or str(
            get(ws.trip, "label", get(ws.trip, "id", DOC_TITLES[doc]))
        )
        body = render_counter_card(ws, title, rendered_at)
    else:
        # plan.yaml is the document: a packing list without one has nothing to list.
        ws.load(require=["plan"], optional=["itinerary", "allowances", "bags", "inventory"])
        title = title_override or DOC_TITLES[doc]
        body = render_packing_list(ws, title, rendered_at)

    lines: list[str] = []
    if frontmatter_pairs is not None:
        lines += frontmatter_block(title, rendered_at.split("T")[0], frontmatter_pairs)
        lines.append("")
    lines += body

    text = "\n".join(lines)
    # Collapse runs of blank lines: the section builders each end with one, and doubling
    # them up would make the diff between two runs depend on which sections were present.
    while "\n\n\n" in text:
        text = text.replace("\n\n\n", "\n\n")
    return guard_braces(text.rstrip("\n") + "\n")


def parse_frontmatter(values: Sequence[str]) -> list[tuple[str, str]]:
    pairs: list[tuple[str, str]] = []
    for raw in values:
        if "=" not in raw:
            raise RenderError(f"--frontmatter needs KEY=VALUE, got {raw!r}")
        key, _, value = raw.partition("=")
        key = key.strip()
        if not key:
            raise RenderError(f"--frontmatter needs a non-empty key, got {raw!r}")
        pairs.append((key, value))
    return pairs


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Render the counter card and the packing list as Markdown."
    )
    parser.add_argument(
        "workspace", nargs="?", default=".", help="trip workspace directory (default: .)"
    )
    parser.add_argument(
        "--doc",
        required=True,
        choices=["counter-card", "packing-list", "both"],
        help="which document to render",
    )
    parser.add_argument(
        "--out", default=None, help="write a single document to this file (default: stdout)"
    )
    parser.add_argument(
        "--out-dir",
        default=None,
        dest="out_dir",
        help="write into this directory (default for --doc both: <workspace>/output)",
    )
    parser.add_argument(
        "--frontmatter",
        action="append",
        default=None,
        metavar="KEY=VALUE",
        help="emit YAML frontmatter with this key; repeatable. `title` and `generated` "
        "are added automatically whenever the flag is used at all",
    )
    parser.add_argument("--title", default=None, help="override the document title")
    parser.add_argument(
        "--now",
        default=None,
        help="override the generation timestamp with a fixed ISO value (reproducible output)",
    )
    args = parser.parse_args()

    workspace = Path(args.workspace).resolve()
    if not workspace.is_dir():
        print(f"error: {workspace} is not a directory", file=sys.stderr)
        return 1

    rendered_at = args.now or dt.datetime.now().astimezone().isoformat(timespec="seconds")

    try:
        frontmatter_pairs = (
            None if args.frontmatter is None else parse_frontmatter(args.frontmatter)
        )
        if args.doc == "both" and args.out:
            raise RenderError("--out writes one file; use --out-dir with --doc both")

        docs = ["counter-card", "packing-list"] if args.doc == "both" else [args.doc]
        rendered = {
            doc: build_document(workspace, doc, args.title, frontmatter_pairs, rendered_at)
            for doc in docs
        }

        if args.out and len(docs) == 1:
            target = Path(args.out).resolve()
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(rendered[docs[0]], encoding="utf-8")
            print(f"Wrote {target}", file=sys.stderr)
        elif args.out_dir or args.doc == "both":
            out_dir = Path(args.out_dir).resolve() if args.out_dir else workspace / "output"
            out_dir.mkdir(parents=True, exist_ok=True)
            for doc in docs:
                target = out_dir / DEFAULT_FILENAMES[doc]
                target.write_text(rendered[doc], encoding="utf-8")
                print(f"Wrote {target}", file=sys.stderr)
        else:
            sys.stdout.write(rendered[docs[0]])
    except RenderError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    except OSError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
