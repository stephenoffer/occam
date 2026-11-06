import sys

from .pipeline import run


def main():
    if len(sys.argv) != 3:
        print("usage: python -m logmerge INPUT OUTPUT", file=sys.stderr)
        return 2
    run(sys.argv[1], sys.argv[2])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
