"""Command line: one thin handler per command, importing what it needs only when it runs."""

from __future__ import annotations

import argparse
import json
import multiprocessing
import os
import re
import signal
import sqlite3
import sys
import traceback
from pathlib import Path

from . import VERSION
from .files import GitProblem, OutsideProject, stop_running_git


def _root(args) -> Path:
    from .files import find_root, root_for_path
    if getattr(args, "root", None):
        return find_root(args.root)
    return root_for_path(args.paths[0]) if getattr(args, "paths", None) else find_root(".")


GRACE_SECONDS = 35  # with the default reading limit, that's 110 of the 120 seconds a shell tool usually allows


def _seconds(text: str) -> int:
    value = int(text)
    if value < 0:
        raise argparse.ArgumentTypeError("can't be negative, and 0 means no limit")
    return value


def _positive(text: str) -> int:
    value = int(text)
    if value < 1:
        raise argparse.ArgumentTypeError("must be at least 1")
    return value


def _sizes(text: str) -> list[int]:
    try:
        return [_positive(size) for size in text.split(",")]
    except ValueError:
        raise argparse.ArgumentTypeError(f"{text!r} isn't a comma-separated list of sizes") from None


def _emit(result: tuple[str, int]) -> int:
    text, code = result
    print(text)
    return code


def _add_time_limit(parser: argparse.ArgumentParser, default: str = "Default 75") -> None:
    parser.add_argument("--max-seconds", type=_seconds, help=f"stop reading after about this long and report what was read, which the next run builds on. 0 means no limit. {default}")


def _time_limit(args) -> int | None:
    """How long a command may read for. A shell tool kills what runs too long, and an answer about part of a repository beats none.

    Whatever decides something on its own needs the whole answer: CI's exit code, and a comparison with what was accepted before.
    """
    from .scan import DEFAULT_SECONDS
    if not hasattr(args, "max_seconds"):
        return None
    if args.max_seconds is None:
        decides = getattr(args, "fail_on", None) or getattr(args, "strict", False) or getattr(args, "new_only", False) or getattr(args, "baseline", None) or getattr(args, "format", None) == "sarif"
        return None if decides else DEFAULT_SECONDS
    return args.max_seconds or None


class _OutOfTime(BaseException):
    """Not an Exception, because code that tolerates a failed file or git call mustn't tolerate this."""


def _raise_out_of_time(*_) -> None:
    raise _OutOfTime


def _save_last(root: Path, findings: list[dict], stats: dict) -> str | None:
    from .files import state_dir
    try:
        path = state_dir(root) / "last-scan.json"
        path.write_text(json.dumps({"stats": stats, "findings": findings}))
        return str(path)
    except OSError:
        return None


def cmd_scan(args) -> int:
    from . import baseline, report, scan
    if args.stdin:
        name = args.name or {"python": "snippet.py", "javascript": "snippet.js", "typescript": "snippet.ts", "go": "snippet.go", "rust": "snippet.rs", "java": "Snippet.java",
                             "shell": "snippet.sh", "sql": "snippet.sql", "c": "snippet.c", "cpp": "snippet.cpp"}.get(args.lang or "python", "snippet.txt")
        result = scan.scan_snippet(name, sys.stdin.read(), args.lang)
        root = None
    else:
        root = _root(args)
        result = scan.run_scan(root, args.paths or None, changed_only=args.changed, base=args.diff, use_cache=not args.no_cache, workers=args.workers, isolated=args.isolated, seconds=_time_limit(args))
        if result.stats.get("partial") and args.format in ("json", "sarif"):  # json has it in stats, but sarif has nowhere to put it, and either can reach a person's terminal
            print("\n".join(report.partial_note(result.stats)), file=sys.stderr)
    findings = result.findings
    if (args.new_only or args.baseline) and root is not None:
        findings, warning = baseline.new_since_baseline(root, findings, args.baseline)
        if warning:
            print(warning, file=sys.stderr)
    visible = scan.filter_findings(findings, args.min_confidence, args.rule)
    hidden = len(scan.filter_findings(findings, "low", args.rule)) - len(visible)
    saved = _save_last(root, findings, result.stats) if root is not None else None
    if args.format == "json":
        print(report.render_json(visible, result.stats))
    elif args.format == "sarif":
        print(report.render_sarif(visible))
    elif args.format == "md":
        print(report.render_markdown(visible, result.stats))
    else:
        print(report.render_text(visible, hidden, result.stats, args.top, saved))
    if args.fail_on:
        order = ("low", "medium", "high", "critical")
        cut = order.index(args.fail_on)
        # What wasn't read can't be called clean, so a limit that left files unread fails the gate it was asked to pass.
        return 1 if any(order.index(f["severity"]) >= cut for f in visible) or report.left_unread(result.stats) else 0
    return 0


def _ask(args, root: Path) -> tuple[dict, object]:
    """The answer to one query, and how to print it."""
    from . import query_code as code, query_graph as graph, query_repo as repo
    top, paths = args.top, args.paths or None
    answer, renderer = {
        "size": (lambda: repo.size(root, paths, args.depth, top), repo.render_size),
        "commands": (lambda: repo.commands(root, top), repo.render_commands),
        "entry": (lambda: repo.entry(root, paths, top), repo.render_entry),
        "markers": (lambda: repo.markers(root, paths, args.kind, top), repo.render_markers),
        "history": (lambda: repo.history(root, paths[0] if paths else None, args.since, args.commits, top, args.follow), repo.render_history),
        "leaks": (lambda: repo.leaks(root, args.commits, top, args.timeout), repo.render_leaks),
        "outline": (lambda: code.outline(root, paths, top), code.render_outline),
        "find": (lambda: code.find(root, args.name, paths, top), code.render_find),
        "grep": (lambda: code.grep(root, args.pattern, paths, args.where, args.lang, args.ignore_case, top), code.render_grep),
        "functions": (lambda: code.functions(root, paths, args.sort, args.include_tests, top), code.render_functions),
        "api": (lambda: code.api(root, paths, args.base, top), code.render_api),
        "boundaries": (lambda: code.boundaries(root, paths, args.kind, args.include_tests, top), code.render_boundaries),
        "graph": (lambda: graph.graph_file(root, paths[0], top), graph.render_graph_file) if paths else (lambda: graph.graph_overview(root, top), graph.render_graph_overview),
        "impact": (lambda: graph.impact(root, paths, args.changed, args.diff, top), graph.render_impact),
        "tests": (lambda: graph.tests_for(root, paths, top), graph.render_tests_for) if paths else (lambda: graph.tests_overview(root, top), graph.render_tests_overview),
    }[args.query_name]
    return answer(), renderer


_MAIN_PROCESS = [os.getpid()]


def _give_up(seconds: int) -> None:
    """Exits from inside the signal. An exception wouldn't do: too much on the way up handles OSError, which TimeoutError is, and a process pool waits for its queue."""
    print(f"Stopped after {seconds} seconds. Nothing was checked. Narrow it with a path, or raise --timeout.", flush=True)
    _end_now(2)


def _end_now(status: int) -> None:
    """Takes what this started with it: a git blocked on a FIFO a repository named would outlive the process, and only the process that started it may stop it."""
    if os.getpid() == _MAIN_PROCESS[0]:
        for child in multiprocessing.active_children():
            child.terminate()
        stop_running_git()
    os._exit(status)


def cmd_query(args) -> int:
    """Whatever a repository does to a query, what comes out is an answer or exit 2, since a traceback or a hang tells an agent nothing."""
    from . import query
    root = _root(args)
    if hasattr(signal, "SIGALRM"):
        signal.signal(signal.SIGALRM, lambda _number, _frame: _give_up(args.timeout))
        signal.alarm(args.timeout)
    try:
        data, renderer = _ask(args, root)
        # `leaks` reads every path on purpose, since a setting mustn't hide a secret from it.
        ignored = [] if args.query_name == "leaks" else query.config_ignores(root)
        if args.format == "json":
            print(json.dumps({**data, "config_ignores": ignored}, indent=2))
        else:
            print(renderer(query.printable(data)))
            if ignored:
                rest = f" and {len(ignored) - 8} more" if len(ignored) > 8 else ""
                print(f"\nThis repository's .occam.json leaves out: {', '.join(query.printable(ignored[:8]))}{rest}.")
    except re.error as error:
        print(f"That isn't a valid expression: {error}")
        return 2
    except query.BadQuestion as error:
        print(error)
        return 2
    except (GitProblem, OutsideProject, BrokenPipeError):
        raise
    except Exception as error:  # occam: ignore[swallowed-exception] reported and exit 2. A hostile file mustn't look like a clean answer
        print(f"This query failed on what it read ({type(error).__name__}: {error}). Nothing was checked.")
        return 2
    return 0


def cmd_rules(args) -> int:
    from . import report
    print(report.render_rules(args.rule_id))
    return 0


def cmd_map(args) -> int:
    from . import inventory
    root = _root(args)
    data = inventory.build_map(root, Path(args.paths[0]).resolve() if args.paths else None, args.isolated, _time_limit(args))
    print(json.dumps(data, indent=2) if args.format == "json" else inventory.render_map(data))
    return 0


def cmd_partition(args) -> int:
    from . import inventory
    root = _root(args)
    plan = inventory.partition(root, args.paths or None, reader_budget=args.budget, host_limit=args.max_agents, mode=args.mode, seconds=_time_limit(args))
    print(json.dumps(plan, indent=2) if args.format == "json" else inventory.render_partition(plan))
    return 0


def cmd_tools(args) -> int:
    from . import toolrun
    root = _root(args)
    print(toolrun.run_tools(root, execute=args.run, allow_exec=args.allow_exec, only=args.only, paths=args.paths or None))
    return 0


def cmd_deps(args) -> int:
    from . import depcheck
    root = _root(args)
    return _emit(depcheck.report(root, online=args.online, names=args.name, seconds=_time_limit(args)))


def cmd_baseline(args) -> int:
    from . import baseline
    root = _root(args)
    try:
        print(baseline.write_baseline(root, args.out) if args.action == "write" else baseline.show_baseline(root))
    except OSError as error:
        print(f"Couldn't write the baseline: {error}.")
        return 2
    return 0


def cmd_golden(args) -> int:
    from . import verify
    command = list(args.command or [])
    # Everything after the name lands in `command`, so options written before the command or its -- get picked out here.
    while len(command) > 1 and command[0] in ("--normalize", "--timeout", "--root"):
        option, value, command = command[0], command[1], command[2:]
        if option == "--normalize":
            args.normalize.append(value)
        elif option == "--root":
            args.root = value
        elif value.isdecimal():
            args.timeout = int(value)
        else:
            print(f"--timeout takes whole seconds, not {value!r}.")
            return 2
    command = command[1:] if command[:1] == ["--"] else command
    root = _root(args)
    return _emit(verify.golden_record(root, args.name, command, args.timeout, args.normalize) if args.action == "record" else verify.golden_check(root, args.name, args.timeout))


def cmd_mutate(args) -> int:
    from . import verify
    return _emit(verify.mutate(_root(args), args.cmd, args.paths or None, changed=args.changed, base=args.diff, limit=args.max, timeout=args.timeout))


def cmd_bench(args) -> int:
    from . import verify
    return _emit(verify.bench(args.cmd, args.sizes, args.repeat, args.limit_seconds, args.timeout))


def cmd_coord(args) -> int:
    from . import workflow
    return _emit(workflow.coord(_root(args), args.action, args.paths or [], args.owner, args.ttl))


def cmd_goal(args) -> int:
    from . import workflow
    return _emit(workflow.goal(_root(args), args))


def cmd_design(args) -> int:
    from . import design
    try:
        root = Path(args.root).resolve() if args.root else _root(args)  # a root named outright is that folder: walking up would read another project's document
        if not root.is_dir():
            raise NotADirectoryError
    except (OSError, RuntimeError):  # 3.9 raises RuntimeError on a symlink loop
        print(f"No such folder, or it can't be read: {args.root or '.'}. Nothing was checked.")
        return 2
    if args.action == "init":
        text, code = design.init(root)
    elif args.action == "check":
        text, code = design.check(root)
    elif args.action == "for":
        text, code = design.for_paths(root, args.words) if args.words else ("Name at least one file: `occam design for <path>`.", 2)
    elif len(args.words) < 2 or not args.why:
        text, code = "Usage: occam design decide ID TEXT --why WHY [--applies PATH] [--proposed] [--supersedes ID]", 2
    else:
        text, code = design.decide(root, args.words[0], " ".join(args.words[1:]), args.why, args.applies or [], args.proposed, args.supersedes)
    print(text)
    return code


def cmd_gate(args) -> int:
    from . import verify
    return _emit(verify.gate(_root(args), base=args.base, strict=args.strict, paths=args.paths or None, seconds=_time_limit(args)))


def cmd_docs(args) -> int:
    from . import docs
    return _emit(docs.check(_root(args), paths=args.paths or None, before=args.before, register=args.register, allow_exec=args.allow_exec))


def _add_query_parsers(commands) -> None:
    sub = commands.add_parser(allow_abbrev=False, name="query", help="Plain answers about the code: its size, who calls what, what a change reaches, who owns it. Read-only, runs nothing, and output is bounded")
    queries = sub.add_subparsers(dest="query_name", required=True)

    def query(name: str, about: str, paths: str | None = "*", top: int = 30):
        parser = queries.add_parser(name, allow_abbrev=False, help=about, description=about)
        if paths:
            parser.add_argument("paths", nargs=paths)
        parser.add_argument("--top", type=int, default=top, help="how many of each list to show")
        parser.add_argument("--format", choices=("text", "json"), default="text")
        parser.add_argument("--timeout", type=int, default=900, help="seconds before giving up, with exit 2")
        parser.add_argument("--root")
        parser.set_defaults(handler=cmd_query, paths=[])
        return parser

    parser = query("size", "Lines and files by language and directory, subsystems, largest files. Fast on any size, because it parses nothing")
    parser.add_argument("--depth", type=int, help="directory depth to group by")
    query("commands", "The build, test and lint commands this repository states. Lists them and runs nothing", paths=None)
    query("entry", "Where execution starts: installed commands, mains, routes, jobs, CLIs, containers")
    parser = query("markers", "Where the code turns its own checks off: silenced checkers, skipped and focused tests, hidden failures")
    parser.add_argument("--kind", action="append", choices=("suppression", "skipped-test", "focused-test", "hidden-check"), help="repeatable")
    parser = query("history", "Churn, fix commits, authors, owners, how few people hold it, and what changes together. One file gets its recent commits", paths="?")
    parser.add_argument("--since", help="such as 6.months")
    parser.add_argument("--commits", type=int, default=5000, help="how far back to read")
    parser.add_argument("--follow", action="store_true", help="follow one file through renames")
    parser = query("leaks", "Credential-shaped lines ever added in history, values withheld. Deleting a secret leaves it there", paths=None)
    parser.add_argument("--commits", type=int, default=500, help="how far back to read")
    query("outline", "A file's classes and functions with line ranges and signatures, so you can read the part that matters", paths="+", top=200)
    parser = query("find", "Where a name is defined, imported, called, tested and mentioned, with the enclosing function", paths=None)
    parser.add_argument("name")
    parser.add_argument("paths", nargs="*")
    parser = query("grep", "A bounded search that knows code from comments and strings. Python's regular expressions", paths=None)
    parser.add_argument("pattern")
    parser.add_argument("paths", nargs="*")
    parser.add_argument("--in", dest="where", choices=("any", "code", "comment", "string"), default="any")
    parser.add_argument("--lang", help="only this language, such as python or shell")
    parser.add_argument("-i", dest="ignore_case", action="store_true")
    parser = query("functions", "The longest and most complex functions")
    parser.add_argument("--sort", choices=("lines", "complexity", "params"), default="lines")
    parser.add_argument("--include-tests", action="store_true")
    parser = query("api", "Public names by convention. With --base, what a change removed or broke")
    parser.add_argument("--base", help="revision to compare with")
    parser = query("boundaries", "Where the code meets the outside world and what's at stake: routes, SQL, money, auth, tenancy, subprocess. An inventory, not findings")
    parser.add_argument("--kind", help="list the sites of one kind")
    parser.add_argument("--include-tests", action="store_true")
    query("graph", "With no path: most depended-on files, cycles, folder layering. With a path: its imports and importers", paths="?")
    parser = query("impact", "What a change reaches, and which tests to run. Give paths, --changed or --diff BASE")
    parser.add_argument("--changed", action="store_true", help="uncommitted changes")
    parser.add_argument("--diff", metavar="BASE", help="changes against this revision")
    query("tests", "With no path: what no test reaches, and any coverage report left here. With a path: which tests reach it")


READS_NAMED_PATHS = {cmd_scan, cmd_query, cmd_map, cmd_partition, cmd_tools, cmd_mutate}


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="occam", description="Audit and repair tools for agents. Read-only unless a command says otherwise.", allow_abbrev=False)
    parser.add_argument("--version", action="version", version=VERSION)
    commands = parser.add_subparsers(dest="command_name", required=True)

    sub = commands.add_parser(allow_abbrev=False, name="map", help="Size, languages, tooling, risky areas, strategy and agent count for this repository")
    sub.add_argument("paths", nargs="*")
    sub.add_argument("--format", choices=("text", "json"), default="text")
    sub.add_argument("--isolated", action="store_true", help="read only this path, for a repository too large to hold in memory. Cross-file rules don't run")
    _add_time_limit(sub)
    sub.set_defaults(handler=cmd_map)

    sub = commands.add_parser(allow_abbrev=False, name="scan", help="Find leads across all rule families. Output is bounded; full results are saved")
    sub.add_argument("paths", nargs="*")
    sub.add_argument("--changed", action="store_true", help="only uncommitted changes")
    sub.add_argument("--diff", metavar="BASE", help="only changes against this revision")
    sub.add_argument("--new-only", action="store_true", help="hide what this machine's baseline already knows")
    sub.add_argument("--baseline", metavar="FILE", help="hide what a committed baseline file knows. For CI")
    sub.add_argument("--stdin", action="store_true", help="scan a snippet or cell from stdin")
    sub.add_argument("--lang", help="language of --stdin code, default python")
    sub.add_argument("--name", help="file name to report for --stdin code")
    sub.add_argument("--format", choices=("text", "json", "sarif", "md"), default="text")
    sub.add_argument("--top", type=int, default=30)
    sub.add_argument("--fail-on", choices=("low", "medium", "high", "critical"), help="exit 1 if a visible finding is at least this severe")
    sub.add_argument("--no-cache", action="store_true")
    sub.add_argument("--workers", type=int)
    _add_time_limit(sub, "Default 75, or none with --fail-on, --new-only, --baseline or --format sarif, since something else decides on those")
    sub.add_argument("--isolated", action="store_true", help="read only these paths, for a repository too large to hold in memory. Cross-file rules don't run")
    sub.add_argument("--min-confidence", choices=("high", "medium", "low"), default="medium")
    sub.add_argument("--rule", action="append", help="repeatable")
    sub.set_defaults(handler=cmd_scan)

    _add_query_parsers(commands)

    sub = commands.add_parser(allow_abbrev=False, name="rules", help="What the scanner can report")
    sub.add_argument("rule_id", nargs="?")
    sub.set_defaults(handler=cmd_rules)

    sub = commands.add_parser(allow_abbrev=False, name="tools", help="Which established analyzers exist here, and run them. They beat occam's rules where they overlap")
    sub.add_argument("paths", nargs="*")
    sub.add_argument("--run", action="store_true", help="run the ones that execute no repository code")
    sub.add_argument("--allow-exec", action="store_true", help="also run tools that load repository config or code, such as eslint or clippy")
    sub.add_argument("--only", action="append", help="repeatable")
    sub.set_defaults(handler=cmd_tools)

    sub = commands.add_parser(allow_abbrev=False, name="deps", help="Declared versus used dependencies, phantom packages, competing libraries")
    sub.add_argument("--online", action="store_true", help="check registries for existence and age. Sends package names only")
    sub.add_argument("--name", action="append", help="check this package before adding it, by asking its registry. Form: pypi:name, npm:name, crates:name")
    sub.add_argument("--root")
    _add_time_limit(sub)
    sub.set_defaults(handler=cmd_deps)

    sub = commands.add_parser(allow_abbrev=False, name="baseline", help="Ratchet for large repositories: accept today's findings so only new ones count")
    sub.add_argument("action", choices=("write", "show"))
    sub.add_argument("--out", help="write: save to a file you can commit, for CI")
    sub.add_argument("--root")
    sub.set_defaults(handler=cmd_baseline)

    sub = commands.add_parser(allow_abbrev=False, name="partition", help="Split work into disjoint shards, and say how many agents that justifies")
    sub.add_argument("paths", nargs="*")
    sub.add_argument("--mode", choices=("read", "write"), default="read")
    sub.add_argument("--budget", type=int, default=5000, help="lines one reader takes")
    sub.add_argument("--max-agents", type=int, default=6, help="host or budget limit")
    sub.add_argument("--format", choices=("text", "json"), default="text")
    _add_time_limit(sub)
    sub.set_defaults(handler=cmd_partition)

    sub = commands.add_parser(allow_abbrev=False, name="golden", help="Record a command's behavior before a refactor, then prove it didn't change. Runs the command")
    sub.add_argument("action", choices=("record", "check"))
    sub.add_argument("name")
    sub.add_argument("command", nargs=argparse.REMAINDER)
    sub.add_argument("--timeout", type=int, default=300)
    sub.add_argument("--normalize", action="append", default=[], help="regex to blank out, such as timestamps. Repeatable")
    sub.add_argument("--root")
    sub.set_defaults(handler=cmd_golden)

    sub = commands.add_parser(allow_abbrev=False, name="mutate", help="Can the tests fail? Breaks a temp copy of the code and runs them. Runs repository code")
    sub.add_argument("paths", nargs="*")
    sub.add_argument("--cmd", required=True, help="test command, for example 'pytest -q tests/test_x.py'")
    sub.add_argument("--changed", action="store_true")
    sub.add_argument("--diff")
    sub.add_argument("--max", type=_positive, default=20)
    sub.add_argument("--timeout", type=int, default=120)
    sub.set_defaults(handler=cmd_mutate)

    sub = commands.add_parser(allow_abbrev=False, name="bench", help="Measure time and peak memory across input sizes, in fresh processes. Runs the command")
    sub.add_argument("--cmd", required=True, help="use {n} for the size")
    sub.add_argument("--sizes", required=True, type=_sizes, help="comma separated")
    sub.add_argument("--repeat", type=_positive, default=3)
    sub.add_argument("--limit-seconds", type=float)
    sub.add_argument("--timeout", type=int, default=600)
    sub.set_defaults(handler=cmd_bench)

    sub = commands.add_parser(allow_abbrev=False, name="coord", help="Who else is working here? Dirty files, worktrees, recent commits and advisory claims")
    sub.add_argument("action", choices=("status", "check", "claim", "release"))
    sub.add_argument("paths", nargs="*")
    sub.add_argument("--owner", help="your agent name. Required to claim or release")
    sub.add_argument("--ttl", type=int, default=3600)
    sub.add_argument("--root")
    sub.set_defaults(handler=cmd_coord)

    sub = commands.add_parser(allow_abbrev=False, name="goal", help="Goal ledger: requirements with checks, constraints, scope. 'verify' runs the checks")
    sub.add_argument("action", choices=("init", "add", "constrain", "scope", "status", "verify", "condition", "clear"))
    sub.add_argument("text", nargs="*")
    sub.add_argument("--check", help="add: command that proves this requirement")
    sub.add_argument("--forbid", help="constrain: path glob that must not change")
    sub.add_argument("--no", choices=("new-dependency", "new-file", "api-break"), help="constrain: a limit verify checks itself: no new dependency in a manifest, no new file, or no public name removed or broken")
    sub.add_argument("--timeout", type=int, default=600)
    sub.add_argument("--base", help="verify: revision to compare scope against")
    sub.add_argument("--root")
    sub.set_defaults(handler=cmd_goal)

    sub = commands.add_parser(allow_abbrev=False, name="design", help="The shared design doc: what applies to a file, whether it has drifted, and adding a decision. Only init and decide write")
    sub.add_argument("action", choices=("init", "check", "for", "decide"))
    sub.add_argument("words", nargs="*", help="for: the files. decide: an id, then the decision")
    sub.add_argument("--why", help="decide: the reason, which is what a later reader needs most")
    sub.add_argument("--applies", action="append", help="decide: a file or folder it governs. Repeatable. Without it, the decision applies everywhere")
    sub.add_argument("--proposed", action="store_true", help="decide: for the owner to accept")
    sub.add_argument("--supersedes", help="decide: the id this replaces")
    sub.add_argument("--root")
    sub.set_defaults(handler=cmd_design)

    sub = commands.add_parser(allow_abbrev=False, name="gate", help="Critique your own change before calling it done. Exit 1 on blockers")
    sub.add_argument("paths", nargs="*", help="what you changed, if this isn't a git repository")
    sub.add_argument("--base", help="revision to compare with, default uncommitted changes")
    sub.add_argument("--strict", action="store_true", help="warnings block too")
    sub.add_argument("--root")
    _add_time_limit(sub)
    sub.set_defaults(handler=cmd_gate)

    sub = commands.add_parser(allow_abbrev=False, name="docs", help="Check documents against the code: names, paths, flags, links and example syntax. Runs the human-voice linter if it's installed. Exit 1 on leads")
    sub.add_argument("paths", nargs="*", help="documents or folders, default the ones changed in git")
    sub.add_argument("--before", help="the same document before a rewrite, to report any number, code, link or code block it lost or added")
    sub.add_argument("--register", help="genre for the human-voice linter, such as technical or tutorial")
    sub.add_argument("--allow-exec", action="store_true", help="also run a human-voice copy inside this repository, which is running repository code")
    sub.add_argument("--root")
    sub.set_defaults(handler=cmd_docs)
    return parser


def main(argv: list[str]) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(errors="replace")  # a document or a path can hold what this terminal can't show
    parser = _parser()
    args = parser.parse_args(argv)
    try:
        os.getcwd()
    except OSError:
        print("The folder this was run from no longer exists, so run it from one that does. Nothing was checked.")
        return 2
    _MAIN_PROCESS[0] = os.getpid()
    if hasattr(signal, "SIGHUP"):
        signal.signal(signal.SIGTERM, lambda _number, _frame: _end_now(143))
        if signal.getsignal(signal.SIGHUP) != signal.SIG_IGN:  # under nohup a hangup is meant to pass unnoticed
            signal.signal(signal.SIGHUP, lambda _number, _frame: _end_now(129))
    # A path that isn't there would otherwise read as an empty, clean answer. A query's single path arrives as text.
    args.paths = [args.paths] if isinstance(getattr(args, "paths", None), str) else getattr(args, "paths", None)
    missing = [path for path in args.paths or [] if not Path(path).exists()] if args.handler in READS_NAMED_PATHS else []
    if missing:
        print(f"No such path: {', '.join(missing)}.")
        return 2
    seconds = _time_limit(args)
    if seconds and hasattr(signal, "setitimer"):  # the limit bounds reading, and this bounds everything else, such as a git that takes minutes to answer
        signal.signal(signal.SIGALRM, _raise_out_of_time)
        signal.setitimer(signal.ITIMER_REAL, seconds + GRACE_SECONDS)
    try:
        return args.handler(args)
    except _OutOfTime:
        print(f"This didn't finish in {seconds + GRACE_SECONDS}s, even reading only part of the repository, which usually means git is very slow here. Nothing was checked. "
              "Name a folder, or use `--max-seconds 0` in the background, which has as long as it needs.")
        return 2
    except (GitProblem, OutsideProject) as error:
        print(f"{error}. Nothing was checked." if not str(error).endswith("checked.") else error)
        return 2
    except sqlite3.DatabaseError as error:
        print(f"occam's saved state can't be read ({error}), so nothing was checked. Removing its folder, under ~/.cache/occam, starts it fresh.")
        return 2
    except BrokenPipeError:
        return 0
    except KeyboardInterrupt:
        return 130
    except Exception:  # 1 means blockers or survivors to `gate` and `mutate`, so a crash can't exit with it
        traceback.print_exc()
        print("occam hit an internal error, so this wasn't checked. That says nothing about the code.")
        return 3
    finally:
        if seconds and hasattr(signal, "setitimer"):
            signal.setitimer(signal.ITIMER_REAL, 0)
