"""Command line: one thin handler per command, importing what it needs only when it runs."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

from . import VERSION
from .catalog import CATEGORIES
from .files import GitProblem, OutsideProject


def _root(args) -> Path:
    from .files import find_root
    target = getattr(args, "root", None) or (args.paths[0] if getattr(args, "paths", None) else ".")
    return find_root(target)


def _add_scan_filters(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--min-confidence", choices=("high", "medium", "low"), default="medium")
    parser.add_argument("--min-severity", choices=("critical", "high", "medium", "low"), default="low")
    parser.add_argument("--category", action="append", choices=CATEGORIES, help="repeatable")
    parser.add_argument("--rule", action="append", help="repeatable")


def _save_last(root: Path, findings: list[dict], stats: dict) -> str | None:
    from .files import state_dir
    try:
        path = state_dir(root) / "last-scan.json"
        path.write_text(json.dumps({"stats": stats, "findings": findings}))
        return str(path)
    except OSError:
        return None


def cmd_scan(args) -> int:
    from . import ledger, report, scan
    if args.stdin:
        name = args.name or {"python": "snippet.py", "javascript": "snippet.js", "typescript": "snippet.ts", "go": "snippet.go", "rust": "snippet.rs", "java": "Snippet.java",
                             "shell": "snippet.sh", "sql": "snippet.sql", "c": "snippet.c", "cpp": "snippet.cpp"}.get(args.lang or "python", "snippet.txt")
        result = scan.scan_snippet(name, sys.stdin.read(), args.lang)
        root = None
    else:
        root = _root(args)
        missing = [path for path in args.paths if not Path(path).exists()]
        if missing:
            print(f"No such path: {', '.join(missing)}.")
            return 2
        result = scan.run_scan(root, args.paths or None, changed_only=args.changed, base=args.diff, use_cache=not args.no_cache, workers=args.workers, isolated=args.isolated)
    findings = result.findings
    if (args.new_only or args.baseline) and root is not None:
        findings, warning = ledger.new_since_baseline(root, findings, args.baseline)
        if warning:
            print(warning, file=sys.stderr)
    visible = scan.filter_findings(findings, args.min_confidence, args.min_severity, args.category, args.rule)
    hidden = len(scan.filter_findings(findings, "low", args.min_severity, args.category, args.rule)) - len(visible)
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
        return 1 if any(order.index(f["severity"]) >= cut for f in visible) else 0
    return 0


def _run_query(args) -> str:
    from . import query, query_code, query_graph, query_repo
    root, name, top = _root(args), args.query_name, args.top
    paths = args.paths or None
    if name == "size":
        return query.render(query_repo.size(root, paths, args.depth, top), query_repo.render_size, args.format)
    if name == "commands":
        return query.render(query_repo.commands(root, top), query_repo.render_commands, args.format)
    if name == "entry":
        return query.render(query_repo.entry(root, paths, top), query_repo.render_entry, args.format)
    if name == "markers":
        return query.render(query_repo.markers(root, paths, args.kind, top), query_repo.render_markers, args.format)
    if name == "history":
        return query.render(query_repo.history(root, paths[0] if paths else None, args.since, args.commits, top, args.follow), query_repo.render_history, args.format)
    if name == "leaks":
        return query.render(query_repo.leaks(root, args.commits, top), query_repo.render_leaks, args.format)
    if name == "outline":
        return query.render(query_code.outline(root, paths, top), query_code.render_outline, args.format)
    if name == "find":
        return query.render(query_code.find(root, args.name, paths, top), query_code.render_find, args.format)
    if name == "grep":
        return query.render(query_code.grep(root, args.pattern, paths, args.where, args.lang, args.ignore_case, top), query_code.render_grep, args.format)
    if name == "functions":
        return query.render(query_code.functions(root, paths, args.sort, args.include_tests, top), query_code.render_functions, args.format)
    if name == "api":
        return query.render(query_code.api(root, paths, args.base, top), query_code.render_api, args.format)
    if name == "boundaries":
        return query.render(query_code.boundaries(root, paths, args.kind, args.include_tests, top), query_code.render_boundaries, args.format)
    if name == "graph":
        if paths:
            return query.render(query_graph.graph_file(root, paths[0], top), query_graph.render_graph_file, args.format)
        return query.render(query_graph.graph_overview(root, top), query_graph.render_graph_overview, args.format)
    if name == "impact":
        return query.render(query_graph.impact(root, paths, args.changed, args.diff, top), query_graph.render_impact, args.format)
    if paths:
        return query.render(query_graph.tests_for(root, paths, top), query_graph.render_tests_for, args.format)
    return query.render(query_graph.tests_overview(root, top), query_graph.render_tests_overview, args.format)


def cmd_query(args) -> int:
    from . import query
    args.paths = [args.paths] if isinstance(args.paths, str) else list(args.paths or [])
    missing = query.missing_paths(args.paths)
    if missing:
        print(f"No such path: {', '.join(missing)}.")
        return 2
    try:
        print(_run_query(args))
    except re.error as error:
        print(f"That isn't a valid expression: {error}")
        return 2
    except query.BadQuestion as error:
        print(error)
        return 2
    return 0


def cmd_rules(args) -> int:
    from . import report
    print(report.render_rules(args.category, args.rule_id))
    return 0


def cmd_map(args) -> int:
    from . import inventory
    root = _root(args)
    data = inventory.build_map(root, Path(args.paths[0]).resolve() if args.paths else None, args.isolated)
    print(json.dumps(data, indent=2) if args.format == "json" else inventory.render_map(data))
    return 0


def cmd_partition(args) -> int:
    from . import inventory
    root = _root(args)
    plan = inventory.partition(root, args.paths or None, reader_budget=args.budget, host_limit=args.max_agents, mode=args.mode)
    print(json.dumps(plan, indent=2) if args.format == "json" else inventory.render_partition(plan, args.goal))
    return 0


def cmd_tools(args) -> int:
    from . import toolrun
    root = _root(args)
    print(toolrun.run_tools(root, execute=args.run, allow_exec=args.allow_exec, only=args.only, paths=args.paths or None))
    return 0


def cmd_reuse(args) -> int:
    from . import reuse
    root = _root(args)
    print(reuse.search(root, " ".join(args.query), limit=args.limit, language=args.lang))
    return 0


def cmd_deps(args) -> int:
    from . import depcheck
    root = _root(args)
    report_text, exit_code = depcheck.report(root, online=args.online, names=args.name)
    print(report_text)
    return exit_code


def cmd_baseline(args) -> int:
    from . import ledger
    root = _root(args)
    print(ledger.write_baseline(root, args.out) if args.action == "write" else ledger.show_baseline(root))
    return 0


def cmd_ledger(args) -> int:
    from . import ledger
    root = _root(args)
    if args.action == "sync":
        print(ledger.sync(root, args.paths or None, changed_only=args.changed, base=args.diff, min_confidence=args.min_confidence))
    elif args.action == "list":
        print(ledger.listing(root, status=args.status, tier=args.tier, category=args.category_one, limit=args.top))
    elif args.action == "next":
        if not args.owner:
            print("Name yourself with --owner, so two agents can't be handed the same file.")
            return 2
        print(ledger.next_batch(root, owner=args.owner, size=args.size, tier=args.tier))
    elif args.action == "set":
        print(ledger.set_status(root, args.ids, args.status, args.note, args.owner))
    elif args.action == "decisions":
        print(ledger.decisions(root))
    else:
        print(ledger.markdown_report(root, args.out, args.title))
    return 0


def cmd_fix(args) -> int:
    from . import fix
    root = _root(args)
    text, code = fix.run(root, args.paths or None, rules=args.rule, apply=args.apply, allow_dirty=args.allow_dirty, owner=args.owner)
    print(text)
    return code


def cmd_golden(args) -> int:
    from . import verify
    root = _root(args)
    command, normalize, timeout = _golden_arguments(args.command or [], args.normalize, args.timeout)
    if args.action == "record":
        text, code = verify.golden_record(root, args.name, command, timeout, normalize)
    else:
        text, code = verify.golden_check(root, args.name, args.timeout)
    print(text)
    return code


def _golden_arguments(rest: list[str], normalize: list[str], timeout: int) -> tuple[list[str], list[str], int]:
    """Everything after the name lands here, so options written before -- still need picking out."""
    normalize = list(normalize)
    index = 0
    while index < len(rest) and rest[index] != "--":
        if rest[index] == "--normalize" and index + 1 < len(rest):
            normalize.append(rest[index + 1])
        elif rest[index] == "--timeout" and index + 1 < len(rest):
            timeout = int(rest[index + 1])
        else:
            break
        index += 2
    if index < len(rest) and rest[index] == "--":
        index += 1
    return rest[index:], normalize, timeout


def cmd_mutate(args) -> int:
    from . import verify
    root = _root(args)
    text, code = verify.mutate(root, args.cmd, args.paths or None, changed=args.changed, base=args.diff, limit=args.max, timeout=args.timeout)
    print(text)
    return code


def cmd_bench(args) -> int:
    from . import verify
    text, code = verify.bench(args.cmd, [int(size) for size in args.sizes.split(",")], args.repeat, args.limit_seconds, args.limit_rss_mb, args.timeout)
    print(text)
    return code


def cmd_coord(args) -> int:
    from . import workflow
    root = _root(args)
    text, code = workflow.coord(root, args.action, args.paths or [], args.owner, args.ttl)
    print(text)
    return code


def cmd_goal(args) -> int:
    from . import workflow
    root = _root(args)
    text, code = workflow.goal(root, args)
    print(text)
    return code


def cmd_debt(args) -> int:
    from . import debt
    root = _root(args)
    missing = [path for path in args.paths if not Path(path).exists()]
    if missing:
        print(f"No such path: {', '.join(missing)}.")
        return 2
    print(debt.debt(root, args.paths or None))
    return 0


def cmd_gate(args) -> int:
    from . import verify
    root = _root(args)
    text, code = verify.gate(root, base=args.base, strict=args.strict, paths=args.paths or None)
    print(text)
    return code


def cmd_docs(args) -> int:
    from . import docs
    text, code = docs.check(_root(args), paths=args.paths or None, before=args.before, register=args.register, allow_exec=args.allow_exec)
    print(text)
    return code


def _add_query_parsers(commands) -> None:
    sub = commands.add_parser(allow_abbrev=False, name="query", help="Plain answers about the code: its size, who calls what, what a change reaches, who owns it. Read-only, runs nothing, and output is bounded")
    queries = sub.add_subparsers(dest="query_name", required=True)

    def query(name: str, about: str, paths: str | None = "*", top: int = 30):
        parser = queries.add_parser(name, allow_abbrev=False, help=about, description=about)
        if paths:
            parser.add_argument("paths", nargs=paths)
        parser.add_argument("--top", type=int, default=top, help="how many of each list to show")
        parser.add_argument("--format", choices=("text", "json"), default="text")
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


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="occam", description="Audit and repair tools for agents. Read-only unless a command says otherwise.", allow_abbrev=False)
    parser.add_argument("--version", action="version", version=VERSION)
    commands = parser.add_subparsers(dest="command_name", required=True)

    sub = commands.add_parser(allow_abbrev=False, name="map", help="Size, languages, tooling, risky areas, strategy and agent count for this repository")
    sub.add_argument("paths", nargs="*")
    sub.add_argument("--format", choices=("text", "json"), default="text")
    sub.add_argument("--isolated", action="store_true", help="read only this path, for a repository too large to hold in memory. Cross-file rules don't run")
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
    sub.add_argument("--isolated", action="store_true", help="read only these paths, for a repository too large to hold in memory. Cross-file rules don't run")
    _add_scan_filters(sub)
    sub.set_defaults(handler=cmd_scan)

    _add_query_parsers(commands)

    sub = commands.add_parser(allow_abbrev=False, name="rules", help="What the scanner can report")
    sub.add_argument("rule_id", nargs="?")
    sub.add_argument("--category", choices=CATEGORIES)
    sub.set_defaults(handler=cmd_rules)

    sub = commands.add_parser(allow_abbrev=False, name="tools", help="Which established analyzers exist here, and run them. They beat occam's rules where they overlap")
    sub.add_argument("paths", nargs="*")
    sub.add_argument("--run", action="store_true", help="run the ones that execute no repository code")
    sub.add_argument("--allow-exec", action="store_true", help="also run tools that load repository config or code, such as eslint or clippy")
    sub.add_argument("--only", action="append", help="repeatable")
    sub.set_defaults(handler=cmd_tools)

    sub = commands.add_parser(allow_abbrev=False, name="reuse", help="Before writing something new: what already exists for this?")
    sub.add_argument("query", nargs="+")
    sub.add_argument("--limit", type=int, default=10)
    sub.add_argument("--lang")
    sub.add_argument("--root")
    sub.set_defaults(handler=cmd_reuse)

    sub = commands.add_parser(allow_abbrev=False, name="deps", help="Declared versus used dependencies, phantom packages, competing libraries")
    sub.add_argument("--online", action="store_true", help="check registries for existence and age. Sends package names only")
    sub.add_argument("--name", action="append", help="check this package before adding it, by asking its registry. Form: pypi:name, npm:name, crates:name")
    sub.add_argument("--root")
    sub.set_defaults(handler=cmd_deps)

    sub = commands.add_parser(allow_abbrev=False, name="baseline", help="Ratchet for large repositories: accept today's findings so only new ones count")
    sub.add_argument("action", choices=("write", "show"))
    sub.add_argument("--out", help="write: save to a file you can commit, for CI")
    sub.add_argument("--root")
    sub.set_defaults(handler=cmd_baseline)

    sub = commands.add_parser(allow_abbrev=False, name="ledger", help="Track findings through triage and repair. Shared by concurrent agents")
    sub.add_argument("action", choices=("sync", "list", "next", "set", "decisions", "report"))
    sub.add_argument("paths", nargs="*", help="sync: paths to scan")
    sub.add_argument("--ids", nargs="*", default=[])
    sub.add_argument("--status", choices=("open", "confirmed", "false-positive", "accepted", "needs-decision", "in-progress", "fixed", "deferred"))
    sub.add_argument("--note")
    sub.add_argument("--owner")
    sub.add_argument("--tier", choices=("A", "B", "C"))
    sub.add_argument("--category-one", dest="category_one", choices=CATEGORIES)
    sub.add_argument("--top", type=int, default=40)
    sub.add_argument("--size", type=int, default=5, help="next: findings per batch")
    sub.add_argument("--changed", action="store_true")
    sub.add_argument("--diff")
    sub.add_argument("--min-confidence", choices=("high", "medium", "low"), default="medium")
    sub.add_argument("--out", help="report: write Markdown here")
    sub.add_argument("--title", default="Audit")
    sub.add_argument("--root")
    sub.set_defaults(handler=cmd_ledger)

    sub = commands.add_parser(allow_abbrev=False, name="partition", help="Split work into disjoint shards, and say how many agents that justifies")
    sub.add_argument("paths", nargs="*")
    sub.add_argument("--mode", choices=("read", "write"), default="read")
    sub.add_argument("--budget", type=int, default=5000, help="lines one reader takes")
    sub.add_argument("--max-agents", type=int, default=6, help="host or budget limit")
    sub.add_argument("--goal", default="Audit this part of the repository.")
    sub.add_argument("--format", choices=("text", "json"), default="text")
    sub.set_defaults(handler=cmd_partition)

    sub = commands.add_parser(allow_abbrev=False, name="fix", help="Tier A repairs with a proof the code didn't change. Dry run unless --apply")
    sub.add_argument("paths", nargs="*")
    sub.add_argument("--rule", action="append", help="default: plain ai-residue. unused-import and commented-out-code must be named")
    sub.add_argument("--apply", action="store_true", help="WRITES FILES")
    sub.add_argument("--allow-dirty", action="store_true", help="also touch files with uncommitted changes. Only your own")
    sub.add_argument("--owner", help="your agent name, so your own claims don't block you")
    sub.set_defaults(handler=cmd_fix)

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
    sub.add_argument("--max", type=int, default=20)
    sub.add_argument("--timeout", type=int, default=120)
    sub.set_defaults(handler=cmd_mutate)

    sub = commands.add_parser(allow_abbrev=False, name="bench", help="Measure time and peak memory across input sizes, in fresh processes. Runs the command")
    sub.add_argument("--cmd", required=True, help="use {n} for the size")
    sub.add_argument("--sizes", required=True, help="comma separated")
    sub.add_argument("--repeat", type=int, default=3)
    sub.add_argument("--limit-seconds", type=float)
    sub.add_argument("--limit-rss-mb", type=float)
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
    sub.add_argument("--where", help="add: where it's implemented")
    sub.add_argument("--forbid", help="constrain: path glob that must not change")
    sub.add_argument("--timeout", type=int, default=600)
    sub.add_argument("--base", help="verify: revision to compare scope against")
    sub.add_argument("--root")
    sub.set_defaults(handler=cmd_goal)

    sub = commands.add_parser(allow_abbrev=False, name="debt", help="Work the code says it deferred: marked shortcuts and TODOs, and which have no trigger to revisit them")
    sub.add_argument("paths", nargs="*")
    sub.add_argument("--root")
    sub.set_defaults(handler=cmd_debt)

    sub = commands.add_parser(allow_abbrev=False, name="gate", help="Critique your own change before calling it done. Exit 1 on blockers")
    sub.add_argument("paths", nargs="*", help="what you changed, if this isn't a git repository")
    sub.add_argument("--base", help="revision to compare with, default uncommitted changes")
    sub.add_argument("--strict", action="store_true", help="warnings block too")
    sub.add_argument("--root")
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
    parser = _parser()
    args = parser.parse_args(argv)
    try:
        return args.handler(args)
    except (GitProblem, OutsideProject) as error:
        print(f"{error}. Nothing was checked." if not str(error).endswith("checked.") else error)
        return 2
    except BrokenPipeError:
        return 0
    except KeyboardInterrupt:
        return 130
