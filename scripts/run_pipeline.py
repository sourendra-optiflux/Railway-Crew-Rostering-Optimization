#!/usr/bin/env python3
"""Run the whole gap-filling pipeline, then put every table into one Excel workbook.

    1. gap_generation/make_gaps.py            leave -> roster_full.csv with gaps (Optimised User Id empty)
    2. option_generation/generate_options.py  layer 1: legal options for every open seat
    3. CP-SAT/run_gap_filling.py              layer 2: choose options, fill Optimised User Id
    4. scripts/export_excel.py                every CSV of the run as one sheet (the CSV files stay)

The base data (data/optiflux_v2) is only read. Rebuild it first if the rules changed:
    python scripts/build_optiflux_v2_data.py && python scripts/roster_making.py

    python scripts/run_pipeline.py
    python scripts/run_pipeline.py --seed 7 --time-limit 300
    python scripts/run_pipeline.py --config config.yml
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data" / "optiflux_v2"
GAPS = ROOT / "gap_generation" / "output"
OPTIONS = ROOT / "option_generation" / "output"
SOLVED = ROOT / "CP-SAT" / "outputs" / "roster_full"
WORKBOOK = SOLVED / "optiflux_all_tables.xlsx"


def step(title: str, args: list[str]) -> None:
    print(f"\n== {title}")
    done = subprocess.run([sys.executable, *args], cwd=ROOT)
    if done.returncode:
        raise SystemExit(f"{title} failed (exit {done.returncode})")


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--seed", type=int, default=2026, help="leave seed (default %(default)s)")
    p.add_argument("--max-chain", type=int, default=2, help="max Demand moves in one chain (default %(default)s)")
    p.add_argument("--time-limit", type=float, default=120, help="CP-SAT seconds per stage (default %(default)s)")
    p.add_argument("--workers", type=int, default=8)
    p.add_argument("--config", type=Path, default=ROOT / "config.yml", help="shared YAML constraint switches")
    a = p.parse_args(argv)
    step("1. Gap generation", ["gap_generation/make_gaps.py", "--seed", str(a.seed)])
    step("2. Option generation", [
        "option_generation/generate_options.py", "--max-chain", str(a.max_chain), "--config", str(a.config.resolve())
    ])
    step("3. CP-SAT", [
        "CP-SAT/run_gap_filling.py", "--time-limit", str(a.time_limit), "--workers", str(a.workers),
        "--config", str(a.config.resolve()),
    ])

    sys.path.insert(0, str(ROOT / "scripts"))
    from export_excel import export

    print("\n== 4. Excel workbook")
    files = [f for d in (DATA, GAPS, OPTIONS, SOLVED) for f in sorted(d.glob("*.csv"))]
    labels = {DATA: "data", GAPS: "gaps", OPTIONS: "options", SOLVED: "final"}
    for name, path, n in export(files, WORKBOOK, labels):
        print(f"  {name:31s} {n:>7,} rows  <- {path.relative_to(ROOT)}")
    print(f"Wrote {WORKBOOK.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
