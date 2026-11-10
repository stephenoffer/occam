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
from command_reach import runs_tests
from occam_commands import narrowed_run
import scale_notes
import scan_notes
import unfinished
from classify import ASKS_FOR_REVIEW, DEPENDENCY_MANIFEST, HIGH_CONSEQUENCE, MONEY, REVIEWER, SECURITY_CRITICAL
from session_state import Session, record
from shell_writes import absolute_path, project_root

# In paid runs the reply to a send-back replaced a good report with a few lines answering the note, which the reader never saw.
WHOLE_REPORT = ("Do anything this asks for first, with no report until it's done. If nothing needs doing, your next message is the report. That message is the "
                "one the reader sees last, and it may be the only one. So write the whole report again, with this taken into account, in plain sentences: "
                "the outcome first, then what changed, anything in the request that turned out wrong, which checks passed, failed or didn't run, and what "
                "wasn't checked. If part of this note doesn't apply, just report what's true, without discussing the note.")


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


CLAIMS_TESTS = re.compile(r"\b(tests?|suites?|specs?)\b|\b\d+\s+passed\b", re.I)
# "All 7 tests", "the full suite": the word beside the tests, not "updated every call site and the tests pass".
CLAIMS_ALL = re.compile(r"\b(?:all|every|full|entire|whole)\b(?:\s+\S+){0,3}?\s+(?:tests?|test suites?|suites?|specs?)\b", re.I)
def _steps(check: dict) -> list[list[str]]:
    return [piece.split() for text, _ in check.get("runs") or [] for piece in text.split(" && ")]


def _line_of(message: str, claim: re.Match) -> str:
    return message[message.rfind("\n", 0, claim.start()) + 1:(message.find("\n", claim.end()) + 1 or len(message) + 1) - 1]


def claims_a_pass_without_one(turn: Turn) -> str | None:
    """A claim needs a pass of its kind: "tests pass" a test run, not a build or a linter, and "all tests pass" a run that wasn't filtered."""
    first = evidence.CLAIMS_PASSING.search(turn.message)
    if not first or evidence.NEGATED_CLAIM.search(turn.message[max(0, first.start() - 60):first.end()]):
        return None
    passed = [e for e in turn.session.turn if e.get("kind") == "check" and e.get("passed") and not e.get("not_this_code")]
    if not passed:  # as before 2026-11-10: three review rounds showed exemptions for honest wording let false claims through
        return "The message reports passing checks, but no check passed during this turn."
    return _wrong_kind_of_pass(turn.message, passed)


def _wrong_kind_of_pass(message: str, passed: list[dict]) -> str | None:
    """A claim beside a pass of another kind. One on a line reporting a standing failure, "5 passed, 1 failed", is a report, not a claim."""
    claims = [claim for claim in evidence.CLAIMS_PASSING.finditer(message)
              if not evidence.NEGATED_CLAIM.search(message[max(0, claim.start() - 60):claim.end()]) and not evidence.reports_a_failure(_line_of(message, claim))]
    about_tests = [claim for claim in claims if CLAIMS_TESTS.search(claim.group(0))]
    # A test runner by name, or output that counted tests, as `make check` running pytest does.
    test_runs = [words for check in passed for words in _steps(check) if runs_tests(words) or check.get("counted")]
    if about_tests and not test_runs and all(check.get("runs") for check in passed):
        return "The message reports passing tests, but what passed this turn was a build, linter or type check, not a test run."
    # Only what leads up to the claim says whether it's about part: "all 7 tests pass (3 unit tests...)" claims them all.
    claimed = [(message[message.rfind("\n", 0, claim.start()) + 1:claim.end()], evidence.claim_subject(message, claim)) for claim in about_tests]
    if test_runs and any(CLAIMS_ALL.search(text) and not evidence.SCOPED_CLAIM.search(subject) for text, subject in claimed) and all(map(narrowed_run, test_runs)):
        return "The message reports all tests passing, but every test run that passed this turn was filtered to part of the suite."
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


# Checks that ride along with a send-back something else causes (RIDERS), and one the person alone is told at the end of a turn (FOR_THE_PERSON).
_SECURE_CLAIM = re.compile(r"\b(?:is|are|now|fully|properly)\s+(?:secure|safe|hardened)\b|\bproduction[- ]ready\b", re.I)
_DONE_CLAIM = re.compile(r"\b(?:done|complete[ds]?|finished|all set|ready to (?:merge|ship))\b", re.I)
_NEGATED = re.compile(r"(?:\bnot|n['\u2019]t|\bnever|\bno longer|\bwithout|\bunverified|\bunchecked)\b[^.\n]{0,40}$", re.I)
_SECURITY_CHECK = re.compile(r"\boccam(?:\.py)?\s+(?:scan|gate)\b|\b(?:semgrep|bandit|codeql|gosec|brakeman|zap-|trivy)\b", re.I)
_CONCURRENT_SOURCE = re.compile(r"\.(?:go|c|cc|cpp|cxx|h|hpp)$")
_CONCURRENCY = re.compile(r"\bgo\s+func\b|\bsync\.|\bchan\s|std::(?:thread|mutex|atomic|async)|\bpthread_|#pragma\s+omp")
_RACE_CHECK = re.compile(r"\brace\b|-fsanitize=thread|\btsan\b", re.I)


def _claims(pattern: re.Pattern, message: str) -> bool:
    """Said outright, not "isn't production ready" or "not yet done"."""
    return any(not _NEGATED.search(message[max(0, match.start() - 60):match.start()]) for match in pattern.finditer(message))


def _ran(turn: Turn, pattern: re.Pattern) -> bool:
    return any(pattern.search(run[0]) for entry in turn.session.after_last_edit("check") for run in entry.get("runs") or [])


def security_claim_unchecked(turn: Turn) -> str | None:
    reviewed = any(e.get("name") == REVIEWER for e in turn.session.after_last_edit("agent_done"))
    if _claims(_SECURE_CLAIM, turn.message) and not reviewed and not _ran(turn, _SECURITY_CHECK):
        return "The report calls this secure, safe or production ready, and no scan or review ran after the last edit. Back that with one, or drop it."
    return None


def done_with_goal_unverified(turn: Turn) -> str | None:
    if not _claims(_DONE_CLAIM, turn.message):  # before opening the goal store, which waits on its lock
        return None
    goal = scale_notes.recorded_goal(turn.event.get("cwd"))
    started = min((e.get("at") or 0 for e in turn.session.entries if e.get("kind") == "prompt"), default=0)
    if not goal or (goal.get("created") or 0) < started:
        return None  # a goal from before this session may belong to other work
    open_items = [r for r in goal.get("requirements", []) if r.get("status") != "verified"]
    if open_items:
        return (f"The report says it's done, and {len(open_items)} of {len(goal['requirements'])} recorded goal requirements aren't verified. "
                "`occam goal verify` shows which. Verify them, or report them as open.")
    return None


def _shown(command: object) -> str:
    """A command as a report would name it: without the settings in front, as in `PORT=3000 npm run dev`."""
    words = str(command or "").split()
    while words and re.match(r"^[A-Za-z_]\w*=", words[0]):
        words = words[1:]
    return " ".join(words)[:80]


def left_running(turn: Turn) -> str | None:
    running = [_shown(task.get("command") or task.get("description")) for task in turn.event.get("background_tasks") or [] if task.get("type") == "shell"]
    unmentioned = [command for command in running if command and command not in turn.message]
    if unmentioned:
        return f"Still running in the background: {'; '.join(unmentioned[:3])}. Stop it if this work started it and nothing needs it, or say in the report that it's running."
    return None


def race_detector_not_run(turn: Turn) -> str | None:
    changed = [path for path, _ in _on_disk(turn.event, sorted(turn.files)) if _CONCURRENT_SOURCE.search(str(path))]
    concurrent = [path for path in changed if _CONCURRENCY.search(scan_notes._read(path) or "")]
    if concurrent and not _ran(turn, _RACE_CHECK):
        return (f"{os.path.basename(str(concurrent[0]))} has goroutines or threads, and no race detector ran this turn (`go test -race`, `-fsanitize=thread`), "
                "so its tests passing doesn't show it's free of races. Run it, or say in the report that it didn't run.")
    return None


_LISTED = re.compile(r"^[ \t]*(?:\d{1,2}[.)]|[-*\u2022])[ \t]+(.+)$", re.M)
_STEPS = re.compile(r"\b(?:repro\w*|steps to|expected|actual(?:ly)? (?:get|see|happens)|observe)\b", re.I)
_WORD = re.compile(r"[a-z][a-z0-9_-]{4,}")
_COMMON = {"about", "after", "again", "should", "would", "could", "every", "there", "their", "these", "those", "which", "where", "while", "make", "sure",
           "using", "check", "update", "change", "please", "thing", "things", "other", "first", "second", "third", "really", "still", "being"}


def listed_item_left_out(turn: Turn) -> str | None:
    """A request listing several things, and a report naming none of one item's words. Pasted text isn't the request."""
    request = scale_notes.asked_for(turn.session.prompt)
    items = _LISTED.findall(request)
    if not 3 <= len(items) <= 12 or _STEPS.search(request):  # numbered steps to reproduce aren't things to do
        return None
    said = turn.message.lower()
    words = [{word[:5] for word in _WORD.findall(item.lower()) if word not in _COMMON} for item in items]
    for number, item in enumerate(items, 1):
        own = words[number - 1] - set().union(*(other for index, other in enumerate(words, 1) if index != number))  # what tells this item from the rest
        if own and not any(stem in said for stem in own):
            return f"The request listed {len(items)} things, and the report doesn't mention item {number} (\"{item.strip()[:80]}\"). Check whether it was done."
    return None


# The owner chose these to ride along with a send-back that something else causes, so they never cost a turn of their own.
RIDERS = (security_claim_unchecked, done_with_goal_unverified, left_running, race_detector_not_run)
FOR_THE_PERSON = (listed_item_left_out,)


def _safely(check, turn: Turn) -> str | None:
    """A rider that fails says nothing, rather than losing the send-back it rides on."""
    try:
        return check(turn)
    except Exception:  # occam: ignore[swallowed-exception] the send-back matters more than a rider
        return None


def for_the_person(event: dict, session: Session) -> str | None:
    """Facts the person should have after a turn that changed code, shown to them alone."""
    edits = session.code_edits()
    if not edits:
        return None
    turn = Turn(event, session, event.get("last_assistant_message") or "", edits, {e.get("path") for e in edits if e.get("path")})
    said = [text for text in (_safely(check, turn) for check in FOR_THE_PERSON) if text]
    return "occam: " + " ".join(said) if said else None


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
    missing += scale_notes.not_yet_said([text for text in map(lambda rider: _safely(rider, turn), RIDERS) if text], session.turn)
    # Never the only reason to continue. In saved runs it was the commonest send-back, 16 of 20 led to nothing but reading, and 14 of 73 runs had no other reason.
    if len(files) >= 2 and not session.after_last_edit("diff"):
        missing.append(f"This changed several files, and the final diff hasn't been inspected against the request. `{scale_notes.TOOL} gate` also lists blockers, dead code and weakened tests in it.")
    record(event, kind="sent_back", said=missing)
    return "occam: " + " ".join(missing) + " " + WHOLE_REPORT
