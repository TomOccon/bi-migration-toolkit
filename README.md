# bi-migration-toolkit

An automation pattern for moving BI dashboards between platforms at scale. The pattern comes from a migration of roughly 1,000 Power BI dashboards completed in about a week. This repository is a clean-room reimplementation of the approach on synthetic data. The target platform is generic: the payload is a simple card/page JSON, not any vendor's schema.

Python standard library only. Tests use pytest.

## Quickstart

```
python fixtures/make_fixtures.py      # regenerate the 25-report synthetic inventory (optional)
python -m bi_migration                # inventory -> triage -> convert -> validate -> report
cat out/report.md
pytest -q
```

`python -m bi_migration` reads `fixtures/inventory.json` and writes `out/payloads/<dashboard_id>.json` plus `out/report.md`. Run it twice: the second run reports `unchanged=25`.

## The approach

1. **Inventory** (`inventory.py`). Crawl workspaces, reports, pages, visuals, and datasets into typed objects. The input is shaped like Power BI REST output joined with a report definition export (the REST API alone does not return visuals). Structural problems fail loudly; dangling dataset references become warnings.
2. **Neutral spec** (`spec.py`, `convert.py`). Convert each report to platform-neutral dataclasses: visual type, fields, aggregations, filters, and a 12-column layout grid. Pixel positions on a 1280px canvas become grid cells. DAX measure text is carried on the field so a person can rewrite it.
3. **Map** (`mapping.py`). Two tables: source visual type to neutral type, and neutral type to target card type with a base fidelity score. Fidelity is in [0, 1]. Penalties apply for DAX measures, filter operators or aggregations the target cannot express, conditional formatting, and very wide visuals. Unsupported types (funnel, decomposition tree, key influencers, Q&A, marketplace custom visuals) map to a `placeholder` card at fidelity 0. The layout and title survive and the card is marked `manual`, so nothing silently disappears.
4. **Triage** (`triage.py`). Dashboard score is the area-weighted mean of visual fidelity.
   - auto: no unsupported visuals and score >= 0.85
   - assisted: at most 25% unsupported visuals and score >= 0.60
   - manual: everything else
   Waves: 1 auto, 2 assisted at >= 0.75, 3 assisted below that, 4 manual. Inside a wave, rank by views in the last 90 days. Zero-view dashboards are flagged as retire candidates and cost no effort.
5. **Convert** (`convert.py`). Emit the target payload. Every id is a hash of source ids (`stable_id`), never a counter or timestamp. Output is serialized with sorted keys, so reruns are byte-identical and the writer reports created / updated / unchanged.
6. **Validate** (`convert.validate_payload`). Every visual has exactly one card, ids are unique, positions stay inside the grid, and no field was dropped. The CLI exits nonzero on any problem.
7. **Report** (`report.py`). Markdown: tier counts, wave table with effort, unsupported and degraded visual types, top manual-tier dashboards by usage.

## Why a week is feasible

Migration cost is not uniform across dashboards. Most of it sits in a small tail. The pipeline does three things to exploit that:

- **Machines do the repetitive part.** Layout, titles, field bindings, simple filters, and common chart types convert mechanically. Humans only touch what the mapping table flags.
- **Triage turns an unknown into a schedule.** Scoring every visual up front tells you how many dashboards need no work beyond sampled review, how many need an hour, and which few need real design. Waves put the cheap, high-usage content first, so value lands early and the hard tail never blocks it.
- **Idempotent, validated output makes reruns cheap.** When the mapping table improves, rerun everything. Unchanged dashboards produce no diff, so review effort goes only to what moved.

The effort model is in `triage.py` as named constants: 3 minutes amortized for auto (automated checks plus sampled review), `30 + 20/degraded visual + 45/unsupported visual` minutes for assisted, `90 + 20 + 60` for manual. These are assumptions to calibrate on a pilot of 10 to 20 dashboards, not measurements. The arithmetic only reaches a one-week result when the tier mix is favorable, retire candidates are dropped, and the manual tier is either small or deferred past cutover. The report prints the numbers for your inventory so you can check that before promising a date.

## Layout

```
bi_migration/   inventory, spec, mapping, convert, triage, report, cli
fixtures/       make_fixtures.py (seeded generator) and inventory.json (25 reports)
tests/          pytest suite
```

## Limits

- Fixtures are synthetic. Real inventories have messier names, nested bookmarks, and report-level filters this sample does not model.
- Fidelity scores are heuristic. Treat them as a sorting key, not a guarantee, and spot-check converted cards against the source.
- The target payload is illustrative. Replace `convert._card` and `mapping.TARGETS` to emit a real platform's schema.
