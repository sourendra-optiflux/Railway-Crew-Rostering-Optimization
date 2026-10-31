#!/usr/bin/env python3
"""Write the blank Excel template for loading real data (one sheet per OptiFlux DB table).

Examples::

    python scripts/make_excel_template.py                                   # real_data/optiflux_db_template.xlsx
    python scripts/make_excel_template.py --from-dir data/sample/briefing_abc --output real_data/example_filled.xlsx
"""

import argparse

import _bootstrap  # noqa: F401

from railway_rostering.db_schema import read_tables, write_excel_template

if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--output", default="real_data/optiflux_db_template.xlsx")
    p.add_argument("--from-dir", help="fill the sheets from a directory of table CSVs (default: blank)")
    args = p.parse_args()
    tables = read_tables(args.from_dir) if args.from_dir else None
    print(f"wrote {write_excel_template(args.output, tables)}")
