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


def score_report(text: str, answers: list[dict] | None = None, decoys: list[dict] | None = None) -> dict:
    """Each mention locates at most one defect, the nearest in severity order, so one `file:line` beside several defects isn't credit
    for all of them. A bare file name counts only where one file in the key has it, so `app.py:10` doesn't find `other/app.py`."""
    answers = answers if answers is not None else json.loads((FIXTURE / "ANSWERS.json").read_text())
    decoys = decoys if decoys is not None else json.loads((FIXTURE / "DECOYS.json").read_text())
    mentions = [(m.group(1), int(m.group(2))) for m in re.finditer(r"([\w./-]+\.\w+)(?:#cell\d+)?:(\d+)", text)]
    files = {item["file"] for item in answers + decoys}

    def names(file: str, path: str) -> bool:
        return file == path or (file.endswith("/" + path) and sum(other == path or other.endswith("/" + path) for other in files) == 1)

    credited = _one_each(answers, mentions, names)

    def near(item: dict, reach: int) -> bool:
        if reach == REACH and any(item is answer for answer in answers):
            return id(item) in credited
        return any(names(item["file"], path) and abs(line - (item.get("line") or 0)) <= reach for path, line in mentions)

    return _tally(near, len(mentions), answers, decoys)


def _one_each(answers: list[dict], mentions: list[tuple[str, int]], names) -> set[int]:
    """Which answers a mention locates, each mention used once, the nearest to the most severe answers first."""
    used, credited = set(), set()
    for item in sorted(answers, key=lambda a: ("critical", "high", "medium", "low").index(a["severity"])):
        options = [(abs(line - (item.get("line") or 0)), index) for index, (path, line) in enumerate(mentions)
                   if index not in used and names(item["file"], path) and abs(line - (item.get("line") or 0)) <= REACH]
        if options:
            used.add(min(options)[1])
            credited.add(id(item))
    return credited


def _tally(near, count: int, answers: list[dict] | None = None, decoys: list[dict] | None = None) -> dict:
    answers = answers if answers is not None else json.loads((FIXTURE / "ANSWERS.json").read_text())
    decoys = decoys if decoys is not None else json.loads((FIXTURE / "DECOYS.json").read_text())
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
