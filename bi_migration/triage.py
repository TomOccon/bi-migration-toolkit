"""Classify dashboards auto / assisted / manual and rank them into waves.

Dashboard score is the area-weighted mean of visual fidelity. Tier rules:

* auto:     no unsupported visuals and score >= AUTO_MIN
* assisted: unsupported share <= ASSISTED_MAX_UNSUPPORTED and score >= ASSISTED_MIN
* manual:   everything else

Waves: 1 = auto, 2 = strong assisted, 3 = weaker assisted, 4 = manual. Inside a
wave dashboards are ranked by usage (views in the last 90 days), so the most
used content moves first. Dashboards with zero views are flagged as retire
candidates and take no effort in the estimate.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, List

from .mapping import map_visual
from .spec import DashboardSpec

AUTO_MIN = 0.85
ASSISTED_MIN = 0.60
ASSISTED_MAX_UNSUPPORTED = 0.25
STRONG_ASSISTED_MIN = 0.75
DEGRADED_BELOW = 0.85

# Effort model, minutes. These are assumptions to calibrate on your first pilot.
AUTO_MINUTES = 3  # amortized: automated checks plus sampled human review
ASSISTED_BASE, ASSISTED_PER_DEGRADED, ASSISTED_PER_UNSUPPORTED = 30, 20, 45
MANUAL_BASE, MANUAL_PER_DEGRADED, MANUAL_PER_UNSUPPORTED = 90, 20, 60


@dataclass(frozen=True)
class Triage:
    dashboard_id: str
    name: str
    workspace: str
    tier: str
    wave: int
    rank: int
    score: float
    visual_count: int
    unsupported: int
    degraded: int
    views_90d: int
    effort_minutes: int
    retire_candidate: bool


def _area(v) -> int:
    return max(1, v.layout.width * v.layout.height)


def score_dashboard(spec: DashboardSpec):
    """Return (score, visual_count, unsupported, degraded)."""
    visuals = spec.visuals
    if not visuals:
        return 1.0, 0, 0, 0
    total = sum(_area(v) for v in visuals)
    score = 0.0
    unsupported = degraded = 0
    for v in visuals:
        res = map_visual(v)
        score += res.fidelity * _area(v) / total
        if not res.supported:
            unsupported += 1
        elif res.fidelity < DEGRADED_BELOW:
            degraded += 1
    return round(score, 3), len(visuals), unsupported, degraded


def classify(score: float, visual_count: int, unsupported: int) -> str:
    if unsupported == 0 and score >= AUTO_MIN:
        return "auto"
    share = unsupported / visual_count if visual_count else 0.0
    if share <= ASSISTED_MAX_UNSUPPORTED and score >= ASSISTED_MIN:
        return "assisted"
    return "manual"


def effort_minutes(tier: str, degraded: int, unsupported: int) -> int:
    if tier == "auto":
        return AUTO_MINUTES
    if tier == "assisted":
        return ASSISTED_BASE + ASSISTED_PER_DEGRADED * degraded + ASSISTED_PER_UNSUPPORTED * unsupported
    return MANUAL_BASE + MANUAL_PER_DEGRADED * degraded + MANUAL_PER_UNSUPPORTED * unsupported


def wave_for(tier: str, score: float) -> int:
    if tier == "auto":
        return 1
    if tier == "assisted":
        return 2 if score >= STRONG_ASSISTED_MIN else 3
    return 4


def triage(specs: Iterable[DashboardSpec]) -> List[Triage]:
    rows = []
    for s in specs:
        score, n, uns, deg = score_dashboard(s)
        tier = classify(score, n, uns)
        retire = s.views_90d == 0
        rows.append(
            (
                wave_for(tier, score),
                s,
                score,
                n,
                uns,
                deg,
                tier,
                retire,
            )
        )
    rows.sort(key=lambda r: (r[0], -r[1].views_90d, r[1].name, r[1].id))
    out = []
    for i, (wave, s, score, n, uns, deg, tier, retire) in enumerate(rows, start=1):
        out.append(
            Triage(
                dashboard_id=s.id,
                name=s.name,
                workspace=s.workspace,
                tier=tier,
                wave=wave,
                rank=i,
                score=score,
                visual_count=n,
                unsupported=uns,
                degraded=deg,
                views_90d=s.views_90d,
                effort_minutes=0 if retire else effort_minutes(tier, deg, uns),
                retire_candidate=retire,
            )
        )
    return out
