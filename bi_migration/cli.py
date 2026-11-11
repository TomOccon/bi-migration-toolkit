"""Command line entry: inventory -> spec -> triage -> convert -> validate -> report."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .convert import inventory_to_specs, to_payload, validate_payload, write_payloads
from .inventory import load_inventory
from .report import build_report
from .triage import triage


def run(inventory_path, outdir, team_size: int = 4) -> dict:
    inv = load_inventory(inventory_path)
    specs = inventory_to_specs(inv)
    rows = triage(specs)
    payloads = []
    problems = []
    for s in specs:
        p = to_payload(s)
        problems += [f"{s.name}: {e}" for e in validate_payload(p, s)]
        payloads.append(p)
    out = Path(outdir)
    counts = write_payloads(payloads, out / "payloads")
    (out / "report.md").write_text(build_report(inv, specs, rows, team_size=team_size), encoding="utf-8")
    return {"counts": counts, "problems": problems, "dashboards": len(specs)}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="bi_migration")
    ap.add_argument("--inventory", default="fixtures/inventory.json")
    ap.add_argument("--out", default="out")
    ap.add_argument("--team-size", type=int, default=4)
    args = ap.parse_args(argv)
    result = run(args.inventory, args.out, args.team_size)
    print(f"dashboards: {result['dashboards']}")
    print("payloads: " + ", ".join(f"{k}={v}" for k, v in result["counts"].items()))
    print(f"validation problems: {len(result['problems'])}")
    for p in result["problems"]:
        print("  " + p)
    print(f"report: {Path(args.out) / 'report.md'}")
    return 1 if result["problems"] else 0


if __name__ == "__main__":
    sys.exit(main())
