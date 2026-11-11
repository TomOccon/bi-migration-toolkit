"""Markdown migration readiness report."""

from __future__ import annotations

from collections import Counter
from typing import List

from .inventory import Inventory
from .mapping import map_visual
from .spec import DashboardSpec
from .triage import Triage

WAVE_LABELS = {
    1: "Wave 1: auto",
    2: "Wave 2: assisted, high fidelity",
    3: "Wave 3: assisted, lower fidelity",
    4: "Wave 4: manual",
}


def _pct(n: int, d: int) -> str:
    return f"{(100.0 * n / d):.0f}%" if d else "0%"


def build_report(
    inv: Inventory,
    specs: List[DashboardSpec],
    rows: List[Triage],
    team_size: int = 4,
    hours_per_day: float = 6.0,
) -> str:
    total = len(rows)
    live = [r for r in rows if not r.retire_candidate]
    tiers = Counter(r.tier for r in rows)
    st = inv.stats()
    hours = sum(r.effort_minutes for r in rows) / 60.0
    days = hours / (team_size * hours_per_day) if team_size else 0.0

    lines = [
        "# Migration readiness report",
        "",
        f"Inventory: {st['workspaces']} workspaces, {st['reports']} reports, "
        f"{st['pages']} pages, {st['visuals']} visuals, {st['datasets']} datasets.",
        "",
        "## Summary",
        "",
        "| Tier | Dashboards | Share |",
        "|---|---:|---:|",
    ]
    for t in ("auto", "assisted", "manual"):
        lines.append(f"| {t} | {tiers.get(t, 0)} | {_pct(tiers.get(t, 0), total)} |")
    lines += [
        "",
        f"Retire candidates (zero views in 90 days): {sum(r.retire_candidate for r in rows)} "
        "(excluded from effort).",
        "",
        f"Estimated effort: {hours:.1f} hours for {len(live)} dashboards. "
        f"With {team_size} people at {hours_per_day:g} productive hours per day that is "
        f"{days:.1f} working days.",
        "",
        "## Waves",
        "",
        "| Wave | Dashboards | Effort (h) | Cumulative (h) |",
        "|---|---:|---:|---:|",
    ]
    cum = 0.0
    for w in (1, 2, 3, 4):
        grp = [r for r in rows if r.wave == w]
        h = sum(r.effort_minutes for r in grp) / 60.0
        cum += h
        lines.append(f"| {WAVE_LABELS[w]} | {len(grp)} | {h:.1f} | {cum:.1f} |")

    unsupported = Counter()
    degraded = Counter()
    for s in specs:
        for v in s.visuals:
            res = map_visual(v)
            if not res.supported:
                unsupported[v.source_type] += 1
            elif res.fidelity < 0.85:
                degraded[v.source_type] += 1
    lines += ["", "## Unsupported visual types", ""]
    if unsupported:
        lines += ["| Source type | Count |", "|---|---:|"]
        lines += [f"| {k} | {n} |" for k, n in sorted(unsupported.items(), key=lambda kv: (-kv[1], kv[0]))]
    else:
        lines.append("None.")
    lines += ["", "## Degraded visual types (fidelity below 0.85)", ""]
    if degraded:
        lines += ["| Source type | Count |", "|---|---:|"]
        lines += [f"| {k} | {n} |" for k, n in sorted(degraded.items(), key=lambda kv: (-kv[1], kv[0]))]
    else:
        lines.append("None.")

    manual = [r for r in rows if r.tier == "manual" and not r.retire_candidate][:10]
    lines += ["", "## Top manual-tier dashboards by usage", ""]
    if manual:
        lines += ["| Dashboard | Views (90d) | Score | Unsupported | Effort (min) |", "|---|---:|---:|---:|---:|"]
        lines += [f"| {r.name} | {r.views_90d} | {r.score:.2f} | {r.unsupported} | {r.effort_minutes} |" for r in manual]
    else:
        lines.append("None.")

    if inv.warnings:
        lines += ["", "## Inventory warnings", ""] + [f"- {w}" for w in inv.warnings]
    lines.append("")
    return "\n".join(lines)
