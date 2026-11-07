"""What a pattern can see of an agent going wrong: the text analysis behind occam_hook's comparisons.

Everything here is a pure function of text or of recorded entries. It keeps no state and makes no decisions: the hook
decides what to hold, mention or send back. docs/failure-modes.md ties each piece to the failure it addresses and to
the ways around it.
"""

from __future__ import annotations  # the stock macOS python3 is 3.9

import os
import re
from pathlib import Path
from urllib.parse import unquote

CLAIMS_PASSING = re.compile(r"(\b(tests?|suite|checks?)\b[^.\n]{0,40}\b(pass|passes|passing|passed|green)\b|\b\d+\s+passed\b)", re.I)
NEGATED_CLAIM = re.compile(r"\b(not|n't|couldn.t|unable|without|never|tells you nothing|no test)\b", re.I)
WEB_TOOLS = {"WebFetch", "WebSearch"}
# A named part: "the pricing tests", "unit tests". Not "the tests", "my tests", "these checks" or "12 tests", which claim everything.
SCOPED_CLAIM = re.compile(r"\b(?!(?:all|the|my|our|these|those|this|every|new|\d+)\b)[a-z][\w-]* (?:tests?|checks?)\b", re.I)
FAILED_CHECKS_BEFORE_NOTE = 3

# Anchored to a stripped line's start, because the word alone also turns up in docstrings, strings and names.
ASSERTION = re.compile(r"^(await\s+)?((\w+\.)*assert\w*(!|\()|assert(\s|$)|Assert\.\w+\(|expect\w*\(|require\.\w+\(|EXPECT_[A-Z_]+|ASSERT_[A-Z_]+"
                       r"|t\.(Error|Fatal)f?\(|(with\s+)?pytest\.raises\()|\.should\b")
SKIPPED_TEST = re.compile(r"(?<![\w.])(pytest\.mark\.(skip\w*|xfail)|pytest\.(skip|xfail)\(|unittest\.skip\w*|t\.Skip\w*\(|(it|test|describe)\.(skip|only|todo)\b"
                          r"|xit\(|xdescribe\()|\.skipTest\(|@(Disabled|Ignore)\b|#\[ignore\]")
SUPPRESSION = re.compile(r"(#|//|/\*)\s*(type:\s*ignore|noqa|pylint:\s*disable|pyright:\s*ignore|eslint-disable|@ts-ignore|@ts-expect-error|@ts-nocheck|nolint)"
                         r"|#\[allow\(|@SuppressWarnings|\b(addopts|fail_under|continue-on-error|collect_ignore)\b|--(ignore|deselect)\b|passWithNoTests"
                         r"|\bstrict[\"']?\s*[=:]\s*[\"']?false\b")
CHECK_CONFIG = re.compile(
    r"(^|/)(pytest\.ini|tox\.ini|noxfile\.py|\.coveragerc|\.flake8|mypy\.ini|\.mypy\.ini|ruff\.toml|\.ruff\.toml|\.eslintrc[^/]*"
    r"|eslint\.config\.[^/]+|jest\.config\.[^/]+|vitest\.config\.[^/]+|tsconfig[^/]*\.json|\.pre-commit-config\.yaml|\.golangci\.ya?ml"
    r"|clippy\.toml|\.gitlab-ci\.yml)$|(^|/)(\.github/workflows|\.circleci)/"
)
SETTINGS_FILE = re.compile(r"\.claude/settings(\.local)?\.json\b")
# The value matters: naming these settings, or leaving the checks on, turns nothing off.
DISABLES_CHECKS = re.compile(r"OCCAM_HOOKS[\"']?\s*[:=]\s*[\"']?(off|0|false)\b|disableAllHooks[\"']?\s*:\s*true\b|occam@occam[\"']?\s*:\s*false\b")
PIPE_TO_SHELL = re.compile(r"\b(curl|wget)\b[^;&|]{0,2000}\|\s*(sudo\s+(-\S+\s+)*)?(\S*/)?(ba|z|da|k)?sh\b")
SHELL_RUNS_DOWNLOAD = re.compile(r"\b(ba|z|da|k)?sh\b[^;&|\n]{0,200}(<\(|\$\()\s*(curl|wget)\b")
HARD_TO_UNDO = {"terraform": "destroy", "pulumi": "destroy", "kubectl": "delete", "helm": "uninstall"}
SQL_CLIENTS = {"psql", "mysql", "mariadb", "sqlite3", "sqlcmd"}
DROPS_DATA = re.compile(r"\b(drop\s+(table|database|schema)|truncate\s+table)\b", re.I)
NETWORK_CLIENTS = {"curl", "wget", "http", "https", "nc", "ncat"}
GENERATED_NAMES = {"build", "dist", "target", "out", "node_modules", "__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache", ".tox", ".nox",
                   ".venv", "venv", ".next", ".cache", ".turbo", ".gradle", "coverage", ".coverage", "htmlcov", "test-results"}
TEST_DIRS = {"tests", "test", "spec", "__tests__"}
# Only unmistakable shapes, so a hold here means something. Nothing derived from a match is ever printed or stored.
SECRET_SHAPES = (
    ("an AWS access key", re.compile(r"\b(?:AKIA|ASIA)(?![0-9A-Z]*EXAMPLE)[0-9A-Z]{16}\b")),
    ("a private key", re.compile(r"-----BEGIN (?:[A-Z]+ )*PRIVATE KEY-----\s*[A-Za-z0-9+/=][A-Za-z0-9+/=\s]{19,}")),
    ("a GitHub token", re.compile(r"\bgh[pousr]_[A-Za-z0-9]{36,}\b|\bgithub_pat_[A-Za-z0-9_]{22,}\b")),
    ("a GitLab token", re.compile(r"\bglpat-[A-Za-z0-9_-]{20,}\b")),
    ("a Slack token", re.compile(r"\bxox[abprs]-[A-Za-z0-9-]{12,}\b")),
    # A digit and a capital, so `sk-learn-pipelines-and-column-transformers` in a URL isn't a key.
    ("an API key", re.compile(r"\bsk-(?:ant-|proj-)?(?=[A-Za-z0-9_-]*\d)(?=[A-Za-z0-9_-]*[A-Z])[A-Za-z0-9_-]{24,}\b|\bAIza[0-9A-Za-z_-]{35}\b|\bnpm_[A-Za-z0-9]{36}\b")),
)
AGENT_INSTRUCTIONS = re.compile(r"(^|/)(CLAUDE\.md|AGENTS\.md|GEMINI\.md|MEMORY\.md|SKILL\.md|\.cursorrules|\.windsurfrules|copilot-instructions\.md)$"
                                r"|(^|/)(\.cursor/rules|\.claude/(skills|agents|commands|rules)|memory)/")
PUSHBACK = re.compile(r"\b(are you sure|you'?re wrong|you are wrong|that'?s (wrong|not right|incorrect)|this is (wrong|incorrect)"
                      r"|i (don'?t|do not) think (that|this|it)|i disagree|that can'?t be right|you made a mistake)\b", re.I)
TEST_COUNT = re.compile(r"(?<![\d.])(\d[\d,]{0,15})\s+(?:(?:[a-z-]+\s+)?(?:tests?|checks?|cases?|specs?)\s+(?:(?:are|were)\s+)?(?:(?:now|all)\s+)?(?:pass|passes|passed|passing)"
                        r"|of\s+them\s+pass(?:ed)?|(?:are\s+)?(?:passed|passing))\b", re.I)
# Output that states a count at all. `go test` prints none, so it can't contradict one.
COUNT_SUMMARY = re.compile(r"(?<![\d,.])\d[\d,]{0,15}\s+(passed|passing|failed|failing|tests?|specs?|examples?)\b|\bRan \d+ tests?\b|\btest result:", re.I)
MEASURED_CHANGE = re.compile(r"(?<![\w.])\d+(?:\.\d+)?\s?(?:x|×|%|times)(?!\w)", re.I)
PERFORMANCE_WORD = re.compile(r"\b(faster|slower|quicker|speed\w*|latency|throughput|run ?time|wall[- ]?(clock|time)|elapsed|p\d\d|memory|rss|cpu|qps|rps|time|takes)\b", re.I)
# A number beside a performance word is often a setting, so a claim also says which way something moved.
DIRECTION = re.compile(r"\b(faster|slower|quicker|speed-?ups?|sped|reduc\w*|drop\w*|lower\w*|less|fewer|cut|improv\w*|sav\w+|shr[iau]nk\w*|down|decreas\w*|increas\w*|higher)\b", re.I)
HEDGED = re.compile(r"\b(estimat\w*|project(ed|ion)|expect\w*|should|would|could|might|(?-i:may)|not measured|unmeasured|untested|predict\w*|theoretical\w*)\b", re.I)
MENTIONS_FAILURE = re.compile(r"\b(fail\w*|errors?|broken|red|blocked|issues?|tim(ed|es) out|still (raises|errors?)"
                              r"|(did|does|do|is|are)(n['’]?t| not) (yet )?(pass|compil|build|run|work)\w*|not (yet )?pass\w*|could(n['’]?t| not) run)\b", re.I)
MENTIONS_VARYING = re.compile(r"\b(flak\w+|intermittent\w*|non-?determini\w+|varies|varied|differ\w*|re-?run\w*|re-?ran|retri\w+|first run|second run)\b", re.I)
# Commands that leave a later run's result alone, so a different result afterward isn't explained by them.
READ_ONLY_PROGRAMS = {"cat", "less", "more", "head", "tail", "grep", "rg", "ag", "ls", "find", "fd", "tree", "wc", "sort", "uniq", "cut", "awk", "sed",
                      "tr", "jq", "yq", "stat", "file", "which", "type", "pwd", "date", "echo", "printf", "sleep", "cd", "pushd", "popd", "source", ".", "true"}
WHOLE_SUITE_PROGRAMS = {"pytest", "py.test", "jest", "vitest", "mocha", "rspec", "phpunit"}
NARROWS_A_RUN = re.compile(r"--ignore|--deselect|--exclude|--testPathIgnore|--grep|--only|(^|\s)-[kmt]\b")
PACKAGE_NAME = re.compile(r"@?[A-Za-z0-9][A-Za-z0-9._/-]*")
INSTALL_VALUE_FLAGS = {"-r", "--requirement", "-c", "--constraint", "-i", "--index-url", "--extra-index-url", "-f", "--find-links", "-t", "--target", "--prefix",
                       "--root", "--python", "-p", "-F", "--features", "--registry", "--cache-dir", "--platform", "--path", "--git", "--branch", "--tag", "--rev"}


def old_and_new_text(name: str, tool_input: dict, cwd: str | None) -> tuple[str, str]:
    """What an edit tool takes out and puts in. A whole-file write is compared with the file as it stands."""
    if name == "MultiEdit":
        pairs = [pair for pair in tool_input.get("edits") or [] if isinstance(pair, dict)]
        return "\n".join(str(p.get("old_string", "")) for p in pairs), "\n".join(str(p.get("new_string", "")) for p in pairs)
    if name == "NotebookEdit":
        return "", str(tool_input.get("new_source", ""))
    if name == "Write":
        try:
            path = Path(cwd or ".") / str(tool_input.get("file_path") or "")
            old = path.read_text(encoding="utf-8", errors="replace") if path.is_file() and path.stat().st_size < 2_000_000 else ""
        except OSError:
            old = ""
        return old, str(tool_input.get("content", ""))
    return str(tool_input.get("old_string", "")), str(tool_input.get("new_string", ""))


def secret_shape(text: str, already: str = "") -> str | None:
    """The kind of credential this text newly carries, and never its value."""
    for label, pattern in SECRET_SHAPES:
        if set(pattern.findall(text)) - set(pattern.findall(already)):
            return label
    return None


def redact(text: str) -> str:
    """Removes credential shapes from anything about to be stored or repeated. Run this before cutting text to length."""
    for _, pattern in SECRET_SHAPES:
        text = pattern.sub("[credential]", text)
    return text


def web_request_text(tool_input: dict) -> str:
    """A web request's values as sent, and decoded, so an escape can't sit between a word boundary and a token."""
    text = " ".join(str(value) for value in tool_input.values())
    return text + " " + unquote(text)


def live_count(pattern: re.Pattern, text: str) -> int:
    """Matching lines that run, since a commented-out assertion checks nothing. `#[` is a Rust attribute, not a comment."""
    lines = (line.lstrip() for line in text.splitlines())
    return sum(1 for line in lines if pattern.search(line) and (line.startswith("#[") or not line.startswith(("#", "//", "*", "--"))))


def failed_here(check: dict) -> bool:
    """Did this check fail in a way that says something about the code being worked on? One that never started, or ran on a copy elsewhere, didn't."""
    return not check.get("passed") and not check.get("not_this_code")


def just_failed(turn: list[dict]) -> bool:
    """Is a failed check the latest thing that happened, with no code changed since? A red start can last a whole task."""
    for entry in reversed(turn):
        if entry.get("kind") == "edit" and entry.get("code"):
            return False
        if entry.get("kind") == "check" and not entry.get("agent") and not entry.get("not_this_code"):
            return not entry.get("passed")
    return False


def how_an_edit_weakens(path: str, old: str, new: str, failing: bool, is_test: bool) -> str | None:
    """How this edit could make a check easier to pass, rather than making the code pass it."""
    if is_test:
        removed = live_count(ASSERTION, old) - live_count(ASSERTION, new)
        if removed > 0:
            return f"removes {removed} assertion{'s' if removed > 1 else ''}"
        if live_count(SKIPPED_TEST, new) > live_count(SKIPPED_TEST, old):
            return "skips or focuses a test"
    if failing and CHECK_CONFIG.search(path):
        return "changes a check's configuration right after a check failed"
    if failing and old and len(SUPPRESSION.findall(new)) > len(SUPPRESSION.findall(old)):  # a new file can't have loosened anything
        return "adds a suppression right after a check failed"
    return None


def is_generated(path: str) -> bool:
    return os.path.basename(path.rstrip("/*")) in GENERATED_NAMES


def deletes_too_much(word: str, inside_project=lambda _: False) -> bool:
    """Would a recursive delete of this reach the root, home, the whole working directory, or outside it?

    A folder in the project written as an absolute path is the same delete as `rm -rf src`, which isn't asked about.
    """
    if not word:
        return False
    if word == "$" or word.startswith(("$(", "`", "$PWD", "${PWD", "$HOME", "${HOME", "~")):
        return True
    if word.startswith("$"):
        return False  # a variable can't be judged from here, and most hold a temp path
    path = os.path.normpath(word)
    if word in ("*", "./*", "../*", "/*") or path in (".", "..", "/") or path.startswith("../"):
        return True
    if not path.startswith("/") or path.startswith(("/tmp/", "/private/tmp/", "/var/folders/")) or inside_project(path):
        return False
    return not is_generated(path)


def reason_for_a_person(text: str, programs: list[tuple[str, list[str]]], inside_project=lambda _: False) -> str | None:
    """Why someone should see this command first. `programs` is each simple command's program and arguments."""
    if DISABLES_CHECKS.search(text) and SETTINGS_FILE.search(text):
        return "this turns off the checks on this session's work."
    if PIPE_TO_SHELL.search(re.sub(r"'[^']*'|\"[^\"]*\"", "''", text)) or SHELL_RUNS_DOWNLOAD.search(text):
        return "this runs a download straight in a shell."
    for name, args in programs:
        if name == "rm" and any(re.fullmatch(r"-[a-zA-Z]*[rR][a-zA-Z]*|--recursive", arg) for arg in args):
            targets = [arg for arg in args if not arg.startswith("-") and deletes_too_much(arg, inside_project)]
            if targets:
                return f"this recursively deletes {targets[0]}."
        elif name in HARD_TO_UNDO and HARD_TO_UNDO[name] in args:
            return f"`{name} {HARD_TO_UNDO[name]}` is hard to undo."
        elif name in SQL_CLIENTS and DROPS_DATA.search(" ".join(args)):
            return "this drops or truncates data."
        elif name in NETWORK_CLIENTS:
            shape = secret_shape(" ".join(args))
            if shape:
                return f"this sends what looks like {shape} over the network."
    return None


def installed_packages(name: str, args: list[str], installers: dict) -> list[str]:
    """Package names a command installs, without versions. Flag values, URLs and paths aren't package names."""
    if name in ("pip", "pip3") and args[:1] == ["install"]:
        skip = 1
    elif name == "uv" and args[:2] == ["pip", "install"]:
        skip = 2
    elif name in installers and args[:1] and args[0] in installers[name]:
        skip = 1
    else:
        return []
    names, value_next = [], False
    for arg in args[skip:]:
        if value_next:
            value_next = False
        elif arg.startswith("-"):
            value_next = arg in INSTALL_VALUE_FLAGS
        else:
            package = re.split(r"(?<=.)[=<>~!\[@]", arg)[0]
            if PACKAGE_NAME.fullmatch(package) and not package.startswith((".", "/")):
                names.append(package)
    return names


def leaves_results_alone(name: str, args: list[str]) -> bool:
    return name in READ_ONLY_PROGRAMS and not (name == "find" and {"-delete", "-exec", "-execdir"} & set(args))


def failed_check_streak(turn: list[dict]) -> list[int]:
    """Positions in the turn of this agent's failed checks since the last pass, latest first."""
    streak = []
    for index, entry in reversed(list(enumerate(turn))):
        if entry.get("kind") == "check" and not entry.get("agent"):
            if failed_here(entry):
                streak.append(index)
            elif not entry.get("not_this_code"):
                break
    return streak


def numbers_in(text: str) -> list[str]:
    """Integers near the end of a command's output, where summaries are, so a reported count can be matched to them."""
    return list(dict.fromkeys(n.replace(",", "") for n in re.findall(r"(?<![\d,.])\d[\d,]{0,15}", text[-8000:])))[-100:]


def shows_a_count(text: str) -> bool:
    return bool(COUNT_SUMMARY.search(text[-8000:]))


def sentences_of(message: str) -> list[str]:
    return re.split(r"(?<=[.!?])\s+|\n", message)


def claims_a_measured_change(message: str) -> bool:
    return any(MEASURED_CHANGE.search(s) and PERFORMANCE_WORD.search(s) and DIRECTION.search(s) and not HEDGED.search(s) for s in sentences_of(message))


def leaves_out_a_failure(message: str) -> bool:
    """No word of a failure, or a claim that everything passes which nothing in its own sentence qualifies. "All the pricing tests pass" is scoped, so it can sit beside an honest failure."""
    if not MENTIONS_FAILURE.search(message):
        return True
    return any(CLAIMS_PASSING.search(s) and not SCOPED_CLAIM.search(s) and not NEGATED_CLAIM.search(s) and not MENTIONS_FAILURE.search(s) for s in sentences_of(message))


def has_an_unsettled_failure(checks: list[dict]) -> bool:
    """Did a check fail with no later pass of that same check? Only an unnarrowed run of a whole suite settles part of it."""
    failed: dict = {}
    for check in checks:
        if check.get("not_this_code"):  # it says nothing either way, so it neither fails this code nor clears a failure
            continue
        runs = check.get("runs") or []
        if not check.get("passed"):
            if not check.get("agent"):  # a subagent probing for failures is doing its job
                failed.update({text: key for text, key in runs})
            continue
        for text, key in runs:
            whole_suite = key in WHOLE_SUITE_PROGRAMS and not NARROWS_A_RUN.search(text.replace("-m pytest", ""))
            failed = {t: k for t, k in failed.items() if t != text and not (whole_suite and k.split()[0] == key)}
    return bool(failed)


def unmatched_test_count(turn: list[dict], message: str) -> str | None:
    """A count of passing tests that appears in no check's output this turn, when some output states a count at all."""
    checks = [e for e in turn if e.get("kind") == "check" and not e.get("not_this_code")]
    if not any(e.get("counted") for e in checks):
        return None
    seen = {number for e in checks for number in e.get("numbers", [])}
    for match in TEST_COUNT.finditer(message):
        sentence = sentences_of(message[max(0, match.start() - 60):match.end()])[-1]
        if match.group(1).replace(",", "") not in seen and not NEGATED_CLAIM.search(sentence):
            return match.group(1)
    return None


def has_before_and_after(earlier: list[dict], turn: list[dict]) -> bool:
    """Did one command run, and succeed, both before this turn's first code edit and after its last?"""
    def passed_keys(entries: list[dict]) -> set[str]:
        return {key for e in entries if e.get("kind") == "check" and e.get("passed") for _, key in e.get("runs") or []}
    edits = [i for i, e in enumerate(turn) if e.get("kind") == "edit" and e.get("code")]
    return bool(edits) and bool(passed_keys(earlier + turn[:edits[0]]) & passed_keys(turn[edits[-1] + 1:]))


def varying_results(turn: list[dict]) -> list[str]:
    """Commands that both failed and passed in consecutive runs, with no other command or edit between them that could explain it."""
    previous = None
    varying: list[str] = []
    for entry in turn:
        if entry.get("kind") in ("edit", "setup"):
            previous = None
        elif entry.get("kind") == "check" and not entry.get("agent"):
            runs = entry.get("runs") or []
            current = (runs[0][0] if len(runs) == 1 else "", entry.get("passed"))
            if previous and current[0] and previous[0] == current[0] and previous[1] != current[1] and current[0] not in varying:
                varying.append(current[0])
            previous = current
    return varying


def names_to_report(turn: list[dict], is_manifest: re.Pattern) -> set[str]:
    """Things a reader needs named, once per turn. A file this turn created and removed isn't one of them."""
    created = {e.get("path") for e in turn if e.get("kind") == "created"}
    told = {e.get("name") for e in turn if e.get("kind") == "told"}
    names = set()
    for entry in turn:
        path = entry.get("path") or ""
        if entry.get("kind") == "to_report" and not (path and path in created):
            names.add(entry.get("name", ""))
        elif entry.get("kind") == "edit" and (is_manifest.search(path) or CHECK_CONFIG.search(path)):
            names.add(os.path.basename(path))
    return {name for name in names if name and name not in told}
