import json
import subprocess
import sys
from pathlib import Path

import pytest

from bi_migration.cli import run
from bi_migration.convert import (
    inventory_to_specs,
    to_grid,
    to_payload,
    validate_payload,
    write_payloads,
)
from bi_migration.inventory import InventoryError, InvVisual, load_inventory, parse_inventory
from bi_migration.mapping import PLACEHOLDER, map_visual, neutral_type
from bi_migration.report import build_report
from bi_migration.spec import FieldRef, FilterSpec, GridLayout, VisualSpec, stable_id
from bi_migration.triage import classify, triage

ROOT = Path(__file__).resolve().parent.parent
FIXTURE = ROOT / "fixtures" / "inventory.json"


@pytest.fixture(scope="module")
def inv():
    return load_inventory(FIXTURE)


@pytest.fixture(scope="module")
def specs(inv):
    return inventory_to_specs(inv)


def vis(vtype="bar", fields=(), filters=(), flags=()):
    return VisualSpec("id1", vtype, "src", "t", GridLayout(0, 0, 4, 3), tuple(fields), tuple(filters), tuple(flags))


# inventory

def test_inventory_counts(inv):
    st = inv.stats()
    assert st["reports"] == 25
    assert st["workspaces"] == 4
    assert st["datasets"] == 6
    assert st["visuals"] > 100
    assert inv.warnings == []


def test_inventory_missing_key():
    with pytest.raises(InventoryError):
        parse_inventory({"datasets": []})


def test_inventory_duplicate_report():
    r = {"id": "r1", "datasetId": "d", "pages": []}
    doc = {"datasets": [{"id": "d"}], "workspaces": [{"id": "w", "reports": [r, r]}]}
    with pytest.raises(InventoryError):
        parse_inventory(doc)


def test_inventory_unknown_dataset_warns():
    doc = {"workspaces": [{"id": "w", "reports": [{"id": "r1", "datasetId": "nope"}]}]}
    assert len(parse_inventory(doc).warnings) == 1


# mapping

def test_neutral_unknown_is_custom():
    assert neutral_type("SomeMarketplaceVisual") == "custom"
    assert neutral_type("clusteredBarChart") == "bar"


def test_supported_visual_full_fidelity():
    r = map_visual(vis("bar"))
    assert r.supported and r.fidelity == 1.0 and r.target_type == "horizontal_bar"


def test_unsupported_is_placeholder_zero():
    r = map_visual(vis("funnel"))
    assert not r.supported and r.fidelity == 0.0 and r.target_type == PLACEHOLDER
    assert map_visual(vis("custom")).fidelity == 0.0


def test_penalties_reduce_fidelity():
    base = map_visual(vis("table")).fidelity
    m = FieldRef("t", "Margin", "value", is_measure=True)
    f = FilterSpec("t", "c", "top_n", (5,))
    worse = map_visual(vis("table", fields=[m], filters=[f], flags=["conditional_formatting"]))
    assert worse.fidelity == pytest.approx(base - 0.10 - 0.10 - 0.10)
    assert len(worse.reasons) >= 3


def test_fidelity_never_negative():
    fields = [FieldRef("t", f"m{i}", "value", is_measure=True, aggregation="median") for i in range(8)]
    assert map_visual(vis("waterfall", fields=fields)).fidelity == 0.0


# convert

def test_grid_bounds():
    v = InvVisual("n", "card", "t", x=1200, y=0, width=500, height=10)
    g = to_grid(v)
    assert g.col + g.width <= 12 and g.width >= 1 and g.height >= 1


def test_stable_id_deterministic():
    assert stable_id("a", "b") == stable_id("a", "b")
    assert stable_id("a", "b") != stable_id("ab")


def test_payload_validates_for_all_fixtures(specs):
    for s in specs:
        assert validate_payload(to_payload(s), s) == []


def test_payload_deterministic(specs):
    a = [json.dumps(to_payload(s), sort_keys=True) for s in specs]
    b = [json.dumps(to_payload(s), sort_keys=True) for s in inventory_to_specs(load_inventory(FIXTURE))]
    assert a == b
    assert len({s.id for s in specs}) == len(specs)


def test_unsupported_become_manual_placeholders(specs):
    cards = [c for s in specs for p in to_payload(s)["pages"] for c in p["cards"]]
    manual = [c for c in cards if c["status"] == "manual"]
    assert manual and all(c["card_type"] == PLACEHOLDER and c["fidelity"] == 0.0 for c in manual)


def test_measures_carry_source_expression(specs):
    cards = [c for s in specs for p in to_payload(s)["pages"] for c in p["cards"]]
    calcs = [col["calc"] for c in cards for col in c["columns"] if "calc" in col]
    assert calcs and all(c["source_expression"] for c in calcs)


def test_write_is_idempotent(specs, tmp_path):
    payloads = [to_payload(s) for s in specs]
    first = write_payloads(payloads, tmp_path)
    second = write_payloads(payloads, tmp_path)
    assert first == {"created": 25, "updated": 0, "unchanged": 0}
    assert second == {"created": 0, "updated": 0, "unchanged": 25}


def test_write_detects_change(specs, tmp_path):
    payloads = [to_payload(s) for s in specs]
    write_payloads(payloads, tmp_path)
    payloads[0]["name"] = "Renamed"
    assert write_payloads(payloads, tmp_path)["updated"] == 1


# triage

def test_classify_rules():
    assert classify(0.95, 5, 0) == "auto"
    assert classify(0.95, 5, 1) == "assisted"
    assert classify(0.70, 8, 1) == "assisted"
    assert classify(0.70, 4, 2) == "manual"
    assert classify(0.50, 4, 0) == "manual"


def test_triage_waves_and_ranking(specs):
    rows = triage(specs)
    assert len(rows) == 25
    assert [r.rank for r in rows] == list(range(1, 26))
    assert [r.wave for r in rows] == sorted(r.wave for r in rows)
    for w in (1, 2, 3, 4):
        views = [r.views_90d for r in rows if r.wave == w]
        assert views == sorted(views, reverse=True)
    assert {r.tier for r in rows} == {"auto", "assisted", "manual"}


def test_retire_candidates_take_no_effort(specs):
    rows = triage(specs)
    retired = [r for r in rows if r.retire_candidate]
    assert retired and all(r.effort_minutes == 0 for r in retired)


# report and cli

def test_report_sections(inv, specs):
    md = build_report(inv, specs, triage(specs))
    for heading in ("# Migration readiness report", "## Summary", "## Waves", "## Unsupported visual types"):
        assert heading in md
    assert "25 reports" in md


def test_cli_run_twice(tmp_path):
    r1 = run(FIXTURE, tmp_path)
    r2 = run(FIXTURE, tmp_path)
    assert r1["problems"] == [] and r1["counts"]["created"] == 25
    assert r2["counts"]["unchanged"] == 25
    assert (tmp_path / "report.md").exists()


def test_fixture_regenerates_identically():
    sys.path.insert(0, str(ROOT / "fixtures"))
    try:
        import make_fixtures
    finally:
        sys.path.pop(0)
    assert make_fixtures.build() == json.loads(FIXTURE.read_text(encoding="utf-8"))


def test_module_entrypoint(tmp_path):
    p = subprocess.run(
        [sys.executable, "-m", "bi_migration", "--inventory", str(FIXTURE), "--out", str(tmp_path)],
        cwd=ROOT, capture_output=True, text=True,
    )
    assert p.returncode == 0, p.stderr
    assert "validation problems: 0" in p.stdout
