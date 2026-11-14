#!/usr/bin/env python3
"""Layer 2 of gap filling: CP-SAT picks from the options of layer 1 and fills `Optimised User Id`.

Run after gap_generation/make_gaps.py and option_generation/generate_options.py. See CP-SAT/README.md.

    python CP-SAT/run_gap_filling.py
    python CP-SAT/run_gap_filling.py --time-limit 120 --workers 8
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))  # option_generation
sys.path.insert(0, str(HERE))  # solver, utils

from solver import solve  # noqa: E402
from utils.load_options import load_options  # noqa: E402
from utils.output import apply, write_outputs, write_summary  # noqa: E402
from utils.validate import validate  # noqa: E402

from option_generation.data import (  # noqa: E402
    DEFAULT_CONFIG,
    DEFAULT_DATA_DIR,
    DEFAULT_ROSTER_FULL,
    load,
    read_csv,
)  # fmt: skip
from option_generation.data import DEFAULT_OUTPUT as DEFAULT_OPTIONS  # noqa: E402
from option_generation.options import Costs  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--data-dir", type=Path, default=DEFAULT_DATA_DIR)
    p.add_argument("--roster-full", type=Path, default=DEFAULT_ROSTER_FULL, help="output of gap_generation")
    p.add_argument("--config", type=Path, default=DEFAULT_CONFIG, help="YAML constraint switches (default: config.yml)")
    p.add_argument("--options-dir", type=Path, default=DEFAULT_OPTIONS, help="output of option_generation")
    p.add_argument("--output-dir", type=Path, default=HERE / "outputs" / "roster_full")
    p.add_argument("--time-limit", type=float, default=120,
                   help="seconds per objective stage (default 120)")  # fmt: skip
    p.add_argument("--workers", type=int, default=8)
    p.add_argument("--seed", type=int, default=2026)
    p.add_argument("--log", action="store_true", help="print the CP-SAT search log")
    args = p.parse_args(argv)
    out = args.output_dir
    out.mkdir(parents=True, exist_ok=True)

    data = load(args.data_dir, args.roster_full, args.config)
    seats, swings = load_options(args.options_dir, data.priority)
    frozen = {(s["User Id"], s["Swing"]) for s in read_csv(args.options_dir / "swings.csv") if s["Status"] == "frozen"}
    print(f"Seats {len(seats)}, swings in the model {len(swings)}, "
          f"options {sum(len(o) for sw in swings for o in sw.options)}")  # fmt: skip

    solved = solve(data.rules, seats, swings, Costs(), args.time_limit, args.workers, args.seed, args.log)
    if not solved.chosen:
        print(f"error: no solution ({solved.status})", file=sys.stderr)
        return 1
    result = apply(data, swings, solved.chosen, seats)
    write_outputs(out, data, result)
    validation = validate(data, args.data_dir, result["roster"], frozen, out / "validation.md")
    write_summary(out / "summary.md", data, seats, solved, result, validation, args)

    gaps = [r for r in result["roster"] if r["Is Gap"] == "True" and r["Is_locked_gap"] == "False"]
    filled = sum(bool(r["Optimised User Id"]) for r in gaps)
    print(f"Filled {filled} of {len(gaps)} open gaps; {len(result['unfilled'])} Demand rows left empty "
          f"(locked gaps included)")  # fmt: skip
    print(f"Rule check: {validation['headline']}")
    for rule, text, _, detail in validation["unexpected"]:
        print(f"  FAIL {rule} {text} [{detail}]")
    print(f"Wrote {out}")
    return 1 if validation["unexpected"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
