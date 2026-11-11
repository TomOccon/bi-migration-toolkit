"""Platform-neutral dashboard spec.

Nothing in this module knows about Power BI or about any target platform. The
converter produces these objects from the inventory, the mapper scores them,
and the payload builder turns them into the target JSON.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field, asdict
from typing import Any, Dict, List, Optional, Tuple

GRID_COLUMNS = 12


def stable_id(*parts: str) -> str:
    """Deterministic 16-hex-char id derived from the given path parts."""
    digest = hashlib.sha1("\x1f".join(parts).encode("utf-8")).hexdigest()
    return digest[:16]


@dataclass(frozen=True)
class FieldRef:
    table: str
    column: str
    role: str
    aggregation: Optional[str] = None  # sum, avg, count, distinct_count, min, max, ...
    is_measure: bool = False
    expression: Optional[str] = None  # source calc text for measures, carried for humans


@dataclass(frozen=True)
class FilterSpec:
    table: str
    column: str
    operator: str  # in, not_in, eq, gt, gte, lt, lte, between, top_n, relative_date, ...
    values: Tuple = ()


@dataclass(frozen=True)
class GridLayout:
    col: int
    row: int
    width: int
    height: int


@dataclass(frozen=True)
class VisualSpec:
    id: str
    type: str  # neutral type, see mapping.NEUTRAL
    source_type: str
    title: str
    layout: GridLayout
    fields: Tuple[FieldRef, ...] = ()
    filters: Tuple[FilterSpec, ...] = ()
    flags: Tuple[str, ...] = ()  # e.g. conditional_formatting


@dataclass(frozen=True)
class PageSpec:
    id: str
    name: str
    visuals: Tuple[VisualSpec, ...] = ()


@dataclass(frozen=True)
class DashboardSpec:
    id: str
    name: str
    workspace: str
    dataset_id: str
    owner: str
    views_90d: int
    pages: Tuple[PageSpec, ...] = ()

    @property
    def visuals(self) -> List[VisualSpec]:
        return [v for p in self.pages for v in p.visuals]

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)
