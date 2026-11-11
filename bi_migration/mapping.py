"""Visual-type mapping: Power BI -> neutral -> generic target card types.

Two tables:

* NEUTRAL: source visual type string -> neutral type. Anything not listed is
  treated as a custom visual and becomes "custom".
* TARGETS: neutral type -> target card type plus a base fidelity score.

Fidelity is a number in [0, 1]: how much of the original visual's behaviour
the target card preserves with no human work. 0.0 means unsupported: the
converter emits a placeholder card so layout and titles survive and a person
fills in the rest.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Tuple

from .spec import VisualSpec

PLACEHOLDER = "placeholder"

NEUTRAL: Dict[str, str] = {
    "clusteredBarChart": "bar",
    "stackedBarChart": "stacked_bar",
    "clusteredColumnChart": "column",
    "stackedColumnChart": "stacked_column",
    "lineChart": "line",
    "areaChart": "area",
    "stackedAreaChart": "area",
    "lineClusteredColumnComboChart": "combo",
    "pieChart": "pie",
    "donutChart": "donut",
    "tableEx": "table",
    "pivotTable": "matrix",
    "card": "kpi",
    "kpi": "kpi",
    "multiRowCard": "multi_kpi",
    "scatterChart": "scatter",
    "map": "map",
    "filledMap": "map",
    "gauge": "gauge",
    "waterfallChart": "waterfall",
    "funnel": "funnel",
    "treemap": "treemap",
    "slicer": "slicer",
    "textbox": "text",
    "shape": "decor",
    "image": "decor",
    "decompositionTreeVisual": "decomposition_tree",
    "keyInfluencersVisual": "key_influencers",
    "qnaVisual": "qna",
}


@dataclass(frozen=True)
class Target:
    card_type: str
    fidelity: float
    note: str = ""


TARGETS: Dict[str, Target] = {
    "bar": Target("horizontal_bar", 1.0),
    "stacked_bar": Target("stacked_horizontal_bar", 1.0),
    "column": Target("vertical_bar", 1.0),
    "stacked_column": Target("stacked_vertical_bar", 1.0),
    "line": Target("line", 1.0),
    "area": Target("area", 0.95, "stacked vs overlapping area may differ"),
    "combo": Target("combo", 0.8, "secondary axis settings need review"),
    "pie": Target("pie", 1.0),
    "donut": Target("donut", 1.0),
    "table": Target("table", 0.95, "column widths and totals rows differ"),
    "matrix": Target("pivot_table", 0.8, "expand/collapse hierarchy not preserved"),
    "kpi": Target("single_value", 0.95),
    "multi_kpi": Target("single_value", 0.7, "split into one card per field"),
    "scatter": Target("scatter", 0.9),
    "map": Target("map", 0.6, "geocoding and layer options differ"),
    "gauge": Target("single_value", 0.55, "gauge rendered as a number with target"),
    "waterfall": Target("vertical_bar", 0.4, "waterfall approximated as bars"),
    "treemap": Target("treemap", 0.8),
    "slicer": Target("filter_control", 0.85, "sync across pages is manual"),
    "text": Target("text_block", 1.0),
    "decor": Target("static_image", 0.9),
    # Explicitly unsupported: placeholder card, fidelity 0.
    "funnel": Target(PLACEHOLDER, 0.0, "no funnel card in target"),
    "decomposition_tree": Target(PLACEHOLDER, 0.0, "interactive drill tree unsupported"),
    "key_influencers": Target(PLACEHOLDER, 0.0, "AI visual unsupported"),
    "qna": Target(PLACEHOLDER, 0.0, "natural language Q&A visual unsupported"),
    "custom": Target(PLACEHOLDER, 0.0, "custom marketplace visual unsupported"),
}

# Penalties applied on top of the base fidelity. Each is subtracted once per hit.
PENALTY_MEASURE = 0.10  # DAX measure must be re-authored (per measure, capped)
PENALTY_MEASURE_CAP = 0.30
PENALTY_FILTER = 0.10  # filter operator the target cannot express
PENALTY_AGG = 0.15  # aggregation the target cannot express
PENALTY_COND_FORMAT = 0.10
PENALTY_WIDE = 0.05  # more than WIDE_FIELDS fields on one visual
WIDE_FIELDS = 6

UNSUPPORTED_FILTER_OPS = frozenset({"top_n", "relative_date"})
UNSUPPORTED_AGGS = frozenset({"median", "percentile", "stddev", "variance"})


@dataclass(frozen=True)
class MappingResult:
    target_type: str
    fidelity: float
    supported: bool
    reasons: Tuple[str, ...] = ()


def neutral_type(source_type: str) -> str:
    return NEUTRAL.get(source_type, "custom")


def map_visual(visual: VisualSpec) -> MappingResult:
    """Return the target card type and fidelity score for one neutral visual."""
    target = TARGETS.get(visual.type, TARGETS["custom"])
    if target.card_type == PLACEHOLDER:
        return MappingResult(PLACEHOLDER, 0.0, False, (target.note,))

    score = target.fidelity
    reasons = [target.note] if target.note else []

    measures = [f for f in visual.fields if f.is_measure]
    if measures:
        score -= min(PENALTY_MEASURE * len(measures), PENALTY_MEASURE_CAP)
        reasons.append(f"{len(measures)} measure(s) need re-authoring")
    for f in visual.fields:
        if f.aggregation in UNSUPPORTED_AGGS:
            score -= PENALTY_AGG
            reasons.append(f"aggregation '{f.aggregation}' unsupported")
    for flt in visual.filters:
        if flt.operator in UNSUPPORTED_FILTER_OPS:
            score -= PENALTY_FILTER
            reasons.append(f"filter '{flt.operator}' unsupported")
    if "conditional_formatting" in visual.flags:
        score -= PENALTY_COND_FORMAT
        reasons.append("conditional formatting dropped")
    if len(visual.fields) > WIDE_FIELDS:
        score -= PENALTY_WIDE
        reasons.append(f"{len(visual.fields)} fields, review column order")

    score = max(0.0, round(score, 3))
    return MappingResult(target.card_type, score, True, tuple(reasons))
