#!/usr/bin/env python3
"""Generate synthetic instances (default: every preset into data/generated/).

Examples::

    python scripts/generate_synthetic_instance.py                    # all presets
    python scripts/generate_synthetic_instance.py --preset small --seed 7 --name small_seed7
"""

import sys

import _bootstrap  # noqa: F401

from railway_rostering.cli import main

if __name__ == "__main__":
    argv = sys.argv[1:]
    if "--preset" not in argv and not any(a in argv for a in ("-h", "--help")):
        argv = ["--preset", "all"] + argv
    sys.exit(main(["generate"] + argv))
