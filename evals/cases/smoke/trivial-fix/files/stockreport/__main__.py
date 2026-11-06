import sys

from .report import render


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: python -m stockreport CSV", file=sys.stderr)
        return 2
    print(render(sys.argv[1]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
