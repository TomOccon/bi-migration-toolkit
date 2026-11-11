"""Inventory -> neutral spec -> generic target 'card/page' payload.

Every id is derived from source ids with a hash, never from a counter or a
clock, so a rerun yields byte-identical payloads and the writer can report
created / updated / unchanged instead of duplicating content.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, List, Optional

from .inventory import Inventory, InvDataset, InvReport, InvVisual
from .mapping import PLACEHOLDER, map_visual, neutral_type
from .spec import (
    GRID_COLUMNS,
    DashboardSpec,
    FieldRef,
    FilterSpec,
    GridLayout,
    PageSpec,
    VisualSpec,
    stable_id,
)

CANVAS_WIDTH = 1280.0
ROW_HEIGHT_PX = 60.0

_OPERATORS = {
    "In": "in",
    "NotIn": "not_in",
    "Is": "eq",
    "GreaterThan": "gt",
    "GreaterThanOrEqual": "gte",
    "LessThan": "lt",
    "LessThanOrEqual": "lte",
    "Between": "between",
    "TopN": "top_n",
    "RelativeDate": "relative_date",
}
_AGGS = {"DistinctCount": "distinct_count"}

REVIEW_THRESHOLD = 0.85  # below this a converted card is flagged needs_review


def to_grid(v: InvVisual) -> GridLayout:
    """Map pixel geometry on a 1280px canvas to a 12-column grid with 60px rows."""
    width = max(1, round(v.width / CANVAS_WIDTH * GRID_COLUMNS))
    col = max(0, round(v.x / CANVAS_WIDTH * GRID_COLUMNS))
    col = min(col, GRID_COLUMNS - width)
    row = max(0, round(v.y / ROW_HEIGHT_PX))
    height = max(1, round(v.height / ROW_HEIGHT_PX))
    return GridLayout(col, row, width, height)


def _agg(name: Optional[str]) -> Optional[str]:
    if name is None:
        return None
    return _AGGS.get(name, name.lower())


def to_spec(report: InvReport, dataset: Optional[InvDataset] = None) -> DashboardSpec:
    pages = []
    for page in report.pages:
        visuals = []
        for v in page.visuals:
            fields = tuple(
                FieldRef(
                    table=f.table,
                    column=f.column,
                    role=f.role,
                    aggregation=_agg(f.aggregation),
                    is_measure=f.is_measure,
                    expression=(dataset.measures.get(f.column) if (dataset and f.is_measure) else None),
                )
                for f in v.fields
            )
            filters = tuple(
                FilterSpec(f.table, f.column, _OPERATORS.get(f.operator, f.operator.lower()), f.values)
                for f in v.filters
            )
            flags = ("conditional_formatting",) if v.conditional_formatting else ()
            visuals.append(
                VisualSpec(
                    id=stable_id(report.id, page.name, v.name),
                    type=neutral_type(v.type),
                    source_type=v.type,
                    title=v.title,
                    layout=to_grid(v),
                    fields=fields,
                    filters=filters,
                    flags=flags,
                )
            )
        pages.append(PageSpec(stable_id(report.id, page.name), page.display_name, tuple(visuals)))
    return DashboardSpec(
        id=stable_id("dashboard", report.id),
        name=report.name,
        workspace=report.workspace_name,
        dataset_id=report.dataset_id,
        owner=report.owner,
        views_90d=report.views_90d,
        pages=tuple(pages),
    )


def inventory_to_specs(inv: Inventory) -> List[DashboardSpec]:
    return [to_spec(r, inv.datasets.get(r.dataset_id)) for r in inv.reports]


def _card(v: VisualSpec) -> Dict:
    res = map_visual(v)
    if res.supported:
        status = "converted" if res.fidelity >= REVIEW_THRESHOLD else "needs_review"
    else:
        status = "manual"
    columns = []
    for f in v.fields:
        col = {"table": f.table, "column": f.column, "role": f.role, "aggregation": f.aggregation}
        if f.is_measure:
            col["calc"] = {"source_expression": f.expression or "", "status": "needs_rewrite"}
        columns.append(col)
    return {
        "card_id": v.id,
        "card_type": res.target_type if res.supported else PLACEHOLDER,
        "title": v.title,
        "status": status,
        "fidelity": res.fidelity,
        "notes": list(res.reasons),
        "source_type": v.source_type,
        "columns": columns,
        "filters": [
            {"table": f.table, "column": f.column, "operator": f.operator, "values": list(f.values)}
            for f in v.filters
        ],
        "position": {
            "col": v.layout.col,
            "row": v.layout.row,
            "width": v.layout.width,
            "height": v.layout.height,
        },
    }


def to_payload(spec: DashboardSpec) -> Dict:
    """Build the generic target payload. Pure function of the spec."""
    return {
        "dashboard_id": spec.id,
        "name": spec.name,
        "source": {"workspace": spec.workspace, "dataset_id": spec.dataset_id, "owner": spec.owner},
        "pages": [
            {
                "page_id": p.id,
                "title": p.name,
                "grid": {"columns": GRID_COLUMNS},
                "cards": [_card(v) for v in p.visuals],
            }
            for p in spec.pages
        ],
    }


def validate_payload(payload: Dict, spec: DashboardSpec) -> List[str]:
    """Return a list of problems; empty means the payload passes structural checks."""
    errors: List[str] = []
    cards = [c for p in payload["pages"] for c in p["cards"]]
    if len(cards) != len(spec.visuals):
        errors.append(f"card count {len(cards)} != visual count {len(spec.visuals)}")
    ids = [c["card_id"] for c in cards]
    if len(set(ids)) != len(ids):
        errors.append("duplicate card ids")
    src = {v.id: v for v in spec.visuals}
    for c in cards:
        pos = c["position"]
        if pos["width"] < 1 or pos["col"] < 0 or pos["col"] + pos["width"] > GRID_COLUMNS:
            errors.append(f"card {c['card_id']} outside grid")
        v = src.get(c["card_id"])
        if v is None:
            errors.append(f"card {c['card_id']} has no source visual")
        elif len(c["columns"]) != len(v.fields):
            errors.append(f"card {c['card_id']} lost fields")
    return errors


def dump(payload: Dict) -> str:
    return json.dumps(payload, indent=2, sort_keys=True) + "\n"


def write_payloads(payloads: List[Dict], outdir) -> Dict[str, int]:
    """Write one file per dashboard, named by dashboard id. Safe to rerun."""
    out = Path(outdir)
    out.mkdir(parents=True, exist_ok=True)
    counts = {"created": 0, "updated": 0, "unchanged": 0}
    for p in payloads:
        path = out / f"{p['dashboard_id']}.json"
        text = dump(p)
        if not path.exists():
            counts["created"] += 1
        elif path.read_text(encoding="utf-8") != text:
            counts["updated"] += 1
        else:
            counts["unchanged"] += 1
            continue
        path.write_text(text, encoding="utf-8")
    return counts
