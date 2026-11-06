"""Generate sample input: python tools/gen_sample.py OUTPUT COUNT"""

import json
import random
import sys


def main(path, count):
    rng = random.Random(7)
    recent = []
    with open(path, "w", encoding="utf-8") as handle:
        for n in range(count):
            if recent and rng.random() < 0.15:
                record = rng.choice(recent)
            else:
                record = {
                    "event_id": f"evt-{n:012d}-{rng.getrandbits(32):08x}",
                    "ts": rng.randrange(1_700_000_000, 1_700_086_400),
                    "source": rng.choice(["api", "web", "cron", "worker"]),
                    "user": f"u{rng.randrange(100000)}",
                    "path": f"/v1/items/{rng.randrange(10000)}",
                }
                recent.append(record)
                recent = recent[-1000:]
            handle.write(json.dumps(record) + "\n")


if __name__ == "__main__":
    main(sys.argv[1], int(sys.argv[2]))
