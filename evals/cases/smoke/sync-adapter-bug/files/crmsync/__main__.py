import argparse
import sys

from . import db, sync, vendor_sandbox
from .client import VendorClient, VendorError


def main(argv=None):
    parser = argparse.ArgumentParser(prog="crmsync")
    parser.add_argument("--base-url", default="https://sandbox.invalid")
    parser.add_argument("--token", default="sandbox-token")
    parser.add_argument("--sandbox", action="store_true")
    parser.add_argument("--db", required=True)
    args = parser.parse_args(argv)

    transport = vendor_sandbox.transport if args.sandbox else None
    client = VendorClient(args.base_url, args.token, transport=transport)
    connection = db.connect(args.db)
    try:
        counts = sync.sync_all(client, connection)
    except VendorError as error:
        print(f"status=failed {error}", file=sys.stderr)
        return 1
    for name, count in counts.items():
        print(f"{name}={count}")
    print("status=ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
