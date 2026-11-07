"""A short design doc that agents and people share: what's decided and why, and what's planned, with checks that cost no model tokens.

Agents obey what they read even when it's stale, so the file itself says the code wins about what exists, and these checks look for drift rather than trusting anyone to
notice it. Decisions are single appended lines, so parallel writers can't lose each other's work. Nothing here reads a whole document into a session: `for_paths` gives only
what applies to the files in hand.
"""

from __future__ import annotations

import datetime
import os
import re
from pathlib import Path
from typing import NamedTuple

from . import docs, files as filesystem

FILE_NAMES = ("DESIGN.md", "docs/DESIGN.md")
MAX_LINES = 200  # Nygard: "Large documents are never kept up to date". A judgment, untested on agents
REQUIRED = ("Problem", "Non-goals", "Current design", "Decisions")
MAX_NOTE = 240
MAX_DECISIONS_IN_A_NOTE = 3
_LONGEST_CITATION = 400  # past any real path, and it bounds what reaches the patterns below
_DECISION = re.compile(r"^- (?P<date>\d{4}-\d{2}-\d{2}) (?P<id>[a-z0-9][a-z0-9-]*) \[(?P<status>accepted|proposed)\] (?P<text>\S.*)$")
_SUPERSEDES = re.compile(r"\bSupersedes: `([a-z0-9-]+)`\.?\s*$")  # only at the end, where decide puts it, so mentioning one retires nothing
_ID = re.compile(r"[a-z0-9][a-z0-9-]*")
_SPAN = re.compile(r"`([^`\n]+)`")
_LIST_ITEM = re.compile(r"\s*(?:[-*+]|\d+[.)])\s")
_APPLIES = re.compile(r"\bApplies: (`[^`\n]+`(?:, `[^`\n]+`)*)$")
_DATE_FIRST = re.compile(r"\d{4}-\d{2}-\d{2}\b")
_LINK = re.compile(r"\]\(([^)\s]+)")
_PATH_LIKE = re.compile(r"^[\w./ @+~()\[\],=$-]+$")  # no `*`: a pattern reads differently to git and to the disk, and a folder says it
_PROVENANCE = re.compile(r"\bVerified (\d{4}-\d{2}-\d{2}) against (?:commit )?`?(\w(?:[\w./-]*\w)?)")
_UNNAMED = "<the person accountable for this file>"
_LABELS = {"Current design": "now", "Contracts": "contract", "Planned": "planned, not built"}
_OWNER = re.compile(r"^[*_]*Owner[*_]*:[*_]* *(.*)$", re.M | re.I)  # people write `**Owner:** Sam` too
_TEMPLATE = """# Design: {name}

Owner: <the person accountable for this file>. {provenance}

Where this file and the code disagree about what exists, the code is right: say so and fix this file. Accepted decisions stand until a later one supersedes them. Anyone can propose, and the owner accepts. Keep it short, with no code, schemas, task lists or tour of the repository. Cite paths from the repository root.

## Problem

<Who has what problem, why now, and how much it's worth spending on.>

## Non-goals

<Things that could reasonably be goals and aren't.>

## Success

<What you would observe or measure to know it worked.>

## Current design

<What exists now: the parts, who owns each, how data moves. Cite `paths`.>

## Planned

<What's intended and not built yet. Nothing here describes the code.>

## Contracts

<What parts built apart could choose incompatibly: shapes, names, errors, deployment order. Cite `paths`.>

## Open questions

<Each with who decides.>

## Decisions

Append only, with `occam design decide`. To change one, supersede it.
"""
_PLACEHOLDERS = {line for line in _TEMPLATE.split("\n") if line.startswith("<")} | {f"Owner: {_UNNAMED}"}
_CLAIMS = ("Current design", "Contracts")  # the sections saying what exists. Anything else can name what doesn't, and that isn't drift
_SECTIONS = (*REQUIRED, "Success", "Planned", "Contracts", "Open questions")
MAX_EVERYWHERE = 8


class Decision(NamedTuple):
    line: int
    id: str
    status: str
    text: str
    raw: str
    supersedes: str | None


class Parsed(NamedTuple):
    text: str
    prose: str           # the text with code blocks and comments blanked, so an example can't count as the document saying something
    sections: dict       # heading -> [(first line, last line), ...], 1-based. More than one is a problem, and nothing in any of them is lost
    decisions: list
    malformed: list      # lines in Decisions that start a list item and don't parse
    unclosed: bool       # a code block never closed, so the rest reads as code
    open_comment: bool   # a comment never closed, so the rest is hidden


def _present(root: Path, name: str) -> bool:
    """Exactly this name. A case-insensitive disk would also say `design.md` is here, and git wouldn't agree. A folder nobody can read holds nothing anyone can follow."""
    path = root / name
    try:
        return path.name in os.listdir(path.parent) and path.is_file()
    except OSError:
        return False


def find(root: Path) -> str | None:
    return next((name for name in FILE_NAMES if _present(root, name)), None)


def _section_key(heading: str) -> str:
    return re.sub(r"[\s-]+", " ", heading).lower()


def _section_name(heading: str) -> str:
    """So `## Non-Goals` and `## Current Design` are the sections they obviously are."""
    return next((name for name in _SECTIONS if _section_key(name) == _section_key(heading)), heading)


def _blank_comments(prose: str) -> tuple[str, bool]:
    """Comments that start a line, as Markdown renders them: whole lines, up to the one that closes it or the end of the file. Naming `<!--` mid-sentence isn't one. A line at a time, so no document can make this slow."""
    lines = prose.split("\n")
    inside = False
    for number, line in enumerate(lines):
        text = line.lstrip(" ")
        if inside or (text.startswith("<!--") and len(line) - len(text) <= 3):
            inside = "-->" not in (line if inside else text[2:])  # `<!-->` is a whole comment
            lines[number] = ""
    return "\n".join(lines), inside


def _heading(line: str) -> str:
    return line[3:].strip().rstrip("#").strip() if line.startswith("## ") else ""


def _read_decisions(lines: list[str], first: int, last: int, decisions: list, malformed: list) -> None:
    """A decision is one line. One opening paragraph can say how to use the section, and anything else there is something a reader would take for a decision, so it has to say it isn't one."""
    intro_open, intro_started = True, False
    for number in range(first + 1, last + 1):
        line = lines[number - 1]
        match = _DECISION.match(line)
        if match:
            later = _SUPERSEDES.search(match.group("text"))
            decisions.append(Decision(number, match.group("id"), match.group("status"), match.group("text"), line, later.group(1) if later else None))
            intro_open = False
        elif not line.strip():
            intro_open = intro_open and not intro_started
        elif intro_open and not (_LIST_ITEM.match(line) or line[0].isspace() or line.startswith(("|", "#")) or _DATE_FIRST.match(line)):
            intro_started = True
        else:
            malformed.append(number)


def parse(text: str) -> Parsed:
    text = text.replace("\r\n", "\n")
    prose, unclosed = docs.blank_fences(text)
    prose, open_comment = _blank_comments(prose)
    lines = prose.split("\n")
    starts = [(_section_name(_heading(line)), number) for number, line in enumerate(lines, start=1) if _heading(line)]
    sections: dict[str, list[tuple[int, int]]] = {}
    for index, (name, start) in enumerate(starts):
        sections.setdefault(name, []).append((start, starts[index + 1][1] - 1 if index + 1 < len(starts) else len(lines)))
    decisions, malformed = [], []
    for first, last in sections.get("Decisions", []):
        _read_decisions(lines, first, last, decisions, malformed)
    return Parsed(text, prose, sections, decisions, malformed, unclosed, open_comment)


def _retired(parsed: Parsed) -> set[str]:
    """Only an accepted decision can supersede: a proposal changes nothing yet."""
    return {decision.supersedes for decision in parsed.decisions if decision.status == "accepted" and decision.supersedes}


def in_force(parsed: Parsed) -> list[Decision]:
    gone = _retired(parsed)
    return [decision for decision in parsed.decisions if decision.status == "accepted" and decision.id not in gone]


def _cited(line: str, bare: bool = False) -> list[str]:
    """Paths a line names in backticks or links to, from the repository root. In prose a bare word could be anything, so a citation needs a slash or an extension unless `bare` says only paths belong here.

    `docs/DESIGN.md` may cite from where it sits, so one leading `../` is dropped. A route, a URL or anything still reaching outside isn't a path here.
    """
    found = []
    for span in (*_SPAN.findall(line), *_LINK.findall(line)):
        if len(span) > _LONGEST_CITATION:
            continue
        path = re.sub(r"(?::[\d:-]+|#.*)$", "", span.strip())
        path = path[2:] if path.startswith("./") else path[3:] if path.startswith("../") else path
        named = "/" in path or re.search(r"\.\w+$", path) or (bare and re.search(r"\w", path))
        if _PATH_LIKE.match(path) and not path.startswith(("-", "/")) and ".." not in path.split("/") and named:
            found.append(path.rstrip("/"))
    return found


def _applies_clause(decision: Decision) -> str | None:
    """Backticked paths at the end of the line, before any Supersedes. Its reason can name code it doesn't govern, so nothing else counts."""
    found = _APPLIES.search(_SUPERSEDES.sub("", decision.text).rstrip(" ."))
    return found.group(1) if found else None


def _applies(decision: Decision) -> list[str]:
    """What a decision is about."""
    clause = _applies_clause(decision)
    return _cited(clause, bare=True) if clause else []


def _says_applies(decision: Decision) -> bool:
    return re.search(r"\bapplies:", decision.text, re.I) is not None


def _unreadable_applies(decision: Decision) -> bool:
    if not _says_applies(decision):
        return False
    clause = _applies_clause(decision)
    return clause is None or len(_SPAN.findall(clause)) != len(_cited(clause, bare=True))


def _covers(citation: str, path: str) -> bool:
    return path == citation or path.startswith(citation + "/")


def _section_lines(parsed: Parsed, name: str) -> list[str]:
    """What a section says, a list item or paragraph at a time, because one hard-wrapped line can say the opposite of its sentence. A table row or subheading stands alone."""
    lines = parsed.prose.split("\n")
    items: list[list[str]] = []
    for first, last in parsed.sections.get(name, []):
        joining = False
        for line in lines[first:last]:
            text = line.strip()
            alone = text.startswith(("|", "#"))
            if joining and text and not alone and not _LIST_ITEM.match(line):
                items[-1].append(text)
            elif text:
                items.append([text])
            joining = bool(text) and not alone
    return [item for item in map(" ".join, items) if item not in _PLACEHOLDERS]


def _header(parsed: Parsed) -> str:
    """What comes before the first section: who owns the file and when it was checked. A decision can mention either without being either."""
    starts = [first for ranges in parsed.sections.values() for first, _ in ranges]
    return "\n".join(parsed.prose.split("\n")[:min(starts) - 1 if starts else None])


def _owner(parsed: Parsed) -> str:
    found = _OWNER.search(_header(parsed))
    name = re.split(r"\s(?:Verified|Not yet verified)\b", found.group(1))[0].strip().strip("*_ .") if found else ""
    return name if name and name != _UNNAMED else "not named"


def clip(line: str, around: str | None = None) -> str:
    """Short enough for a note, keeping what it was quoted for. A cut is always marked, so a fragment can't read as the whole sentence."""
    line = line.strip()
    if len(line) <= MAX_NOTE:
        return line
    position = max(line.find(f"`{around}"), line.find(around)) if around and f"`{around}" not in line else line.find(f"`{around}") if around else 0
    start = max(position - MAX_NOTE // 2, 0)
    return ("..." if start else "") + line[start:start + MAX_NOTE - (6 if start else 3)] + "..."


def _claimed_paths(parsed: Parsed) -> set[str]:
    """Every path the document says something about: what it says exists, and what decisions in force govern."""
    lines = [line for section in _CLAIMS for line in _section_lines(parsed, section)]
    return {citation for line in lines for citation in _cited(line)} | {citation for decision in in_force(parsed) for citation in _applies(decision)}


def _is_here(root: Path, name: str, path: str) -> bool:
    """From the root, or from beside the document, as the shared check reads a citation."""
    return docs._exists(root / path) or docs._exists((root / name).parent / path)


def _leads(root: Path, name: str, parsed: Parsed) -> list:
    """Where what it claims and the repository disagree. The shared check accepts a path by its tail, so a file moved under another folder needs this stricter look too."""
    numbers = [number for section in _CLAIMS for first, last in parsed.sections.get(section, []) for number in range(first + 1, last + 1)]
    lines, prose = _blank_comments(parsed.text)[0].replace("<!--", "    ").split("\n"), parsed.prose.split("\n")  # the shared check would read a `<!--` named in passing as hiding what follows
    kept = [""] * len(lines)
    for number in numbers:
        kept[number - 1] = lines[number - 1]
    index = docs.build_index(root)
    leads = docs.document_leads(root, name, "\n".join(kept), index)
    leads += [docs.Lead(number, "missing-path", f"`{path}` isn't at that path from the repository root") for number in numbers for path in _cited(prose[number - 1]) if path in index.paths and not _is_here(root, name, path)]
    leads += [docs.Lead(decision.line, "missing-path", f"{decision.id} applies to `{path}`, and nothing is there") for decision in in_force(parsed) for path in _applies(decision) if not docs._exists(root / path)]
    return sorted(set(leads))


def _unchecked(root: Path, name: str, parsed: Parsed, leads: list) -> list[str]:
    """Citations that could be paths or names, which nothing here can tell apart, so silence about them doesn't read as a pass."""
    reported = " ".join(lead.message for lead in leads)
    return sorted(path for path in _claimed_paths(parsed) if not re.search(rf"`(?:\.\.?/)?{re.escape(path)}", reported) and not _is_here(root, name, path))


def _counted(count: int, noun: str) -> str:
    return f"{count} {noun}" + ("" if count == 1 else "s")


def init(root: Path) -> tuple[str, int]:
    name = find(root)
    if name:
        return (f"{name} already exists, so nothing was written.", 2)
    head = (filesystem.run_git(root, "rev-parse", "--short", "HEAD") or "").strip()
    today = datetime.date.today().isoformat()
    provenance = f"Verified {today} against {head}." if head else "Not yet verified against a commit."
    try:
        with open(root / FILE_NAMES[0], "x", encoding="utf-8") as handle:
            handle.write(_TEMPLATE.format(name=root.name, provenance=provenance))
    except OSError as error:
        return (f"Couldn't write {FILE_NAMES[0]}: {error.strerror or error}.", 2)
    return (f"Wrote {FILE_NAMES[0]}. Fill in only what someone could otherwise get wrong, and delete the rest.", 0)


def _text_refused(text: str, why: str) -> str | None:
    if not all(field.isprintable() and any(character.isalnum() for character in field) for field in (text, why)):
        return "A decision is one line of printable text, and needs both its text and --why."
    if any(field.count("`") % 2 for field in (text, why)):
        return "A stray backtick would hide what the decision applies to. Close it or remove it."
    if any(word in field for word in ("Supersedes:", "Applies:") for field in (text, why)):
        return "Supersedes: and Applies: are fields, so say those with --supersedes and --applies."
    return None


def _why_refused(parsed: Parsed, identifier: str, text: str, why: str, supersedes: str | None) -> str | None:
    """What would corrupt the record, since an appended line can't be taken back quietly."""
    known = {decision.id for decision in parsed.decisions}
    if not _ID.fullmatch(identifier):
        return f"{identifier!r} isn't usable as an id: lowercase letters, digits and hyphens only."
    if identifier in known:
        return f"{identifier} is already taken, and a decision can't be rewritten. Choose another id, and use --supersedes to replace it."
    if supersedes and supersedes not in known:
        return f"Nothing here is called {supersedes}, so it can't be superseded."
    if not _decisions_are_last(parsed):
        return "Decisions has to be the last section, because a decision is appended to the end of the file."
    return _text_refused(text, why)


def _decisions_are_last(parsed: Parsed) -> bool:
    starts = [first for ranges in parsed.sections.values() for first, _ in ranges]
    return any(first == max(starts) for first, _ in parsed.sections.get("Decisions", []))


def _reads_back(before: Parsed, after: Parsed, identifier: str, supersedes: str | None, applies: list[str]) -> bool:
    """Whatever slipped past the rules above, the line has to parse as exactly the decision meant, with everything before it untouched."""
    if after.decisions[:-1] != before.decisions or len(after.decisions) != len(before.decisions) + 1 or after.unclosed or after.malformed != before.malformed or after.sections.keys() != before.sections.keys() or len(_cycles(after)) != len(_cycles(before)):
        return False
    added = after.decisions[-1]
    return added.id == identifier and added.supersedes == supersedes and _applies(added) == [path.rstrip("/") for path in applies]


def _paths_to_apply(root: Path, applies: list[str]) -> tuple[list[str], str | None]:
    if any(not path.strip() or "*" in path for path in applies):
        return [], "--applies takes a file or folder, not a pattern or nothing. Leave it out for a decision on the whole project."
    paths = [_relative(root, path) for path in applies]
    if None in paths:
        return [], f"{applies[paths.index(None)]} is outside this project, so a decision can't apply to it."
    if "." in paths:
        return [], "--applies . is the whole project, which is what leaving it out means."
    return paths, None


def _entry(identifier: str, text: str, why: str, paths: list[str], proposed: bool, supersedes: str | None) -> str:
    parts = [f"- {datetime.date.today().isoformat()} {identifier} [{'proposed' if proposed else 'accepted'}] {text.strip().rstrip('.')}. Why: {why.strip()}"]
    parts += ["Applies: " + ", ".join(f"`{path}`" for path in paths)] if paths else []
    parts += [f"Supersedes: `{supersedes}`"] if supersedes else []
    return ". ".join(part.rstrip(".") for part in parts) + ".\n"


def _append(root: Path, name: str, identifier: str, joined: str) -> str | None:
    """One write to a file opened for appending, so writers running at once can't overwrite each other."""
    data = joined.encode()
    try:
        descriptor = os.open(root / name, os.O_WRONLY | os.O_APPEND)
        try:
            if os.write(descriptor, data) != len(data):
                return f"Only part of {identifier} reached {name}, so check the end of that file."
        finally:
            os.close(descriptor)
    except OSError as error:
        return f"Couldn't write {name}: {error.strerror or error}."
    return None


def decide(root: Path, identifier: str, text: str, why: str, applies: list[str], proposed: bool, supersedes: str | None) -> tuple[str, int]:
    name = find(root)
    if not name:
        return ("No design doc here. `occam design init` starts one.", 2)
    raw = filesystem.read_text(root / name)
    if raw is None:
        return (f"{name} couldn't be read, so nothing was added.", 2)
    parsed = parse(raw)
    paths, refused = _paths_to_apply(root, applies)
    problem = _why_refused(parsed, identifier, text, why, supersedes) or refused
    if problem:
        return (problem, 2)
    joined = ("" if parsed.text.endswith("\n") else "\n") + _entry(identifier, text, why, paths, proposed, supersedes)
    if not _reads_back(parsed, parse(parsed.text + joined), identifier, supersedes, paths):
        return ("That wouldn't read back as one decision, so nothing was added. A path may have characters a citation can't hold, it may close a cycle, or the end of the file may not be read: `occam design check`.", 2)
    failed = _append(root, name, identifier, joined.replace("\n", "\r\n") if "\r\n" in raw else joined)
    if failed:
        return (failed, 2)
    return (f"Added {identifier} to {name}{' as a proposal, for the owner to accept' if proposed else ''}.", 0)


def _cycles(parsed: Parsed) -> list[Decision]:
    """Decisions that end up superseding themselves, which would retire them all with nothing left standing."""
    replaces = {decision.id: decision.supersedes for decision in parsed.decisions if decision.status == "accepted" and decision.supersedes}
    stuck = []
    for decision in parsed.decisions:
        seen: set[str] = set()
        current = replaces.get(decision.id)
        while current and current != decision.id and current not in seen:
            seen.add(current)
            current = replaces.get(current)
        if current == decision.id:
            stuck.append(decision)
    return stuck


def _decision_problems(parsed: Parsed) -> list[tuple[int, str, str]]:
    problems = [(line, "malformed-decision", "Expected `- YYYY-MM-DD id [accepted|proposed] text`.") for line in parsed.malformed]
    known: set[str] = set()
    for decision in parsed.decisions:
        if decision.id in known:
            problems.append((decision.line, "duplicate-decision", f"{decision.id} appears twice."))
        known.add(decision.id)
    problems += [(decision.line, "unknown-supersedes", f"{decision.id} supersedes {decision.supersedes}, which isn't here.") for decision in parsed.decisions if decision.supersedes and decision.supersedes not in known]
    problems += [(decision.line, "supersedes-cycle", f"{decision.id} ends up superseding itself, so it isn't in force.") for decision in _cycles(parsed)]
    problems += [(decision.line, "unreadable-applies", f"{decision.id} has an Applies this can't read in full. It takes backticked files or folders, separated by commas, at the end of the line.") for decision in parsed.decisions if _unreadable_applies(decision)]
    problems += [(decision.line, "misplaced-supersedes", f"{decision.id} says Supersedes: in a form that retires nothing. It takes one backticked id at the very end of the line.") for decision in parsed.decisions if "Supersedes:" in decision.text and not decision.supersedes]
    return problems


def _structure_problems(parsed: Parsed) -> list[tuple[int, str, str]]:
    problems = [(1, "missing-section", f"No `## {section}` section.") for section in REQUIRED if section not in parsed.sections]
    problems += [(ranges[1][0], "duplicate-section", f"`## {section}` appears {len(ranges)} times. Keep one.") for section, ranges in parsed.sections.items() if len(ranges) > 1]
    if "Decisions" in parsed.sections and not _decisions_are_last(parsed):
        problems.append((parsed.sections["Decisions"][0][0], "decisions-not-last", "Decisions has to be the last section, so a decision can be appended safely."))
    if parsed.unclosed:
        problems.append((1, "unclosed-fence", "A code block is never closed, so everything after it reads as code."))
    if parsed.open_comment:
        problems.append((1, "unclosed-comment", "A comment is never closed, so everything after it is hidden."))
    problems += _decision_problems(parsed)
    problems += [(number, "placeholder", "Still the template's text. Fill it in or delete it.") for number, line in enumerate(parsed.prose.split("\n"), start=1)
                 if line.strip() in _PLACEHOLDERS or line.startswith(f"Owner: {_UNNAMED}")]
    return problems


def _history_of(root: Path, commit: str, citations: list[str]) -> list[str]:
    specs = [f":(literal){citation}" for citation in citations]
    log = filesystem.run_git(root, "log", "--format=", "--name-status", "--relative", "--diff-filter=DR", f"{commit}..HEAD", "--", *specs)
    count = filesystem.run_git(root, "rev-list", "--count", f"{commit}..HEAD", "--", *specs)
    if log is None or count is None:
        return [f"NOT CHECKED: drift since {commit}, because git couldn't read the history of what this cites."]
    gone = sorted({field for entry in log.splitlines() for field in entry.split("\t")[1:2] if field and not docs._exists(root / field)})
    notes = [f"Renamed or deleted since {commit}: {', '.join(gone[:8])}{f' and {len(gone) - 8} more' if len(gone) > 8 else ''}."] if gone else []
    if count.strip() != "0":
        notes.append(f"{_counted(int(count), 'commit')} since {commit} touched paths this cites, so its claims about them may be stale. Recheck them, then update the Verified line.")
    return notes


def _drift(root: Path, parsed: Parsed) -> list[str]:
    """What git says happened to the cited paths since the doc was last checked. Advisory, because a commit touching a file doesn't make a claim about it false."""
    if not filesystem.in_git(root):
        return ["NOT CHECKED: drift since it was last verified, because this isn't a git repository."]
    provenance = _PROVENANCE.search(_header(parsed))
    if not provenance:
        return ["No `Verified <date> against <commit>` line, so drift can't be measured."]
    commit = provenance.group(2)
    if filesystem.run_git(root, "rev-parse", "--verify", "-q", f"{commit}^{{commit}}") is None:
        return [f"The commit it was verified against, {commit}, isn't in this history, so drift can't be measured."]
    if filesystem.run_git(root, "merge-base", "--is-ancestor", commit, "HEAD") is None:
        return [f"The commit it was verified against, {commit}, isn't an ancestor of this one, so drift can't be measured."]
    if commit == "HEAD" or commit == (filesystem.run_git(root, "symbolic-ref", "--short", "-q", "HEAD") or "").strip():
        return [f"It was verified against {commit}, which moves with every commit, so drift can't be measured. Use a commit hash."]
    citations = sorted(_claimed_paths(parsed))
    return _history_of(root, commit, citations) if citations else []


def check(root: Path) -> tuple[str, int]:
    name = find(root)
    if not name:
        return ("No design doc here. That's fine for most work. `occam design init` starts one.", 0)
    text = filesystem.read_text(root / name)
    if text is None:
        return (f"NOT CHECKED: {name} couldn't be read.", 2)
    parsed = parse(text)
    problems = _structure_problems(parsed)
    leads = _leads(root, name, parsed)
    size = parsed.text.count("\n") + (1 if parsed.text and not parsed.text.endswith("\n") else 0)
    lines = [f"occam design: {name}, {size} lines, {_counted(len(in_force(parsed)), 'decision')} in force, {_counted(len(problems), 'problem')}.", ""]
    lines += [f"  ! {name}:{line}  {rule}: {message}" for line, rule, message in sorted(problems)]
    lines += [f"  - {name}:{lead.line}  {lead.rule}: {lead.message}" for lead in leads]
    lines += _advice(root, name, parsed, leads, size)
    return "\n".join(lines).rstrip(), 1 if problems else 0


def _advice(root: Path, name: str, parsed: Parsed, leads: list, size: int) -> list[str]:
    lines = [f"  - {name}:1  too-long: over {MAX_LINES} lines. Long documents stop being kept up to date, so move detail next to the code it describes."] if size > MAX_LINES else []
    unchecked = _unchecked(root, name, parsed, leads)
    if unchecked:
        lines.append(f"  - NOT CHECKED: {', '.join(f'`{path}`' for path in unchecked[:8])}{f' and {len(unchecked) - 8} more' if len(unchecked) > 8 else ''}. These could be paths or names, so nothing here says whether they exist.")
    lines += [f"  - {note}" for note in _drift(root, parsed)]
    if all(_present(root, candidate) for candidate in FILE_NAMES):
        lines.append(f"  - Both {' and '.join(FILE_NAMES)} exist, and only {name} is read.")
    return lines


def decisions_on(parsed: Parsed, path: str) -> list[Decision]:
    return [decision for decision in in_force(parsed) if any(_covers(citation, path) for citation in _applies(decision))]


def _about(root: Path, parsed: Parsed, relative: str) -> list[str]:
    """What the document says about one path. A folder gets everything cited inside it."""
    is_folder = docs._exists(root / relative) and (root / relative).is_dir()
    def bears(citation: str) -> bool:
        return _covers(citation, relative) or (is_folder and (relative == "." or citation.startswith(relative + "/")))
    retired = _retired(parsed)
    lines = [f"  decided: {clip(decision.raw[2:])}" for decision in in_force(parsed) if any(bears(citation) for citation in _applies(decision))]
    lines += [f"  proposed, not decided: {clip(decision.raw[2:])}" for decision in parsed.decisions if decision.status == "proposed" and decision.id not in retired and any(bears(citation) for citation in _applies(decision))]
    lines += _what_sections_say(parsed, bears)
    return lines or ["  nothing specific."]


def _what_sections_say(parsed: Parsed, bears) -> list[str]:
    lines = []
    for section in parsed.sections:
        if section not in ("Decisions", "Non-goals"):  # those have their own lines
            for line in _section_lines(parsed, section):
                citation = next((citation for citation in _cited(line) if bears(citation)), None)
                if citation:
                    lines.append(f"  {_LABELS.get(section, section)}: {clip(line, citation)}")
    return lines


def for_paths(root: Path, paths: list[str]) -> tuple[str, int]:
    """Only what bears on these files, so nobody has to load the whole document to edit one of them."""
    name = find(root)
    if not name:
        return ("No design doc here.", 0)
    text = filesystem.read_text(root / name)
    if text is None:
        return (f"NOT CHECKED: {name} couldn't be read, so this says nothing about what applies.", 2)
    parsed = parse(text)
    lines = [f"{name}, owner {_owner(parsed)}. Where it and the code disagree about what exists, the code is right: say so and fix this file."]
    problems = len(_structure_problems(parsed))
    if problems:
        lines.append(f"It has {_counted(problems, 'structural problem')}, so this may be incomplete: `occam design check`.")
    for path in paths:
        relative = _relative(root, path)
        lines += ["", f"{relative or path}:", *(_about(root, parsed, relative) if relative else ["  outside this project."])]
    lines += _everywhere("Non-goals, which apply everywhere:", _section_lines(parsed, "Non-goals"))
    lines += _everywhere("Decisions on no particular file, which apply everywhere:", [decision.raw[2:] for decision in in_force(parsed) if not _says_applies(decision)])
    return "\n".join(lines), 0


def _everywhere(title: str, found: list[str]) -> list[str]:
    if not found:
        return []
    more = [f"  and {len(found) - MAX_EVERYWHERE} more in the document."] if len(found) > MAX_EVERYWHERE else []
    return ["", title, *[f"  {clip(line)}" for line in found[:MAX_EVERYWHERE]], *more]


def _relative(root: Path, path: str) -> str | None:
    """From the repository root, or None if it's outside. A path given from below the root or with `--root` from elsewhere may mean either, so the reading with the least missing wins, and cwd wins a tie.

    A new file exists under neither, which is why `src/new.py` from inside `src` means the one beside its siblings, not `src/src/new.py`.
    """
    top = Path(os.path.realpath(root))
    inside = []
    for start in (Path.cwd(), root):
        try:
            resolved = Path(os.path.realpath(start / path))
            if resolved.is_relative_to(top):
                missing = next(count for count, folder in enumerate((resolved, *resolved.parents)) if docs._exists(folder))
                inside.append((missing, resolved.relative_to(top).as_posix()))
        except ValueError:
            continue
    return min(inside, key=lambda reading: reading[0])[1] if inside else None


def _scope_note(rule: str, path: str, line: int, message: str, category: str = "scope") -> dict:
    return {"rule": rule, "path": path, "line": max(line, 1), "message": message, "category": category}


def _before(root: Path, revision: str) -> tuple[str | None, str | None]:
    """The document that was being read then, in the order `find` looks, because a move shouldn't hide what else changed."""
    for candidate in FILE_NAMES:
        text = filesystem.file_at(root, revision, candidate)
        if text is not None:
            return candidate, text
    return None, None


def _stale_note(parsed: Parsed, name: str, touched_paths: list[str]) -> list[dict]:
    citations = _claimed_paths(parsed)
    touched = sorted(path for path in touched_paths if any(_covers(citation, path) for citation in citations))
    if not touched:
        return []
    shown = ", ".join(touched[:5]) + (f" and {len(touched) - 5} more" if len(touched) > 5 else "")
    return [_scope_note("design-not-updated", name, 1, f"This change touches {shown}, which {name} cites, and {name} isn't in this change. Check what it says is still true: `occam design for <path>`.")]


def gate_notes(root: Path, revision: str, changed: dict, gone: tuple[str, ...] = ()) -> list[dict]:
    """For `occam gate`: decisions rewritten rather than superseded, and cited code that changed while the doc didn't. These warn. The code may well still match.

    `gone` is what this change deleted, or renamed away from: cited code leaving is the likeliest way for the doc to go stale.
    """
    name = find(root)
    was_named, was = _before(root, revision)
    standing = _counted(len(in_force(parse(was or ""))), "decision")
    if not name:
        return [_scope_note("design-removed", was_named, 1, f"{was_named} was removed, and with it {standing} in force. If that's meant, say why.")] if was_named else []
    text = filesystem.read_text(root / name)
    if text is None:
        return [_scope_note("design-unreadable", name, 1, f"{name} couldn't be read, so nothing compared it with this change.")]
    parsed = parse(text)
    if name not in changed and was_named in (name, None):
        return _stale_note(parsed, name, [*changed, *gone])
    notes = [_scope_note(lead.rule, name, lead.line, lead.message, "docs") for lead in _leads(root, name, parsed)]
    if was_named not in (name, None) and _present(root, was_named):
        return [*notes, _scope_note("design-shadowed", name, 1, f"{name} is now read instead of {was_named}, whose {standing} in force no longer apply. If that's meant, supersede them here.")]
    return [*notes, *_rewritten(parsed, name, parse(was or ""))]


def _rewritten(parsed: Parsed, name: str, was: Parsed) -> list[dict]:
    """Accepted decisions that changed since. One still in the file that stopped reading as a decision wasn't removed, and the note has to say so."""
    now = {decision.id: decision for decision in parsed.decisions}
    lines = parsed.text.split("\n")
    notes = []
    for decision in was.decisions:
        current = now.get(decision.id)
        if decision.status != "accepted" or (current and current.raw == decision.raw):
            continue
        if not current and decision.raw in lines:
            notes.append(_scope_note("decision-unread", name, lines.index(decision.raw) + 1, f"Accepted decision {decision.id} is still in the file and no longer reads as a decision, so it isn't in force. It may be inside a comment or code block, or under another heading."))
        else:
            notes.append(_scope_note("decision-rewritten", name, current.line if current else 1, f"Accepted decision {decision.id} was {'edited' if current else 'removed'}. Decisions are superseded, not rewritten, so the reason stays on record."))
    return notes
