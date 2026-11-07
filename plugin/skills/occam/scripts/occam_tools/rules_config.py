"""Rules for what isn't code but decides what runs: CI, containers, infrastructure, manifests, migrations and the files that steer agents. Text only, because no parser for these is in the standard library."""

from __future__ import annotations

import re
from collections.abc import Iterable, Iterator

_I = re.I
_M = re.M

WORKFLOW = re.compile(r"(^|/)(\.github/workflows/[^/]+\.ya?ml|\.gitlab-ci\.ya?ml|\.circleci/config\.ya?ml|azure-pipelines\.ya?ml|bitbucket-pipelines\.ya?ml)$")
GITHUB_WORKFLOW = re.compile(r"(^|/)\.github/workflows/[^/]+\.ya?ml$")
DOCKERFILE = re.compile(r"(^|/)(Dockerfile(\.[^/]+)?|[^/]+\.dockerfile)$", _I)
YAML_FILE = re.compile(r"\.ya?ml$", _I)
PACKAGE_JSON = re.compile(r"(^|/)package\.json$")
REQUIREMENTS = re.compile(r"(^|/)(requirements[^/]*\.(txt|in)|pip\.conf)$")
ENV_FILE = re.compile(r"(^|/)\.env(\.[^/]+)?$")
AGENT_SETTINGS = re.compile(r"(^|/)(\.claude/settings(\.local)?\.json|\.mcp\.json|\.cursor/mcp\.json|\.vscode/(settings|mcp)\.json|\.codex/config\.toml|\.gemini/settings\.json|[^/]+\.code-workspace)$")
AGENT_INSTRUCTIONS = re.compile(r"(^|/)(CLAUDE\.md|AGENTS\.md|GEMINI\.md|SKILL\.md|\.cursorrules|\.windsurfrules|copilot-instructions\.md|\.cursor/rules/[^/]+|\.clinerules)$")
# A folder called migrations can hold anything, so there a file counts only if it's numbered, as migrations are.
MIGRATION = re.compile(r"(^|/)(alembic/versions|db/migrate|prisma/migrations|flyway)/(?:[^/]+/){0,8}[^/]+\.(py|sql|rb|js|ts)$|(^|/)migrations?/(?:[^/]+/){0,2}(?:\d|V\d)[^/]*\.(py|sql|rb|js|ts)$")
VENDORED_SOURCE = re.compile(r"(^|/)(third_party|third-party|bower_components|site-packages|node_modules)/|^vendor/")
CLIENT_VISIBLE_SECRET = re.compile(r"\b(?:NEXT_PUBLIC|VITE|REACT_APP|EXPO_PUBLIC|NUXT_PUBLIC|GATSBY|VUE_APP)_\w*(?:SECRET|PRIVATE|SERVICE_ROLE|SERVICE_KEY|PASSWORD|ADMIN_KEY)\w*")
MAX_INSTRUCTION_LINES = 400  # a judgment. Bloated rule files were common in the one study that counted them, and none gives a limit
MAX_HIDDEN_REPORTED = 5

_TEST_COMMAND = r"(?:py\.?test|tox|nox|npm (?:run )?test|pnpm (?:run )?test|yarn test|go test|go vet|cargo (?:test|clippy)|make (?:test|check|lint)|ruff|mypy|pyright|flake8|pylint|eslint|tsc\b|jest|vitest|mvn (?:test|verify)|gradle\w* (?:test|check))"
_RUN_PREFIX = r"^[ \t]*(?:-[ \t]*)?(?:run:[ \t]*)?(?:\w+=\S+[ \t]+)*(?:(?:python3? -m|uv run|poetry run|npx|pnpm exec|bundle exec)[ \t]+)?"
_CI_DISABLED = (
    re.compile(rf"{_RUN_PREFIX}{_TEST_COMMAND}[^\n#]*\|\|\s*(?:true|:|exit 0)\s*$", _M),
    re.compile(r"^[ \t]*if:[ \t]*(?:false|\$\{\{\s*false\s*\}\})[ \t]*$", _M),
    re.compile(r"--passWithNoTests\b|--no-fail-on-empty\b"),
)
_ALLOWED_TO_FAIL = re.compile(r"^[ \t]*(?:continue-on-error|allow_failure):[ \t]*true\b", _M)
_RUNS_A_CHECK = re.compile(rf"{_RUN_PREFIX}{_TEST_COMMAND}", _M)
LINES_AROUND_A_STEP = 6
_BRANCH_REF = re.compile(r"^[ \t]*(?:-[ \t]*)?uses:\s*[\w.-]+/[\w./-]+@(main|master|latest|HEAD|dev|develop)\s*(?:#.*)?$", _M)
# What a stranger writes, expanded into the script before the shell starts.
_STRANGER_TEXT = r"github\.(?:event\.(?:issue\.(?:title|body)|pull_request\.(?:title|body|head\.ref|head\.label)|comment\.body|review\.body|review_comment\.body|discussion\.(?:title|body)|head_commit\.(?:message|author\.\w+)|commits\[[^\]]*\]\.(?:message|author\.\w+))|head_ref)"
_RUN_LINE = re.compile(r"^[ \t]*(?:-[ \t]*)?(?P<key>run):[ \t]*(?P<block>[|>][-+]?[ \t]*$)?(?P<inline>[^\n]*)")
_EXPANSION = re.compile(r"\$\{\{\s*" + _STRANGER_TEXT + r"\s*\}\}")  # the whole expression, since `startsWith(...)` or `... != ''` comes out as a boolean
_PR_TARGET = re.compile(r"^[ \t]*(?:-[ \t]*)?pull_request_target\b|^on:\s*pull_request_target\b|\bon:\s*\[[^\]]*pull_request_target", _M)
_HEAD_CHECKOUT = re.compile(r"ref:\s*\$\{\{\s*github\.event\.pull_request\.head\.(?:sha|ref)|ref:\s*refs/pull/|ref:\s*\$\{\{\s*github\.head_ref\s*\}\}")
_WRITE_ALL = re.compile(r"^[ \t]*permissions:\s*write-all\b", _M)

_FROM = re.compile(r"^[ \t]*FROM\s+(?:--platform=\S+\s+)?(?!scratch\b)(?P<image>[^\s:@]+(?::(?P<tag>[^\s@]+))?)(?:\s+AS\s+\S+)?\s*$", _M | _I)
_STAGE_NAME = re.compile(r"^[ \t]*FROM\s+\S+(?:\s+\S+)?\s+AS\s+(\S+)", _M | _I)
_IMAGE_LATEST = re.compile(r"^[ \t]*(?:-[ \t]*)?image:\s*[\"']?[\w./-]+:latest[\"']?\s*(?:#.*)?$", _M)
_PRIVILEGED = re.compile(r"^[ \t]*(?:-[ \t]*)?(privileged|hostNetwork|hostPID|hostIPC|allowPrivilegeEscalation):\s*true\b", _M)
_KUBE_OR_COMPOSE = re.compile(r"^[ \t]*(?:apiVersion:|kind:|services:)\s*", _M)

_OPEN_INGRESS = re.compile(r"\bingress\b[^{\n]*\{[^}]*?\"0\.0\.0\.0/0\"|\b(?:publicly_accessible|associate_public_ip_address)\s*=\s*true\b", re.S)
_WILDCARD_PERMISSION = re.compile(r"[\"']?(?:Action|actions)[\"']?\s*[:=]\s*\[?\s*[\"']\*[\"']")
_PUBLIC_DATA = re.compile(r"\bacl\s*=\s*\"public-read(?:-write)?\"|\bblock_public_(?:acls|policy)\s*=\s*false\b|\b(?:storage_encrypted|encrypted)\s*=\s*false\b")
_LOSES_DATA = re.compile(r"\b(?:skip_final_snapshot|force_destroy)\s*=\s*true\b|\bdeletion_protection(?:_enabled)?\s*=\s*false\b|\bprevent_destroy\s*=\s*false\b")

_NODE_SECTIONS = re.compile(r"\"(?:dependencies|devDependencies|optionalDependencies)\"\s*:\s*\{(?P<body>[^{}]*)\}")  # a peer range is meant to be wide
_NODE_ANYTHING = re.compile(r"\"[@\w./-]+\"\s*:\s*\"latest\"|\"(?!@)[\w./-]+\"\s*:\s*\"(?:\*|x)\"")  # a scoped name at `*` is usually a workspace package
_NODE_INSTALL_SCRIPT = re.compile(r"^[ \t]*\"(preinstall|install|postinstall)\"\s*:\s*\"", _M)
_EXTRA_INDEX = re.compile(r"^[ \t]*(?:--extra-index-url|extra-index-url)\b", _M)

_WIDE_AGENT = re.compile(r"\"defaultMode\"\s*:\s*\"bypassPermissions\"|dangerously-?skip-?permissions|\"chat\.tools\.(?:global\.)?autoApprove\"\s*:\s*true|\"(?:Bash|Write|Edit|mcp__\w*)\(\*(?::\*)?\)\"|approval_policy\s*=\s*\"never\"|sandbox_mode\s*=\s*\"danger-full-access\"", _I)
# Reordering controls and invisible tag characters: a reviewer and the machine read different text. Joiners stay out, since emoji and several scripts need them.
HIDDEN = re.compile("[\u202a-\u202e\u2066-\u2069\U000e0000-\U000e007f]")
_ZERO_WIDTH = re.compile("[\u200b\u2060]")
RIGHT_TO_LEFT = re.compile("[\u0590-\u08ff\ufb1d-\ufdff\ufe70-\ufefc]")
FLAG_BASE = "\U0001f3f4"
ADDRESSES_AN_AGENT = re.compile(r"\b(?:ignore|disregard|forget)\s+(?:all\s+|any\s+)?(?:(?:the|your)\s+)?(?:previous|prior|above|earlier|preceding)\s+(?:instructions?|prompts?|rules?)\b"
                                r"|\b(?:do not|don't|never)\s+(?:tell|inform|mention (?:this |it )?to|notify|alert)\s+the\s+(?:user|developer|human)\b|\bwithout\s+(?:telling|informing|notifying|alerting)\s+the\s+(?:user|developer|human)\b", _I)

_ROLLBACK_EMPTY = re.compile(r"^def downgrade\([^)\n]*\)[^:\n]*:[ \t]*\n(?:[ \t]*\"\"\"[^\n]*\"\"\"[ \t]*\n|[ \t]*#[^\n]*\n){0,5}[ \t]+pass[ \t]*$", _M)
_RUNPYTHON_ONE_WAY = re.compile(r"\bmigrations\.RunPython\(\s*[\w.]+\s*\)")
_DROPS = re.compile(r"\bDROP\s+(?:TABLE|COLUMN)\b|\bTRUNCATE\s+(?:TABLE\s+)?\w|\bop\.drop_(?:table|column)\(|\bmigrations\.(?:RemoveField|DeleteModel)\(|\b(?:remove_column|drop_table)\b|\.dropTable\(|\.dropColumn\(", _I)
_TAKES_A_LOCK = re.compile(r"\bCREATE\s+(?:UNIQUE\s+)?INDEX\s+(?!CONCURRENTLY\b)|\bADD\s+COLUMN\b[^;\n]*\bNOT\s+NULL\b(?![^;\n]*\bDEFAULT\b)|\bALTER\s+COLUMN\b[^;\n]*\bTYPE\b", _I)
_CREATES_TABLE = re.compile(r"\bCREATE\s+TABLE\b", _I)
_THE_WAY_BACK = re.compile(r"^(?:def downgrade\b|[ \t]*def down\b|exports\.down\b|[ \t]*(?:async\s+)?down\s*\()", _M)


def _line(text: str, offset: int) -> int:
    return text.count("\n", 0, offset) + 1


def _allowed_to_fail(text: str) -> Iterator[tuple]:
    """Only on a step that runs a check, since a publish or an upload may be allowed to fail."""
    lines = text.split("\n")
    for match in _ALLOWED_TO_FAIL.finditer(text):
        line = _line(text, match.start())
        nearby = "\n".join(lines[max(0, line - 1 - LINES_AROUND_A_STEP):line + LINES_AROUND_A_STEP])
        if _RUNS_A_CHECK.search(nearby):
            yield "ci-check-disabled", line, f"The pipeline stays green here whatever the check does: `{match.group(0).strip()[:60]}`.", {}


def _workflow_findings(path: str, text: str) -> Iterator[tuple]:
    for pattern in _CI_DISABLED:
        for match in pattern.finditer(text):
            yield "ci-check-disabled", _line(text, match.start()), f"The pipeline stays green here whatever happens: `{match.group(0).strip()[:60]}`.", {}
    yield from _allowed_to_fail(text)
    if not GITHUB_WORKFLOW.search(path):
        return
    for match in _BRANCH_REF.finditer(text):
        yield "ci-unpinned-action", _line(text, match.start()), f"This runs whatever {match.group(1)} holds today, with this workflow's token.", {}
    yield from _run_injections(text)
    if _PR_TARGET.search(text):
        for match in _HEAD_CHECKOUT.finditer(text):
            yield "ci-untrusted-checkout", _line(text, match.start()), "pull_request_target has secrets and write access, and this checks out the pull request's own code.", {}
    for match in _WRITE_ALL.finditer(text):
        yield "ci-write-all", _line(text, match.start()), None, {}


def _run_body(lines: list[str], start: int, match: re.Match) -> tuple[list[str], int, int]:
    """The script of this `run:`, the line number of its first line, and where to carry on reading. A block runs while lines sit deeper than the `run` key, and in `- run: |` that's past the dash."""
    if not match.group("block"):
        return [match.group("inline")], start, start
    column = match.start("key")
    end = start
    while end < len(lines) and (not lines[end].strip() or len(lines[end]) - len(lines[end].lstrip()) > column):
        end += 1
    return lines[start:end], start + 1, end


def _run_injections(text: str) -> Iterator[tuple]:
    lines = text.split("\n")
    index = 0
    while index < len(lines):
        match = _RUN_LINE.match(lines[index])
        index += 1
        if not match:
            continue
        body, first, index = _run_body(lines, index, match)
        for offset, line in enumerate(body):
            found = _EXPANSION.search(line)
            if found:
                yield "ci-script-injection", first + offset, f"`{found.group(0)[:60]}` is text a stranger writes, expanded into a script. Pass it through env: instead.", {}


def _dockerfile_findings(text: str) -> Iterator[tuple]:
    stages = {name.lower() for name in _STAGE_NAME.findall(text)}
    for match in _FROM.finditer(text):
        image, tag = match.group("image"), match.group("tag")
        if tag in (None, "latest") and image.split(":")[0].lower() not in stages and "$" not in image:
            yield "container-unpinned-image", _line(text, match.start()), f"`{image}` means whichever image is newest on the day it builds.", {}


def _yaml_findings(text: str) -> Iterator[tuple]:
    if not _KUBE_OR_COMPOSE.search(text):
        return
    for match in _IMAGE_LATEST.finditer(text):
        yield "container-unpinned-image", _line(text, match.start()), "`:latest` means whichever image is newest on the day it starts.", {}
    for match in _PRIVILEGED.finditer(text):
        yield "container-privileged", _line(text, match.start()), f"{match.group(1)} gives this container much of the host.", {}


def terraform_findings(text: str) -> Iterator[tuple]:
    for rule, pattern in (("iac-open-ingress", _OPEN_INGRESS), ("iac-public-data", _PUBLIC_DATA), ("iac-data-loss-setting", _LOSES_DATA), ("iac-wildcard-permission", _WILDCARD_PERMISSION)):
        for match in pattern.finditer(text):
            yield rule, _line(text, match.start()), None, {}


def _package_json_findings(text: str) -> Iterator[tuple]:
    for section in _NODE_SECTIONS.finditer(text):
        for match in _NODE_ANYTHING.finditer(section.group("body")):
            yield "dep-unpinned", _line(text, section.start("body") + match.start()), f"{match.group(0)[:60]} installs whatever is newest, including a compromised release.", {}
    for match in _NODE_INSTALL_SCRIPT.finditer(text):
        yield "dep-install-script", _line(text, match.start()), f"A {match.group(1)} script runs on every machine that installs this.", {}


def _requirements_findings(text: str) -> Iterator[tuple]:
    for match in _EXTRA_INDEX.finditer(text):
        yield "dep-extra-index", _line(text, match.start()), "pip takes a name from whichever index offers it, so a public package can replace a private one.", {}


def _is_hiding(text: str, match: re.Match) -> bool:
    """A flag emoji is built from tag characters, and right-to-left text uses these controls for what they're for."""
    if RIGHT_TO_LEFT.search(text, text.rfind("\n", 0, match.start()) + 1, _end_of_line(text, match.end())):
        return False
    return not (match.group(0) >= "\U000e0000" and FLAG_BASE in text[max(0, match.start() - 12):match.start()])


def _end_of_line(text: str, start: int) -> int:
    end = text.find("\n", start)
    return end if end >= 0 else len(text)


def first_hidden(text: str) -> re.Match | None:
    return next((match for match in HIDDEN.finditer(text) if _is_hiding(text, match)), None)


def hidden_characters(text: str, also_zero_width: bool = False) -> Iterator[tuple]:
    reported = 0
    found = [match for match in HIDDEN.finditer(text) if _is_hiding(text, match)] + (list(_ZERO_WIDTH.finditer(text)) if also_zero_width else [])
    for match in found:
        yield "hidden-unicode", _line(text, match.start()), f"U+{ord(match.group(0)):04X} is invisible, so a reviewer and the machine read different text here.", {}
        reported += 1
        if reported >= MAX_HIDDEN_REPORTED:
            return


_LOGIN_ROUTE = re.compile(r"""(?:@\w+\.(?:route|post|get)|\b(?:app|router)\.(?:post|all))\(\s*["'`][^"'`\n]*(?:login|signin|sign-in|sign_in|forgot|reset-password|reset_password|otp)""", _I)
_A_LIMIT = re.compile(r"limiter|rate_?limit|throttl|slowapi|ratelimit", _I)


def login_without_a_limit(text: str, language: str) -> Iterator[tuple]:
    """This file only. A limit set elsewhere isn't visible from here, so these stay below the usual confidence."""
    if language not in ("python", "javascript", "typescript") or _A_LIMIT.search(text):
        return
    for match in _LOGIN_ROUTE.finditer(text):
        yield "login-no-rate-limit", _line(text, match.start()), None, {}


def _instruction_findings(path: str, text: str) -> Iterator[tuple]:
    yield from hidden_characters(text, also_zero_width=True)
    for match in ADDRESSES_AN_AGENT.finditer(text):
        yield "instruction-injection", _line(text, match.start()), f"`{match.group(0)[:60]}` in a file agents obey. Check who wrote it and why.", {}
    lines = text.count("\n") + 1
    if lines > MAX_INSTRUCTION_LINES and not path.endswith("SKILL.md"):  # a skill loads only when it applies
        yield "instructions-bloated", 1, f"{lines} lines, read on every session whether or not they apply. Move what's rarely needed somewhere it loads on demand.", {}


def findings(path: str, text: str) -> Iterable[tuple]:
    """(rule, line, message or None, overrides) for a file that isn't code."""
    if WORKFLOW.search(path):
        yield from _workflow_findings(path, text)
    elif DOCKERFILE.search(path):
        yield from _dockerfile_findings(text)
    elif PACKAGE_JSON.search(path):
        yield from _package_json_findings(text)
    elif REQUIREMENTS.search(path):
        yield from _requirements_findings(text)
    elif AGENT_SETTINGS.search(path):
        for match in _WIDE_AGENT.finditer(text):
            yield "agent-permission-widened", _line(text, match.start()), f"`{match.group(0)[:60]}` lets an agent act without a person. Someone should choose that knowingly.", {}
    elif AGENT_INSTRUCTIONS.search(path):
        yield from _instruction_findings(path, text)
    elif YAML_FILE.search(path):
        yield from _yaml_findings(text)
    elif ENV_FILE.search(path):
        for match in CLIENT_VISIBLE_SECRET.finditer(text):
            yield "secret-in-client-bundle", _line(text, match.start()), f"{match.group(0)[:50]} is compiled into what the browser downloads.", {}


def migration_findings(path: str, text: str) -> Iterator[tuple]:
    """A migration runs once, on real data, so what it can't undo or how long it locks matters more than in other code."""
    if not MIGRATION.search(path):
        return
    for pattern, rule, message in ((_ROLLBACK_EMPTY, "migration-no-rollback", "downgrade does nothing, so this can't be rolled back."),
                                   (_RUNPYTHON_ONE_WAY, "migration-no-rollback", "RunPython with no reverse_code can't be rolled back.")):
        for match in pattern.finditer(text):
            yield rule, _line(text, match.start()), message, {}
    way_back = _THE_WAY_BACK.search(text)  # undoing a create is what a way back is for
    for match in _DROPS.finditer(text, 0, way_back.start() if way_back else len(text)):
        yield "migration-destroys-data", _line(text, match.start()), f"`{match.group(0)[:40]}` destroys data, and code still running from before this deploy may need it.", {}
    if not _CREATES_TABLE.search(text):  # a table made in the same migration is empty, so nothing waits on it
        for match in _TAKES_A_LOCK.finditer(text):
            yield "migration-locks-table", _line(text, match.start()), f"`{match.group(0)[:50]}` blocks writes for as long as it runs on a large table.", {}
