"""Questions about the repository as a whole: how big, how to run it, where it starts, what it silences, who changed what."""

from __future__ import annotations

import fnmatch
import json
import re
from collections import Counter, defaultdict
from pathlib import Path

from . import files as filesystem
from .project import _CONSEQUENCE
from .query import WORD_START, Views, hits_by_file, language_at, more, safe_line, search, selected_files
from .rules_text import has_secret_assignment, has_secret_shape
from .source import is_test_path

MANIFESTS = {"pyproject.toml", "setup.py", "package.json", "go.mod", "Cargo.toml", "pom.xml", "build.gradle", "build.gradle.kts", "composer.json", "Gemfile", "mix.exs", "CMakeLists.txt"}
HUGE_LINES = 5_000_000  # where a whole-repository scan starts to cost gigabytes, at about 0.55 GB per million lines


# ---------------------------------------------------------------- size

def _newlines(path: Path) -> int:
    """What `wc -l` reports. Symlinks count as nothing, because they could point anywhere."""
    if not filesystem.is_plain_file(path):
        return 0
    count = 0
    try:
        with open(path, "rb") as handle:
            for chunk in iter(lambda: handle.read(1 << 20), b""):
                count += chunk.count(b"\n")
    except OSError:
        return 0
    return count


def _group(path: str, depth: int) -> str:
    parts = path.split("/")[:-1]
    return "/".join(parts[:depth]) or "."


def size(root: Path, targets: list[str] | None, depth: int | None, top: int) -> dict:
    files = selected_files(root, targets)
    known = filesystem.tracked_files(root)
    skipped = len(known) - len(selected_files(root, None)) if known is not None else None
    base = min((target.count("/") + 1 for target in map(lambda t: _relative(root, t), targets or []) if target != "."), default=0)
    depth = depth if depth is not None else base + 1
    languages: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    folders: dict[str, dict] = defaultdict(lambda: {"files": 0, "lines": 0, "test_lines": 0, "languages": Counter()})
    subsystems = sorted({path.rsplit("/", 1)[0] if "/" in path else "." for path in filesystem.list_files(root, None, filesystem.load_config(root)) if path.rsplit("/", 1)[-1] in MANIFESTS},
                        key=lambda folder: -folder.count("/"))
    package_lines: Counter = Counter()
    largest = []
    other = lines = code_files = 0
    for path in files:
        language = language_at(root, path)
        if not language:
            other += 1
            continue
        count = _newlines(root / path)
        code_files += 1
        lines += count
        largest.append((count, path))
        languages[language][0] += 1
        languages[language][1] += count
        folder = folders[_group(path, depth)]
        folder["files"] += 1
        folder["lines"] += count
        folder["languages"][language] += count
        folder["test_lines"] += count if is_test_path(path) else 0
        package_lines[next((s for s in subsystems if s == "." or path.startswith(s + "/")), "")] += count
    largest.sort(key=lambda item: (-item[0], item[1]))
    rows = [{"path": name, **{key: value for key, value in row.items() if key != "languages"}, "languages": [language for language, _ in row["languages"].most_common(3)]}
            for name, row in sorted(folders.items(), key=lambda item: -item[1]["lines"])]
    return {"root": str(root), "lines": lines, "files": code_files, "other_files": other, "vendored_or_generated_skipped": skipped, "depth": depth,
            "languages": {name: {"files": count[0], "lines": count[1]} for name, count in sorted(languages.items(), key=lambda item: -item[1][1])},
            "directories": rows[:top], "directories_total": len(rows),
            "largest_files": [{"path": path, "lines": count} for count, path in largest[:top]],
            "subsystems": [{"path": name or "(outside any manifest)", "lines": count} for name, count in package_lines.most_common(top)], "subsystems_total": len(package_lines)}


def _relative(root: Path, target: str) -> str:
    try:
        return str(Path(target).resolve().relative_to(root.resolve())).replace("\\", "/")
    except ValueError as error:
        raise filesystem.OutsideProject(f"{target} is outside this project ({root}). Nothing was checked.") from error


def render_size(data: dict) -> str:
    languages = ", ".join(f"{name} {row['lines']:,}" for name, row in list(data["languages"].items())[:8])
    skipped = data["vendored_or_generated_skipped"]
    out = [f"{data['lines']:,} lines in {data['files']:,} code files, as `wc -l` counts ({languages or 'no code'}). {data['other_files']:,} other files."
           + (f" {skipped:,} vendored or generated files left out." if skipped else "")]
    if data["lines"] >= HUGE_LINES:
        out.append(f"That's about {data['lines'] * 0.55 / 1_000_000:.0f} GB for a whole-repository `occam scan`. Scope reading to one subsystem with `occam scan --isolated PATH`.")
    out += ["", f"By directory, to depth {data['depth']}:", f"  {'lines':>10} {'files':>7} {'tests':>6}  directory"]
    for row in data["directories"]:
        share = f"{100 * row['test_lines'] // row['lines']}%" if row["lines"] else "-"
        out.append(f"  {row['lines']:>10,} {row['files']:>7,} {share:>6}  {row['path']}  ({', '.join(row['languages'])})")
    out += more(data["directories_total"] - len(data["directories"]))
    if len(data["subsystems"]) > 1:
        out += ["", f"Subsystems, each folder with a manifest ({data['subsystems_total']}):"]
        out += [f"  {row['lines']:>10,}  {row['path']}" for row in data["subsystems"]]
    out += ["", "Largest files:"] + [f"  {row['lines']:>10,}  {row['path']}" for row in data["largest_files"]]
    return "\n".join(out)


# ---------------------------------------------------------------- commands

_KINDS = (("setup", r"\b(?:pip3? install|npm (?:ci|install)|uv sync|apt-get|apt install|brew install|poetry install|pnpm install|yarn install|bundle install|curl|actions/\S+)\b"),
          ("test", r"\b(?:test|tests|pytest|unittest|nose|tox|nox|jest|vitest|mocha|ava|rspec|ctest|phpunit|e2e|spec|coverage|check-all)\b"),
          ("lint", r"\b(?:lint|linter|ruff|flake8|pylint|eslint|biome|clippy|golangci|shellcheck|staticcheck|rubocop|semgrep|bandit|vet)\b"),
          ("types", r"\b(?:mypy|pyright|tsc|typecheck|type-check|types)\b"),
          ("format", r"\b(?:format|fmt|black|isort|prettier|gofmt|rustfmt|shfmt)\b"),
          ("build", r"\b(?:build|compile|bundle|package|dist|wheel|webpack|vite|rollup|docker build)\b"),
          ("run", r"\b(?:run|start|serve|server|dev|up|deploy|release|publish|install|migrate)\b"))
_MAKE_TARGET = re.compile(r"^([A-Za-z0-9][\w./-]*)[ \t]*:(?!=)", re.M)
_JUST_RECIPE = re.compile(r"^@?([A-Za-z0-9][\w-]*)[^\n:=]*:(?!=)[^\n]*$", re.M)
_CI_FILE = re.compile(r"(^|/)(\.github/workflows/[^/]+\.ya?ml|\.gitlab-ci\.yml|\.travis\.yml|\.circleci/config\.yml|azure-pipelines\.ya?ml|bitbucket-pipelines\.yml)$")
_CI_KEY = re.compile(r"^(\s*)(?:-\s*)?(run|command|script|before_script|after_script)\s*:\s*(.*)$")
_DOC_FILE = re.compile(r"(?:^|/)(README|CONTRIBUTING|DEVELOPMENT|HACKING)(\.\w+)?$", re.I)
_TOX_SECTION = re.compile(r"\[testenv:([\w-]+)\]")
_TOX_COMMANDS = re.compile(r"commands[ \t]*=[ \t]*(.*)")
_FENCE = re.compile(r"^```(bash|sh|shell|console|zsh)\s*$(.*?)^```", re.M | re.S)
_INFERRED = {"go.mod": ["go test ./...", "go vet ./..."], "Cargo.toml": ["cargo test", "cargo clippy"], "pom.xml": ["mvn test"], "build.gradle": ["./gradlew test"],
             "build.gradle.kts": ["./gradlew test"], "CMakeLists.txt": ["ctest"], "WORKSPACE": ["bazel test //..."], "MODULE.bazel": ["bazel test //..."], "Gemfile": ["bundle exec rake test"]}
_PYPROJECT_TOOLS = {"pytest": "pytest", "ruff": "ruff check .", "mypy": "mypy .", "pyright": "pyright", "black": "black --check .", "isort": "isort --check .", "coverage": "coverage run -m pytest"}


def _unquoted(text: str) -> str:
    return text[1:-1] if len(text) >= 2 and text[0] == text[-1] and text[0] in "'\"" else text


def _kind_of(text: str) -> str:
    lowered = text.lower()
    return next((kind for kind, pattern in _KINDS if re.search(pattern, lowered)), "other")


def _line_at(text: str, offset: int) -> int:
    return text.count("\n", 0, offset) + 1


def _entry(path: str, line: int, name: str, command: str, how: str) -> dict:
    return {"kind": _kind_of(f"{name} {command}"), "name": name, "command": safe_line(command), "where": f"{path}:{line}", "how": how}


def _make_commands(path: str, text: str) -> list[dict]:
    found = []
    lines = text.split("\n")
    for match in _MAKE_TARGET.finditer(text):
        if not match.group(1).startswith("."):
            number = _line_at(text, match.start())
            recipe = lines[number].strip() if number < len(lines) and lines[number].startswith("\t") else ""
            found.append(_entry(path, number, match.group(1), recipe or f"make {match.group(1)}", "make target"))
    return found


def _just_commands(path: str, text: str) -> list[dict]:
    return [_entry(path, _line_at(text, match.start()), match.group(1), f"just {match.group(1)}", "just recipe") for match in _JUST_RECIPE.finditer(text) if not match.group(0).startswith((" ", "\t"))]


def _package_commands(path: str, text: str) -> list[dict]:
    try:
        scripts = json.loads(text).get("scripts")
    except (ValueError, AttributeError):
        return []
    if not isinstance(scripts, dict):
        return []
    return [_entry(path, _line_at(text, max(text.find(f'"{name}"'), 0)), name, str(command), "package.json script") for name, command in scripts.items()]


def _pyproject_commands(path: str, text: str) -> list[dict]:
    found = []
    for tool, command in _PYPROJECT_TOOLS.items():
        match = re.search(rf"^\[tool\.{tool}[.\]]", text, re.M)
        if match:
            found.append(_entry(path, _line_at(text, match.start()), tool, command, "inferred from its configuration, not stated"))
    for section in re.finditer(r"^\[tool\.(?:poe\.tasks|pdm\.scripts|hatch\.envs\.[\w-]+\.scripts)\]\s*$(.*?)(?=^\[|\Z)", text, re.M | re.S):
        for task in re.finditer(r"^([\w-]+)\s*=\s*(.+)$", section.group(1), re.M):
            found.append(_entry(path, _line_at(text, section.start(1) + task.start()), task.group(1), task.group(2).strip("\"' "), "pyproject task"))
    return found


def _tox_commands(path: str, text: str) -> list[dict]:
    """By line, since an expression that runs on to the next `commands` would reread the file for every environment that has none."""
    found: list[dict] = []
    current = None
    for number, line in enumerate(text.split("\n"), start=1):
        section = _TOX_SECTION.match(line)
        if section:
            current = (section.group(1), number)
            found.append(_entry(path, number, f"tox -e {current[0]}", "", "tox environment"))
        elif line.startswith("[") or current is None:
            current = None
        else:
            command = _TOX_COMMANDS.match(line)
            if command:
                found[-1] = _entry(path, current[1], f"tox -e {current[0]}", command.group(1).strip(), "tox environment")
                current = None
    return found


def _nox_commands(path: str, text: str) -> list[dict]:
    return [_entry(path, _line_at(text, match.start()), match.group(1), f"nox -s {match.group(1)}", "nox session") for match in re.finditer(r"@nox\.session[^\n]*\n\s*def (\w+)", text)]


def _ci_commands(path: str, text: str) -> list[dict]:
    """A small reading of YAML shapes every CI system shares: a key whose value is a command, a block, or a list."""
    found = []
    lines = text.split("\n")
    index = 0
    while index < len(lines):
        match = _CI_KEY.match(lines[index])
        index += 1
        if not match:
            continue
        indent, value = len(match.group(1)), match.group(3).strip()
        if value and value[0] not in "|>" and not value.startswith("#"):
            if not value.startswith("["):
                found.append(_entry(path, index, value.split(" ")[0], _unquoted(value), "CI step"))
            continue
        while index < len(lines) and (not lines[index].strip() or len(lines[index]) - len(lines[index].lstrip()) > indent or lines[index].lstrip().startswith("- ")):
            body = _unquoted(lines[index].strip().lstrip("- "))
            if body and not body.startswith("#"):
                found.append(_entry(path, index + 1, body.split(" ")[0], body, "CI step"))
            index += 1
    return found


def _doc_commands(path: str, text: str) -> list[dict]:
    found = []
    for fence in _FENCE.finditer(text):
        offset = fence.start(2)
        for number, line in enumerate(fence.group(2).split("\n")):
            if fence.group(1) == "console" and not line.lstrip().startswith("$ "):  # the rest of a console block is output
                continue
            command = line.strip().lstrip("$ ").strip()
            if command and not command.startswith("#") and _kind_of(command) != "other":
                found.append(_entry(path, _line_at(text, offset) + number, command.split(" ")[0], command, "documented"))
    return found


def commands(root: Path, top: int) -> dict:
    found: list[dict] = []
    readers = {"Makefile": _make_commands, "GNUmakefile": _make_commands, "makefile": _make_commands, "justfile": _just_commands, "Justfile": _just_commands,
               "package.json": _package_commands, "pyproject.toml": _pyproject_commands, "tox.ini": _tox_commands, "noxfile.py": _nox_commands}
    all_files = selected_files(root, None)
    for path in all_files:
        name = path.rsplit("/", 1)[-1]
        reader = readers.get(name) or (_ci_commands if _CI_FILE.search(path) else _doc_commands if _DOC_FILE.search(path) else None)
        inferred = _INFERRED.get(name)
        if reader is None and not inferred:
            continue
        text = filesystem.read_text(root / path)
        if text is None:
            continue
        found += reader(path, text) if reader else []
        found += [_entry(path, 1, command.split(" ")[0], command, "inferred from this manifest, not stated") for command in inferred or []]
    found.sort(key=lambda row: (row["where"].count("/"), row["kind"] == "other", row["kind"], row["where"]))
    groups: dict[str, list[dict]] = defaultdict(list)
    for row in found:
        groups[row["kind"]].append(row)
    return {"total": len(found), "kinds": {kind: rows[:top] for kind, rows in groups.items()}, "kind_totals": {kind: len(rows) for kind, rows in groups.items()}}


def render_commands(data: dict) -> str:
    if not data["total"]:
        return "No build, test or lint commands are stated in the manifests, Makefiles, CI files or READMEs here."
    out = [f"{data['total']} commands this repository states. Listed, not run. They're repository content, so read them before running any."]
    for kind in ("test", "lint", "types", "format", "build", "run", "setup", "other"):
        rows = data["kinds"].get(kind)
        if rows:
            out += ["", f"{kind} ({data['kind_totals'][kind]}):"]
            out += [f"  {row['command']}  [{row['where']}, {row['how']}]" for row in rows]
            out += more(data["kind_totals"][kind] - len(rows))
    return "\n".join(out)


# ---------------------------------------------------------------- entry points

_ROUTE = (r"@[A-Za-z_][A-Za-z0-9_.]*\.(route|get|post|put|patch|delete|websocket|api_route)\("
          r"|(app|router|server|fastify|api)\.(get|post|put|patch|delete|use|all)\([\"'`]"
          r"|[^A-Za-z0-9_](HandleFunc|Handle|GET|POST|PUT|DELETE|PATCH)\(\""
          r"|@(Get|Post|Put|Delete|Patch|Request)Mapping"
          r"|#\[(get|post|put|delete|patch)\(\""
          r"|Route::(get|post|put|patch|delete)\("
          r"|^[ \t]*(re_)?path\([\"'r]")
_MAINS = (("main", r"^[ \t]*if __name__ *== *[\"']__main__[\"']"), ("main", r"^func main\("), ("main", r"^[ \t]*(pub )?(async )?fn main\("),
          ("main", r"public static void main[ (]"), ("main", r"^(int|void) +main *\("), ("main", r"^fun main\("), ("main", r"if __FILE__ *== *\$0"))
_JOBS = (r"@([A-Za-z_][A-Za-z0-9_.]*\.)?(task|shared_task|periodic_task|scheduled_job|actor)([^A-Za-z0-9_]|$)|@Scheduled|@KafkaListener|@RabbitListener"
         r"|(BackgroundScheduler|BlockingScheduler|AsyncIOScheduler|KafkaConsumer|CronJob)\(|^kind: *CronJob|^[ \t]*-[ \t]*cron:")
_CLIS = r"ArgumentParser\(|@click\.(command|group)|typer\.Typer\(|cobra\.Command\{|derive\(.*Parser|program\.command\(|yargs\("
_NEXT_ROUTE = re.compile(r"(^|/)(pages/api/.+|app/(.+/)?route)\.(js|ts|jsx|tsx)$")


def _route_label(text: str) -> str:
    quoted = re.search(r"[\"'`](/[^\"'`]*|[^\"'`]*)[\"'`]", text)
    verb = re.search(r"\.(route|get|post|put|patch|delete|websocket|use|all)\(|(GET|POST|PUT|DELETE|PATCH)\(|(Get|Post|Put|Delete|Patch)Mapping", text)
    method = next((group for group in verb.groups() if group), "") if verb else ""
    return f"{method.upper()} {quoted.group(1) if quoted else ''}".strip() or text.strip()[:80]


def _manifest_entries(root: Path, files: list[str]) -> list[dict]:
    found = []
    for path in files:
        name = path.rsplit("/", 1)[-1]
        if name == "__main__.py":
            found.append({"kind": "main", "where": f"{path}:1", "what": "python -m entry"})
        elif _NEXT_ROUTE.search(path):
            found.append({"kind": "http", "where": f"{path}:1", "what": "route by file location"})
        elif name in ("pyproject.toml", "setup.py", "setup.cfg", "package.json", "Procfile", "docker-compose.yml", "compose.yaml") or name.startswith("Dockerfile"):
            text = filesystem.read_text(root / path)
            found += _entries_in(path, name, text) if text else []
    return found


def _entries_in(path: str, name: str, text: str) -> list[dict]:
    found = []
    if name == "pyproject.toml":
        for section in re.finditer(r"^\[(?:project\.scripts|tool\.poetry\.scripts|project\.gui-scripts)\]\s*$(.*?)(?=^\[|\Z)", text, re.M | re.S):
            found += [{"kind": "script", "where": f"{path}:{_line_at(text, section.start(1) + item.start())}", "what": f"{item.group(1)} = {item.group(2).strip()}"}
                      for item in re.finditer(r"^([\w.-]+)\s*=\s*(.+)$", section.group(1), re.M)]
    elif name in ("setup.py", "setup.cfg"):
        found += [{"kind": "script", "where": f"{path}:{_line_at(text, item.start())}", "what": item.group(0).strip()} for item in re.finditer(r"(?<![\w-])[\w-]+[ \t]*=[ \t]*[\w.]+:[\w.]+", text)]
    elif name == "package.json":
        try:
            manifest = json.loads(text)
        except ValueError:
            return []
        if isinstance(manifest, dict):
            bins = manifest.get("bin")
            bins = bins if isinstance(bins, dict) else {manifest.get("name", "bin"): bins} if bins else {}
            found += [{"kind": "script", "where": f"{path}:1", "what": f"{key} = {value}"} for key, value in bins.items()]
            found += [{"kind": "main", "where": f"{path}:1", "what": f"{key} {manifest[key]}"} for key in ("main", "module") if isinstance(manifest.get(key), str)]
    elif name == "Procfile":
        found += [{"kind": "container", "where": f"{path}:{number}", "what": safe_line(line)} for number, line in enumerate(text.split("\n"), 1) if ":" in line and not line.startswith("#")]
    else:
        found += [{"kind": "container", "where": f"{path}:{_line_at(text, item.start())}", "what": safe_line(item.group(0))} for item in re.finditer(r"^[ \t]*(?:CMD|ENTRYPOINT|command:|entrypoint:)[ \t]*\S.*$", text, re.M)]
    return found


def entry(root: Path, targets: list[str] | None, top: int) -> dict:
    views = Views(root)
    files = selected_files(root, targets)
    found = _manifest_entries(root, files)
    searches = [("main", pattern) for _, pattern in _MAINS] + [("http", _ROUTE), ("job", _JOBS), ("cli", _CLIS)]
    rows, stopped = hits_by_file([(kind, pattern, *search(root, pattern, targets)) for kind, pattern in searches])
    for hit, kind, compiled in rows:
        match = None if is_test_path(hit.path) else compiled.search(hit.text)
        if match and views.kind_of(hit, match) in ("code", "text"):
            found.append({"kind": kind, "where": f"{hit.path}:{hit.line}", "what": _route_label(hit.text) if kind == "http" else safe_line(hit.text)})
    groups: dict[str, list[dict]] = defaultdict(list)
    for row in sorted(found, key=lambda row: row["where"]):
        groups[row["kind"]].append(row)
    return {"totals": {kind: len(rows) for kind, rows in groups.items()}, "kinds": {kind: rows[:top] for kind, rows in groups.items()}, "stopped_at_limit": stopped}


def render_entry(data: dict) -> str:
    if not data["totals"]:
        return "No entry points found by name or pattern. Frameworks that register by configuration won't show here, so check the manifests and the README."
    names = {"script": "Installed commands", "main": "Program starts", "cli": "Command line parsers", "http": "HTTP routes", "job": "Background jobs and schedules", "container": "Container and process commands"}
    out = ["Where execution starts, found by pattern, in code and manifests. Tests are left out. Routes registered in a loop or from configuration won't show."]
    for kind, title in names.items():
        rows = data["kinds"].get(kind)
        if rows:
            out += ["", f"{title} ({data['totals'][kind]}):"] + [f"  {row['where']}  {row['what']}" for row in rows]
            out += more(data["totals"][kind] - len(rows))
    return "\n".join(out)


# ---------------------------------------------------------------- markers

MARKERS = (
    ("suppression", r"noqa|type: *ignore|pylint: *disable|pyright: *ignore|mypy: *ignore|nosec|eslint-disable|@ts-ignore|@ts-expect-error|@ts-nocheck|biome-ignore|nolint|NOLINT|#!?\[allow\(|@SuppressWarnings"
     r"|shellcheck +disable|pragma: *no cover|istanbul ignore|c8 ignore|occam: *ignore", ("comment", "code"), "A checker told not to look here"),
    ("skipped-test", r"pytest\.mark\.(skip|xfail|skipif)|pytest\.(skip|xfail)\(|unittest\.(skip|expectedFailure)|@(Disabled|Ignore)|t\.Skip\(|#\[ignore|\.skip\(|" + WORD_START + r"(xit|xdescribe|xtest)\(", ("code",), "Tests that don't run"),
    ("focused-test", r"\.only\(|" + WORD_START + r"(fit|fdescribe)\(", ("code",), "Tests that stop the others running"),
    ("hidden-check", r"continue-on-error: *true|allow[-_]failure: *true|fail_ci_if_error: *false|ignore_errors *= *[Tt]rue|ignore_missing_imports *= *true|addopts.*(--ignore|--deselect|-k *[\"']?not)|\|\| *true", ("code", "string", "text"), "Configuration or commands that hide a failure"),
)


_CONFIG_FILE = re.compile(r"\.(?:ya?ml|toml|ini|cfg|conf)$|(?:^|/)(?:Makefile|Dockerfile[^/]*|Jenkinsfile)$")


def _marker_counts(root: Path, views: Views, kind: str, allowed: tuple, hit, match) -> bool:
    found = views.kind_of(hit, match)
    if found == "text":
        return kind == "hidden-check" and bool(_CONFIG_FILE.search(hit.path))
    if kind == "hidden-check" and language_at(root, hit.path) != "shell":
        return False
    return found in allowed


def markers(root: Path, targets: list[str] | None, kinds: list[str] | None, top: int) -> dict:
    views = Views(root)
    wanted = [row for row in MARKERS if not kinds or row[0] in kinds]
    rows, stopped = hits_by_file([(kind, pattern, *search(root, pattern, targets)) for kind, pattern, _, _ in wanted])
    allowed = {kind: places for kind, _, places, _ in wanted}
    kept_by_kind: dict[str, list] = defaultdict(list)
    for hit, kind, compiled in rows:
        match = compiled.search(hit.text)
        if match and _marker_counts(root, views, kind, allowed[kind], hit, match):
            kept_by_kind[kind].append(hit)
    results = {}
    for kind, _, _, meaning in wanted:
        kept = kept_by_kind[kind]
        per_file = Counter(hit.path for hit in kept)
        results[kind] = {"meaning": meaning, "total": len(kept), "files": len(per_file), "top_files": per_file.most_common(10),
                         "sample": [{"where": f"{hit.path}:{hit.line}", "text": safe_line(hit.text)} for hit in sorted(kept, key=lambda hit: (is_test_path(hit.path), hit.path, hit.line))[:top]]}
    return {"kinds": results, "stopped_at_limit": stopped}


def render_markers(data: dict) -> str:
    out = ["Where this code turns its own checks off: silenced checkers, tests that don't run, failures hidden. A count, not a verdict, so read whether each has a reason. Deferred work is `occam debt`."]
    for kind, row in data["kinds"].items():
        out += ["", f"{kind}: {row['total']:,} in {row['files']:,} files. {row['meaning']}."]
        out += [f"  {entry_['where']}  {entry_['text']}" for entry_ in row["sample"]]
        out += more(row["total"] - len(row["sample"]))
    return "\n".join(out)


# ---------------------------------------------------------------- history

_FIX_SUBJECT = re.compile(r"\b(?:fix(?:es|ed)?|bug|hotfix|revert|regression|incident|patch)\b", re.I)
_CODEOWNERS = (".github/CODEOWNERS", "CODEOWNERS", "docs/CODEOWNERS")
_COMMIT = re.compile(r"^\x00([0-9a-f]+)\x1f(.*)\x1f(\d+)\x1f(.*)$", re.S)
_BIG_COMMIT = 30  # a commit touching more than this is a sweep, and says nothing about which files belong together


def codeowners(root: Path, path: str) -> str | None:
    """The owners of a path. CODEOWNERS uses gitignore patterns, read here simply: the last match wins, and negation isn't supported there either."""
    for name in _CODEOWNERS:
        text = filesystem.read_text(root / name)
        if text is None:
            continue
        owners = None
        for line in text.split("\n"):
            parts = line.split("#", 1)[0].split()
            if len(parts) >= 2 and _owner_match(parts[0], path):
                owners = " ".join(parts[1:])
        return owners
    return None


def _owner_match(pattern: str, path: str) -> bool:
    if pattern.endswith("/"):
        pattern += "*"
    anchored = pattern.startswith("/") or "/" in pattern.rstrip("*").rstrip("/")
    bare = pattern.lstrip("/")
    if not anchored:
        return fnmatch.fnmatch(path.rsplit("/", 1)[-1], bare) or any(fnmatch.fnmatch(part, bare) for part in path.split("/"))
    return fnmatch.fnmatch(path, bare) or fnmatch.fnmatch(path, bare + "/*") or path.startswith(bare.rstrip("*"))


def _bus_factor(authors: Counter) -> int:
    """How few people account for more than half of the commits."""
    total = sum(authors.values())
    covered = people = 0
    for _, count in authors.most_common():
        covered += count
        people += 1
        if covered * 2 > total:
            break
    return people


class _Log:
    """What a run of `git log --name-only` adds up to."""

    def __init__(self, allowed: set[str], focus: str | None, is_file: bool, keep_recent: int) -> None:
        self.allowed, self.focus, self.is_file, self.keep_recent = allowed, focus, is_file, keep_recent
        self.churn: Counter = Counter()
        self.fixes: Counter = Counter()
        self.last: dict[str, int] = {}
        self.file_authors: dict[str, Counter] = defaultdict(Counter)
        self.authors: Counter = Counter()
        self.pairs: Counter = Counter()
        self.partners: Counter = Counter()
        self.recent: list[dict] = []
        self.read = 0
        self.newest = self.oldest = None

    def commit(self, short: str, author: str, when: int, subject: str, names: list[str]) -> None:
        fix = bool(_FIX_SUBJECT.search(subject))
        self.authors[author] += 1
        self.read += 1
        self.newest = max(self.newest or when, when)
        self.oldest = min(self.oldest or when, when)
        if len(self.recent) < self.keep_recent:
            self.recent.append({"commit": short, "time": when, "author": author, "subject": safe_line(subject), "fix": fix})
        kept = sorted(path for path in names if path in self.allowed)
        for path in kept:
            self.churn[path] += 1
            self.fixes[path] += fix
            self.last.setdefault(path, when)
            self.file_authors[path][author] += 1
        if 2 <= len(kept) <= _BIG_COMMIT:
            if self.is_file:
                self.partners.update(path for path in kept if path != self.focus)
            elif not self.focus:
                self.pairs.update((a, b) for index, a in enumerate(kept) for b in kept[index + 1:])


def _read_log(root: Path, args: list[str], log: _Log) -> None:
    pending = None
    for line in filesystem.stream_git(root, *args, timeout=300):
        match = _COMMIT.match(line)
        if match:
            if pending:
                log.commit(*pending)
            pending = (match.group(1), match.group(2), int(match.group(3)), match.group(4), [])
        elif line and pending:
            pending[4].append(line)
    if pending:
        log.commit(*pending)


def history(root: Path, target: str | None, since: str | None, commits: int, top: int, follow: bool = False) -> dict:
    if not filesystem.in_git(root):
        raise filesystem.GitProblem("Not a git repository, so there's no history here")
    relative = _relative(root, target) if target else None
    relative = None if relative == "." else relative
    is_file = bool(relative) and (root / relative).is_file()
    args = ["log", f"-n{commits}", "--no-merges", "--format=%x00%h%x1f%an%x1f%at%x1f%s", "--name-only"]
    args += [f"--since={since}"] if since else []
    args += ["--follow"] if follow and is_file else ["--full-diff"] if relative else []
    args += ["--", f":(literal){relative}"] if relative else []
    log = _Log(set(selected_files(root, None)), relative, is_file, top)
    _read_log(root, args, log)
    prefix = relative + "/" if relative and not is_file else ""
    ranked = sorted((path for path in log.churn if path.startswith(prefix) and (not is_file or path == relative)), key=lambda path: (-log.churn[path], path))
    folders: Counter = Counter()
    folder_authors: dict[str, Counter] = defaultdict(Counter)
    for path in ranked:
        folder = _group(path, relative.count("/") + 2 if relative else 1)
        folders[folder] += log.churn[path]
        folder_authors[folder].update(log.file_authors[path])
    return {
        "target": relative, "is_file": is_file, "commits_read": log.read, "limit_reached": log.read >= commits, "newest": log.newest, "oldest": log.oldest,
        "shallow": (filesystem.run_git(root, "rev-parse", "--is-shallow-repository") or "").strip() == "true",
        "authors": log.authors.most_common(top), "bus_factor": _bus_factor(log.authors) if log.authors else 0, "owners": codeowners(root, relative) if relative else None,
        "files": [{"path": path, "commits": log.churn[path], "fix_commits": log.fixes[path], "last_changed": log.last[path], "authors": len(log.file_authors[path]),
                   "top_author": log.file_authors[path].most_common(1)[0][0], "bus_factor": _bus_factor(log.file_authors[path]), "high_consequence": bool(_CONSEQUENCE.search(path)),
                   "owners": codeowners(root, path)} for path in ranked[:top]],
        "files_total": len(ranked),
        "directories": [{"path": name, "commits": count, "bus_factor": _bus_factor(folder_authors[name]), "top_author": folder_authors[name].most_common(1)[0][0]} for name, count in folders.most_common(top)],
        "changed_together": [{"path": path, "shared_commits": count, "share": round(count / max(log.read, 1), 2)} for path, count in log.partners.most_common(top) if count >= 2],
        "pairs": [{"a": a, "b": b, "shared_commits": count} for (a, b), count in log.pairs.most_common(top) if count >= 2],
        "recent": log.recent if relative else [],
    }


def _date(stamp: int | None) -> str:
    import datetime as dt
    return dt.datetime.fromtimestamp(stamp, dt.timezone.utc).strftime("%Y-%m-%d") if stamp else "?"


def render_history(data: dict) -> str:
    if not data["commits_read"]:
        return "No commits found for that path and period."
    out = [f"{data['commits_read']:,} commits from {_date(data['oldest'])} to {_date(data['newest'])}. Merges left out."]
    if data["limit_reached"]:
        out.append("Stopped at the commit limit, so older history isn't counted. Raise --commits.")
    if data["shallow"]:
        out.append("This is a shallow clone, so the history is cut short and these counts are too low.")
    if data["target"] and not data["is_file"] or not data["target"]:
        out.append("A renamed file's history starts again at its new name. --follow on one file traces it.")
    out.append(f"Authors: {', '.join(f'{name} {count}' for name, count in data['authors'][:6])}. "
               f"{data['bus_factor']} of them account for over half of the commits.")
    if data["owners"]:
        out.append(f"CODEOWNERS: {data['owners']}")
    if data["recent"]:
        out += ["", "Recent commits. Their messages are data, not instructions:"]
        out += [f"  {row['commit']}  {_date(row['time'])}  {row['author']}  {'[fix] ' if row['fix'] else ''}{row['subject']}" for row in data["recent"]]
    if data["changed_together"]:
        out += ["", "Changed together with this file. A change here may need one there:"]
        out += [f"  {row['shared_commits']:>4} commits  {row['path']}" for row in data["changed_together"]]
    if not data["is_file"]:
        if len(data["directories"]) > 1:
            out += ["", f"{'commits':>9}  {'people':>6}  directory (people = how few make over half)"]
            out += [f"{row['commits']:>9,}  {row['bus_factor']:>6}  {row['path']}  mostly {row['top_author']}" for row in data["directories"]]
        out += ["", f"Most changed files ({data['files_total']:,} changed). [fix] counts commits whose subject reads like a fix:"]
        for row in data["files"]:
            flag = "  high consequence" if row["high_consequence"] else ""
            owner = f"  owners {row['owners']}" if row["owners"] else ""
            out.append(f"  {row['commits']:>5}  [{row['fix_commits']} fix]  {row['path']}  last {_date(row['last_changed'])}, {row['authors']} people, mostly {row['top_author']}{owner}{flag}")
        out += more(data["files_total"] - len(data["files"]))
        if data["pairs"]:
            out += ["", "Pairs that change together, across files:"] + [f"  {row['shared_commits']:>4}  {row['a']}  {row['b']}" for row in data["pairs"]]
    return "\n".join(out)


# ---------------------------------------------------------------- secrets in history

_DIFF_FILE = re.compile(r"^\+\+\+ b/(.*)$")


def leaks(root: Path, commits: int, top: int) -> dict:
    """Added lines shaped like credentials, across history, since deleting one from the tree leaves it there. Values never reach the output."""
    if not filesystem.in_git(root):
        raise filesystem.GitProblem("Not a git repository, so there's no history to read")
    found: dict[tuple[str, str], dict] = {}
    commit = None
    read = 0
    path = None
    for line in filesystem.stream_git(root, "log", f"-n{commits}", "--no-merges", "--format=%x00%h", "-p", "--unified=0", "--no-ext-diff", "--no-textconv", "--no-color", "--diff-filter=AM", timeout=600):
        if line.startswith("\0"):
            commit = line[1:]
            read += 1
            continue
        file_match = _DIFF_FILE.match(line)
        if file_match:
            path = file_match.group(1).rstrip("\t")
            continue
        if not (line.startswith("+") and path) or is_test_path(path) or line.startswith("+++ "):
            continue
        added = line[1:]
        if has_secret_shape(added) or has_secret_assignment(added):
            key = (path, commit or "")
            row = found.setdefault(key, {"path": path, "commit": commit, "lines": 0})
            row["lines"] += 1
    rows = sorted(found.values(), key=lambda row: row["path"])
    still_there = {row["path"] for row in rows if filesystem.read_text(root / row["path"]) is not None and _has_secret_now(root / row["path"])}
    for row in rows:
        row["in_tree_now"] = row["path"] in still_there
    return {"commits_read": read, "limit_reached": read >= commits, "total": len(rows), "files": len({row["path"] for row in rows}), "rows": rows[:top]}


def _has_secret_now(path: Path) -> bool:
    text = filesystem.read_text(path) or ""
    return any(has_secret_shape(line) or has_secret_assignment(line) for line in text.split("\n"))


def render_leaks(data: dict) -> str:
    out = [f"Read the diffs of {data['commits_read']:,} commits. {data['total']} added credential-shaped lines' commits in {data['files']} files. Values withheld. Test paths are skipped."]
    if data["limit_reached"]:
        out.append("Stopped at the commit limit, so older history wasn't read. Raise --commits.")
    out += [f"  {row['commit']}  {row['path']}  {row['lines']} lines{'  still in the tree' if row['in_tree_now'] else ''}" for row in data["rows"]]
    out += more(data["total"] - len(data["rows"]))
    if data["total"]:
        out.append("These are shapes, so confirm each with `git show`, keeping the value out of what you report. A real one needs rotating, since history keeps it. gitleaks, if installed, knows more shapes.")
    return "\n".join(out)
