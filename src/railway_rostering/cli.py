"""Command-line interface.

Sub-commands (also exposed through the wrappers in ``scripts/``)::

    python -m railway_rostering generate  --preset small
    python -m railway_rostering solve     --instance-dir data/sample/briefing_abc --output-dir outputs/abc
    python -m railway_rostering validate  --instance-dir DIR --assignments outputs/abc/assignments.csv
    python -m railway_rostering benchmark --time-limit 60

Run any sub-command with ``-h`` for its options.
"""

from __future__ import annotations

import argparse
import csv
import json
import platform
import sys
from dataclasses import replace
from pathlib import Path

from .config import ModelConfig, SolverConfig, load_configs, model_config_from_dict
from .data_loader import DataError, load_instance, write_instance
from .reporting import console_summary, write_outputs
from .solution_validation import validate_solution
from .solve import solve_instance
from .synthetic import PRESETS, SyntheticConfig, generate_instance


def _parse_override(text: str):
    key, _, raw = text.partition("=")
    if not key or not _:
        raise argparse.ArgumentTypeError(f"--set expects key=value, got {text!r}")
    try:
        value = json.loads(raw)
    except json.JSONDecodeError:
        value = raw
    return key, value


def _configs(args) -> tuple[ModelConfig, SolverConfig]:
    if args.config:
        mcfg, scfg = load_configs(args.config)
    else:
        mcfg, scfg = ModelConfig(), SolverConfig()
    overrides = dict(args.set or [])
    if getattr(args, "positioning", False):
        overrides["positioning_enabled"] = True
    if overrides:
        mcfg = model_config_from_dict({**mcfg.to_dict(), **overrides})
    if args.time_limit is not None:
        scfg.time_limit_seconds = args.time_limit
    if args.workers is not None:
        scfg.num_workers = args.workers
    if args.seed is not None:
        scfg.random_seed = args.seed
    if getattr(args, "log", False):
        scfg.log_search_progress = True
    if getattr(args, "no_hint", False):
        scfg.use_greedy_hint = False
    return mcfg, scfg


def _add_config_args(p: argparse.ArgumentParser) -> None:
    p.add_argument("--config", help="JSON file with {'model': {...}, 'solver': {...}}")
    p.add_argument("--set", action="append", type=_parse_override, metavar="KEY=VALUE",
                   help="override a ModelConfig field, value parsed as JSON (repeatable)")  # fmt: skip
    p.add_argument("--time-limit", type=float, help="CP-SAT seconds per objective stage")
    p.add_argument("--workers", type=int, help="CP-SAT worker threads")
    p.add_argument("--seed", type=int, help="CP-SAT random seed")


def _load(args):
    return load_instance(
        args.instance_dir,
        crew_path=args.crew,
        duties_path=args.duties,
        eligibility_path=args.eligibility,
        travel_path=args.travel,
        metadata_path=args.metadata,
    )


def _add_instance_args(p: argparse.ArgumentParser) -> None:
    p.add_argument("--instance-dir", help="directory with crew.csv, duties.csv, ...")
    p.add_argument("--crew", help="crew CSV (overrides instance dir)")
    p.add_argument("--duties", help="duties CSV (overrides instance dir)")
    p.add_argument("--eligibility", help="eligibility CSV")
    p.add_argument("--travel", help="travel/positioning CSV")
    p.add_argument("--metadata", help="instance.json")


# ---------------------------------------------------------------------------


def cmd_generate(args) -> int:
    names = list(PRESETS) if args.preset == "all" else [args.preset]
    for name in names:
        cfg = replace(PRESETS[name]) if name in PRESETS else SyntheticConfig(name=name)
        for field_name in ("seed", "n_crew", "n_duties", "horizon_days"):
            val = getattr(args, field_name)
            if val is not None:
                setattr(cfg, field_name, val)
        if args.name:
            cfg.name = args.name
        inst = generate_instance(cfg)
        out = write_instance(inst, Path(args.output_root) / cfg.name)
        ch = inst.metadata["characteristics"]
        print(
            f"wrote {out}  ({ch['n_crew']} crew, {ch['n_duties']} duties, {ch['open_demand_units']} open units, "
            f"seed {cfg.seed})"
        )
    return 0


def cmd_solve(args) -> int:
    mcfg, scfg = _configs(args)
    try:
        inst = _load(args)
    except DataError as exc:
        print(exc, file=sys.stderr)
        return 2
    result = solve_instance(inst, mcfg, scfg)
    paths = write_outputs(result, args.output_dir)
    print(console_summary(result))
    print(f"Outputs written to {Path(args.output_dir).resolve()}")
    for key in ("assignments", "uncovered_duties", "summary", "validation_report"):
        print(f"  {key:18s} {paths[key]}")
    if result.solution.status == "INPUT_ERROR":
        for issue in result.input_issues:
            if issue.severity == "ERROR":
                print(f"  ERROR {issue.code}: {issue.message}", file=sys.stderr)
        return 2
    if result.validation is not None and not result.validation.passed:
        return 3
    return 0


def cmd_validate(args) -> int:
    mcfg, _ = _configs(args)
    inst = _load(args)
    with open(args.assignments, newline="") as fh:
        pairs = [(r["crew_id"], r["duty_id"]) for r in csv.DictReader(fh)]
    report = validate_solution(inst, mcfg, pairs)
    print(json.dumps(report.to_dict(), indent=2))
    return 0 if report.passed else 3


def cmd_benchmark(args) -> int:
    from .benchmark import run_benchmarks

    mcfg, scfg = _configs(args)
    rows = run_benchmarks(
        presets=args.presets,
        output_dir=Path(args.output_dir),
        time_limit=scfg.time_limit_seconds,
        workers=scfg.num_workers,
        variants=args.variants,
        mip_check_max_duties=args.mip_check_max_duties,
    )
    print(f"{len(rows)} benchmark runs written to {Path(args.output_dir).resolve()}")
    print(f"python {platform.python_version()} on {platform.platform()}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="railway_rostering", description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)

    g = sub.add_parser("generate", help="generate synthetic instance(s)")
    g.add_argument("--preset", default="small", choices=list(PRESETS) + ["all"])
    g.add_argument("--output-root", default="data/generated")
    g.add_argument("--name")
    g.add_argument("--seed", type=int)
    g.add_argument("--n-crew", type=int)
    g.add_argument("--n-duties", type=int)
    g.add_argument("--horizon-days", type=int)
    g.set_defaults(func=cmd_generate)

    s = sub.add_parser("solve", help="solve an instance and write outputs")
    _add_instance_args(s)
    _add_config_args(s)
    s.add_argument("--output-dir", default="outputs/run")
    s.add_argument("--positioning", action="store_true", help="enable positioning via travel.csv")
    s.add_argument("--log", action="store_true", help="print CP-SAT search log")
    s.add_argument("--no-hint", action="store_true", help="do not pass the greedy solution as a hint")
    s.set_defaults(func=cmd_solve)

    v = sub.add_parser("validate", help="independently validate an assignments CSV")
    _add_instance_args(v)
    _add_config_args(v)
    v.add_argument("--assignments", required=True, help="CSV with crew_id,duty_id columns")
    v.set_defaults(func=cmd_validate)

    b = sub.add_parser("benchmark", help="run the benchmark suite")
    _add_config_args(b)
    b.add_argument("--presets", nargs="+", default=["small", "medium", "tight", "large"])
    b.add_argument("--variants", nargs="+", default=["default"])
    b.add_argument("--output-dir", default="outputs/benchmarks")
    b.add_argument("--mip-check-max-duties", type=int, default=150,
                   help="run the flow-MIP cross-check on instances up to this many duties")  # fmt: skip
    b.set_defaults(func=cmd_benchmark)
    return parser


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    if getattr(args, "command", None) in ("solve", "validate") and not (
        args.instance_dir or (args.crew and args.duties)
    ):
        print("give --instance-dir or both --crew and --duties", file=sys.stderr)
        return 2
    return args.func(args)


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
