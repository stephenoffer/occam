"""Skill routing: which module of the core skill turns on for what a request, an edit or a check shows. (Switching accounts, projects
or clusters is something else, in repo_notes.py.)

The core skill stays lean and lists every switch. Text in context is paid again on every later model call, and agents load the
core on their first call, so a module stated when it applies is paid only from then on, and only by work it applies to. A
pointer alone got a reference opened in 1 of 15 recorded runs (in_place.py), so the module's text itself goes in, once per
session or since the last compaction. An agent that reads the module's file has heard it.

The request arms its switches when it arrives, and they're stated when the core loads. Edits and checks turn on the rest as
they happen. The modules are part of the core, so a session that never loads it hears none of them, as before they moved out.

The references, language skills, the audit and docs skills and the reviewer agent have switches of their own, where they've
always been in occam_hook.py and stop_checks.py. The core's list names them all.
"""

from __future__ import annotations  # the stock macOS python3 is 3.9

import re
from pathlib import Path

import scale_notes

REFERENCES = Path(__file__).resolve().parents[1] / "skills" / "occam" / "references"

# Why each module turns on, as the note says it. The order is the order they're stated in when several turn on at once.
MODULES = {
    "bugs": "this request reports a defect, or a check failed after an edit",
    "new-code": "this work adds something new",
    "findings": "something outside the request has turned up",
    "done": "a check has run on work beyond a small change, so the report is near",
    "critique": "the diff is ready for a skeptical read",
}

# Wording, so best effort. A wrong switch costs one module's text, about 1,000 characters, and a miss leaves the core's list.
BUG_PROMPT = re.compile(
    r"\b(bugs?|buggy|broken|breaks|regress(ion|ions|ed)|crash\w*|fails?|failing|failures?|errors?|exceptions?|traceback|stack ?trace"
    r"|incorrect|wrong|doesn'?t work|isn'?t working|not working|off[- ]by[- ]one|flaky|hangs?|leaks?|segfaults?|mismatch\w*)\b", re.I)
BUILD_PROMPT = re.compile(
    r"\b(add|adding|implement\w*|build|create|introduce|extend|port|support for|scaffold|new (feature|endpoint|command|option|flag|module|service"
    r"|api|page|screen|table|field|column|class|function|script|tool|integration))\b", re.I)
# Whitespace inside a line only: `\s` crossing newlines made lines of bare modifiers quadratic (a fresh review, 2026-11-08).
_DEFINES = re.compile(r"(?m)^[ \t]*(?:export[ \t]+|pub(?:\([\w ]+\))?[ \t]+|public[ \t]+|private[ \t]+|static[ \t]+)*(?:async[ \t]+)?"
                      r"(?:def|class|function|func|fn|interface|struct|enum|trait|impl|type|module|object)[ \t]+([A-Za-z_][\w]*)")
_IMPORTS = re.compile(r"(?m)^[ \t]*(?:import[ \t]+[\w.{*]|from[ \t]+[\w.]+[ \t]+import\b|#include[ \t]*[<\"]|use[ \t]+[\w:]+|(?:const|let|var)[ \t]+\w+[ \t]*=[ \t]*require\()"
                      r"[^\n]*$")


# Asking for a review or a plan, not naming one: "review comments on PR #42", "the audit log" and "pricing plans" aren't requests for either.
_NOT_A_MODE = r"(?!\s+(?:role|user|mode|access|token|permission|flag|field)s?\b)"
_ASKING = r"(?:^|[.!?\n]\s*)(?:(?:please|can you|could you|would you|kindly|now)\s+)*"
REVIEW = re.compile(rf"{_ASKING}(?:review|audit|critique)\b|\bcode[- ]review\b|\b(?:review|audit)[- ]only\b{_NOT_A_MODE}"
                    r"|\b(?:review|audit|look over|go over)\s+(?:this|the|my|our|these|that|his|her|their)\s+(?:diff|pr|pull request|change|changes|code|commit|branch|module|file|patch|implementation|work)\b"
                    r"|\bdo (?:a|an|another) (?:quick |full |code )?(?:review|audit)\b", re.I)
PLAN = re.compile(rf"{_ASKING}plan\b|\bplan(?:ning)?[- ]only\b{_NOT_A_MODE}|\b(?:make|write|draft|propose|sketch|give me|come up with)\s+(?:a |an )?plan\b"
                  r"|\bhow would (?:you|we)\b", re.I)
PLAN_ONLY = re.compile(rf"\bplan(?:ning)?[- ]only\b{_NOT_A_MODE}", re.I)


def prompt_switches(words: str, read_only: bool, asks_for_work: bool) -> list[str]:
    """The modules a request arms. A review of code, by its wording and not asking for work itself, hears what to do with findings,
    how to read a diff, and the razor's tests of what should exist. A plan hears those tests only, since it has no diff yet, and a
    diagnosis hears neither. `asks_for_work` is a request to build or change something, so "open a pull request" isn't a review.
    `read_only` is a review-only or plan-only turn, which builds nothing whatever its wording."""
    names = ["bugs"] if BUG_PROMPT.search(words) else []
    review = bool(REVIEW.search(words)) and not asks_for_work and not PLAN_ONLY.search(words)
    plan = bool(PLAN.search(words)) and not asks_for_work
    if review or plan or (not read_only and BUILD_PROMPT.search(words)):
        names.append("new-code")
    if review:
        names += ["findings", "critique"]
    return names


def adds_something(created: bool, manifest: bool, old: str, new: str) -> bool:
    """A new file, a dependency, or a definition or import the old text didn't have. Bounded, like the other patterns on edit text."""
    if created or manifest:
        return True
    if len(old) + len(new) > scale_notes.CONSEQUENCE_CHARS:
        return True
    names = set(_DEFINES.findall(new)) - set(_DEFINES.findall(old))
    imports = {line.strip() for line in _IMPORTS.findall(new)} - {line.strip() for line in _IMPORTS.findall(old)}
    return bool(names or imports)


def tests_only(turn: list[dict], test_path: re.Pattern) -> bool:
    """Every code edit this turn is to a test, so a failing check is more likely a test written to fail first than a bug."""
    edits = [entry for entry in turn if entry.get("kind") == "edit" and entry.get("code")]
    return bool(edits) and all(test_path.search(entry.get("path") or "") for entry in edits)


def beyond_small(prompt_entry: dict, turn: list[dict]) -> bool:
    """This turn's code edits are past what the small path allows: one edit too big to size as small, too many edits or files, or a
    request that named something consequential. Earlier turns don't count: their work is over."""
    edits = [entry for entry in turn if entry.get("kind") == "edit" and entry.get("code")]
    return bool(edits) and (any(entry.get("big") for entry in edits) or not scale_notes.stays_small([prompt_entry, *turn], []))


def heard(entries: list[dict], name: str) -> bool:
    """Stated or read since the session began or was last compacted, which drops what was said before it."""
    start = max((i for i, entry in enumerate(entries) if entry.get("kind") == "compacted"), default=-1)
    return any(entry.get("name") in (name, f"module-{name}") and entry.get("kind") in ("mentioned", "reference") for entry in entries[start + 1:])


def armed(turn: list[dict], entries: list[dict]) -> list[str]:
    """Modules this turn's request armed that haven't been stated yet, in MODULES order. An earlier request's work is over."""
    names = {name for entry in turn if entry.get("kind") == "armed" for name in entry.get("names", [])}
    return [name for name in MODULES if name in names and not heard(entries, name)]


def statement(name: str, why: str | None = None) -> str:
    """The module's text after its title and the line saying when it turns on, introduced by why it turned on now."""
    path = REFERENCES / f"{name}.md"
    text = path.read_text(encoding="utf-8")
    title, _, rest = text.partition("\n")
    body = rest.strip().split("\n\n", 1)[1] if "\n\n" in rest.strip() else rest.strip()
    return f"occam: {why or MODULES[name]}, so this is the core skill's \"{title.lstrip('# ').strip()}\" module, also at {path}.\n{body.strip()}\n"
