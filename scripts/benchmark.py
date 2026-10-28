#!/usr/bin/env python3
"""Run the benchmark suite.

Examples::

    python scripts/benchmark.py --presets small medium --time-limit 30
    python scripts/benchmark.py --presets large --variants default relaxed --time-limit 120
"""

import sys

import _bootstrap  # noqa: F401

from railway_rostering.cli import main

if __name__ == "__main__":
    sys.exit(main(["benchmark"] + sys.argv[1:]))
