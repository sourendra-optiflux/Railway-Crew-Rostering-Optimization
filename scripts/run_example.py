#!/usr/bin/env python3
"""Solve an instance and write outputs.

Examples::

    python scripts/run_example.py                                  # briefing ABC sample
    python scripts/run_example.py --instance-dir data/generated/medium --output-dir outputs/medium
    python scripts/run_example.py --crew data/sample/v1_toy/crew.csv --duties data/sample/v1_toy/duties.csv
"""

import sys

import _bootstrap  # noqa: F401

from railway_rostering.cli import main

if __name__ == "__main__":
    argv = sys.argv[1:]
    if not any(a in argv for a in ("--instance-dir", "--crew", "-h", "--help")):
        argv = ["--instance-dir", "data/sample/briefing_abc"] + argv
    if "--output-dir" not in argv and not any(a in argv for a in ("-h", "--help")):
        argv += ["--output-dir", "outputs/example"]
    sys.exit(main(["solve"] + argv))
