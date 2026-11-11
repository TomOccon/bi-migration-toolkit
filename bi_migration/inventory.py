"""Crawl a Power BI REST-API-shaped JSON inventory into typed objects.

The input mirrors the nesting you get when you combine the Power BI admin
endpoints (workspaces, reports, datasets) with a report definition export
(pages, visuals). The REST API alone does not return visuals, so real projects
usually join the two. Here everything arrives in one JSON document.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple


class InventoryError(ValueError):
    """Raised when the inventory document is structurally invalid."""


@dataclass(frozen=True)
class InvField:
    table: str
    column: str
    role: str  # category | value | series | detail
    aggregation: Optional[str] = None
    is_measure: bool = False


@dataclass(frozen=True)
class InvFilter:
    table: str
    column: str
    operator: str
    values: Tuple = ()


@dataclass(frozen=True)
class InvVisual:
    name: str
    type: str
    title: str
    x: float
    y: float
    width: float
    height: float
    fields: Tuple[InvField, ...] = ()
    filters: Tuple[InvFilter, ...] = ()
    conditional_formatting: bool = False


@dataclass(frozen=True)
class InvPage:
    name: str
    display_name: str
    visuals: Tuple[InvVisual, ...] = ()


@dataclass(frozen=True)
class InvReport:
    id: str
    name: str
    workspace_id: str
    workspace_name: str
    dataset_id: str
    owner: str
    views_90d: int
    pages: Tuple[InvPage, ...] = ()

    @property
    def visual_count(self) -> int:
        return sum(len(p.visuals) for p in self.pages)


@dataclass(frozen=True)
class InvDataset:
    id: str
    name: str
    tables: Dict[str, Tuple[str, ...]]
    measures: Dict[str, str]  # measure name -> DAX expression


@dataclass
class Inventory:
    workspaces: List[Tuple[str, str]] = field(default_factory=list)
    reports: List[InvReport] = field(default_factory=list)
    datasets: Dict[str, InvDataset] = field(default_factory=dict)
    warnings: List[str] = field(default_factory=list)

    def stats(self) -> Dict[str, int]:
        return {
            "workspaces": len(self.workspaces),
            "reports": len(self.reports),
            "pages": sum(len(r.pages) for r in self.reports),
            "visuals": sum(r.visual_count for r in self.reports),
            "datasets": len(self.datasets),
        }


def _req(obj: dict, key: str, ctx: str):
    if key not in obj:
        raise InventoryError(f"missing '{key}' in {ctx}")
    return obj[key]


def _parse_visual(raw: dict, ctx: str) -> InvVisual:
    layout = _req(raw, "layout", ctx)
    fields = tuple(
        InvField(
            table=f["table"],
            column=f["column"],
            role=f.get("role", "value"),
            aggregation=f.get("aggregation"),
            is_measure=bool(f.get("isMeasure", False)),
        )
        for f in raw.get("fields", [])
    )
    filters = tuple(
        InvFilter(
            table=f["table"],
            column=f["column"],
            operator=f["operator"],
            values=tuple(f.get("values", [])),
        )
        for f in raw.get("filters", [])
    )
    return InvVisual(
        name=_req(raw, "name", ctx),
        type=_req(raw, "type", ctx),
        title=raw.get("title", ""),
        x=float(layout["x"]),
        y=float(layout["y"]),
        width=float(layout["width"]),
        height=float(layout["height"]),
        fields=fields,
        filters=filters,
        conditional_formatting=bool(raw.get("formatting", {}).get("conditionalFormatting", False)),
    )


def parse_inventory(doc: dict) -> Inventory:
    """Walk workspaces -> reports -> pages -> visuals and the dataset list."""
    inv = Inventory()
    for d in doc.get("datasets", []):
        ds = InvDataset(
            id=_req(d, "id", "dataset"),
            name=d.get("name", d["id"]),
            tables={t["name"]: tuple(c["name"] for c in t.get("columns", [])) for t in d.get("tables", [])},
            measures={m["name"]: m.get("expression", "") for t in d.get("tables", []) for m in t.get("measures", [])},
        )
        inv.datasets[ds.id] = ds

    seen = set()
    for ws in _req(doc, "workspaces", "inventory"):
        ws_id = _req(ws, "id", "workspace")
        inv.workspaces.append((ws_id, ws.get("name", ws_id)))
        for r in ws.get("reports", []):
            rid = _req(r, "id", f"report in workspace {ws_id}")
            if rid in seen:
                raise InventoryError(f"duplicate report id {rid}")
            seen.add(rid)
            ds_id = r.get("datasetId", "")
            if ds_id not in inv.datasets:
                inv.warnings.append(f"report {rid} references unknown dataset '{ds_id}'")
            pages = []
            for p in r.get("pages", []):
                pname = _req(p, "name", f"page in report {rid}")
                visuals = tuple(
                    _parse_visual(v, f"visual in {rid}/{pname}") for v in p.get("visuals", [])
                )
                pages.append(InvPage(pname, p.get("displayName", pname), visuals))
            inv.reports.append(
                InvReport(
                    id=rid,
                    name=r.get("name", rid),
                    workspace_id=ws_id,
                    workspace_name=ws.get("name", ws_id),
                    dataset_id=ds_id,
                    owner=r.get("owner", ""),
                    views_90d=int(r.get("viewsLast90d", 0)),
                    pages=tuple(pages),
                )
            )
    return inv


def load_inventory(path) -> Inventory:
    with open(Path(path), encoding="utf-8") as fh:
        return parse_inventory(json.load(fh))
