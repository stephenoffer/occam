"""What a pattern can see of an agent going wrong: the text analysis behind occam_hook's comparisons.

Everything here is a pure function of text or of recorded entries. It keeps no state and makes no decisions: the hook
decides what to hold, mention or send back. docs/failure-modes.md ties each piece to the failure it addresses and to
the ways around it.
"""

from __future__ import annotations  # the stock macOS python3 is 3.9

import os
import re
from collections import Counter
from pathlib import Path
from typing import Callable, NamedTuple
from urllib.parse import unquote

from destructive import RECURSIVE_FLAG, assigned_names, deletes_through_unset, deletes_too_much_of, find_piped_to_a_delete, guarded_names, hard_to_undo
from occam_commands import RUNS_A_FILE
from printed_secrets import credential_printed

CLAIMS_PASSING = re.compile(r"(\b(tests?|suite|checks?)\b[^.\n]{0,40}\b(pass|passes|passing|passed|green)\b|\b\d+\s+passed\b"
                            r"|`[^`\n]*\b(tests?|specs?)\b[^`\n]*`[^.\n]{0,20}\b(pass|passes|passed|green)\b"  # "`go test ./...` passes", whose dots end the first form
                            r"|\b\d+ (tests?|examples?|specs?),? 0 failures\b)", re.I)  # ExUnit and RSpec
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
DISABLES_CHECKS = re.compile(r"OCCAM_HOOKS[\"']?\s*[:=]\s*[\"']?\s*(?i:off|0|false|guard)\b|disableAllHooks[\"']?\s*:\s*true\b|occam@occam[\"']?\s*:\s*false\b")


def disables_checks(text: str) -> bool:
    """JSON can spell a value with escapes, so `\\u006f` followed by `ff` is "off" too."""
    decoded = re.sub(r"\\u([0-9a-fA-F]{4})", lambda found: chr(int(found.group(1), 16)), text)
    return bool(DISABLES_CHECKS.search(decoded))


# An interpreter given no script or code reads its program from the pipe, as `curl URL | python3 -` does. `| python3 -m json.tool` reads data.
PIPE_TO_SHELL = re.compile(r"\b(curl|wget)\b[^;&|]{0,2000}\|\s*(sudo\s+(-\S+\s+)*)?(env\s+(-\S+\s+)*(\w+=\S*\s+)*)?(\S*/)?(?:(ba|z|da|k)?sh\b|(?:python[\d.]*|node|perl|ruby|php)(?:[ \t]+-(?=\s|$)|[ \t]*(?=$|[;&|)\n])))")
# An interpreter counts only when the download is its program: `python3 <(curl ...)` or `-c "$(curl ...)"`, not a fetched token as an argument.
SHELL_RUNS_DOWNLOAD = re.compile(r"\b(ba|z|da|k)?sh\b[^;&|\n]{0,200}(<\(|\$\()\s*(curl|wget)\b"
                                 r"|\b(?:python[\d.]*|node|perl|ruby)[ \t]+(?:-[ce][ \t]+[\"']?\$\(|<\()\s*(?:curl|wget)\b|(?:\bsource|(?:^|[\s;&|(])\.)[ \t]+<\(\s*(?:curl|wget)\b")
POWERSHELL_RUNS_DOWNLOAD = re.compile(r"\b(?:iwr|irm|Invoke-WebRequest|Invoke-RestMethod|DownloadString)\b[^;\n|]{0,2000}\|\s*(?:iex|Invoke-Expression)\b"
                                      r"|\b(?:iex|Invoke-Expression)\b[\s(]{0,10}(?:iwr|irm|Invoke-WebRequest|Invoke-RestMethod|New-Object\s+(?:System\.)?Net\.WebClient)\b", re.I)
_ENVIRONMENT = re.compile(r"(?:RAILS_ENV|RACK_ENV|APP_ENV|NODE_ENV)=(.*)")
_PASSES_THE_ENVIRONMENT = {"env", "sudo", "doas", "nice", "nohup", "time", "command", "exec"}
_DROPS_THE_ENVIRONMENT = {"sudo", "doas", "su"}
_WINDOWS_RECURSIVE_DELETE = re.compile(r"(?:^|[\s;&|(])(?:rmdir|rd|del|erase)\s+(?:/\w\s+)*/s\b(?:\s+/\w)*\s+(\S+)|\bRemove-Item\b(?=[^;&|\n]*\s-Recurse\b)((?:\s+-\w+)*)\s+(?!-)(\S+)", re.I)
_TOO_MUCH_ON_WINDOWS = re.compile(r"^(?:[A-Za-z]:[\\/]?|[\\/]|~.*|%USERPROFILE%.*|\$env:USERPROFILE.*|\$HOME.*|\.\.?[\\/]?|\*)$", re.I)
_QUOTED_TEXT = re.compile(r"'[^']*'|\"[^\"]*\"")
# `curl URL > i.sh` saves through the shell, which the program's arguments don't show.
_SAVED_BY_REDIRECT = re.compile(r"\b(?:curl|wget)\b[^;&|\n<>]{0,1000}>[ \t]*([^\s;&|<>]+)")  # bounded, so a long command stays linear
SQL_CLIENTS = {"psql", "mysql", "mariadb", "sqlite3", "sqlcmd", "mongosh", "mongo"}
DROPS_DATA = re.compile(r"\b(drop\s+(table|database|schema)|truncate(?=\s+(?:table\s+)?[\w\"`\[])|dropDatabase)\b", re.I)
_CHANGES_ROWS = re.compile(r"\b(?:delete\s+from|update\s+(?:only\s+)?[\w.\"`\[\]]+(?:\s+(?:as\s+)?[\w\"`]+)?\s+set)\b", re.I)  # anywhere in the statement, so a leading comment can't hide it
# One left open runs to the end, as the database reads it, which also keeps this linear on a command full of openers.
_SQL_TEXT_AND_COMMENTS = re.compile(r"'(?:[^']|'')*(?:'|\Z)|\"(?:[^\"]|\"\")*(?:\"|\Z)|--[^\n]*|/\*.*?(?:\*/|\Z)", re.S)
NETWORK_CLIENTS = {"curl", "wget", "http", "https", "nc", "ncat"}
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
COUNT_SUMMARY = re.compile(r"(?<![\d,.])\d[\d,]{0,15}\s+(passed|passing|failed|failing|tests?|specs?|examples?)\b|\bRan \d+ tests?\b|\btest result:|\bTests run: \d", re.I)
MEASURED_CHANGE = re.compile(r"(?<![\w.])\d+(?:\.\d+)?\s?(?:x|×|%|times)(?!\w)", re.I)
PERFORMANCE_WORD = re.compile(r"\b(faster|slower|quicker|speed\w*|latency|throughput|run ?time|wall[- ]?(clock|time)|elapsed|p\d\d|memory|rss|cpu|qps|rps|time|takes)\b", re.I)
# A number beside a performance word is often a setting, so a claim also says which way something moved.
DIRECTION = re.compile(r"\b(faster|slower|quicker|speed-?ups?|sped|reduc\w*|drop\w*|lower\w*|less|fewer|cut|improv\w*|sav\w+|shr[iau]nk\w*|down|decreas\w*|increas\w*|higher)\b", re.I)
HEDGED = re.compile(r"\b(estimat\w*|project(ed|ion)|expect\w*|should|would|could|might|(?-i:may)|not measured|unmeasured|untested|predict\w*|theoretical\w*)\b", re.I)
# What says a check failed. Strong words do anywhere: fail, failing, failure, broken, blocked, "doesn't pass", "timed out". "Error" also
# names things in the code ("treated every error as a 500"), so it counts only beside a check, a test or a test's name. "0 failures" says none did.
STRONG_FAILURE = re.compile(r"\b(fail\w*|broken|red|blocked|issues?|tim(ed|es) out|still (raises|errors?)|(did|does|do|is|are)(n['’]?t| not) (yet )?(pass|compil|build|run|work)\w*"
                            r"|not (yet )?pass\w*|could(n['’]?t| not) run)\b", re.I)
WEAK_FAILURE = re.compile(r"\berrors?\b", re.I)
NAMES_A_CHECK = re.compile(r"\b(tests?|test suites?|suites?|specs?|cases?|builds?|compil\w*|lint\w*|type[- ]?check\w*|mypy|tsc|vet|clippy|ci|checks?|pipelines?|jobs?"
                           r"|pytest|jest|vitest|mocha|rspec|cargo|gradle|maven|mvn|make|tox|go test)\b|\btest_\w+|(?-i:\bTest[A-Z_]\w*)|(?<!\w)\w+_test\b|(?<![\w.])\w+\.(?:test|spec)\.\w+", re.I)
NONE_FAILED = re.compile(r"\b(?:0|no|zero|without(?: any)?)\s+(?:[\w-]+\s+)?(?:failures?|errors?|failed)\b", re.I)


# A failure that stands now, as a count or "still fails". "Fixed the failing test, and all tests pass" names one that's gone, so it's a claim.
FAILURE_NOW = re.compile(r"\b[1-9]\d*\s+(?:failed|failing|failures?|errors?)\b|\bstill (?:fail\w*|errors?)\b|(?:does|do|did|is|are)(?:n['’]?t| not) (?:yet )?pass\w*", re.I)


def claim_subject(message: str, claim: re.Match) -> str:
    """The words naming what passed: "all tests" in "fixed the failing test, and all tests pass", "pricing tests" in "the pricing tests pass"."""
    text = message[max(0, claim.start() - 40):claim.end()]
    nouns = list(re.finditer(r"(?:\S+\s+)?(?:tests?|suites?|checks?|specs?)\b", text, re.I))
    return nouns[-1].group(0) if nouns else text


def reports_a_failure(text: str) -> bool:
    """A line that reports a standing failure, "5 passed, 1 failed": an honest report beside its pass count, not a claim that all passed."""
    return bool(FAILURE_NOW.search(text))


def mentions_a_failure(sentence: str) -> bool:
    sentence = NONE_FAILED.sub("", sentence)
    return bool(STRONG_FAILURE.search(sentence) or (WEAK_FAILURE.search(sentence) and NAMES_A_CHECK.search(sentence)))


MENTIONS_VARYING = re.compile(r"\b(flak\w+|intermittent\w*|non-?determini\w+|varies|varied|differ\w*|re-?run\w*|re-?ran|retri\w+|first run|second run)\b", re.I)
# Commands that leave a later run's result alone, so a different result afterward isn't explained by them.
READ_ONLY_PROGRAMS = {"cat", "less", "more", "head", "tail", "grep", "rg", "ag", "ls", "find", "fd", "tree", "wc", "sort", "uniq", "cut", "awk", "sed",
                      "tr", "jq", "yq", "stat", "file", "which", "type", "pwd", "date", "echo", "printf", "sleep", "cd", "pushd", "popd", "source", ".", "true"}
WHOLE_SUITE_PROGRAMS = {"pytest", "py.test", "jest", "vitest", "mocha", "rspec", "phpunit"}
NARROWS_A_RUN = re.compile(r"--ignore|--deselect|--exclude|--testPathIgnore|--grep|--only|(^|\s)-[kmt]\b")
PACKAGE_NAME = re.compile(r"@?[A-Za-z0-9][A-Za-z0-9._/-]*")
INSTALL_VALUE_FLAGS = {"-r", "--requirement", "-c", "--constraint", "-i", "--index-url", "--extra-index-url", "-f", "--find-links", "-t", "--target", "--prefix",
                       "--root", "--python", "-p", "-F", "--features", "--registry", "--cache-dir", "--platform", "--path", "--git", "--branch", "--tag", "--rev"}


MAX_WHOLE_FILE = 2_000_000


def whole_file_change(name: str, tool_input: dict, path: Path) -> tuple[str, str] | None:
    """The whole file before and after an Edit or MultiEdit, so a change reads in its context. None when the file can't be read or the text isn't in it."""
    try:
        if name not in ("Edit", "MultiEdit") or not path.is_file() or path.stat().st_size > MAX_WHOLE_FILE:
            return None
        before = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    after = before
    pairs = tool_input.get("edits") if name == "MultiEdit" else [tool_input]
    for pair in pairs if isinstance(pairs, list) else []:
        old, new = str((pair or {}).get("old_string", "")), str((pair or {}).get("new_string", ""))
        if not old or old not in after:
            return None
        after = after.replace(old, new) if (pair or {}).get("replace_all") else after.replace(old, new, 1)
    return before, after


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


def drops_data(sql: str) -> bool:
    """A drop or truncate, or a DELETE or UPDATE statement with no WHERE, judged a statement at a time.
    Quoted text and comments are blanked first, so a `;` or `WHERE` inside them neither splits a statement nor stands in for its condition."""
    plain = _SQL_TEXT_AND_COMMENTS.sub(lambda match: match.group(0)[0] * 2 if match.group(0)[0] in "'\"" else " ", sql)
    return bool(DROPS_DATA.search(plain)) or any(_changes_every_row(statement) for statement in plain.split(";"))


def _changes_every_row(statement: str) -> bool:
    """An UPDATE or DELETE, the outer one or one inside a CTE, with no WHERE of its own: one at its depth before its parentheses close.
    A subquery's or another CTE's WHERE can't stand in for it."""
    for change in _CHANGES_ROWS.finditer(statement):
        depth, own = 0, False
        for token in re.finditer(r"[()]|\bwhere\b", statement[change.end():], re.I):
            if token.group(0) == "(":
                depth += 1
            elif token.group(0) == ")":
                if depth == 0:
                    break  # its own parentheses closed
                depth -= 1
            elif depth == 0:
                own = True
                break
        if not own:
            return True
    return False


def _own_settings(words: list[str]) -> dict[str, str]:
    """RAILS_ENV and the like as this command sets them: in front of the program, or as an argument for rails and rake, which read them there.
    `sudo`, `doas`, `su` and `env -i` or `-u` start the environment again, so what came before them doesn't reach the program."""
    settings: dict[str, str] = {}
    reads_arguments = any(os.path.basename(word) in ("rails", "rake") for word in words)
    in_front, after_env, after_exec = True, False, False
    for word in words:
        plain = word.replace('"', "").replace("'", "")
        match = _ENVIRONMENT.fullmatch(plain)
        name = os.path.basename(plain)
        if name in _DROPS_THE_ENVIRONMENT or (after_env and (plain == "-" or re.fullmatch(r"-[a-zA-Z]*[iu].*|--(?:ignore-environment|unset)\b.*", plain))) \
                or (after_exec and re.fullmatch(r"-[abd-zA-Z]*c[a-zA-Z]*", plain)):
            settings.clear()
        if match and (in_front or reads_arguments):
            settings[plain.split("=", 1)[0]] = match.group(1)
        elif not re.match(r"\w+=", plain) and not plain.startswith("-") and name not in _PASSES_THE_ENVIRONMENT:
            in_front = False
        after_env = name == "env" or (after_env and plain.startswith("-"))
        after_exec = name == "exec" or (after_exec and plain.startswith("-"))
    return settings


def in_a_test_environment(commands: list[list[str]]) -> list[bool]:
    """For each simple command, whether it runs with RAILS_ENV, NODE_ENV or the like set to `test` by its own settings.
    An earlier `export` doesn't count: whether it reaches the command depends on subshells, nested shells and branches
    that three rounds of reviews found new ways around, and asking once for a test reset costs far less than missing a real one."""
    return [bool(own) and all(value == "test" for value in own.values()) for own in map(_own_settings, commands)]  # NODE_ENV=test beside RAILS_ENV=production still asks


def _saved_as(name: str, args: list[str]) -> list[str]:
    """Where curl or wget writes what it fetches: curl's `-o`, `--output`, `-fsSLo f` or `-o/tmp/f`, wget's `-O` and `-qO f`, or the URL's own name
    for curl's `-O`, `-LO` and plain wget."""
    letter, long_flag = ("o", "--output") if name == "curl" else ("O", "--output-document")
    saved, remote = [], False
    for index, arg in enumerate(args):
        following = args[index + 1] if index + 1 < len(args) else ""
        if arg == long_flag or arg.startswith(long_flag + "="):
            saved.append(arg.split("=", 1)[1] if "=" in arg else following)
        elif arg == "--remote-name":
            remote = True
        elif arg.startswith("-") and not arg.startswith("--") and len(arg) > 1:
            at = arg.find(letter, 1)
            if at == 1 or (at > 1 and arg[1:at].isalpha()):  # the flags before it take no value
                saved.append(arg[at + 1:] or following)
            elif name == "curl" and "O" in arg and arg[1:].isalpha():
                remote = True
    if remote or (name == "wget" and not saved):
        folder = next((args[index + 1] for index, arg in enumerate(args[:-1]) if arg in ("-P", "--directory-prefix", "--output-dir")), "")
        saved += [os.path.join(folder, arg.split("?", 1)[0].rstrip("/").rsplit("/", 1)[-1]) for arg in args if re.match(r"(?:https?|ftp)://", arg)]
    return [os.path.normpath(path) for path in saved if path and path != "-"]


def _runs_what_it_downloaded(text: str, programs: list[tuple[str, list[str]]]) -> bool:
    """`curl -o i.sh URL && bash i.sh` is a download run straight away, as much as `curl URL | sh` is. Checked in one pass, in order. A program
    named as a command shows only its own name here, so that is compared by name, and a file handed to an interpreter by its whole path."""
    downloaded = {os.path.normpath(found) for found in _SAVED_BY_REDIRECT.findall(text)}
    runnable: set[str] = set()  # `./tool` shows here as `tool`, the same as one on the PATH, so it counts once chmod +x made it runnable
    for name, args in programs:
        if name in ("curl", "wget"):
            downloaded.update(_saved_as(name, args))
            continue
        if name == "chmod" and any("x" in arg for arg in args if arg.startswith("+") or re.fullmatch(r"[0-7]{3,4}", arg)):
            runnable.update(os.path.basename(arg) for arg in args if not arg.startswith("+") and not re.fullmatch(r"[0-7]{3,4}", arg))
        handed = next((arg for arg in args if not arg.startswith("-")), "") if name in RUNS_A_FILE and "-n" not in args else ""  # -n only checks syntax
        names = {os.path.basename(path) for path in downloaded}
        if downloaded and ((name in names and name in runnable) or (handed and os.path.normpath(handed) in downloaded)):
            return True
    return False


def _downloaded_run_or_credential_printed(text: str, programs: list[tuple[str, list[str]]]) -> str | None:
    """Two asks the owner chose on 2026-11-07: running a file the same command downloaded, and printing a credential file into the conversation."""
    if _runs_what_it_downloaded(text, programs):
        return "this runs a file it just downloaded."
    printed = credential_printed(programs)
    if printed:
        return f"this prints {printed}, which holds credentials, into the conversation and its logs. `cut -d= -f1 .env` shows what's set without the values."
    return None


def reason_for_a_person(text: str, programs: list[tuple[str, list[str]]], inside_project=lambda _: False, testing: list[bool] | None = None) -> str | None:
    """Why someone should see this command first. `programs` is each simple command's program and arguments, and `testing` whether each runs in a test environment."""
    whole = _whole_command_reason(text, programs)
    if whole:
        return whole
    guards = guarded_names(text)
    known: list[set[str]] = []  # what this command assigns, read once and only if a delete needs it, since a command can hold thousands

    def assigned() -> set[str]:
        if not known:
            known.append(assigned_names(text) | guards)
        return known[0]

    if "xargs" in text and "find" in text:
        piped = find_piped_to_a_delete(text, assigned())
        if piped:
            return piped
    for index, (name, args) in enumerate(programs):
        reason = _step_reason(name, args, text, inside_project, bool(testing and testing[index]), guards, assigned)
        if reason:
            return reason
    return None


def _whole_command_reason(text: str, programs: list[tuple[str, list[str]]]) -> str | None:
    """What the command as a whole does: switches off the checks, runs a download, prints a credential, or deletes too much on Windows."""
    if disables_checks(text) and SETTINGS_FILE.search(text):
        return "this turns off the checks on this session's work."
    if PIPE_TO_SHELL.search(re.sub(r"'[^']*'|\"[^\"]*\"", "''", text)) or SHELL_RUNS_DOWNLOAD.search(text) or POWERSHELL_RUNS_DOWNLOAD.search(text):
        return "this runs a download straight in a shell."
    reads_or_runs = _downloaded_run_or_credential_printed(text, programs)
    if reads_or_runs:
        return reads_or_runs
    windows = _WINDOWS_RECURSIVE_DELETE.search(_QUOTED_TEXT.sub("''", text))
    if windows and _TOO_MUCH_ON_WINDOWS.match(windows.group(1) or windows.group(3) or ""):
        return f"this recursively deletes {windows.group(1) or windows.group(3)}, and on Windows that skips the Recycle Bin."
    return None


def _step_reason(name: str, args: list[str], text: str, inside_project, testing: bool, guards: set[str], assigned: Callable[[], set[str]]) -> str | None:
    """Why one simple command needs a person. `assigned` gives what the whole command assigns, read the first time it's asked for."""
    unset = deletes_through_unset(name, args, assigned)
    if unset:
        return unset
    if name == "rm" and any(arg == "--recursive" or RECURSIVE_FLAG.fullmatch(arg) for arg in args):
        return deletes_too_much_of(args, text, inside_project, assigned())
    hard = hard_to_undo(name, args, testing, guards)
    if hard:
        return hard
    if name in SQL_CLIENTS and any(drops_data(arg) for arg in args):
        return "this drops or truncates data."
    shape = secret_shape(" ".join(args)) if name in NETWORK_CLIENTS else None
    return f"this sends what looks like {shape} over the network." if shape else None


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
    sentences = sentences_of(message)
    if not any(map(mentions_a_failure, sentences)):
        return True
    return any(CLAIMS_PASSING.search(s) and not SCOPED_CLAIM.search(s) and not NEGATED_CLAIM.search(s) and not mentions_a_failure(s) for s in sentences)


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


# ---------------------------------------------------------------- an edit that makes a check easier to pass, whatever ran before it (F270, F276)

# Each is a setting or wording that lets a check fail without failing anything. Counted before and after, so one that was already there isn't news.
_RELAXES = (
    ("lets a CI job or step fail without failing the build", re.compile(r"\bcontinue-on-error:[ \t]*true\b|\ballow_failure:[ \t]*true\b")),
    ("switches off a type or lint check for whole files or modules", re.compile(r"\bignore_errors[ \t]*=[ \t]*true\b|@ts-nocheck\b|/\*[ \t]*eslint-disable[ \t]*\*/|\bstrict[\"']?[ \t]*[:=][ \t]*false\b"
                                                                              r"|#[ \t]*(?:pylint|mypy|flake8)[ \t]*:[ \t]*(?:disable-all|ignore-errors|noqa)\b")),
    ("stops a failing check from failing the build", re.compile(r"<failOnError>[ \t]*false|<failOnViolation>[ \t]*false|<failsOnError>[ \t]*false|<testFailureIgnore>[ \t]*true"
                                                                r"|\bignoreFailures[ \t]*=[ \t]*true\b|\babortOnError[ \t]*[=(]?[ \t]*false\b|\bwarningsAsErrors[ \t]*[=(]?[ \t]*false\b"
                                                                r"|--exit-zero\b|\bfail_ci_if_error:[ \t]*false\b")),
    ("skips tests in the build", re.compile(r"<skipTests>[ \t]*true|\bmaven\.test\.skip[ \t]*=[ \t]*true|-DskipTests\b|--deselect\b|--ignore(?:-glob)?[= ]|--testPathIgnorePatterns\b"
                                            r"|--passWithNoTests\b|\bcollect_ignore\b")),
)
# A check's failure ignored in a script or Makefile: `pytest || true`, or make's `-` before a recipe line.
_CHECK_COMMAND = (r"(?:pytest|py\.test|tox|nox|mypy|pyright|ruff|flake8|pylint|bandit|eslint|tsc|jest|vitest|mocha|playwright|cypress|rspec|rubocop|phpunit|phpstan|psalm"
                  r"|golangci-lint|go[ \t]+(?:test|vet)|cargo[ \t]+(?:test|clippy)|(?:npm|yarn|pnpm|bun)[ \t]+(?:run[ \t]+)?(?:test|lint|typecheck|check)[\w:-]*"
                  r"|make[ \t]+(?:test|lint|check|verify)[\w-]*|mvnw?[ \t][^\n]{0,200}\b(?:test|verify)|gradlew?[ \t][^\n]{0,200}\b(?:test|check)|shellcheck|semgrep|spotbugs|checkstyle"
                  r"|detekt|ktlint|swiftlint|clippy|staticcheck|govulncheck)\b")
_CHECK_RUN = re.compile(_CHECK_COMMAND)
_FAILURE_IGNORED = re.compile(r"^\t-[ \t]*\S|(?:\|\||;)[ \t]*(?:true|:|exit[ \t]+0)[ \t]*(?:$|[;&|)#\"'])")
# Lint and type-check configuration, where an added path is one the checks now skip.
_EXCLUDING_CONFIG = re.compile(r"(?:^|/)(?:\.rubocop\.ya?ml|\.eslintignore|\.eslintrc[^/]*|eslint\.config\.[^/]+|pyproject\.toml|setup\.cfg|\.flake8|tox\.ini|\.?ruff\.toml|mypy\.ini"
                               r"|\.golangci\.ya?ml|tsconfig[^/]*\.json|\.stylelintignore|phpcs\.xml(?:\.dist)?|phpstan\.neon|\.pylintrc|sonar-project\.properties|jest\.config\.[^/]+"
                               r"|vitest\.config\.[^/]+|\.coveragerc|codecov\.ya?ml|\.swiftlint\.yml|detekt\.ya?ml)$")
_EXCLUDING_KEY = re.compile(r"(?i)\b(?:exclude|excludes|extend-exclude|ignore|ignores|ignore_patterns|ignorePatterns|omit|skip-dirs|skip-files|exclude-dirs|exclude-files"
                            r"|testPathIgnorePatterns|coveragePathIgnorePatterns|sonar\.exclusions|per-file-ignores)\b")
_GENERATED_PATH = re.compile(r"(?:^|[/\"'\s*])(?:db/schema\.rb|db/structure\.sql|bin|vendor|node_modules|tmp|log|logs|build|dist|out|target|coverage|generated|gen|\.venv|venv"
                             r"|__pycache__|public|storage|third_party|external|migrations?|\.git|\.cache|\.next|\.turbo|docs?)(?:/|[\"'\s]|$)"
                             r"|_pb2(?:_grpc)?\.py|\.pb\.go|\.min\.js|\.d\.ts\b|\.generated\.|\bschema\.rb\b")
# Each run starts only where its characters start: retried from inside a long word, the runs made this quadratic.
_PATH_ENTRY = re.compile(r"(?<![\w.*-])[\w.*-]+/[\w./*-]*|\*\*|(?<![\w-])[\w-]+\.(?:rb|py|js|ts|tsx|go|java|kt|php)\b")
_THRESHOLD = re.compile(r"(?i)\b(branches|functions|lines|statements|fail_under|fail-under|cov-fail-under|minimum[_-]?coverage|coverage[_-]?minimum|threshold|minimum)\b[\"']?[ \t]*[:=][ \t]*[\"']?(\d+(?:\.\d+)?)")
_EXACT = re.compile(r"\bassert(?:Equals?|Same|_eq!?)\b|\bassertThat\b[^\n]{0,300}\.(?:isEqualTo|isEqualByComparingTo|containsExactly)\b|\.toBe\(|\.toEqual\(|\.toStrictEqual\("
                    r"|\.to\s+eql?\b|\bassert\b[^\n]{0,300}==|\b(?:require|assert)\.Equal\(|\bEqual\(t,|\.to\.(?:equal|eql)\(")
_LOOSE = re.compile(r"\bassertNotNull\b|\bassertNotEquals?\b|\.isNotNull\(|\.toBeDefined\(|\.toBeTruthy\(|\.not\.toBeNull\(|\.not\.toBeUndefined\(|\bassert_not_nil\b|\bbe_present\b"
                    r"|\.to\s+be_truthy\b|\bNotNil\(|\bNotEmpty\(|\bassert\b[^\n=]{0,300}\bis\s+not\s+None\b|\bassertIsNotNone\(|\.to\.exist\b|\.to\.be\.ok\b")
_LITERAL = re.compile(r"\"[^\"\n]{0,200}\"|'[^'\n]{0,200}'|(?<![\w.])\d+(?:\.\d+)?(?![\w.])")
MAX_CHECKS_COMPARED = 20
_HOOK_COMMAND = re.compile(r"\"type\"[ \t]*:[ \t]*\"command\"")
_BUILD_FILE = re.compile(r"(?:^|/)(?:Dockerfile[^/]*|Containerfile|[^/]*\.dockerfile|Makefile|GNUmakefile|Jenkinsfile|Taskfile\.ya?ml|justfile|\.gitlab-ci\.yml|[^/]*\.sh)$"
                         r"|(?:^|/)(?:\.github/workflows|\.circleci|\.buildkite)/")


def _lines(text: str) -> list[str]:
    return [line.strip() for line in text.split("\n") if line.strip()]


class _Change(NamedTuple):
    """An edit, with the views of it the checks below compare. Lines are compared stripped, except where a recipe's tab or leading `-` matters."""
    path: str
    old: str
    new: str
    is_test: bool
    gained: str  # the lines it adds, repeats kept, joined: every relaxing pattern matches within a line, so these count what the files would
    lost: str
    added: list[str]  # stripped lines only the new text has
    removed: list[str]
    kept_old: set[str]


def how_a_change_relaxes(path: str, old: str, new: str, is_test: bool) -> str | None:
    """How this edit makes a check easier to pass whatever the code does, read from the change itself. A note, never a hold: the hold in
    how_an_edit_weakens is for edits right after a check failed."""
    change = _read_change(path, old, new, is_test)
    return next((how for check in _RELAXING_CHECKS for how in [check(change)] if how), None)


def _read_change(path: str, old: str, new: str, is_test: bool) -> _Change:
    old_counts, new_counts = Counter(old.split("\n")), Counter(new.split("\n"))
    old_lines, new_lines = _lines(old), _lines(new)
    kept_old, kept_new = set(old_lines), set(new_lines)  # built once: a set per line would be quadratic on a large file
    return _Change(path, old, new, is_test, "\n".join((new_counts - old_counts).elements()), "\n".join((old_counts - new_counts).elements()),
                   [line for line in new_lines if line not in kept_old], [line for line in old_lines if line not in kept_new], kept_old)


def _relaxing_setting(change: _Change) -> str | None:
    return next((how for how, pattern in _RELAXES if len(pattern.findall(change.gained)) > len(pattern.findall(change.lost))), None)


def _failure_ignored(change: _Change) -> str | None:
    raw_added = (line for line in change.new.split("\n") if line.strip() and line.strip() not in change.kept_old)
    return "lets a check's failure pass unnoticed" if any(_FAILURE_IGNORED.search(line) and _CHECK_RUN.search(line) for line in raw_added) else None


def _hooks_removed(change: _Change) -> str | None:
    fewer = SETTINGS_FILE.search(change.path) and len(_HOOK_COMMAND.findall(change.new)) < len(_HOOK_COMMAND.findall(change.old))
    return "removes hooks that check this session's work" if fewer else None


def _excluded_or_lowered(change: _Change) -> str | None:
    if not _EXCLUDING_CONFIG.search(change.path):
        return None
    excluded = _excluded_paths(change.new, set(change.added))
    return f"stops the checks covering {excluded}" if excluded else _lowered_threshold(change.old, change.new)


def _runs_check_steps(change: _Change) -> bool:
    """A build, CI or check configuration file, or a manifest whose scripts run checks, that this edit takes lines out of."""
    return bool((_BUILD_FILE.search(change.path) or CHECK_CONFIG.search(change.path) or change.path.endswith(("package.json", "pyproject.toml", "tox.ini"))) and change.removed)


def _check_step_removed(change: _Change) -> str | None:
    if not _runs_check_steps(change):
        return None
    dropped = list(dict.fromkeys(found.group(0) for line in change.removed for found in [_CHECK_RUN.search(line)] if found))[:MAX_CHECKS_COMPARED]
    kept = " ".join(change.added)
    gone = [check for check in dropped if check not in kept]  # each a pass over what was added, so only the first few
    return f"removes the step that runs `{gone[0]}`" if gone else None


def _packages_narrowed(change: _Change) -> str | None:
    if not _runs_check_steps(change):
        return None
    narrowed = next((line for line in change.removed if "./..." in line and _CHECK_RUN.search(line)), None)
    if narrowed and not any("./..." in line for line in change.added if _CHECK_RUN.search(line)):
        return "narrows which packages the tests run on"
    return None


def _assertions_loosened(change: _Change) -> str | None:
    if not change.is_test:
        return None
    loosened = live_count(_EXACT, change.gained) < live_count(_EXACT, change.lost) and live_count(_LOOSE, change.gained) > live_count(_LOOSE, change.lost)
    return "replaces exact assertions with ones that pass for almost any value" if loosened else None


def _expected_values_changed(change: _Change) -> str | None:
    if not change.is_test:
        return None
    before = {_LITERAL.sub("§", line) for line in change.removed if ASSERTION.search(line)}
    changed = [line for line in change.added if ASSERTION.search(line) and _LITERAL.sub("§", line) in before]
    return f"changes the expected values in {len(changed)} assertion{'s' if len(changed) > 1 else ''}" if changed else None


# In the order they're asked: the first that applies names how the edit relaxes a check.
_RELAXING_CHECKS = (_relaxing_setting, _failure_ignored, _hooks_removed, _excluded_or_lowered, _check_step_removed, _packages_narrowed, _assertions_loosened,
                    _expected_values_changed)


def _excluded_paths(new: str, added: set[str]) -> str | None:
    """An added path, under an exclude or ignore key, that is hand-written code rather than generated or vendored files."""
    key_seen = False
    for line in new.split("\n"):
        stripped = line.strip()
        if _EXCLUDING_KEY.search(stripped):
            key_seen = True
        elif re.match(r"[ \t]*[\w.\"'-]+[ \t]*[:=]", line) and not stripped.startswith("-"):
            key_seen = False  # another key, so the list under the exclusion has ended
        if stripped in added and (key_seen or _EXCLUDING_KEY.search(stripped)) and not _GENERATED_PATH.search(stripped):
            entry = _PATH_ENTRY.search(stripped.split("=", 1)[-1])
            if entry:
                return entry.group(0)
    return None


def _lowered_threshold(old: str, new: str) -> str | None:
    before = {}
    for key, value in _THRESHOLD.findall(old):
        before.setdefault(key.lower(), []).append(float(value))
    for key, value in _THRESHOLD.findall(new):
        values = before.get(key.lower())
        if values and float(value) < min(values):
            return f"lowers the {key} threshold to {value}"
    return None


def pipe_to_shell_added(path: str, old: str, new: str) -> str | None:
    """The host of a download newly piped into a shell in a build, CI or script file, which runs whatever that URL serves each time."""
    if not _BUILD_FILE.search(path) and not CHECK_CONFIG.search(path):
        return None
    before = set(_lines(old))
    for line in _lines(new):
        if line in before:
            continue
        unquoted = re.sub(r"'[^']*'|\"[^\"]*\"", "''", line)
        if PIPE_TO_SHELL.search(unquoted) or SHELL_RUNS_DOWNLOAD.search(line):
            found = re.search(r"https?://([^/\s'\")]+)", line)
            return found.group(1) if found else "the network"
    return None
