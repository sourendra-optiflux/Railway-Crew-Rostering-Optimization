#!/usr/bin/env python3
"""Generate synthetic instances in the OptiFlux DB schema (default: every preset into data/generated/).

Each instance is a directory of the 12 database tables (roster_df.csv, activities_df.csv, ...).

Examples::

    python scripts/generate_synthetic_instance.py                    # all presets
    python scripts/generate_synthetic_instance.py --preset small --seed 7 --name small_seed7
    python scripts/generate_synthetic_instance.py --preset large --n-crew 500 --demand-scale 3 --name half
"""

import sys

import _bootstrap  # noqa: F401

from railway_rostering.cli import main

if __name__ == "__main__":
    argv = sys.argv[1:]
    if "--preset" not in argv and not any(a in argv for a in ("-h", "--help")):
        argv = ["--preset", "all"] + argv
    sys.exit(main(["generate"] + argv))
