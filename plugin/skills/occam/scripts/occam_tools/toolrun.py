"""Established analyzers first. They know more than occam's rules wherever the two overlap.

A tool that loads repository configuration can execute repository code. Those need an explicit --allow-exec.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import time
from pathlib import Path
from typing import NamedTuple

from . import files as filesystem
from .query import language_at
from .source import language_of

MAX_FILES_NAMED = 400  # what one command line can carry


class Tool(NamedTuple):
    name: str
    languages: tuple
    purpose: str
    command: tuple        # read-only invocation, with no fixing or formatting
    executes_repo: bool   # may load and run code or config from the repository
    install: str
    narrows: str          # how named paths reach it: "." or "./..." is the argument they replace, "files" names each file, "" means it can only read everything
    count_json: str = ""  # how to count results: 'list', or a key in a JSON object
    ok_exit: tuple | None = None  # exit codes besides 0 that its documentation gives for finishing, as with findings. None where occam doesn't know them


CATALOG = [
    Tool("ruff", ("python",), "lint, unused code, many bugbear and security rules", ("ruff", "check", "--output-format=json", "--no-fix", "--no-cache", "."), False, "uv tool install ruff", ".", "list", (1,)),
    Tool("mypy", ("python",), "types", ("mypy", "--no-error-summary", "--no-incremental", "--cache-dir=/dev/null", "."), True, "uv tool install mypy", ".", ok_exit=(1,)),
    Tool("pyright", ("python",), "types", ("pyright", "--outputjson", "."), False, "npm i -g pyright", ".", ok_exit=(1,)),
    Tool("bandit", ("python",), "security", ("bandit", "-q", "-r", ".", "-f", "json"), False, "uv tool install bandit", ".", "results", (1,)),
    Tool("vulture", ("python",), "dead code", ("vulture", "."), False, "uv tool install vulture", ".", ok_exit=(3,)),
    Tool("deptry", ("python",), "unused, missing and transitive dependencies", ("deptry", "."), True, "uv tool install deptry", "", ok_exit=(1,)),  # its argument is the project
    Tool("skylos", ("python",), "dead code, security and AI-code mistakes, with framework awareness (may fetch your Cloud rules if a token is set)", ("skylos", ".", "--json"), False, "pip install skylos", "."),
    Tool("sloppylint", ("python",), "AI-code patterns", ("sloppylint", "."), False, "pip install sloppylint", "."),
    Tool("radon", ("python",), "complexity", ("radon", "cc", "-n", "C", "-s", "."), False, "uv tool install radon", ".", ok_exit=()),  # exits 0 with findings
    Tool("pip-audit", ("python",), "known vulnerable dependencies", ("pip-audit", "--progress-spinner=off"), True, "uv tool install pip-audit", "", ok_exit=(1,)),
    Tool("semgrep", ("python", "javascript", "typescript", "go", "java", "kotlin", "ruby", "php", "c", "cpp", "rust", "csharp"), "security patterns across languages (fetches rules from the network)",
         ("semgrep", "scan", "--config=p/default", "--quiet", "--json", "--metrics=off", "."), False, "uv tool install semgrep", ".", "results", (1,)),
    Tool("eslint", ("javascript", "typescript"), "lint", ("eslint", "--format=json", "."), True, "npm i -D eslint", ".", "list", (1,)),
    Tool("tsc", ("typescript",), "types", ("tsc", "--noEmit", "--pretty", "false"), True, "npm i -D typescript", "", ok_exit=(1, 2)),  # named files would skip tsconfig.json
    Tool("knip", ("javascript", "typescript"), "unused files, exports and dependencies", ("knip", "--no-progress"), True, "npm i -D knip", "", ok_exit=(1,)),
    Tool("fallow", ("javascript", "typescript"), "unused code, duplication, complexity and cycles from one graph", ("fallow", "--format", "json", "--quiet"), True, "npm i -D fallow", ""),
    Tool("npm", ("javascript", "typescript"), "known vulnerable dependencies", ("npm", "audit", "--json"), False, "ships with Node", "", ok_exit=(1,)),
    Tool("golangci-lint", ("go",), "lint, many analyzers", ("golangci-lint", "run", "--out-format=json", "./..."), True, "go install github.com/golangci/golangci-lint/cmd/golangci-lint@latest", "./...", ok_exit=(1,)),
    Tool("deadcode", ("go",), "functions no main package can reach", ("deadcode", "-test", "./..."), True, "go install golang.org/x/tools/cmd/deadcode@latest", "", ok_exit=()),  # fewer roots would make reachable code look dead
    Tool("govulncheck", ("go",), "known vulnerabilities in reachable code", ("govulncheck", "./..."), True, "go install golang.org/x/vuln/cmd/govulncheck@latest", "./...", ok_exit=(3,)),
    Tool("cargo", ("rust",), "clippy lint (runs build scripts)", ("cargo", "clippy", "--quiet", "--message-format=short", "--", "-W", "clippy::all"), True, "rustup component add clippy", ""),
    Tool("cargo-audit", ("rust",), "known vulnerable crates", ("cargo-audit", "audit"), False, "cargo install cargo-audit", "", ok_exit=(1,)),
    Tool("shellcheck", ("shell",), "shell bugs", ("shellcheck", "-f", "json"), False, "brew install shellcheck", "files", "list", (1,)),
    Tool("gitleaks", ("*",), "secrets in files and history", ("gitleaks", "detect", "--no-banner", "--redact", "--report-format=json", "--report-path=/dev/stdout"), True, "brew install gitleaks", "", "list", (1,)),
    Tool("jscpd", ("*",), "duplicate code across languages", ("jscpd", "--silent", "."), False, "npm i -g jscpd", ".", ok_exit=()),
    Tool("pylint", ("python",), "import cycles and more (loads plugins its config names)", ("pylint", "--disable=all", "--enable=cyclic-import", "--score=n", "."), True, "uv tool install pylint", ".",
         ok_exit=tuple(range(2, 32, 2))),  # bit flags, where 1 is fatal and 32 a usage error
    Tool("osv-scanner", ("*",), "known vulnerable dependencies, from any lockfile (sends package names to osv.dev)", ("osv-scanner", "scan", "source", "--recursive", "--format=json", "."), False, "brew install osv-scanner",
         ".", ok_exit=(1, 128)),  # 128 is no lockfile found
    Tool("shfmt", ("shell",), "shell formatting and parse errors, diff only", ("shfmt", "-d", "."), False, "brew install shfmt", ".", ok_exit=(1,)),
    Tool("hadolint", ("*",), "Dockerfile mistakes", ("hadolint",), False, "brew install hadolint", "files", ok_exit=(1,)),
    Tool("actionlint", ("*",), "GitHub Actions workflow mistakes", ("actionlint",), False, "brew install actionlint", "", ok_exit=(1,)),
    Tool("zizmor", ("*",), "security problems in GitHub Actions workflows", ("zizmor", "--format=plain", "."), False, "uv tool install zizmor", ".", ok_exit=tuple(range(10, 15))),  # 10-14 findings, 1 an error
    Tool("terraform", ("terraform",), "invented or missing arguments, against the provider's schema (needs `terraform init` first)", ("terraform", "validate", "-no-color"), True, "brew install terraform", "", ok_exit=(1,)),
    Tool("tflint", ("terraform",), "provider-specific Terraform mistakes (loads plugins its config names)", ("tflint", "--no-color"), True, "brew install tflint", ""),
    Tool("checkov", ("terraform",), "infrastructure policy: public storage, wildcard grants, missing encryption (its config can load checks from the repository)", ("checkov", "-d", ".", "--quiet", "--compact"), True,
         "uv tool install checkov", "", ok_exit=(1,)),  # its "." belongs to -d
    Tool("tokei", ("*",), "lines of code, faster than `occam query size` if installed", ("tokei", "--output", "json", "."), False, "brew install tokei", ".", ok_exit=()),
    Tool("clang-tidy", ("c", "cpp"), "lint and bug patterns (needs a compile database)", ("clang-tidy", "--version"), False, "ships with LLVM", ""),
]
TIMEOUT_SECONDS = 300


def _locate(root: Path, name: str) -> tuple[str | None, bool]:
    """The tool's path, and whether it lives inside the repository, in which case running it runs repository code."""
    for folder in (root / ".venv" / "bin", root / "venv" / "bin", root / "node_modules" / ".bin"):
        candidate = folder / name
        if candidate.exists() and os.access(candidate, os.X_OK):
            return str(candidate), True
    found = shutil.which(name)
    if found and str(Path(found).resolve()).startswith(str(root.resolve()) + os.sep):
        return found, True
    return found, False


def _languages_here(root: Path) -> set[str]:
    present: set[str] = set()
    for path in filesystem.list_files(root, None, filesystem.load_config(root)):
        language = language_of(path)
        if language:
            present.add("python" if language == "notebook" else language)
    return present


def _relative(root: Path, paths: list[str]) -> list[str]:
    """Each named path from the root. One outside the project raises, since leaving it out would read as a clean result."""
    try:
        return [str(Path(path).resolve().relative_to(root.resolve())).replace(os.sep, "/") for path in paths]
    except ValueError:
        raise filesystem.OutsideProject(f"{' '.join(paths)} isn't all inside this project ({root})") from None


def _scoped(command: list[str], root: Path, paths: list[str] | None, whole: str = ".") -> list[str]:
    """A tool told `.`, or Go's `./...`, reads the whole repository, which can take longer than the time it's given on a large one. Named paths narrow it."""
    if not paths or whole not in command:
        return command
    if whole == ".":
        named = [f"./{path}" for path in _relative(root, paths)]
    else:  # Go packages: a folder and everything under it, or the package a file belongs to
        named = [f"./{path}/..." if (root / path).is_dir() else f"./{path.rsplit('/', 1)[0]}" if "/" in path else "." for path in _relative(root, paths)]
    index = command.index(whole)
    return [*command[:index], *named, *command[index + 1:]]


def _invocation(tool: Tool, location: str, root: Path, paths: list[str] | None) -> tuple[list[str], str | None]:
    """The command line, and a note when named paths couldn't narrow it. A tool that takes each file has them added by _named_files."""
    command = [location, *tool.command[1:]]
    if not paths or tool.narrows == "files":
        return command, None
    if not tool.narrows:
        return command, "it can't be pointed at named paths, so it read the whole repository"
    return _scoped(command, root, paths, tool.narrows), None


def _summarize(tool: Tool, stdout: str) -> str:
    if tool.count_json:
        try:
            document = json.loads(stdout)
            items = document if tool.count_json == "list" else document.get(tool.count_json, [])
            return f"{len(items)} results"
        except (ValueError, AttributeError):
            pass
    return f"{len(stdout.splitlines())} lines of output"


def _describe(present: list[tuple], languages: set[str]) -> str:
    lines = [f"Languages here: {', '.join(sorted(languages)) or 'none'}. Prefer these analyzers to occam's rules where they overlap.", ""]
    for tool, location, in_repository in present:
        state = "available" if location else f"missing, install with: {tool.install}"
        caution = "  [runs repo code: needs --allow-exec]" if (tool.executes_repo or in_repository) and location else ""
        lines.append(f"  {tool.name:<15}{tool.purpose}: {state}{caution}")
    lines += ["", "`occam tools --run` runs the available ones with no note above, which only read files and execute nothing from the repository. Installing anything is your user's call, so ask first."]
    return "\n".join(lines)


def _named_files(tool: Tool, root: Path, paths: list[str] | None) -> tuple[list[str], str | None]:
    """For a tool that needs each file named: which ones, and a note if that means it can't run or can't read them all. ./ so a name can't be read as a flag."""
    if tool.name == "hadolint":
        found = [f"./{p}" for p in filesystem.list_files(root, paths, {}) if p.rsplit("/", 1)[-1].startswith("Dockerfile")]
        return found[:MAX_FILES_NAMED], None if found else "no Dockerfile here"
    if tool.name == "shellcheck":
        found = [f"./{p}" for p in filesystem.list_files(root, paths, {}) if language_at(root, p) == "shell"]
        return found[:MAX_FILES_NAMED], None if found else "no shell scripts here"
    return [], None


def _version(location: str, root: Path) -> str | None:
    """The first line `--version` prints, which most tools answer at once. None if it doesn't answer that."""
    try:
        done = filesystem.run_bounded([location, "--version"], root, 10)
    except (OSError, subprocess.TimeoutExpired):
        return None
    lines = (done.stdout or done.stderr).decode("utf-8", "replace").strip().splitlines()
    return lines[0][:200] if done.returncode == 0 and lines else None


def _save(folder: Path | None, tool: Tool, command: list[str], root: Path, done: subprocess.CompletedProcess, started: float, seconds: float) -> str:
    """Its output with what produced it, so a saved result can be told from another run's."""
    if folder is None:
        return ""
    target = folder / f"{tool.name}.json"
    envelope = {"tool": tool.name, "version": _version(command[0], root), "command": command[0], "args": command[1:], "cwd": str(root), "exit": done.returncode,
                "started": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(started)), "seconds": round(seconds, 3),
                "stdout": done.stdout.decode("utf-8", "replace"), "stderr": done.stderr.decode("utf-8", "replace")}
    try:
        target.write_text(json.dumps(envelope))
    except OSError as error:
        return f", not saved ({error})"
    return f", saved to {target}"


def _run_one(tool: Tool, command: list[str], root: Path, output_folder: Path | None) -> tuple[str, bool]:
    """Its line of the report, and whether it ran to the end. Findings are an end, while a crash, a failed start or a timeout isn't."""
    started, clock = time.time(), time.monotonic()
    try:
        done = filesystem.run_bounded(command, root, TIMEOUT_SECONDS)
    except subprocess.TimeoutExpired:
        return f"  {tool.name}: timed out after {TIMEOUT_SECONDS}s, so it reported nothing", False
    except OSError as error:
        return f"  {tool.name}: failed to start ({error})", False
    saved = _save(output_folder, tool, command, root, done, started, time.monotonic() - clock)
    line = f"  {tool.name}: exit {done.returncode}, {_summarize(tool, done.stdout.decode('utf-8', 'replace'))}{saved}"
    if done.returncode < 0:
        return f"{line}. It was killed by signal {-done.returncode}, so it didn't finish", False
    if done.returncode and tool.ok_exit is not None and done.returncode not in tool.ok_exit:
        return f"{line}. For {tool.name} that exit is an error, not findings, so it didn't finish", False
    return line + (". Its output passed 8 MB, so the middle was cut" if b"[occam cut " in done.stdout + done.stderr else ""), True


def _run_present(tool, location, in_repository: bool, root: Path, paths, allow_exec: bool, output_folder) -> tuple[list[str], bool | None]:
    """What one tool's run says, and whether it finished: None when it wasn't run at all."""
    if not location:
        return [f"  {tool.name}: not run, not installed"], None
    if (tool.executes_repo or in_repository) and not allow_exec:
        return [f"  {tool.name}: not run, it can execute repository code. Read the config, then use --allow-exec"], None
    named, reason = _named_files(tool, root, paths)
    if tool.command[-1] == "--version":
        reason = "it needs arguments only you know, such as a compile database, so run it yourself. It's installed, and nothing was analyzed"
    if reason:
        return [f"  {tool.name}: not run, {reason}"], True
    said = [f"  {tool.name}: read at most the first {MAX_FILES_NAMED} files, so name a folder for the rest"] if len(named) == MAX_FILES_NAMED else []
    command, whole = _invocation(tool, location, root, paths)
    line, finished = _run_one(tool, [*command, *named], root, output_folder)
    return [*said, line + (f"; {whole}" if whole else "")], finished


def run_tools(root: Path, execute: bool = False, allow_exec: bool = False, only: list[str] | None = None, paths: list[str] | None = None) -> tuple[str, int]:
    """The report and its exit code: 2 if `only` names no known tool, 1 if one that ran crashed, didn't start or timed out. A tool's findings don't change it."""
    unknown = sorted(set(only or ()) - {tool.name for tool in CATALOG})
    if unknown:
        return f"No tool named {', '.join(unknown)}. The ones occam knows: {', '.join(tool.name for tool in CATALOG)}.", 2
    languages = _languages_here(root)
    relevant = [t for t in CATALOG if ("*" in t.languages or languages & set(t.languages)) and (not only or t.name in only)]
    present = [(t, *_locate(root, t.name)) for t in relevant]
    elsewhere = sorted(set(only or ()) - {tool.name for tool in relevant})
    notes = [f"Not run, since they're for languages that aren't here: {', '.join(elsewhere)}."] if elsewhere else []
    if not execute:
        return "\n".join([_describe(present, languages), *notes]), 0
    if paths:
        _relative(root, paths)  # before anything runs
    try:
        output_folder = filesystem.state_dir(root) / "tools"
        output_folder.mkdir(exist_ok=True)
    except OSError:
        output_folder = None
    lines, unfinished = [], []
    for tool, location, in_repository in present:
        said, finished = _run_present(tool, location, in_repository, root, paths, allow_exec, output_folder)
        lines += said
        # a tool asked for by name that didn't run isn't a pass; one occam chose and couldn't run is only said
        unfinished += [] if finished or (finished is None and not (only and tool.name in only)) else [tool.name]
    if unfinished:
        lines.append(f"Didn't finish: {', '.join(unfinished)}, so this exits 1. Findings alone don't.")
    return "\n".join(["Findings from these tools are leads too. Triage them with the same care.", *notes, *lines]), 1 if unfinished else 0
