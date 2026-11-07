"""Established analyzers first. They know more than occam's rules wherever the two overlap.

A tool that loads repository configuration can execute repository code. Those need an explicit --allow-exec.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
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
    count_json: str = ""  # how to count results: 'list', or a key in a JSON object


CATALOG = [
    Tool("ruff", ("python",), "lint, unused code, many bugbear and security rules", ("ruff", "check", "--output-format=json", "--no-fix", "--no-cache", "."), False, "uv tool install ruff", "list"),
    Tool("mypy", ("python",), "types", ("mypy", "--no-error-summary", "--no-incremental", "--cache-dir=/dev/null", "."), True, "uv tool install mypy"),
    Tool("pyright", ("python",), "types", ("pyright", "--outputjson", "."), False, "npm i -g pyright"),
    Tool("bandit", ("python",), "security", ("bandit", "-q", "-r", ".", "-f", "json"), False, "uv tool install bandit", "results"),
    Tool("vulture", ("python",), "dead code", ("vulture", "."), False, "uv tool install vulture"),
    Tool("deptry", ("python",), "unused, missing and transitive dependencies", ("deptry", "."), True, "uv tool install deptry"),
    Tool("skylos", ("python",), "dead code, security and AI-code mistakes, with framework awareness (may fetch your Cloud rules if a token is set)", ("skylos", ".", "--json"), False, "pip install skylos"),
    Tool("sloppylint", ("python",), "AI-code patterns", ("sloppylint", "."), False, "pip install sloppylint"),
    Tool("radon", ("python",), "complexity", ("radon", "cc", "-n", "C", "-s", "."), False, "uv tool install radon"),
    Tool("pip-audit", ("python",), "known vulnerable dependencies", ("pip-audit", "--progress-spinner=off"), True, "uv tool install pip-audit"),
    Tool("semgrep", ("python", "javascript", "typescript", "go", "java", "kotlin", "ruby", "php", "c", "cpp", "rust", "csharp"), "security patterns across languages (fetches rules from the network)",
         ("semgrep", "scan", "--config=p/default", "--quiet", "--json", "--metrics=off", "."), False, "uv tool install semgrep", "results"),
    Tool("eslint", ("javascript", "typescript"), "lint", ("eslint", "--format=json", "."), True, "npm i -D eslint", "list"),
    Tool("tsc", ("typescript",), "types", ("tsc", "--noEmit", "--pretty", "false"), True, "npm i -D typescript"),
    Tool("knip", ("javascript", "typescript"), "unused files, exports and dependencies", ("knip", "--no-progress"), True, "npm i -D knip"),
    Tool("fallow", ("javascript", "typescript"), "unused code, duplication, complexity and cycles from one graph", ("fallow", "--format", "json", "--quiet"), True, "npm i -D fallow"),
    Tool("npm", ("javascript", "typescript"), "known vulnerable dependencies", ("npm", "audit", "--json"), False, "ships with Node"),
    Tool("golangci-lint", ("go",), "lint, many analyzers", ("golangci-lint", "run", "--out-format=json", "./..."), True, "go install github.com/golangci/golangci-lint/cmd/golangci-lint@latest"),
    Tool("deadcode", ("go",), "functions no main package can reach", ("deadcode", "-test", "./..."), True, "go install golang.org/x/tools/cmd/deadcode@latest"),
    Tool("govulncheck", ("go",), "known vulnerabilities in reachable code", ("govulncheck", "./..."), True, "go install golang.org/x/vuln/cmd/govulncheck@latest"),
    Tool("cargo", ("rust",), "clippy lint (runs build scripts)", ("cargo", "clippy", "--quiet", "--message-format=short", "--", "-W", "clippy::all"), True, "rustup component add clippy"),
    Tool("cargo-audit", ("rust",), "known vulnerable crates", ("cargo-audit", "audit"), False, "cargo install cargo-audit"),
    Tool("shellcheck", ("shell",), "shell bugs", ("shellcheck", "-f", "json"), False, "brew install shellcheck", "list"),
    Tool("gitleaks", ("*",), "secrets in files and history", ("gitleaks", "detect", "--no-banner", "--redact", "--report-format=json", "--report-path=/dev/stdout"), True, "brew install gitleaks", "list"),
    Tool("jscpd", ("*",), "duplicate code across languages", ("jscpd", "--silent", "."), False, "npm i -g jscpd"),
    Tool("pylint", ("python",), "import cycles and more (loads plugins its config names)", ("pylint", "--disable=all", "--enable=cyclic-import", "--score=n", "."), True, "uv tool install pylint"),
    Tool("osv-scanner", ("*",), "known vulnerable dependencies, from any lockfile (sends package names to osv.dev)", ("osv-scanner", "scan", "source", "--recursive", "--format=json", "."), False, "brew install osv-scanner"),
    Tool("shfmt", ("shell",), "shell formatting and parse errors, diff only", ("shfmt", "-d", "."), False, "brew install shfmt"),
    Tool("hadolint", ("*",), "Dockerfile mistakes", ("hadolint",), False, "brew install hadolint"),
    Tool("actionlint", ("*",), "GitHub Actions workflow mistakes", ("actionlint",), False, "brew install actionlint"),
    Tool("tokei", ("*",), "lines of code, faster than `occam query size` if installed", ("tokei", "--output", "json", "."), False, "brew install tokei"),
    Tool("clang-tidy", ("c", "cpp"), "lint and bug patterns (needs a compile database)", ("clang-tidy", "--version"), False, "ships with LLVM"),
]


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


def _scoped(command: list[str], root: Path, paths: list[str] | None) -> list[str]:
    """A tool told `.` reads the whole repository, which can take longer than the time it's given on a large one. Named paths narrow it."""
    if not paths or "." not in command:
        return command
    try:
        relative = [f"./{Path(path).resolve().relative_to(root.resolve())}".replace(os.sep, "/") for path in paths]
    except ValueError:
        raise filesystem.OutsideProject(f"{' '.join(paths)} isn't all inside this project ({root})") from None
    index = command.index(".")
    return [*command[:index], *relative, *command[index + 1:]]


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


def _run_one(tool: Tool, command: list[str], root: Path, output_folder: Path | None) -> str:
    try:
        done = subprocess.run(command, cwd=str(root), capture_output=True, text=True, errors="replace", timeout=300)
    except subprocess.TimeoutExpired:
        return f"  {tool.name}: timed out after 300s"
    except OSError as error:
        return f"  {tool.name}: failed to start ({error})"
    saved = ""
    if output_folder:
        target = output_folder / f"{tool.name}.out"
        target.write_text(done.stdout + "\n" + done.stderr)
        saved = f", saved to {target}"
    return f"  {tool.name}: exit {done.returncode}, {_summarize(tool, done.stdout)}{saved}"


def run_tools(root: Path, execute: bool = False, allow_exec: bool = False, only: list[str] | None = None, paths: list[str] | None = None) -> str:
    languages = _languages_here(root)
    relevant = [t for t in CATALOG if ("*" in t.languages or languages & set(t.languages)) and (not only or t.name in only)]
    present = [(t, *_locate(root, t.name)) for t in relevant]
    if not execute:
        return _describe(present, languages)
    try:
        output_folder = filesystem.state_dir(root) / "tools"
        output_folder.mkdir(exist_ok=True)
    except OSError:
        output_folder = None
    lines = []
    for tool, location, in_repository in present:
        if not location:
            lines.append(f"  {tool.name}: not run, not installed")
        elif (tool.executes_repo or in_repository) and not allow_exec:
            lines.append(f"  {tool.name}: not run, it can execute repository code. Read the config, then use --allow-exec")
        else:
            named, reason = _named_files(tool, root, paths)
            if tool.command[-1] == "--version":
                reason = "it needs arguments only you know, such as a compile database, so run it yourself. It's installed, and nothing was analyzed"
            if reason:
                lines.append(f"  {tool.name}: not run, {reason}")
                continue
            if len(named) == MAX_FILES_NAMED:
                lines.append(f"  {tool.name}: read at most the first {MAX_FILES_NAMED} files, so name a folder for the rest")
            lines.append(_run_one(tool, [*_scoped([location, *tool.command[1:]], root, paths), *named], root, output_folder))
    return "\n".join(["Findings from these tools are leads too. Triage them with the same care.", *lines])
