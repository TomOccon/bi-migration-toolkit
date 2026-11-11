"""Generate fixtures/inventory.json: 25 synthetic reports, fully fictional.

Run: python fixtures/make_fixtures.py
Output is deterministic (seeded), so the committed JSON can be regenerated and diffed.
"""

import json
import random
from pathlib import Path

SEED = 7

DATASETS = [
    ("ds-01", "Sales Model", "Sales", ["Region", "Product", "Category", "Channel"],
     ["Revenue", "Units", "Discount"], "OrderDate",
     [("YoY Growth", "DIVIDE([Revenue] - CALCULATE([Revenue], SAMEPERIODLASTYEAR('Sales'[OrderDate])), CALCULATE([Revenue], SAMEPERIODLASTYEAR('Sales'[OrderDate])))"),
      ("Margin Pct", "DIVIDE(SUM('Sales'[Margin]), SUM('Sales'[Revenue]))")]),
    ("ds-02", "Support Model", "Tickets", ["Queue", "Priority", "Agent", "Product"],
     ["Handle Minutes", "Reopens", "Backlog"], "OpenedDate",
     [("SLA Met Pct", "DIVIDE(CALCULATE(COUNTROWS('Tickets'), 'Tickets'[SlaMet] = TRUE()), COUNTROWS('Tickets'))")]),
    ("ds-03", "People Model", "Headcount", ["Department", "Location", "Level"],
     ["FTE", "Attrition", "Salary Band"], "SnapshotDate",
     [("Attrition Rate", "DIVIDE(SUM('Headcount'[Leavers]), AVERAGE('Headcount'[FTE]))")]),
    ("ds-04", "Finance Model", "Ledger", ["Cost Center", "Account", "Entity"],
     ["Actual", "Budget", "Forecast"], "PostingDate",
     [("Variance", "[Actual] - [Budget]")]),
    ("ds-05", "Marketing Model", "Campaigns", ["Campaign", "Channel", "Segment"],
     ["Spend", "Leads", "Clicks"], "StartDate",
     [("Cost Per Lead", "DIVIDE(SUM('Campaigns'[Spend]), SUM('Campaigns'[Leads]))")]),
    ("ds-06", "Operations Model", "Shipments", ["Warehouse", "Carrier", "Lane"],
     ["Shipments", "Late Count", "Weight"], "ShipDate",
     [("On Time Pct", "1 - DIVIDE(SUM('Shipments'[Late Count]), SUM('Shipments'[Shipments]))")]),
]

WORKSPACES = [("ws-01", "Sales Analytics"), ("ws-02", "Finance"), ("ws-03", "Operations"), ("ws-04", "People and Support")]

NAMES = [
    "Regional Sales Overview", "Product Mix Explorer", "Channel Performance", "Quarterly Revenue Review",
    "Discount Impact Monitor", "Support Queue Health", "SLA Compliance", "Agent Workload", "Backlog Aging",
    "Headcount Summary", "Attrition Watch", "Org Level Mix", "Budget vs Actual", "Cost Center Detail",
    "Forecast Accuracy", "Campaign ROI", "Lead Funnel Analysis", "Segment Engagement", "Shipment Tracker",
    "Carrier Scorecard", "Warehouse Throughput", "Lane Delay Analysis", "Executive KPI Strip",
    "Customer Cohorts", "Pricing Sensitivity",
]

CLEAN = ["clusteredBarChart", "clusteredColumnChart", "lineChart", "pieChart", "donutChart", "tableEx", "card", "slicer", "textbox"]
MIXED = CLEAN + ["pivotTable", "lineClusteredColumnComboChart", "scatterChart", "map", "gauge", "multiRowCard", "treemap", "areaChart", "waterfallChart", "stackedColumnChart"]
HEAVY = MIXED + ["funnel", "decompositionTreeVisual", "keyInfluencersVisual", "WordCloud1447959067750", "qnaVisual"]

# profile per report index: 11 clean, 9 mixed, 5 heavy, interleaved deterministically
PROFILES = ["clean", "mixed", "clean", "heavy", "clean", "mixed", "clean", "mixed", "heavy",
            "clean", "mixed", "clean", "heavy", "mixed", "clean", "mixed", "clean", "heavy",
            "clean", "mixed", "clean", "mixed", "clean", "heavy", "mixed"]
POOLS = {"clean": CLEAN, "mixed": MIXED, "heavy": HEAVY}

AGGS = ["Sum", "Sum", "Sum", "Average", "Count", "Min", "Max", "DistinctCount"]


def pick_filter(rng, ds, profile):
    ops = ["In", "In", "Is", "GreaterThan", "Between", "NotIn"]
    if profile != "clean":
        ops += ["TopN", "RelativeDate"]
    op = rng.choice(ops)
    table = ds[2]
    if op in ("GreaterThan", "Between"):
        col = rng.choice(ds[4])
        vals = [rng.randint(1, 50)] if op == "GreaterThan" else [10, 100]
    elif op == "RelativeDate":
        col, vals = ds[5], [rng.choice([7, 30, 90]), "days"]
    elif op == "TopN":
        col, vals = rng.choice(ds[3]), [rng.choice([5, 10])]
    else:
        col = rng.choice(ds[3])
        vals = [f"{col} {rng.randint(1, 4)}" for _ in range(rng.randint(1, 3))]
    return {"table": table, "column": col, "operator": op, "values": vals}


def make_fields(rng, vtype, ds, profile):
    table = ds[2]
    dims, facts, measures = ds[3], ds[4], ds[6]

    def value():
        if measures and rng.random() < (0.25 if profile == "clean" else 0.4):
            m = rng.choice(measures)[0]
            return {"table": table, "column": m, "role": "value", "isMeasure": True}
        agg = rng.choice(AGGS if profile != "clean" else AGGS[:5])
        if profile != "clean" and rng.random() < 0.06:
            agg = "Median"
        return {"table": table, "column": rng.choice(facts), "role": "value", "aggregation": agg}

    def cat(role="category"):
        return {"table": table, "column": rng.choice(dims), "role": role}

    if vtype in ("textbox", "shape", "image"):
        return []
    if vtype in ("card", "kpi", "gauge"):
        return [value()]
    if vtype == "multiRowCard":
        return [value(), value(), value()]
    if vtype == "slicer":
        return [cat()]
    if vtype in ("tableEx", "pivotTable"):
        return [cat("detail") for _ in range(rng.randint(1, 3))] + [value() for _ in range(rng.randint(2, 4))]
    if vtype == "scatterChart":
        return [cat(), value(), value()]
    if vtype in ("stackedColumnChart", "stackedBarChart", "lineClusteredColumnComboChart"):
        return [cat(), cat("series"), value()]
    return [cat(), value()] + ([value()] if rng.random() < 0.2 else [])


def make_visual(rng, report_no, page_no, i, vtype, ds, profile):
    small = vtype in ("card", "kpi", "gauge", "slicer", "textbox", "shape", "image", "multiRowCard")
    cols = 4
    x = 20 + (i % cols) * 310
    y = 20 + (i // cols) * 250
    w = 290
    h = 110 if small else 230
    name = f"v{report_no:02d}{page_no}{i:02d}"
    visual = {
        "name": name,
        "type": vtype,
        "title": "" if vtype in ("shape", "image") else f"{vtype[:1].upper()}{vtype[1:]} {i + 1}",
        "layout": {"x": x, "y": y, "width": w, "height": h},
        "fields": make_fields(rng, vtype, ds, profile),
        "filters": [pick_filter(rng, ds, profile) for _ in range(rng.choice([0, 0, 1, 2]))] if not small else [],
    }
    if vtype in ("tableEx", "pivotTable") and rng.random() < (0.1 if profile == "clean" else 0.4):
        visual["formatting"] = {"conditionalFormatting": True}
    if vtype == "textbox":
        visual["title"] = "Notes"
    return visual


def build():
    rng = random.Random(SEED)
    datasets = []
    for d in DATASETS:
        cols = [{"name": c, "dataType": "string"} for c in d[3]] + \
               [{"name": c, "dataType": "double"} for c in d[4]] + [{"name": d[5], "dataType": "dateTime"}]
        datasets.append({
            "id": d[0], "name": d[1],
            "tables": [{"name": d[2], "columns": cols,
                        "measures": [{"name": n, "expression": e} for n, e in d[6]]}],
        })
    ws_reports = {w[0]: [] for w in WORKSPACES}
    for n, (name, profile) in enumerate(zip(NAMES, PROFILES), start=1):
        ds = DATASETS[(n - 1) % len(DATASETS)]
        ws = WORKSPACES[(n - 1) % len(WORKSPACES)]
        pool = POOLS[profile]
        pages = []
        for p in range(1, rng.randint(1, 4) + 1):
            count = rng.randint(3, 9)
            vtypes = [rng.choice(pool) for _ in range(count)]
            if p == 1 and "slicer" not in vtypes:
                vtypes[0] = "slicer"
            pages.append({
                "name": f"ReportSection{p}",
                "displayName": f"Page {p}",
                "visuals": [make_visual(rng, n, p, i, t, ds, profile) for i, t in enumerate(vtypes)],
            })
        views = 0 if n in (5, 11, 20) else int(rng.lognormvariate(4.5, 1.0))
        ws_reports[ws[0]].append({
            "id": f"rpt-{n:03d}", "name": name, "datasetId": ds[0],
            "owner": f"owner{(n % 7) + 1}@example.com", "viewsLast90d": views, "pages": pages,
        })
    return {
        "datasets": datasets,
        "workspaces": [{"id": w[0], "name": w[1], "reports": ws_reports[w[0]]} for w in WORKSPACES],
    }


if __name__ == "__main__":
    out = Path(__file__).with_name("inventory.json")
    out.write_text(json.dumps(build(), indent=2) + "\n", encoding="utf-8")
    print(f"wrote {out}")
