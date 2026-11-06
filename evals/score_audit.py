#!/usr/bin/env python3
"""Score a scan, or an agent's written report, against the blind fixture's answer key. Free: no model runs.

    score_audit.py                  score the scanner
    score_audit.py --report FILE    score a report: a defect counts as located if the report names its file and a line within reach

"Located" means pointed at the right place. It doesn't mean understood. A person should read the report too.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "blind-audit"
SCRIPTS = Path(__file__).resolve().parents[1] / "plugin" / "skills" / "occam" / "scripts"
REACH = 3


def scanner_findings() -> list[dict]:
    sys.path.insert(0, str(SCRIPTS))
    from occam_tools import scan
    return scan.run_scan(FIXTURE / "repo", use_cache=False).findings


def score_scan(findings: list[dict], minimum: tuple[str, ...]) -> dict:
    kept = [f for f in findings if f["confidence"] in minimum]

    def near(item: dict, reach: int) -> bool:
        return any(f["path"] == item["file"] and abs(f["line"] - (item.get("line") or 0)) <= reach for f in kept)

    return _tally(near, len(kept))


def score_report(text: str) -> dict:
    mentions = [(m.group(1), int(m.group(2))) for m in re.finditer(r"([\w./-]+\.\w+)(?:#cell\d+)?:(\d+)", text)]

    def near(item: dict, reach: int) -> bool:
        return any(item["file"].endswith(path) and abs(line - (item.get("line") or 0)) <= reach for path, line in mentions)

    return _tally(near, len(mentions))


def _tally(near, count: int) -> dict:
    answers = json.loads((FIXTURE / "ANSWERS.json").read_text())
    decoys = json.loads((FIXTURE / "DECOYS.json").read_text())
    static = [a for a in answers if a["detectable_statically"]]
    semantic = [a for a in answers if not a["detectable_statically"]]
    severity = Counter(a["severity"] for a in answers)
    located = Counter(a["severity"] for a in answers if near(a, REACH))
    return {"findings": count, "located": sum(near(a, REACH) for a in answers), "defects": len(answers),
            "static": f"{sum(near(a, REACH) for a in static)}/{len(static)}", "semantic": f"{sum(near(a, REACH) for a in semantic)}/{len(semantic)}",
            "by_severity": {key: f"{located[key]}/{severity[key]}" for key in ("critical", "high", "medium", "low")},
            "decoys_flagged": f"{sum(near(d, 1) for d in decoys)}/{len(decoys)}"}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    if args.report:
        print(json.dumps(score_report(args.report.read_text()), indent=2))
        return
    findings = scanner_findings()
    for label, minimum in (("high confidence", ("high",)), ("medium and up, the default", ("high", "medium")), ("everything", ("high", "medium", "low"))):
        print(label, json.dumps(score_scan(findings, minimum)))


if __name__ == "__main__":
    main()
