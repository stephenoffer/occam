#!/usr/bin/env python3
"""Enforcement hooks for the occam plugin.

A skill is guidance the model may or may not follow. These hooks are the deterministic part:

  session-start   says occam is active, and offers a reload after compaction
  user-prompt     records the request, and notices review-only and plan-only requests
  expansion       records a skill the user typed by name
  subagent-stop   records a subagent that finished, so a review counts only once it has completed
  pre-tool        holds code edits until the skill is loaded, holds edits on read-only turns,
                  asks before git commands that could destroy someone's work, holds edits until
                  the relevant reference is read, mentions language skills once, holds edits that make
                  a check easier to pass or write a credential, and denies credentials in web requests
  post-tool       records what happened, mentions once when an edited source file is very large, and
                  mentions a run of failed checks once
  post-failure    records a failed command, because a failing check still ran
  stop            sends the agent back once if it edited code and skipped verification, or if its final
                  message disagrees with the record (see occam_evidence.py and docs/failure-modes.md)

State comes only from documented hook events, kept per session in the plugin's data directory.
It does not parse the transcript, whose format is undocumented and which may lag behind.

Limits, on purpose:
  * Any error fails open. A broken hook must not wedge someone's session.
  * Holds give way after MAX_HOLDS retries of the same edit, and Stop continues at most once, so nothing
    can loop. Read-only turns are the exception: they don't give way, because the agent reports and stops
    rather than looping, and the user can lift them in plain words.
  * From the shell, only a named list of destructive actions stops a command. The other holds are for edit tools.
  * Shell commands are parsed best-effort. This is a guardrail, not a security boundary.
  * OCCAM_HOOKS=off in the environment turns all of this off.

Messages are written as facts rather than commands, as the Claude Code docs recommend.
"""

from __future__ import annotations  # the stock macOS python3 is 3.9

import hashlib
import json
import os
import re
import sys
import tempfile
import time
from pathlib import Path

import occam_evidence as evidence  # noqa: E402  (beside this script, like scan_notes)
import docs_notes  # noqa: E402  (beside this script, like scan_notes)
import scan_notes  # noqa: E402  (beside this script, on sys.path because Python put it there)
import unfinished  # noqa: E402  (beside this script, like scan_notes)
from python_notes import edit_facts, prompt_facts, read_source, say_once, shadow_note  # noqa: E402
from occam_commands import (INSTALLERS, golden_command, head, inline_python_writes, is_check, logical_lines, nbconvert_target, output_text, run_by, runs_inline_python, shell_tokens, shows_no_pass, unquote,  # noqa: E402
                            writes_project_files)

MAX_HOLDS = 2
REWRITE_MIN_LINES = 30
MAX_HOLDS_ANY_INPUT = 6
STATE_RETENTION_SECONDS = 7 * 24 * 3600
CORE_SKILL = "occam"
REVIEWER = "code-reviewer"
EDIT_TOOLS = {"Edit", "Write", "MultiEdit", "NotebookEdit"}
AGENT_TOOLS = {"Agent", "Task"}
SHELL_TOOLS = {"Bash", "PowerShell"}
# Anything beyond one plain command with plain paths can change what those paths mean.
NOT_PLAIN = re.compile(r"[;&|`$(){}*?\[\]~\"'\\\n]|\s(?:-C|--chdir)\b")
APPROVAL_TOOLS = {"ExitPlanMode", "AskUserQuestion"}
FOREGROUND_BLOCKING_TASKS = {"subagent", "workflow", "teammate", "cloud session"}

DOC_SUFFIXES = {".md", ".markdown", ".mdx", ".txt", ".rst", ".adoc", ".org", ".csv", ".tsv", ".log",
                ".png", ".jpg", ".jpeg", ".gif", ".svg", ".pdf"}
LANGUAGE_SKILLS = {
    **dict.fromkeys((".py", ".pyi", ".pyw", ".pyx", ".pxd", ".ipynb"), "occam-python"),
    **dict.fromkeys((".ts", ".tsx", ".mts", ".cts", ".js", ".jsx", ".mjs", ".cjs"), "occam-typescript"),
    ".rs": "occam-rust",
    ".go": "occam-go",
    **dict.fromkeys((".java", ".kt", ".kts"), "occam-jvm"),
    **dict.fromkeys((".c", ".h", ".cc", ".cpp", ".cxx", ".hpp", ".hh"), "occam-cpp"),
    ".sql": "occam-sql",
    **dict.fromkeys((".sh", ".bash", ".zsh"), "occam-shell"),
}
LANGUAGE_NAMES = {"occam-python": "Python", "occam-typescript": "TypeScript and JavaScript", "occam-rust": "Rust",
                  "occam-go": "Go", "occam-jvm": "Java and Kotlin", "occam-cpp": "C and C++", "occam-sql": "SQL",
                  "occam-shell": "shell"}

READ_ONLY = re.compile(
    r"(?<![\w-])(review|plan|planning|audit)[- ]only\b"
    r"|\bread[- ]only\s+(review|pass|audit|please|for now)\b"
    r"|\b(do not|don'?t|dont|without)\s+(change|changing|modify|modifying|edit|editing|touch|touching|fix|fixing|make|making|write|writing|apply|applying)\s+"
    r"(anything|any\s+(code|files?|changes|edits|fixes)|the code|changes|edits)\b"
    r"(?!\s+(else|in|under|outside|except|other|that|besides|from|unless|to the)\b)"
    r"|\bno (code|file|source) (changes|edits)\b"
    r"|\bno changes (please|for now|yet)\b",
    re.I,
)
READ_ONLY_LIFTED = re.compile(
    r"\b(no longer|not|isn'?t|not just)\s+(a\s+)?(review|plan|planning|audit|read)[- ]only\b"
    r"|\b(go ahead|you can (edit|change|fix)|feel free to (edit|change|fix)|make the (change|fix|edit)s?|apply (the|your) (change|fix|edit)s?)\b",
    re.I,
)
AUDIT_REQUEST = re.compile(r"\b(audit|deslop|vibe[- ]coded|ai[- ]generated (?:code|codebase|app)|clean ?up (?:this|the) (?:code|codebase|repo)|pay down)\b", re.I)
AUDIT_ONLY = re.compile(r"^\W*(?:(?:please|hey|ok|okay|can you|could you|would you|just|go ahead and|let'?s)\W+)*(?:audit|assess)\b(?!\s+(?:trail|log\w*|entries)\b)"
                        r"|\b(?:run|do|perform|conduct|want|need)\s+(?:an?\s+)?(?:\w+\s+){0,2}audit\b(?!\s+(?:trail|log\w*)\b)|^\W*what'?s wrong with\b", re.I)
AUDIT_WITH_REPAIR = re.compile(r"\b(?:fix(?:es|ing)?|repair\w*|clean(?:ing)? ?up|harden\w*|refactor\w*|deslop\w*|remediat\w*|resolve|rewrite|improve|update|implement|add|patch|change|make|build|create|write)\b", re.I)
# A request that opens by asking for work keeps its restrictions as restrictions. "Fix the bug. Don't change any APIs" isn't read-only.
BUILD_REQUEST = re.compile(r"(?:^|[.!?\n]\s*)(?:(?:please|can you|could you|would you|let'?s)\s+)*(?:fix|refactor|add|implement|write|build|create|update|change|remove|delete|rename|migrate|speed up|optimi[sz]e|make|improve|port|convert|clean up|harden)\b"
                           r"(?!\s+(?:nothing\b|no\b|up\b|an?\s+(?:plan|review|report|summary|analysis|audit|assessment)\b(?!-)))", re.I)
EXPLICIT_READ_ONLY = re.compile(r"(?<![\w-])(?<!\ba\s)(?<!\ban\s)(?:review|plan|planning|audit)[- ]only\b(?!\s+(?:role|user|mode|access|token|permission|flag|field)\b)"
                                r"|\b(?:fix|change|touch|edit|modify|update)\s+nothing\b", re.I)
NOT_FROM_THE_USER = re.compile(r"\s*(<task-notification\b|<agent-message\b|<cross-session-message\b|Another Claude session sent a message)", re.I)
REVIEW_OR_PLAN = re.compile(r"\b(review|audit|pull request|merge|plan how|how would you (add|build|change)|architecture)\b", re.I)
HIGH_CONSEQUENCE = re.compile(
    r"(^|[/_.\-])(auth|authn|authz|oauth|login|sessions?|tokens?|passwords?|secrets?|credentials?|permissions?|acl|rbac"
    r"|tenants?|tenancy|billing|payments?|invoices?|checkout|refunds?|ledgers?|migrations?|migrate|crypto|webhooks?"
    r"|signatures?)([/_.\-]|$)",
    re.I,
)
SECURITY_PROMPT = re.compile(r"\b(authenticat\w*|authoriz\w*|tenant\w*|permissions?|credentials?|secrets?|vulnerab\w*|injection)\b", re.I)
PERFORMANCE_PROMPT = re.compile(
    r"\b(p[59]\d|latency|throughput|slow(er|ness)?|performance|faster|speed up|scal(e|es|ing|able|ability)"
    r"|out of memory|oom|peak rss|memory (limit|usage)"
    r"|(\d{1,3}(,\d{3})+|\d{4,}|\d+\s*(k|m|million|billion|thousand))\s*(rows|records|requests|urls|items|events|users))\b",
    re.I,
)
DEPENDENCY_MANIFEST = re.compile(
    r"(^|/)(pyproject\.toml|requirements[^/]*\.(txt|in)|requirements/[^/]+\.(txt|in)|constraints[^/]*\.txt|environment\.ya?ml"
    r"|setup\.py|setup\.cfg|Pipfile|package\.json|Cargo\.toml|go\.mod|pom\.xml|build\.gradle(\.kts)?|Gemfile)$"
)
DEPENDENCY_PROMPT = re.compile(r"\b(new dependency|which library|should we (use|add|bring|pull)|add a dependency)\b", re.I)
TEST_PATH = re.compile(r"(^|/)(tests?|spec|__tests__)/|(^|/)(test_[^/]+|conftest\.py)$|_test\.[a-z]+$|\.(test|spec)\.[a-z]+$")
PYTHON_PROMPT = re.compile(r"\b(python|pytest|django|flask|fastapi|pandas|notebooks?|ipynb)\b|\.pyi?\b", re.I)

# pylint's max-module-lines default. A prompt to look, not a limit: nothing is held.
LARGE_FILE_LINES = 1000
GENERATED_MARK = re.compile(rb"@generated|DO NOT EDIT|(?i:(code|file) generated by)|(?im:^\W*(auto-?)?generated)"
                            rb"|(?i:generated[^\n]*do not edit|do not edit[^\n]*generated)")
NOT_MEASURED_IN_LINES = {".ipynb", ".sql"}

CLAIMS_PASSING = re.compile(r"(\b(tests?|suite|checks?)\b[^.\n]{0,40}\b(pass|passes|passing|passed|green)\b|\b\d+\s+passed\b)", re.I)
NEGATED_CLAIM = re.compile(r"\b(not|n't|couldn.t|unable|without|never|tells you nothing|no test)\b", re.I)
GIT = r"(?:^|[\s;&|(\"'`])(?:[^\s;&|(\"'`]*/)?git(?:\s+(?:-[cC]\s+\S+|--[\w-]+(?:=\S+)?))*\s+"
# Each of these can lose work, and a word in a prompt ("fix the password reset flow") isn't consent.
DESTRUCTIVE_GIT = {
    "reset": re.compile(GIT + r"reset\b[^;&|]*--hard"),
    "checkout": re.compile(GIT + r"checkout\s+(?:[^;&|]*\s)?(?:--\s|\.(?:\s|$))"),
    "restore": re.compile(GIT + r"restore\s(?![^;&|]*--staged)"),
    "clean": re.compile(GIT + r"clean\b[^;&|]*\s-[a-zA-Z]*f"),
    "stash": re.compile(GIT + r"stash\b(?!\s+(?:list|show)\b)"),
    "push": re.compile(GIT + r"push\b[^;&|]*(?:--force|\s-f\b)"),
    "rebase": re.compile(GIT + r"rebase\b"),
    "commit --amend": re.compile(GIT + r"commit\b[^;&|]*--amend\b"),
    "branch": re.compile(GIT + r"branch\s+[^;&|]*-D\b"),
}


# Semantics in each language that commonly go wrong. When an edit or request involves one, the first
# edit in that language pauses once so the agent decides whether to load the skill. Retrying declines it.
LANGUAGE_RISKS = {
    "occam-python": ("async, cancellation, shared state, memory, time, money, text, packaging, module structure, tests, unsafe APIs or notebooks",
                     r"\b(async|await|asyncio|cancel\w*|thread\w*|multiprocessing|concurren\w*|datetime|timezone|Decimal"
                     r"|pandas|numpy|generator|yield|memory|encod\w*|unicode|pickle|subprocess|__all__|setup\.py"
                     r"|pyproject|__init__\.py|conftest|monkeypatch|yaml\.load|lru_cache|tarfile|os\.system"
                     r"|circular imports?|split (up )?(the|this) (file|module)|audit\w*|notebooks?|ipynb)\b"
                     r"|\b(round|float|eval|exec)\(|\b(pytest|mock)\.\w|\bshell=True"),
    "occam-typescript": ("null versus undefined, promises, cancellation, number precision or output escaping",
                         r"\b(async|await|cancel\w*|Promise|AbortController|BigInt|parseInt|parseFloat|JSON\.parse|innerHTML|eval|null|undefined|falsy)\b|\|\||\?\?"),
    "occam-rust": ("ownership, panics, unsafe code or async cancellation",
                   r"\b(unsafe|unwrap|expect|panic\w*|\.await|async|cancel\w*|Mutex|Arc|RefCell|lifetime)\b"),
    "occam-go": ("goroutine lifetimes, context cancellation, nil or error handling",
                 r"\b(go func|goroutine|context\.|cancel\w*|chan|sync\.|defer|panic|nil|errors\.)\b"),
    "occam-jvm": ("nullability, interruption, coroutine cancellation, thread pools or exact decimals",
                  r"\b(synchronized|Thread|cancel\w*|Executor\w*|CompletableFuture|BigDecimal|suspend|GlobalScope|Transactional|Optional|InterruptedException)\b"),
    "occam-cpp": ("ownership, lifetimes or undefined behavior",
                  r"\b(malloc|free|new|delete|memcpy|strcpy|sprintf|reinterpret_cast|std::thread|std::move|shared_ptr|unique_ptr|overflow)\b"),
    "occam-sql": ("NULL logic, join grain, time, money, collation or migrations",
                 r"\b(join|group by|null|not in|timestamp|datetime|date\(|alter|drop|migrat\w*|collate|sum|avg|decimal|real)\b"),
    "occam-shell": ("quoting, failure handling and portability", r"."),
}


# ---------------------------------------------------------------- state

def state_file(session_id: str | None) -> Path:
    uid = getattr(os, "getuid", lambda: "user")()
    base = os.environ.get("CLAUDE_PLUGIN_DATA") or os.path.join(tempfile.gettempdir(), f"occam-{uid}")
    folder = Path(base) / "sessions"
    folder.mkdir(parents=True, exist_ok=True)
    return folder / (re.sub(r"[^A-Za-z0-9_.-]", "_", session_id or "unknown") + ".jsonl")


def record(event: dict, **entry) -> None:
    with open(state_file(event.get("session_id")), "a", encoding="utf-8") as handle:
        handle.write(json.dumps(entry) + "\n")


class Session:
    """What has happened so far, derived from recorded hook events."""

    def __init__(self, event: dict) -> None:
        path = state_file(event.get("session_id"))
        self.entries: list[dict] = []
        if path.exists():
            for line in path.read_text(encoding="utf-8", errors="replace").split("\n"):
                try:
                    self.entries.append(json.loads(line))
                except ValueError:
                    continue
        start = max((i for i, e in enumerate(self.entries) if e.get("kind") == "prompt"), default=-1)
        self.prompt_entry = self.entries[start] if start >= 0 else {}
        self.turn = self.entries[start + 1:]
        self.prompt = self.prompt_entry.get("text", "")
        self.read_only = bool(self.prompt_entry.get("read_only")) and not any(e.get("kind") == "approved" for e in self.turn)

    def has(self, kind: str, name: str | None = None) -> bool:
        return any(e.get("kind") == kind and (name is None or e.get("name") == name) for e in self.entries)

    def count(self, kind: str, name: str) -> int:
        return sum(1 for e in self.entries if e.get("kind") == kind and e.get("name") == name)

    def code_edits(self) -> list[dict]:
        return [e for e in self.turn if e.get("kind") == "edit" and e.get("code")]

    def after_last_edit(self, kind: str) -> list[dict]:
        last = max(i for i, e in enumerate(self.turn) if e.get("kind") == "edit" and e.get("code"))
        return [e for e in self.turn[last + 1:] if e.get("kind") == kind]


# ---------------------------------------------------------------- classifying paths and commands

def is_under(path: str, folder: str | None) -> bool:
    if not folder:
        return False
    root = os.path.realpath(folder)
    return path == root or path.startswith(root + os.sep)


def in_project(file_path: str, event: dict) -> bool:
    """True for files in the project. Scratch files and anything outside the project aren't held."""
    cwd = event.get("cwd") or os.getcwd()
    path = os.path.realpath(os.path.join(cwd, file_path))
    if is_under(path, event.get("scratchpad_dir")):
        return False
    return is_under(path, cwd) or is_under(path, os.environ.get("CLAUDE_PROJECT_DIR"))


def is_code(file_path: str) -> bool:
    if DEPENDENCY_MANIFEST.search(file_path):
        return True
    return Path(file_path).suffix.lower() not in DOC_SUFFIXES


def without_heredoc_bodies(command: str) -> str:
    return re.sub(r"<<-?\s*['\"]?(\w+)['\"]?([^\n]*)\n.*?\n\s*\1\b", r"<<\1\2", command, flags=re.S)


def expand_variables(command: str) -> str:
    """Resolve simple assignments, so `G=/usr/bin/git; $G reset --hard` still reads as git.

    Only whole values: a part of one, such as a lone opening quote, would make the lexer give up on the line and hide
    everything on it. A value with a substitution or a quote inside stays a variable, which can't be judged from here.
    """
    assignment = r"""(?:^|[\s;&|(])([A-Za-z_]\w*)=(?:"([^"'`()]*)"|'([^"']*)'|([^\s;&|()`"']+))(?=$|[\s;&|)])"""
    for name, double_quoted, single_quoted, bare in re.findall(assignment, command):
        value = double_quoted or single_quoted or bare
        command = re.sub(r"\$\{?" + re.escape(name) + r"\b\}?", lambda _: value, command)
    return command


def parse_shell(command: str) -> tuple[list[list[str]], list[str]]:
    """Split a command line into its simple commands and its redirect targets. Best-effort."""
    commands: list[list[str]] = []
    targets: list[str] = []
    for line in logical_lines(without_heredoc_bodies(expand_variables(command))):
        tokens = shell_tokens(line)
        current: list[str] = []
        index = 0
        while index < len(tokens):
            token = tokens[index]
            if set(token) <= set("();<>|&"):
                if ">" in token:
                    target = tokens[index + 1] if index + 1 < len(tokens) else ""
                    if not (token.endswith("&") and target.isdigit()):
                        targets.append(unquote(target))
                    index += 2
                    continue
                if "<" in token:
                    index += 2
                    continue
                if current:
                    commands.append(current)
                current = []
            else:
                current.append(token)
            index += 1
        if current:
            commands.append(current)
    for words in list(commands):  # bash -c '...' and friends
        name, args = head(words)
        if name in ("bash", "sh", "zsh", "eval") and args:
            inner = args[1] if args[0] == "-c" and len(args) > 1 else args[0] if name == "eval" else ""
            if inner:
                more, more_targets = parse_shell(unquote(inner))
                commands += more
                targets += more_targets
    return commands, targets


def project_path(word: str, event: dict) -> bool:
    if not word or word.startswith(("$", "/dev/", "-", "&")) or word.isdigit():
        return False
    return in_project(word, event)


def leaves_project(place: str, event: dict) -> bool:
    """True for a `cd` known to go elsewhere. `..`, `-` and an unknown variable can lead straight back."""
    if re.match(r"\$\{?TMPDIR\b", place):
        return True
    return os.path.isabs(place) and not in_project(place, event)


def shell_edits(command: str, event: dict) -> list[str]:
    """Paths this command writes in the project, with "" where it writes but the path isn't clear. Best-effort."""
    edits = [target for target in inline_python_writes(command) if not target or project_path(target, event)]
    commands, targets = parse_shell(command)
    edits += [target for target in targets if project_path(target, event)]
    for words in commands:
        name, args = run_by(words)
        paths = [arg for arg in args if not arg.startswith("-")]
        tool = scan_notes.occam_subcommand(words)
        if tool and tool[0] == "fix" and "--apply" in tool[1]:
            edits.append("")
        elif tool and "--out" in tool[1]:  # baseline and ledger report write where they're told
            edits.append("")
        elif tool and tool[0] == "golden":  # it runs whatever follows, so judge that
            edits += shell_edits(" ".join(golden_command(tool[1])), event)
        in_place = any(re.fullmatch(r"-[a-zA-Z]*i\S*|--in-place\S*", arg) for arg in args)
        if name in ("sed", "perl") and in_place:  # BSD sed's `-i ''` puts an empty word before the script
            edits += [path for path in paths[2 if paths[:1] == [""] else 1:] if project_path(path, event)] or [""]
        elif name in ("tee", "truncate", "touch", "rm", "mv"):
            edits += [path for path in paths if project_path(path, event)]
        elif name == "cp" and paths and project_path(paths[-1], event):
            edits.append(paths[-1])
        elif name == "patch" or (name == "git" and args[:1] == ["apply"]):
            edits.append("")
        elif name == "git" and args[:1] == ["rm"]:
            edits += [path for path in paths[1:] if project_path(path, event)]
        elif writes_project_files(name, args):
            edits.append("")
        elif name == "papermill" and len(paths) > 1 and project_path(paths[1], event):
            edits.append(paths[1])
        elif name == "jupyter":
            target = nbconvert_target(args)
            if target == "" or (target and project_path(target, event)):
                edits.append(target)
    places = [head(words)[1][0] for words in commands if head(words)[0] in ("cd", "pushd") and head(words)[1]]
    outside = places and all(leaves_project(unquote(place), event) for place in places)
    return [edit for edit in edits if os.path.isabs(edit)] if outside else edits  # after `cd $TMPDIR`, relative paths aren't the project's


def is_diff(words: list[str]) -> bool:
    name, args = head(words)
    positional = [arg for arg in args if not arg.startswith("-")]
    return name == "git" and bool(positional) and positional[0] in ("diff", "show", "status")


def destructive_git(command: str) -> str | None:
    """The git operation in this command that can lose work."""
    text = expand_variables(without_heredoc_bodies(command))
    return next((operation for operation, pattern in DESTRUCTIVE_GIT.items() if pattern.search(text)), None)


def relative_path(file_path: str, event: dict) -> str:
    """Relative to the project, so a parent directory's name can't make every file look high consequence."""
    if not file_path:
        return ""
    cwd = event.get("cwd") or os.getcwd()
    path = os.path.realpath(os.path.join(cwd, file_path))
    for root in (os.environ.get("CLAUDE_PROJECT_DIR"), cwd):
        if root and is_under(path, root):
            return os.path.relpath(path, os.path.realpath(root)).replace("\\", "/")
    return file_path.replace("\\", "/")


def skill_name(raw: str) -> str:
    return (raw or "").split(":")[-1].strip()


def reference_path(name: str, skill: str = CORE_SKILL) -> str:
    root = os.environ.get("CLAUDE_PLUGIN_ROOT") or str(Path(__file__).resolve().parents[1])
    return str(Path(root) / "skills" / skill / "references" / f"{name}.md")


# ---------------------------------------------------------------- output

def respond(event_name: str, **fields) -> dict:
    return {"hookSpecificOutput": {"hookEventName": event_name, **fields}}


def context(event_name: str, text: str) -> dict:
    return respond(event_name, additionalContext=text)


def hold(event: dict, session: Session, name: str, fact: str, next_step: str, limit: int = MAX_HOLDS) -> dict:
    """Deny, unless this same call has been held `limit` times. Then let it through and say so."""
    # A shell call's description is free text, so rewording it doesn't make a retry a different call.
    call = event.get("tool_input") or {}
    digest = hashlib.sha1(json.dumps(call.get("command", call), sort_keys=True).encode()).hexdigest()[:12]
    key = f"{name}:{digest}"
    total = sum(1 for e in session.entries if e.get("kind") == "held" and str(e.get("name", "")).startswith(name + ":"))
    if session.count("held", key) >= limit or total >= MAX_HOLDS_ANY_INPUT:
        return context("PreToolUse", f"occam: this went ahead without it: {fact} That is worth stating in the final report.")
    record(event, kind="held", name=key)
    return respond("PreToolUse", permissionDecision="deny", permissionDecisionReason=f"occam: {fact} {next_step}")


# ---------------------------------------------------------------- comparing what is said and done with the record

def deleted_paths(command: str, event: dict) -> list[str]:
    found = []
    for words in parse_shell(command)[0]:
        name, args = head(words)
        if name == "git" and args[:1] == ["rm"] and "--cached" not in args:
            args = args[1:]
        elif name != "rm":
            continue
        found += [relative_path(arg, event) for arg in args if not arg.startswith("-") and project_path(arg, event)]
    return found


def weakens_a_check(name: str, tool_input: dict, event: dict, session: Session, code: list[str]) -> tuple[str, str] | None:
    """(path, how) when this edit could make a check easier to pass, rather than making the code pass it."""
    if name in SHELL_TOOLS:
        deleted = deleted_paths(tool_input.get("command", ""), event)
        created = {e.get("path") for e in session.turn if e.get("kind") == "created"}
        for path in code:
            is_test_source = (TEST_PATH.search(path) and Path(path).suffix.lower() in LANGUAGE_SKILLS) or os.path.basename(path) in evidence.TEST_DIRS
            if is_test_source and path in deleted and path not in created:
                return path, "deletes a test file"
        return None
    if not code:
        return None
    old, new = evidence.old_and_new_text(name, tool_input, event.get("cwd"))
    how = evidence.how_an_edit_weakens(code[0], old, new, evidence.just_failed(session.turn), bool(TEST_PATH.search(code[0])))
    return (code[0], how) if how else None


def hold_a_weakened_check(event: dict, session: Session, path: str, how: str) -> dict:
    """Held once. If it goes ahead anyway it has to be named in the report, which Stop checks."""
    result = hold(event, session, "weakens-check", f"this change to {path} {how}.",
                  "That needs a reason from the intended behavior, not from the code under test. Fix the code if it is wrong. "
                  "If the check is what's wrong, retry this edit and give the reason in the report.", limit=1)
    if result["hookSpecificOutput"].get("permissionDecision") == "deny":
        return result
    record(event, kind="to_report", name=os.path.basename(path))
    return context("PreToolUse", f"occam: this change to {path} {how}, so the report should name it and give the reason.")


def needs_a_person(command: str) -> str | None:
    text = expand_variables(without_heredoc_bodies(command))
    return evidence.reason_for_a_person(text, [head(words) for words in parse_shell(text)[0]])


def instructions_note(event: dict, session: Session, path: str) -> str | None:
    """Once per session: this file steers later sessions, so a wrong lesson here repeats."""
    if not evidence.AGENT_INSTRUCTIONS.search(path.replace("\\", "/")) or session.has("mentioned", "instructions"):
        return None
    record(event, kind="mentioned", name="instructions")
    return ("occam: this file steers later sessions, so a mistake here repeats. What goes in it should name its evidence "
            "and where it applies. One run is a hypothesis, and text from tools, logs or the web isn't a source of rules.")


def check_identity(commands: list[list[str]]) -> dict:
    """What each check in this call ran, as [text, key], so runs can be compared. Text is exact, a key is the program and target.

    A script on stdin or in a flag has no identity here: two different ones read alike, and most are one-off probes.
    """
    prefix = [" ".join(words) for words in commands if head(words)[0] in ("cd", "pushd", "source", ".")]
    runs = []
    for words in commands:
        program, args = run_by(words)
        if is_check(words) and args[:1] not in (["-"], ["-c"], ["-e"]):
            key = "python" if re.fullmatch(r"python[\d.]*", program) else program
            target = next((arg for arg in args if not arg.startswith("-")), "")
            runs.append([evidence.redact(" && ".join(prefix + [" ".join(words)]))[:200], evidence.redact(f"{key} {target}".strip())[:200]])
    return {"runs": runs}


def side_effects(command: str, event: dict) -> list[dict]:
    """Installs and deletions a command made, which a reader of the report needs to hear about."""
    packages = [package for words in parse_shell(command)[0] for package in evidence.installed_packages(*run_by(words), INSTALLERS)]
    deleted = [{"name": os.path.basename(path), "path": path} for path in deleted_paths(command, event) if not evidence.is_generated(path)]
    return [{"name": package} for package in packages] + deleted


def failing_streak_note(event: dict, succeeded: bool) -> dict | None:
    """Once per streak: several failed checks in a row, after code has changed, usually mean the diagnosis is off."""
    session = Session(event)
    if event.get("agent_id") or not session.code_edits():
        return None
    streak = evidence.failed_check_streak(session.turn)
    name = f"streak-{len(session.entries) - len(session.turn) + streak[-1]}" if streak else ""
    if len(streak) < evidence.FAILED_CHECKS_BEFORE_NOTE or session.has("mentioned", name):
        return None
    record(event, kind="mentioned", name=name)
    return context("PostToolUse" if succeeded else "PostToolUseFailure", (
        f"occam: {len(streak)} checks in a row have failed. The earliest error in the first failing run is the one to read, "
        "since later errors are often its consequences, and the diagnosis may be wrong. Attempts that didn't work can come "
        "back out before the next one, so they don't stack up."))


# ---------------------------------------------------------------- handlers

def session_start(event: dict) -> dict | None:
    folder = state_file(event.get("session_id")).parent
    for old in folder.glob("*.jsonl"):
        try:
            if time.time() - old.stat().st_mtime > STATE_RETENTION_SECONDS:
                old.unlink()
        except OSError:
            continue
    if event.get("source") == "compact":
        return context("SessionStart", "The conversation was compacted, so the occam skill's full text may no longer "
                                       "be in context. Loading `occam:occam` again restores it.")
    return context("SessionStart", "The occam plugin is active. Its `occam:occam` skill covers changing and reviewing "
                                   "code. Code edits through edit tools are held until that skill has been loaded.")


def python_project(event: dict) -> bool:
    folders = [event.get("cwd") or os.getcwd(), os.environ.get("CLAUDE_PROJECT_DIR")]
    markers = ("pyproject.toml", "setup.py", "setup.cfg", "requirements.txt", "Pipfile")
    return any(folder and os.path.exists(os.path.join(folder, name)) for folder in folders for name in markers)


def visible_prompt(prompt: str) -> str:
    """The user's own words, without pasted material or quoted code."""
    text = re.sub(r"<pasted_content\b.*?</pasted_content>", " ", prompt, flags=re.S | re.I)
    text = re.sub(r"```.*?```", " ", text, flags=re.S)
    return re.sub(r"`[^`\n]*`", " ", text)


def reads_as_read_only(words: str) -> bool:
    explicit = EXPLICIT_READ_ONLY.search(words)
    if BUILD_REQUEST.search(words) and not explicit:
        return False
    audit_only = bool(AUDIT_ONLY.search(words)) and not AUDIT_WITH_REPAIR.search(words)
    lifted = READ_ONLY_LIFTED.search(re.sub(r"go ahead and (?:audit|assess)\b", "", words, flags=re.I))
    return bool(explicit or READ_ONLY.search(words) or audit_only) and not lifted


def user_prompt(event: dict) -> dict | None:
    prompt = event.get("prompt") or ""
    # These hooks also fire when a background agent reports back. That isn't a new request.
    if NOT_FROM_THE_USER.match(prompt):
        return None
    words = visible_prompt(prompt)
    read_only = reads_as_read_only(words)
    record(event, kind="prompt", text=evidence.redact(prompt)[:4000], read_only=read_only)
    typed = re.match(r"\s*/(?:occam:)?(occam[\w-]*)\b", prompt)
    if typed:
        record(event, kind="skill", name=typed.group(1))
    notes = []
    if read_only:
        notes.append("This request reads as review-only or plan-only, so edits to project files are held for this turn.")
    if not typed and not Session(event).has("skill", CORE_SKILL) and (read_only or REVIEW_OR_PLAN.search(words)):
        notes.append("The `occam:occam` skill covers code review and planning, and has not been loaded yet.")
    if AUDIT_REQUEST.search(words) and not Session(event).has("skill", "occam-audit") and not (typed and typed.group(1) == "occam-audit"):
        notes.append("The `occam:occam-audit` skill covers auditing and repairing existing code at any size, with tools.")
    if docs_notes.REQUEST.search(words) and not read_only:
        notes += filter(None, [docs_pointer(event)])
    # A review makes no edit, so this is the only place it hears about the language skill.
    if (read_only or REVIEW_OR_PLAN.search(words)) and (PYTHON_PROMPT.search(prompt) or python_project(event)) \
            and not Session(event).has("skill", "occam-python"):
        notes.append("`occam:occam-python` has Python guidance on auditing, structure, tests and semantics.")
    if PYTHON_PROMPT.search(prompt) or python_project(event):
        notes += say_once(Session(event), lambda key: record(event, kind="mentioned", name=key), prompt_facts(words, reference_path))
    if evidence.PUSHBACK.search(words) and (Session(event).has("check") or Session(event).has("edit")):
        notes.append("occam: if this disputes a fact or a result, rather than saying what's wanted, it is a claim to test. Recheck "
                     "against the evidence first. Change the answer for what the recheck shows or for new evidence, and say "
                     "which. If neither moves it, keep the answer and show why.")
    return context("UserPromptSubmit", " ".join(notes)) if notes else None


def expansion(event: dict) -> dict | None:
    record(event, kind="skill", name=skill_name(event.get("command_name", "")))
    return None


def subagent_stop(event: dict) -> dict | None:
    name = skill_name(event.get("agent_type") or "")
    if name:
        record(event, kind="agent_done", name=name)
    return None


def could_lose_work(edits: list[str], command: str, event: dict) -> bool:
    """Whether these shell writes could change or remove something already there.

    Only one plain command naming paths that aren't there yet can't. A `cd`, a variable, a link made on the way or
    quoting can each change what a path means, so reading the path alone isn't enough to call it new.
    """
    if not edits:
        return False
    if NOT_PLAIN.search(without_heredoc_bodies(command).strip()):
        return True
    cwd = event.get("cwd") or os.getcwd()
    return any(not path or os.path.lexists(os.path.join(cwd, path)) for path in edits)


def read_only_hold(known: list[str], unknown_path: bool, session: Session) -> dict | None:
    """Denied, unless it is a plan or review written where the request asked for it, which isn't a source edit."""
    requested = all(not is_code(path) and os.path.basename(path).lower() in session.prompt.lower() for path in known)
    if known and not unknown_path and requested:
        return None
    return respond("PreToolUse", permissionDecision="deny", permissionDecisionReason=(
        "occam: the current request reads as review-only or plan-only, so edits to project files are held for "
        "this turn. Findings go in the report. If the request did authorize edits, the user can say so, for "
        "example with \"go ahead\"."))


def hold_a_shell_edit(command: str, event: dict, session: Session) -> dict | None:
    """Two shell writes are held: a deleted test, and on a read-only turn anything that could change what's already there."""
    edits = shell_edits(command, event)
    if not edits or event.get("permission_mode") == "plan":
        return None
    known = [relative_path(path, event) for path in edits if path]
    if session.read_only and could_lose_work(edits, command, event):
        return read_only_hold(known, "" in edits, session)
    code = [path for path in known if is_code(path)]
    weakened = weakens_a_check(event.get("tool_name", ""), event.get("tool_input") or {}, event, session, code)
    return hold_a_weakened_check(event, session, *weakened) if weakened else None


def pre_tool(event: dict) -> dict | None:
    name = event.get("tool_name", "")
    tool_input = event.get("tool_input") or {}
    session = Session(event)

    edits: list[str]
    if name in SHELL_TOOLS:
        command = tool_input.get("command", "")
        operation = destructive_git(command)
        if operation:
            old_version = " `git show HEAD:<file>` into a temp folder gives the old version and leaves the working tree alone." if operation == "stash" else ""
            return respond("PreToolUse", permissionDecision="ask", permissionDecisionReason=(
                f"occam: `git {operation}` can lose or publish uncommitted work, possibly someone else's. "
                f"A person should confirm.{old_version}"))
        reason = needs_a_person(command)
        if reason:
            return respond("PreToolUse", permissionDecision="ask", permissionDecisionReason=f"occam: {reason} A person should confirm.")
        return hold_a_shell_edit(command, event, session)
    elif name in EDIT_TOOLS:
        edit_path = tool_input.get("file_path") or tool_input.get("notebook_path") or ""
        if evidence.SETTINGS_FILE.search(edit_path.replace("\\", "/")) and evidence.DISABLES_CHECKS.search(evidence.old_and_new_text(name, tool_input, event.get("cwd"))[1]):
            return respond("PreToolUse", permissionDecision="ask", permissionDecisionReason=(
                "occam: this turns off the checks on this session's work. A person should confirm."))
        if not in_project(edit_path, event):
            note = instructions_note(event, session, edit_path)
            return context("PreToolUse", note) if note else None
        remember_findings(event, session, edit_path)
        edits = [edit_path]
    elif name in evidence.WEB_TOOLS:
        shape = evidence.secret_shape(evidence.web_request_text(tool_input))
        if shape:
            return respond("PreToolUse", permissionDecision="deny", permissionDecisionReason=(
                f"occam: this request carries what looks like {shape}, and it would leave this machine and sit in other "
                "people's logs. It stays denied until the value is out of the request."))
        return None
    elif name in AGENT_TOOLS:
        if not event.get("agent_id") and not session.has("mentioned", "collaboration") and session.has("skill", CORE_SKILL):
            record(event, kind="mentioned", name="collaboration")
            return context("PreToolUse", "occam's delegation guidance is at " + reference_path("collaboration") + ".")
        return None
    else:
        return None

    if event.get("permission_mode") == "plan":
        return None

    known = [relative_path(path, event) for path in edits if path]
    code = [path for path in known if is_code(path)]
    unknown_path = "" in edits

    if session.read_only:
        return read_only_hold(known, unknown_path, session)

    if name == "Write" and known and not os.path.exists(os.path.join(event.get("cwd") or "", tool_input.get("file_path") or "")):
        record(event, kind="created", path=known[0])
    old, new = evidence.old_and_new_text(name, tool_input, event.get("cwd")) if known else ("", "")
    shape = evidence.secret_shape(new, old)
    if shape:
        target = known[0]
        result = hold(event, session, "secret", f"this writes what looks like {shape} into {target}.",
                      "A real credential belongs in configuration, and one already exposed needs rotating. "
                      "If this is a fake value for a test, retry this.", limit=1)
        if result["hookSpecificOutput"].get("permissionDecision") != "deny":
            record(event, kind="to_report", name=os.path.basename(target))
        return result

    if not code and not unknown_path:
        note = instructions_note(event, session, known[0])
        return context("PreToolUse", note) if note else None

    weakened = weakens_a_check(name, tool_input, event, session, code)
    if weakened:
        return hold_a_weakened_check(event, session, *weakened)

    # Subagents answer to the coordinating agent, which loaded the skill and keeps responsibility.
    if event.get("agent_id"):
        return None

    if not session.has("skill", CORE_SKILL):
        return hold(event, session, "skill", "the `occam:occam` skill has not been loaded in this session, and code "
                                             "edits are held until it is.", "Load it, then retry this edit.")

    file_path = code[0] if code else ""
    for reference, applies, why in (
        ("security", any(HIGH_CONSEQUENCE.search(path) for path in code) or SECURITY_PROMPT.search(session.prompt),
         "this touches access control, money, migrations or similar"),
        ("performance", PERFORMANCE_PROMPT.search(session.prompt), "this request states speed, scale or memory needs"),
        ("design", any(DEPENDENCY_MANIFEST.search(path) for path in code) or DEPENDENCY_PROMPT.search(session.prompt),
         "this touches a dependency manifest or a dependency decision"),
    ):
        if applies and not session.has("reference", reference):
            return hold(event, session, f"reference-{reference}",
                        f"{why}, and occam's {reference} reference has not been read.",
                        f"It is at {reference_path(reference)}. Read it, then retry this edit.")

    notes = []
    language = LANGUAGE_SKILLS.get(Path(file_path).suffix.lower())
    if language and not session.has("skill", language) and not session.has("mentioned", language):
        record(event, kind="mentioned", name=language)
        topics, pattern = LANGUAGE_RISKS[language]
        written = " ".join(str(tool_input.get(key, "")) for key in ("new_string", "content", "new_source"))
        if re.search(pattern, written + " " + session.prompt, re.I):
            return respond("PreToolUse", permissionDecision="deny", permissionDecisionReason=(
                f"occam: this work involves {LANGUAGE_NAMES[language]} semantics that commonly go wrong, and "
                f"`occam:{language}` covers {topics}. It hasn't been loaded. This pause happens once: either load it "
                "and then retry this edit, or retry this edit to continue without it."))
        notes.append(f"`occam:{language}` has {LANGUAGE_NAMES[language]} guidance on {topics}.")
    if TEST_PATH.search(file_path) and not session.has("reference", "verification") and not session.has("mentioned", "verification"):
        record(event, kind="mentioned", name="verification")
        notes.append("occam's guidance on tests that can fail is at " + reference_path("verification") + ".")
    note = instructions_note(event, session, file_path)
    if note:
        notes.append(note)
    if file_path:
        notes += python_edit_notes(event, session, tool_input.get("file_path") or tool_input.get("notebook_path") or file_path, file_path, tool_input)
    if file_path and not session.has("mentioned", "rewrite") and replaces_working_code(event, name, tool_input, file_path):
        record(event, kind="mentioned", name="rewrite")
        notes.append(f"This replaces a large part of the existing code in {os.path.basename(file_path)}. The existing tests "
                     "may not cover everything it does, so comparing old and new on the same inputs, awkward ones included, "
                     "is what shows its behavior survived.")
    return context("PreToolUse", " ".join(notes)) if notes else None


def replaces_working_code(event: dict, name: str, tool_input: dict, file_path: str) -> bool:
    """True when this edit overwrites a substantial existing source file, or a large part of one."""
    if Path(file_path).suffix.lower() not in LANGUAGE_SKILLS:
        return False
    if name == "Write":
        path = Path(event.get("cwd") or os.getcwd(), file_path)
        try:
            # is_file first: reading a FIFO would block until the hook's timeout.
            existing = path.read_text(encoding="utf-8", errors="replace") if path.is_file() else ""
        except OSError:
            return False
        return existing.count("\n") >= REWRITE_MIN_LINES
    return str(tool_input.get("old_string", "")).count("\n") >= REWRITE_MIN_LINES


def size_text(event: dict, file_path: str, relative: str) -> str | None:
    """What to say, once per file per session, about a very large source file."""
    suffix = Path(relative).suffix.lower()
    if suffix not in LANGUAGE_SKILLS or suffix in NOT_MEASURED_IN_LINES:
        return None
    try:
        data = Path(event.get("cwd") or os.getcwd(), file_path).read_bytes()
    except OSError:
        return None
    lines = data.count(b"\n")
    key = f"size:{relative}"
    if lines <= LARGE_FILE_LINES or GENERATED_MARK.search(data[:600]) or Session(event).has("mentioned", key):
        return None
    record(event, kind="mentioned", name=key)
    note = (f"occam: {relative} is {lines} lines, past the {LARGE_FILE_LINES} where a module is worth a second look. New code "
            "with its own responsibility belongs in its own module, though one more of a kind this file already holds can follow its siblings. Splitting what is already here is a separate change "
            "to propose, unless this request asks for it. A limit this repository configures takes precedence.")
    if LANGUAGE_SKILLS[suffix] == "occam-python":
        note += " How to split safely is at " + reference_path("structure", "occam-python") + "."
    return note


def size_note(event: dict, file_path: str, relative: str) -> dict | None:
    note = size_text(event, file_path, relative)
    return context("PostToolUse", note) if note else None


def python_edit_notes(event: dict, session: Session, edit_path: str, relative: str, tool_input: dict) -> list[str]:
    """Facts for an edit, before it happens, each once per session. Files and code with no known trap add nothing."""
    notes = [size_text(event, edit_path, relative)]  # any language, and it can still change where the code goes
    if LANGUAGE_SKILLS.get(Path(relative).suffix.lower()) == "occam-python":
        target = Path(event.get("cwd") or os.getcwd(), edit_path)
        notes.append(shadow_note(relative, target.exists()))
        written = output_text({key: tool_input.get(key) for key in ("new_string", "content", "new_source", "edits")})
        facts = edit_facts(relative, bool(TEST_PATH.search(relative)), written, reference_path, lambda: read_source(target))
        notes += say_once(session, lambda key: record(event, kind="mentioned", name=key), facts)
    return [note for note in notes if note]


def absolute_path(event: dict, file_path: str) -> Path:
    return Path(event.get("cwd") or os.getcwd(), file_path)


def remember_findings(event: dict, session: Session, file_path: str) -> None:
    """Before the first edit of a code file, note what it already has, so only what this work adds gets mentioned."""
    relative = relative_path(file_path, event)
    if is_code(relative) and not session.has("scan-baseline", relative):
        # A file that doesn't exist yet has no findings, so everything in it will be this work's.
        record(event, kind="scan-baseline", name=relative, ids=scan_notes.identities(absolute_path(event, file_path), relative))


def known_findings(event: dict, session: Session, relative: str) -> list[str] | None:
    for entry in session.entries:
        if entry.get("kind") == "scan-baseline" and entry.get("name") == relative:
            return entry.get("ids")
    return scan_notes.committed_identities(Path(event.get("cwd") or os.getcwd()), relative)


def scan_note(event: dict, file_path: str, relative: str) -> dict | None:
    """Say what this edit just introduced. Each finding is mentioned once, and a clean edit costs no tokens."""
    if not is_code(relative):
        return None
    session = Session(event)
    found = scan_notes.introduced(absolute_path(event, file_path), relative, known_findings(event, session, relative))
    already = {identity for entry in session.entries if entry.get("kind") == "scan-noted" for identity in entry.get("ids", [])}
    fresh = [finding for finding in found if finding["id"] not in already]
    if not fresh:
        return None
    record(event, kind="scan-noted", ids=[finding["id"] for finding in fresh])
    return context("PostToolUse", "occam scan of this edit: " + scan_notes.describe(fresh) + ". These are leads. If one is real, this is the moment to fix it, and if it isn't, carry on.")


def docs_pointer(event: dict) -> str | None:
    return docs_notes.once(Session(event), lambda name: record(event, kind="mentioned", name=name))


def docs_note(event: dict, relative: str) -> dict | None:
    note = docs_pointer(event) if docs_notes.is_document(relative) else None
    return context("PostToolUse", note) if note else None


def joined_context(event_name: str, *results: dict | None) -> dict | None:
    texts = [result["hookSpecificOutput"]["additionalContext"] for result in results if result]
    return context(event_name, " ".join(texts)) if texts else None


def post_tool(event: dict, succeeded: bool = True) -> dict | None:
    name = event.get("tool_name", "")
    tool_input = event.get("tool_input") or {}
    if name == "Skill":
        if succeeded and not event.get("agent_id"):
            record(event, kind="skill", name=skill_name(tool_input.get("skill", "")))
    elif name == "Read":
        match = re.search(r"/skills/occam/references/(\w+)\.md$", tool_input.get("file_path") or "")
        if match:
            record(event, kind="reference", name=match.group(1))
    elif name in EDIT_TOOLS:
        file_path = tool_input.get("file_path") or tool_input.get("notebook_path") or ""
        if succeeded and in_project(file_path, event):
            path = relative_path(file_path, event)
            record(event, kind="edit", path=path, code=is_code(path))
            return joined_context("PostToolUse", size_note(event, file_path, path), scan_note(event, file_path, path), docs_note(event, path))
    elif name in APPROVAL_TOOLS:
        # A person answered, or approved a plan. That can lift a read-only turn without a new prompt.
        if succeeded and not event.get("agent_id"):
            record(event, kind="approved")
    elif name in SHELL_TOOLS:
        command = tool_input.get("command", "")
        for reference in re.findall(r"/skills/occam/references/(\w+)\.md", command):
            record(event, kind="reference", name=reference)
        if succeeded and not event.get("agent_id"):
            for effect in side_effects(command, event):
                record(event, kind="to_report", **effect)
        response = event.get("tool_response")
        changed = response.get("bashEditDiff") if isinstance(response, dict) else None
        if isinstance(changed, dict) and changed.get("changedFiles"):
            for path in changed["changedFiles"]:
                if in_project(path, event):
                    relative = relative_path(path, event)
                    record(event, kind="edit", path=relative, code=is_code(relative))
        elif succeeded:
            for path in shell_edits(command, event):
                relative = relative_path(path, event)
                record(event, kind="edit", path=relative, code=not relative or is_code(relative))
        commands, _ = parse_shell(command)
        if any(not is_check(words) and not is_diff(words) and not evidence.leaves_results_alone(*head(words)) for words in commands):
            record(event, kind="setup")
        # Launching a command in the background isn't having run it, and neither is being interrupted.
        # So is an edit made by inline Python, which would otherwise count as having checked itself.
        writes = [target for target in inline_python_writes(command) if not target or project_path(target, event)]
        ran_check = any(is_check(words) and not (writes and runs_inline_python(words)) for words in commands) and not tool_input.get("run_in_background") and not event.get("is_interrupt")
        if ran_check:
            output = output_text(response)
            error = str(event.get("error") or "")
            record(event, kind="check", passed=succeeded and not shows_no_pass(output), counted=evidence.shows_a_count(output + "\n" + error),
                   not_this_code=evidence.says_nothing_about_this_code(command, output + "\n" + error),
                   numbers=evidence.numbers_in(output + "\n" + error), **({"agent": True} if event.get("agent_id") else {}), **check_identity(commands))
            if re.search(r"\btim(ed|e)[ -]?out\b", error, re.I):  # a rerun passing says little about a run that never finished
                record(event, kind="setup")
        if any(is_diff(words) for words in commands):
            record(event, kind="diff")
        if ran_check:
            return failing_streak_note(event, succeeded)
    return None


def post_failure(event: dict) -> dict | None:
    return post_tool(event, succeeded=False)


def stop(event: dict) -> dict | None:
    if event.get("stop_hook_active") or event.get("agent_id"):
        return None
    # Delegated work still underway will report back, and this runs again then. A dev server doesn't count.
    if any(task.get("type") in FOREGROUND_BLOCKING_TASKS for task in event.get("background_tasks") or []):
        return None
    session = Session(event)
    edits = session.code_edits()
    if not edits:
        return None

    missing = []
    if not session.after_last_edit("check"):
        missing.append("No check has run since the last code edit. A relevant test or the real entry point would "
                       "show whether it works. If a check can't run here, the report should say so.")
    message = event.get("last_assistant_message") or ""
    claim = CLAIMS_PASSING.search(message)
    if claim and not NEGATED_CLAIM.search(message[max(0, claim.start() - 60):claim.end()]) \
            and not any(e.get("kind") == "check" and e.get("passed") for e in session.turn):
        missing.append("The message reports passing checks, but no check passed during this turn.")
    risky = sorted({e["path"] for e in edits if e.get("path") and HIGH_CONSEQUENCE.search(e["path"])})
    if risky and not any(e.get("name") == REVIEWER for e in session.after_last_edit("agent_done")):
        missing.append(f"This changed {', '.join(os.path.basename(p) for p in risky[:3])}, which is high consequence, "
                       f"and the `occam:{REVIEWER}` agent hasn't finished a review since the last edit. It needs the "
                       "requirements and the diff. If it can't run, the report should call this a self-review.")
    files = {e.get("path") for e in edits if e.get("path")}
    if len(files) < len(edits) and any(not e.get("path") for e in edits):  # an edit script hid its target, so ask git
        files |= set(unfinished.changed_in_git(Path(event.get("cwd") or ".")))
    if len(files) >= 2 and not session.after_last_edit("diff"):
        missing.append("This changed several files, and the final diff hasn't been inspected against the request.")
    if message and evidence.has_an_unsettled_failure(session.after_last_edit("check")) and evidence.leaves_out_a_failure(message, CLAIMS_PASSING, NEGATED_CLAIM):
        missing.append("A check failed after the last code edit and hasn't passed since, and the message doesn't mention a failure.")
    count = evidence.unmatched_test_count(session.turn, message, NEGATED_CLAIM)
    if count:
        missing.append(f"The message reports {count} passing, but no check's output this turn contains that number.")
    if evidence.claims_a_measured_change(message) and not evidence.has_before_and_after(session.entries[:len(session.entries) - len(session.turn)], session.turn):
        missing.append("The message states a measured speedup or saving, but no command ran both before the first code edit and "
                       "after the last one, so this session has no like-for-like before and after. If the figure came from "
                       "elsewhere or is an estimate, the report should say so.")
    varying = evidence.varying_results(session.turn)
    if varying and not evidence.MENTIONS_VARYING.search(message):
        missing.append(f"`{varying[0]}` both failed and passed with nothing changed between the runs, so its result varies. One "
                       "green run doesn't settle that, so the report should say it is flaky or what differed.")
    names = evidence.names_to_report(session.turn, DEPENDENCY_MANIFEST) if message else set()
    for name in names:
        record(event, kind="told", name=name)
    silent = sorted(name for name in names if name.lower() not in message.lower())
    if silent:
        missing.append(f"The message doesn't name {', '.join(silent[:6])}. Reports tend to leave out most of what an agent did, "
                       "and a reader needs these.")
    introduced_here = [finding for path in scan_notes.within_budget(sorted(files)) for finding in scan_notes.introduced(
        absolute_path(event, path), path, known_findings(event, session, path))]
    if introduced_here:
        missing.append("The scanner sees these in what you changed, and they weren't there before: " + scan_notes.describe(introduced_here) +
                       ". Fix each one, or say in the report why it's fine.")
    remaining = scan_notes.still_raised_note([(absolute_path(event, path), path) for path in sorted(files)]) if session.has("skill", "occam-audit") else None
    if remaining:
        missing.append(remaining)
    missing += unfinished.notes(event, session, message, [(absolute_path(event, path), path) for path in sorted(files)], record)
    if not missing:
        return None
    return context("Stop", "occam: " + " ".join(missing) +
                   " The report should cover what changed, what was checked with its status, and what wasn't.")


HANDLERS = {"session-start": session_start, "user-prompt": user_prompt, "expansion": expansion,
            "subagent-stop": subagent_stop, "pre-tool": pre_tool,
            "post-tool": post_tool, "post-failure": post_failure, "stop": stop}


def main(argv: list[str]) -> int:
    if os.environ.get("OCCAM_HOOKS", "").lower() in ("off", "0", "false") or len(argv) != 2 or argv[1] not in HANDLERS:
        return 0
    try:
        event = json.loads(sys.stdin.read() or "{}")
        result = HANDLERS[argv[1]](event if isinstance(event, dict) else {})
        if result:
            print(json.dumps(result))
    except Exception as error:  # fail open: a broken hook must not wedge a session
        print(f"occam hook failed open: {type(error).__name__}: {error}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
