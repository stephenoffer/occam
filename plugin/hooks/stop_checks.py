"""What Stop compares: the record of this turn against the message about to reach the reader.

Each check returns what to say, or nothing. They run in this order and say each thing once per state of the code (`scale_notes.not_yet_said`).
Limits and the ways around each one are in docs/failure-modes.md.
"""

from __future__ import annotations  # the stock macOS python3 is 3.9

import os
import re
from pathlib import Path
from typing import NamedTuple

import occam_evidence as evidence
import scale_notes
import scan_notes
import unfinished
from classify import ASKS_FOR_REVIEW, DEPENDENCY_MANIFEST, HIGH_CONSEQUENCE, MONEY, REVIEWER, SECURITY_CRITICAL
from session_state import Session, record
from shell_writes import absolute_path, project_root

# In paid runs the reply to a send-back replaced a good report with a few lines answering the note, which the reader never saw.
WHOLE_REPORT = ("Do anything this asks for first, with no report until it's done. If nothing needs doing, your next message is the report. That message is the "
                "one the reader sees last, and it may be the only one, and they haven't seen this note. So write the whole "
                "report again, with this taken into account: what you found, including anything in the request that turned out wrong, what changed, what "
                "was checked with its status, and what wasn't. If part of this note doesn't apply, just report what's true, without discussing the note.")


# Superpowers replaced a review subagent with a checklist like this after measuring the same quality in far less time (v5.0.6). Unmeasured here.
SELF_REVIEW = ("read it as its reviewer would: every caller and data path it reaches, the invariants it must keep, failure, retry and partial-write paths, "
               "awkward inputs such as empty, zero, duplicate or very large, and whether a test would fail without the fix.")
# A fixed line, because reading free text either passes "self-review: not done" or rejects "no issues found in my self-review" (a fresh review found both).
SELF_REVIEW_LINE = "`Self-review:` followed by what it found"
# A label at a line's start, after a sentence, or in a table cell; then a colon, a dash or a cell border; then what it found, on that line.
_SELF_REVIEW_LINE = re.compile(r"(?:^|(?<=[.;!?])[ \t]+|\|)[ \t>*_#\-\d.)]*self[- ]review[*_]*[ \t]*(?::|\||[-\u2013\u2014](?=[ \t]))[*_]*[ \t]*([^\n|]*)", re.I | re.M)
_LEADING = re.compile(r"^[\s>*_#\-\u2013\u2014\d.)(\[\"'`]+")
_ANOTHER_LABEL = re.compile(r"^[A-Z][\w /-]{0,30}:")
_NOT_DONE = re.compile(r"^(?:(?:i|we)\s+)?(?:not\b|none\b(?!\s+(?:found|seen|spotted|left|remain))|n/?a\b|no\s*[.!]?\s*$|skip|pending|to ?do\b|still to do|deferred"
                       r"|later\b|tbd\b|unable|could ?n[o']t|can'?t|cannot|did ?n[o']t|was ?n[o']t|has ?n[o']t|have ?n[o']t|won'?t|will\b|no time|false\b"
                       r"|[\u2717\u2718\u00d7x]\s*$|$)", re.I)


def asks_for_a_review(prompt: str) -> bool:
    return bool(ASKS_FOR_REVIEW.search(scale_notes.asked_for(prompt or "")))  # not what was pasted


def needs_a_fresh_review(paths: list[str], prompt: str) -> bool:
    """A fresh reviewer for security and money, or when the request asks for one. Migrations and webhooks get a self-review of the whole diff."""
    return any(SECURITY_CRITICAL.search(path) or MONEY.search(path) for path in paths) or asks_for_a_review(prompt)


def says_it_self_reviewed(message: str) -> bool:
    for match in _SELF_REVIEW_LINE.finditer(message):
        found = _LEADING.sub("", match.group(1)).strip()
        if not found:  # a heading: its first line below is what it found, unless that's the next heading
            below = next((line for line in message[match.end():].splitlines() if line.strip()), "")
            found = "" if _ANOTHER_LABEL.match(_LEADING.sub("", below)) else _LEADING.sub("", below).strip()
        if not _NOT_DONE.match(found):
            return True
    return False


class Turn(NamedTuple):
    event: dict
    session: Session
    message: str
    edits: list
    files: set  # every path this turn's edits named


def _on_disk(event: dict, paths: list[str]) -> list[tuple[Path, str]]:
    return [(absolute_path(event, path), path) for path in paths]


def no_check_since_the_edit(turn: Turn) -> str | None:
    if [check for check in turn.session.after_last_edit("check") if not check.get("not_this_code")]:
        return None
    return ("No check has run since the last code edit. A relevant test or the real entry point would "
            f"show whether it works, and `{scale_notes.TOOL} query impact <file>` lists the tests that reach a file. If a check can't run here, the report should say so.")


def claims_a_pass_without_one(turn: Turn) -> str | None:
    claim = evidence.CLAIMS_PASSING.search(turn.message)
    if claim and not evidence.NEGATED_CLAIM.search(turn.message[max(0, claim.start() - 60):claim.end()]) \
            and not any(e.get("kind") == "check" and e.get("passed") and not e.get("not_this_code") for e in turn.session.turn):
        return "The message reports passing checks, but no check passed during this turn."
    return None


def unreviewed_high_consequence(turn: Turn) -> str | None:
    session = turn.session
    risky = sorted({e["path"] for e in turn.edits if e.get("path") and HIGH_CONSEQUENCE.search(e["path"])})
    if not risky or any(e.get("name") == REVIEWER for e in session.after_last_edit("agent_done")):
        return None
    if not needs_a_fresh_review(risky, session.prompt):
        if says_it_self_reviewed(turn.message):
            return None
        return (f"This changed {', '.join(os.path.basename(p) for p in risky[:3])}, which is high consequence, "
                f"and the message doesn't say the diff was reviewed. Before the report, review the whole diff yourself: {SELF_REVIEW} Then give the report a line starting {SELF_REVIEW_LINE}.")
    # A finished review says nothing of what it covered, so whoever briefed it decides whether a second one can cost less than the first.
    scope = ("If its earlier review finished and covered the whole diff, it needs the requirements, that review's findings and only what changed since, "
             "and should be told so. Otherwise it needs the requirements and the diff."
             if any(e.get("kind") == "agent_done" and e.get("name") == REVIEWER for e in session.turn) else "It needs the requirements and the diff.")
    return (f"This changed {', '.join(os.path.basename(p) for p in risky[:3])}, which is high consequence, "
            f"and the `occam:{REVIEWER}` agent hasn't finished a review since the last edit. {scope} "
            "If it can't run, the report should call this a self-review.")


def failure_left_out(turn: Turn) -> str | None:
    if turn.message and evidence.has_an_unsettled_failure(turn.session.after_last_edit("check")) and evidence.leaves_out_a_failure(turn.message):
        return "A check failed after the last code edit and hasn't passed since, and the message doesn't mention a failure."
    return None


def count_nothing_printed(turn: Turn) -> str | None:
    count = evidence.unmatched_test_count(turn.session.turn, turn.message)
    return f"The message reports {count} passing, but no check's output this turn contains that number." if count else None


def measured_with_no_baseline(turn: Turn) -> str | None:
    session = turn.session
    if not evidence.claims_a_measured_change(turn.message) or evidence.has_before_and_after(session.entries[:len(session.entries) - len(session.turn)], session.turn):
        return None
    return ("The message states a measured speedup or saving, but no command ran both before the first code edit and "
            "after the last one, so this session has no like-for-like before and after. If the figure came from "
            "elsewhere or is an estimate, the report should say so.")


def varying_result(turn: Turn) -> str | None:
    varying = evidence.varying_results(turn.session.turn)
    if not varying or evidence.MENTIONS_VARYING.search(turn.message):
        return None
    return (f"`{varying[0]}` both failed and passed with nothing changed between the runs, so its result varies. One "
            "green run doesn't settle that, so the report should say it is flaky or what differed.")


def left_unnamed(turn: Turn) -> str | None:
    names = evidence.names_to_report(turn.session.turn, DEPENDENCY_MANIFEST) if turn.message else set()
    for name in names:
        record(turn.event, kind="told", name=name)
    silent = sorted(name for name in names if name.lower() not in turn.message.lower())
    if not silent:
        return None
    return (f"The message doesn't name {', '.join(silent[:6])}. Reports tend to leave out most of what an agent did, "
            "and a reader needs these.")


def scanner_sees_new_findings(turn: Turn) -> str | None:
    found = [finding for path in scan_notes.within_budget(sorted(turn.files)) for finding in scan_notes.introduced(
        absolute_path(turn.event, path), path, scan_notes.known_findings(turn.event, turn.session, path))]
    if not found:
        return None
    return ("The scanner sees these in what you changed, and they weren't there before: " + scan_notes.describe(found) +
            ". Fix each one, or say in the report why it's fine.")


def scanner_still_raises(turn: Turn) -> str | None:
    return scan_notes.still_raised_note(_on_disk(turn.event, sorted(turn.files))) if turn.session.has("skill", "occam-audit") else None


CHECKS = (no_check_since_the_edit, claims_a_pass_without_one, unreviewed_high_consequence, failure_left_out, count_nothing_printed,
          measured_with_no_baseline, varying_result, left_unnamed, scanner_sees_new_findings, scanner_still_raises)


def send_back(event: dict, session: Session) -> str | None:
    """What to send the agent back with, or None to let it finish."""
    edits = session.code_edits()
    if not edits:
        return None
    files = {e.get("path") for e in edits if e.get("path")}
    turn = Turn(event, session, event.get("last_assistant_message") or "", edits, files)
    missing = [text for text in (check(turn) for check in CHECKS) if text]
    # An edit script can hide its target, so git says what changed this turn, though in a shared tree that can be someone else's work too.
    unclear = sorted(set(unfinished.changed_in_git(project_root(event), session.prompt_entry.get("at"))) - files) if any(not e.get("path") for e in edits) else []
    missing += unfinished.notes(event, session, turn.message, _on_disk(event, sorted(files)), _on_disk(event, unclear), session.turn, record)
    missing = scale_notes.not_yet_said(missing, session.turn)
    if not missing:
        return None
    # Never the only reason to continue. In saved runs it was the commonest send-back, 16 of 20 led to nothing but reading, and 14 of 73 runs had no other reason.
    if len(files) >= 2 and not session.after_last_edit("diff"):
        missing.append(f"This changed several files, and the final diff hasn't been inspected against the request. `{scale_notes.TOOL} gate` also lists blockers, dead code and weakened tests in it.")
    record(event, kind="sent_back", said=missing)
    return "occam: " + " ".join(missing) + " " + WHOLE_REPORT
