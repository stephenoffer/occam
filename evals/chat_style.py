"""How the agent talked to the person in saved runs: what a developer reads, not whether the code passed.

    python3 evals/chat_style.py evals/results/LABEL [evals/results/OTHER ...]

For each folder it reads every graded run (trace.jsonl and final_message.txt) and prints, per arm:
- labels: share of final reports with a status-stamp line such as "**Verified:** ..." or "Not run: ...", which reads as a form;
- self-talk: share of runs whose visible text talks about occam itself: occam, the skill, its hooks or its modes;
- silence: the median, across runs, of each run's longest stretch of tool calls with no text in between;
- words: the median final report length, and the median sentence length in it.
Two folders with one arm each (say a before and an after copy, both `with`) are compared as given. It reads, and never runs anything.
"""

from __future__ import annotations

import json
import re
import statistics
import sys
from pathlib import Path

LABEL_LINE = re.compile(r"^[ \t]*(?:[-*][ \t]+)?\**(?:verified|not run|not checked|unverified|blocked|failed|checks?(?: run)?)\**[ \t]*:", re.I | re.M)
SELF_TALK = re.compile(r"\boccam\b|\bthe (?:occam )?skill\b|\bthe hook\b|\bhook (?:blocked|held|flagged|asked|said|says|wants)\b"
                       r"|\b(?:small|standard|high[- ]consequence) mode\b|^(?:small|standard) (?:mode|change)\.", re.I | re.M)
FENCE = re.compile(r"```.*?```", re.S)
SENTENCE_END = re.compile(r"(?<=[.!?])\s+")


def texts_and_silence(trace: Path) -> tuple[list[str], int]:
    """Every text the person saw, in order, and the longest run of tool calls between two of them."""
    texts, streak, longest = [], 0, 0
    for line in trace.read_text(errors="replace").splitlines():
        try:
            event = json.loads(line)
        except ValueError:
            continue
        if event.get("type") != "assistant":
            continue
        for block in event["message"].get("content", []):
            if block.get("type") == "text" and block["text"].strip():
                texts.append(block["text"])
                streak = 0
            elif block.get("type") == "tool_use":
                streak += 1
                longest = max(longest, streak)
    return texts, longest


def sentence_length(report: str) -> float:
    prose = " ".join(line for line in FENCE.sub(" ", report).splitlines() if line.strip() and not line.lstrip().startswith("|"))
    lengths = [len(s.split()) for s in SENTENCE_END.split(prose) if s.strip()]
    return statistics.mean(lengths) if lengths else 0.0


def runs(folder: Path) -> list[dict]:
    found = []
    for trace in sorted(folder.rglob("graded/*/*/trace.jsonl")):
        final = trace.with_name("final_message.txt")
        if not final.exists():
            continue
        report = final.read_text(errors="replace")
        texts, silence = texts_and_silence(trace)
        found.append({"arm": re.sub(r"-\d+$", "", trace.parent.name), "case": trace.parent.parent.name, "labels": bool(LABEL_LINE.search(report)),
                      "self_talk": any(SELF_TALK.search(text) for text in texts + [report]), "silence": silence,
                      "words": len(FENCE.sub(" ", report).split()), "sentence": sentence_length(report)})
    return found


def summary(rows: list[dict]) -> str:
    def share(key):
        return f"{sum(r[key] for r in rows)}/{len(rows)}"

    def median(key):
        return statistics.median(r[key] for r in rows)
    return (f"runs {len(rows):3}  labels {share('labels'):6}  self-talk {share('self_talk'):6}  silence {median('silence'):4.1f}  "
            f"words {median('words'):5.0f}  sentence {median('sentence'):4.1f}")


def main(folders: list[str]) -> None:
    if not folders:
        raise SystemExit(__doc__)
    for folder in folders:
        rows = runs(Path(folder))
        for arm in sorted({r["arm"] for r in rows}):
            print(f"{Path(folder).name:28} {arm:8} {summary([r for r in rows if r['arm'] == arm])}")


if __name__ == "__main__":
    main(sys.argv[1:])
