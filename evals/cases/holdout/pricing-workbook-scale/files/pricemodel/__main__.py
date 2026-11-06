import argparse
import json
import sys

from pricemodel.workbook import CircularReference, Workbook


def main(argv=None):
    parser = argparse.ArgumentParser(prog="pricemodel", description="Evaluate a pricing model.")
    parser.add_argument("model", help="path to a model JSON file")
    parser.add_argument("--cell", action="append", help="print only this cell (repeatable)")
    args = parser.parse_args(argv)

    with open(args.model) as handle:
        cells = json.load(handle)["cells"]

    workbook = Workbook()
    for name, value in cells.items():
        workbook.set(name, value)

    try:
        for name in args.cell or workbook.names():
            print(f"{name} = {workbook.get(name)}")
    except CircularReference as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
