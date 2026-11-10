"""Rules for what isn't code but decides what runs: CI, containers, infrastructure, manifests, migrations and the files that steer agents. Text only, because no parser for these is in the standard library."""

from __future__ import annotations

import bisect
import re
from collections.abc import Callable, Iterable, Iterator
from itertools import islice

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
AGENT_INSTRUCTIONS = re.compile(r"(^|/)(CLAUDE\.md|AGENTS\.md|GEMINI\.md|SKILL\.md|\.cursorrules|\.windsurfrules|copilot-instructions\.md|\.cursor/rules/[^/]+|\.clinerules"
                                r"|\.claude/(?:commands|agents)/(?:[^/]+/){0,4}[^/]+\.md)$")
# A folder called migrations can hold anything, so there a file counts only if it's numbered, as migrations are.
MIGRATION = re.compile(r"(^|/)(alembic/versions|db/migrate|prisma/migrations|flyway)/(?:[^/]+/){0,8}[^/]+\.(py|sql|rb|js|ts)$|(^|/)migrations?/(?:[^/]+/){0,2}(?:\d|V\d)[^/]*\.(py|sql|rb|js|ts)$")
VENDORED_SOURCE = re.compile(r"(^|/)(third_party|third-party|bower_components|site-packages|node_modules)/|^vendor/")
CLIENT_VISIBLE_SECRET = re.compile(r"\b(?:NEXT_PUBLIC|VITE|REACT_APP|EXPO_PUBLIC|NUXT_PUBLIC|GATSBY|VUE_APP)_\w*(?:SECRET|PRIVATE|SERVICE_ROLE|SERVICE_KEY|PASSWORD|ADMIN_KEY)\w*")
# config team, 2026-11-08: more kinds of file that decide what runs. source.SECRETS_ONLY_FILE routes the first three here.
WEB_SERVER_CONF = re.compile(r"(^|/)(?:[^/]+\.conf|\.htaccess|sites-(?:available|enabled)/[^/]+)$")
MAKEFILE = re.compile(r"(^|/)(?:GNUmakefile|[Mm]akefile|[^/]+\.mk)$")
SPRING_CONFIG = re.compile(r"(^|/)(?:application|bootstrap)(?:-(?P<profile>[\w.-]+))?\.(?:ya?ml|properties)$")
# Text an agent may read as data: docs, logs, saved pages and dumps. Only the agent-addressed check runs on these, from scan.py.
PROSE = re.compile(r"\.(?:md|markdown|mdx|rst|adoc|txt|log)$", re.I)
# An application's own prompt tells its model what to keep from the user, and that's not an injection.
PROMPT_FILE = re.compile(r"prompt", re.I)
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
# A third party's tag can be moved to other code by whoever controls the action, so only a full commit hash stays put. GitHub's own `actions/`
# and `github/` aren't third parties. The owner's decision, 2026-11-07.
_TAG_REF = re.compile(r"^[ \t]*(?:-[ \t]*)?uses:\s*(?!(?:actions|github)/)([\w.-]+/[\w./-]+)@(?!(?:main|master|latest|HEAD|dev|develop)\b)(?![0-9a-f]{40}\b)([\w.-]+)\s*(?:#.*)?$", _M)
PYPROJECT = re.compile(r"(^|/)pyproject\.toml$")
_TOOL_TABLE = re.compile(r"^\[tool\.(black|ruff|isort|flake8)\]\s*$", _M)
_LINE_LENGTH = re.compile(r"^(?:line[-_]length|max[-_]line[-_]length)\s*=\s*(\d+)", _M)
_ISORT_PROFILE = re.compile(r"^profile\s*=\s*[\"']([\w-]+)[\"']", _M)
# What a stranger writes, expanded into the script before the shell starts.
_STRANGER_TEXT = r"github\.(?:event\.(?:issue\.(?:title|body)|pull_request\.(?:title|body|head\.ref|head\.label)|comment\.body|review\.body|review_comment\.body|discussion\.(?:title|body)|head_commit\.(?:message|author\.\w+)|commits\[[^\]]*\]\.(?:message|author\.\w+))|head_ref)"
_RUN_LINE = re.compile(r"^[ \t]*(?:-[ \t]*)?(?P<key>run):[ \t]*(?P<block>[|>][-+]?[ \t]*$)?(?P<inline>[^\n]*)")
_EXPANSION = re.compile(r"\$\{\{\s*" + _STRANGER_TEXT + r"\s*\}\}")  # the whole expression, since `startsWith(...)` or `... != ''` comes out as a boolean
# config team, 2026-11-08: workflow_run and issue_comment run with secrets and a write token too, whoever opened the pull request.
_PRIVILEGED_TRIGGER = re.compile(r"^[ \t]*(?:-[ \t]*)?(pull_request_target|workflow_run|issue_comment)[ \t]*:?[ \t]*(?:#.*)?$|^on:[ \t]*(pull_request_target|workflow_run|issue_comment)\b"
                                r"|\bon:[ \t]*\[[^\]\n]*\b(pull_request_target|workflow_run|issue_comment)\b", _M)
_HEAD_CHECKOUT = re.compile(r"ref:\s*\$\{\{\s*github\.event\.pull_request\.head\.(?:sha|ref)|ref:\s*refs/pull/|ref:\s*\$\{\{\s*github\.head_ref\s*\}\}"
                            r"|ref:\s*\$\{\{\s*github\.event\.workflow_run\.head_(?:sha|branch)\b|repository:\s*\$\{\{\s*github\.event\.(?:pull_request\.head\.repo|workflow_run\.head_repository)\.full_name"
                            r"|ref:\s*\$\{\{\s*steps\.[\w-]+\.outputs\.\w*(?:head|sha)\w*\s*\}\}|(?<![\w-])gh[ \t]+pr[ \t]+checkout\b|(?<![\w-])git[ \t]+fetch\b[^\n]*\bpull/")
# Who may trigger a comment workflow, checked before it runs anything. The commenter's association, or their permission on the repository.
_CHECKS_COMMENTER = re.compile(r"author_association|getCollaboratorPermissionLevel|checkCollaborator|/collaborators/|permission-level|permission_level|comment\.user\.login[ \t]*==")
_DOWNLOAD_ARTIFACT = re.compile(r"uses:[ \t]*(?:actions/download-artifact|dawidd6/action-download-artifact)@")
_FROM_ANOTHER_RUN = re.compile(r"github\.event\.workflow_run\.id\b")
_STEP_PATH = re.compile(r"^[ \t]+path:[ \t]*[\"']?([^\s\"'#]+)", _M)
_RUNNER_MASKED = re.compile(r"^[ \t]*([A-Za-z_]\w*):[ \t]*[\"']?\$\{\{\s*(?:secrets\.\w+|github\.token)\s*\}\}", _M)
_SECRET_REFERENCE = re.compile(r"\$\{\{\s*secrets\.(\w+)\s*\}\}")
_READS_ONLY = re.compile(r"\b(?:smoke|health|healthcheck|read-?only|canary|synthetic|probe|liveness|readiness)\b", _I)
MAX_ENV_LINES = 300
_PRODUCTION_NAME = re.compile(r"(?:^|_)(?:PROD|PRODUCTION|PRD|LIVE)(?:_|$)", _I)
_BUILD_ARG_SECRET = re.compile(r"--build-arg[ \t=]+[\"']?\w+=[\"']?\$\{\{\s*secrets\.|build-args:[^\n]*\$\{\{\s*secrets\.|build-args:[ \t]*[|>][-+]?[ \t]*\n(?:[ \t]+[^\n]*\n){0,8}?[ \t]+[^\n]*\$\{\{\s*secrets\.")
_CI_IMAGE_UNTAGGED = re.compile(r"^[ \t]*(?:-[ \t]*)?(?:image|container):[ \t]*[\"']?(?![\w./-]*\$)([\w.-]+(?:/[\w.-]+)*)[\"']?[ \t]*(?:#.*)?$", _M)
_REMOTE_PIPELINE = re.compile(r"^[ \t]*(?:-[ \t]*)?(?:remote:|include:)?[ \t]*[\"']?(https?://[^\s\"'#]+?\.ya?ml)[\"']?[ \t]*(?:#.*)?$", _M)
_MOVING_COMPONENT = re.compile(r"^[ \t]*(?:-[ \t]*)?component:[ \t]*[\"']?([\w.-]+/[^\s@\"']+)@(main|master|~latest|latest|HEAD)[\"']?[ \t]*(?:#.*)?$", _M)
_VOLATILE_ORB = re.compile(r"^[ \t]+[\w-]+:[ \t]*([\w-]+/[\w-]+)@volatile\b", _M)
_COMMIT = re.compile(r"\b[0-9a-f]{40}\b")
_EXECUTES = r"(?:^|[;&|(]|\bthen\b|run:)[ \t]*(?:sudo[ \t]+)?(?:bash|sh|zsh|source|\.|python3?|node|ruby|perl|pwsh|chmod[ \t]+\+x)[ \t]+[\"']?(?:\./)?{path}/|(?:^|[\s;&|(\"'])\./{path}/|(?<![\w-])make[ \t]+-C[ \t]+[\"']?{path}\b|(?<![\w-])cd[ \t]+[\"']?{path}[\"']?[ \t]*(?:&&|;|$)"
_WRITE_ALL = re.compile(r"^[ \t]*permissions:\s*write-all\b", _M)

_FROM = re.compile(r"^[ \t]*FROM\s+(?:--platform=\S+\s+)?(?!scratch\b)(?P<image>[^\s:@]+(?::(?P<tag>[^\s@]+))?)(?:\s+AS\s+\S+)?\s*$", _M | _I)
# A switch about a password isn't one: ALLOW_EMPTY_PASSWORD=yes, MYSQL_RANDOM_ROOT_PASSWORD=yes. A bare `ARG NAME` gets "\0" for its value.
_SWITCH_NAME = re.compile(r"(?:^|_)(?:ALLOW|RANDOM|EMPTY|GENERATE|REQUIRE|REQUIRED|SKIP|DISABLE|ENABLE|USE|NO|MIN|MAX|EXPIRE|EXPIRY|RESET|ONETIME)(?:_|$)", _I)
_FLAG_VALUES = {"yes", "no", "true", "false", "0", "1", "on", "off", "", "y", "n"}
_ARG_OR_ENV = re.compile(r"^[ \t]*(ARG|ENV)[ \t]+([^\n]*)", _M | _I)  # config team, 2026-11-08
_STAGE_NAME = re.compile(r"^[ \t]*FROM\s+\S+(?:\s+\S+)?\s+AS\s+(\S+)", _M | _I)
_IMAGE_LATEST = re.compile(r"^[ \t]*(?:-[ \t]*)?image:\s*[\"']?[\w./-]+:latest[\"']?\s*(?:#.*)?$", _M)
_PRIVILEGED = re.compile(r"^[ \t]*(?:-[ \t]*)?(privileged|hostNetwork|hostPID|hostIPC|allowPrivilegeEscalation):\s*true\b", _M)
_KUBE_OR_COMPOSE = re.compile(r"^[ \t]*(?:apiVersion:|kind:|services:)\s*", _M)

# config team, 2026-11-08
_FAILS_OPEN = re.compile(r"[\"']?\b(?:failure_mode_allow|failOpen)[\"']?[ \t]*:[ \t]*[\"']?true\b", _I)
_EXT_AUTHZ = re.compile(r"ext_authz|ExtAuthz|envoyExtAuthz", _I)
AUTHZ_CONTEXT = 3000  # failure_mode_allow also belongs to ext_proc, which isn't a security check, so the authorization filter must be just before it
_REVOCATION_OFF = re.compile(r"[\"']?\bEnableTokenRevocation[\"']?[ \t]*:[ \t]*[\"']?false\b|\benable_token_revocation[ \t]*=[ \t]*false\b")
_DEVELOPMENT_PROFILE = re.compile(r"^(?:dev|local|test|debug|development)\b", _I)
_SPRING_EXPOSURE = (
    (re.compile(r"\binclude[-_]stacktrace[\"']?[ \t]*[:=][ \t]*[\"']?(?:always|on[-_](?:trace[-_])?param)\b|\binclude[-_]exception[\"']?[ \t]*[:=][ \t]*[\"']?true\b", _I),
     "error-details-exposed", "Error responses carry the stack trace or exception class, which shows a caller code paths and libraries. Leave them out of production profiles."),
    (re.compile(r"\bexposure\.include[ \t]*[:=][ \t]*[\"']?\*|^[ \t]*exposure:[ \t]*\n(?:[ \t]+[^\n]*\n){0,3}?[ \t]+include:[ \t]*[\"']?\*", _M),
     "debug-exposed", "Every actuator endpoint is exposed, including env, heapdump and loggers, which read secrets and change the running service. Expose health and info only."),
    (re.compile(r"\bshow-values[\"']?[ \t]*[:=][ \t]*[\"']?always\b", _I),
     "debug-exposed", "The env and configprops endpoints show values unmasked, so they hand out passwords and keys. Leave show-values at never."),
)
_BINDS_CLUSTER_ADMIN = re.compile(r"^roleRef:[ \t]*\n(?:[ \t]+[^\n]*\n){0,4}?[ \t]+name:[ \t]*[\"']?cluster-admin\b", _M)
_ALL_VERBS = re.compile(r"verbs:[ \t]*\[[ \t]*[\"']\*[\"'][ \t]*\]|verbs:[ \t]*\n[ \t]*-[ \t]*[\"']\*[\"']")
_ALL_RESOURCES = re.compile(r"resources:[ \t]*\[[ \t]*[\"']\*[\"'][ \t]*\]|resources:[ \t]*\n[ \t]*-[ \t]*[\"']\*[\"']")
_TF_CLUSTER_ADMIN = re.compile(r"\brole_ref[ \t]*\{[^}]{0,300}?\bname[ \t]*=[ \t]*\"cluster-admin\"")
_ADMINISTRATOR_POLICY = re.compile(r"arn:aws:iam::aws:policy/AdministratorAccess\b")
_NEVER_EXPIRES = re.compile(r"\bexpiration_type[ \t]*=[ \t]*\"non-expiring\"")
_TF_MODULE = re.compile(r"^[ \t]*module[ \t]+\"[^\"\n]+\"[ \t]*\{", _M)
_TF_SOURCE = re.compile(r"^[ \t]*source[ \t]*=[ \t]*\"([^\"\n]+)\"", _M)
_TF_VERSION = re.compile(r"^[ \t]*version[ \t]*=", _M)
_REGISTRY_MODULE = re.compile(r"^(?:[\w.-]+\.[a-z]{2,}/)?[\w-]+/[\w-]+/[\w-]+$")
_VERSION_LIKE = re.compile(r"^v?\d+(?:\.\d+)+(?:[-+.][\w.-]*)?$|^[0-9a-f]{7,40}$")
_GIT_REQUIREMENT = re.compile(r"\bgit\+(?:https?|ssh|git|file)://[^\s\"',\]]+")
_ARCHIVE_ON_BRANCH = re.compile(r"\bhttps://(?:github\.com|gitlab\.com)/[^\s\"']+/(?:archive|-/archive)/(?:refs/heads/)?(?:main|master|develop|dev|HEAD|trunk)[^\s\"']*\.(?:zip|tar\.gz|tgz)")
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
_CLASSIC_INJECTION = re.compile(r"\b(?:ignore|disregard|forget)\s+(?:all\s+|any\s+)?(?:(?:the|your)\s+)?(?:previous|prior|above|earlier|preceding)\s+(?:instructions?|prompts?|rules?)\b"
                                r"|\b(?:do not|don't|never)\s+(?:tell|inform|mention (?:this |it )?to|notify|alert)\s+the\s+(?:user|developer|human)\b|\bwithout\s+(?:telling|informing|notifying|alerting)\s+the\s+(?:user|developer|human)\b", _I)
# config team, 2026-11-08. Planted text speaks to its reader by role, then asks for what a person would refuse: to keep it from them, to
# skip their approval, or to run or send something. Naming a role isn't enough: release notes, product docs and install pages describe what
# an AI product does ("Get started with large language models", "The AI assistant now never mentions…"). Only a role spoken to counts: a
# note or notice for it, a line opening "For the AI agent…", "If you are an automated assistant", or the role and its errand before a colon.
_ROLE = (r"(?:(?-i:AI|LLM)s?(?:[ \t]+[\w-]+)?[ \t]+(?:agents?|assistants?|bots?|models?)|(?:automated|autonomous|agentic)(?:[ \t]+[\w-]+)?[ \t]+(?:agents?|assistants?)"
         r"|(?:large[ \t]+)?language[ \t]+models?|coding[ \t]+(?:agents?|assistants?))")
_AGENT_ROLE = re.compile(
    rf"\b(?:notes?|notices?|messages?|instructions?|attention|important|reminder|warning|directive)[ \t]+(?:for|to)[ \t]+(?:any[ \t]+|all[ \t]+|the[ \t]+|every[ \t]+)?{_ROLE}\b"
    rf"|(?:^|[.!?][ \t]+|[*_#>(\-][ \t]*)(?:to|for|dear|hey|hi|hello)[ \t,]+(?:any[ \t]+|all[ \t]+|the[ \t]+|every[ \t]+)?{_ROLE}\b"
    rf"|\bif[ \t]+you(?:[ \t]+are|'re)[ \t]+(?:an?[ \t]+)?{_ROLE}\b|\bas[ \t]+an?[ \t]+{_ROLE},[ \t]+you\b|\byou,[ \t]+the[ \t]+{_ROLE}\b"
    rf"|\b{_ROLE}(?:[ \t]+(?:\w+ing|assigned|tasked)\b[^.:\n]{{0,60}})?[ \t]*:(?!//)", _I | _M)
_AGENT_ASK = re.compile(
    r"\b(?:do[ \t]+not|don't|never)[ \t]+(?:tell|inform|notify|alert|mention|disclose)\b"
    r"|\b(?:do|does)[ \t]*n[o']?t[ \t]+need[ \t]+to[ \t]+(?:be[ \t]+)?(?:tell|told|inform(?:ed)?|notif(?:y|ied)|alert(?:ed)?|mention(?:ed)?|disclosed?|ask(?:ed)?)\b"
    r"|\b(?:no[ \t]+need|not[ \t]+(?:necessary|needed|required))[ \t]+(?:for[ \t]+\w+[ \t]+)?to[ \t]+(?:be[ \t]+)?(?:tell|told|inform(?:ed)?|notif(?:y|ied)|alert(?:ed)?|mention(?:ed)?|ask(?:ed)?|confirm)\b"
    r"|\bwithout[ \t]+(?:telling|informing|notifying|alerting)\b"
    r"|\b(?:do[ \t]+not|don't)[ \t]+(?:ask|wait|check)[ \t]+(?:for[ \t]+|with[ \t]+)?(?:anyone|anybody|the[ \t]+user|a[ \t]+human|permission|approval|confirmation)\b"
    r"|\bno[ \t]+(?:human[ \t]+)?(?:review|approval|confirmation|sign-?off)[ \t]+(?:is[ \t]+)?(?:needed|required|necessary)\b"
    r"|\b(?:has|have)[ \t]+(?:already[ \t]+)?(?:been[ \t]+)?(?:pre-?approved|approved)[ \t]+(?:this|it|the[ \t]+(?:fix|change|steps?|request))\b"
    r"|\b(?:curl|wget)\b[^\n|]{0,200}\|[ \t]*(?:sudo[ \t]+)?(?:ba|z|da)?sh\b|\benv[ \t]*\|[ \t]*base64\b|@\.env\b|/branches/[^/\s]+/protection\b", _I)
# Imperatives, since "the assistant doesn't ask for confirmation" describes a product and "don't ask for confirmation" gives an order.
MAX_PER_PATTERN = 10  # config team: past this a file is generated or hostile, and each finding counts its lines from the top
AGENT_WINDOW = 600  # characters from the role to the ask. Planted notes are a paragraph or two, and HTML comments and logs break lines often


_QUOTE = "\"'`\u201c\u2018"
_OVERRIDE = re.compile(_CLASSIC_INJECTION.pattern.split("|\\b(?:do not")[0], _I)


class _AddressesAnAgent:
    """A classic override, or text naming an AI agent and then asking it for what a person would refuse. Two passes and a pairing, rather
    than one pattern spanning the window, so text stuffed with role names stays linear. The match given back is the ask. A phrase in quotes
    is someone mentioning it, as in a warning about "ignore previous instructions", so it's left out."""

    def __init__(self, classic: re.Pattern) -> None:
        self.classic = classic

    def finditer(self, text: str, pos: int = 0, endpos: int = 1 << 62) -> Iterator[re.Match]:
        end = min(len(text), endpos)
        found = {match.start(): match for match in self.classic.finditer(text, pos, end) if not _quoted(text, match)}
        asks = list(_AGENT_ASK.finditer(text, pos, end))
        if asks:
            starts = [ask.start() for ask in asks]
            for role in _AGENT_ROLE.finditer(text, pos, end):
                index = bisect.bisect_left(starts, role.end())
                if index < len(asks) and starts[index] - role.end() <= AGENT_WINDOW:
                    found.setdefault(starts[index], asks[index])
        for start in sorted(found):
            if not _quoted(text, found[start]):
                yield found[start]

    def search(self, text: str, pos: int = 0, endpos: int = 1 << 62) -> re.Match | None:
        return next(self.finditer(text, pos, endpos), None)


def _quoted(text: str, match: re.Match) -> bool:
    """A phrase in quotes is mentioned. A command in backticks is still a command."""
    return re.fullmatch(r"[A-Za-z' \t\n-]+", match.group(0)) is not None and match.start() > 0 and text[match.start() - 1] in _QUOTE and bool(re.match(r"[^\n]{0,3}?[\"'`\u201d\u2019]", text[match.end():match.end() + 4]))


ADDRESSES_AN_AGENT = _AddressesAnAgent(_CLASSIC_INJECTION)
# Docs say "retries without informing the user" about a product, so in what an agent reads as data only the override and the role-and-ask pair count.
ADDRESSED_IN_DATA = _AddressesAnAgent(_OVERRIDE)

# config team, 2026-11-08
_RUNS_ON_EXPANSION = re.compile(r"!`([^`\n]{1,400})`")
_PIPES_TO_SHELL = re.compile(r"\b(?:curl|wget)\b[^|\n]{0,300}\|[ \t]*(?:sudo[ \t]+)?(?:\S*/)?(?:ba|z|da|k)?sh\b")
_ALLOW_KEY = re.compile(r"\"allow\"\s*:\s*\[")
_STRING_OR_CLOSE = re.compile(r"\"(?:\\.|[^\"\\\n])*\"|\]")
MAX_ALLOW_LIST = 50_000
_INFRASTRUCTURE_CLI = r"(?:aws|gcloud|gsutil|bq|az|kubectl|helm|terraform|tofu|pulumi|psql|mysql|mongosh|mongo|redis-cli|heroku|flyctl|fly|doctl|vercel|netlify|firebase|eksctl|oc|ssh|scp)"
_ALLOWS_EVERY = re.compile(rf"\"Bash\((?:sudo[ \t]+)?({_INFRASTRUCTURE_CLI})(?::\*|[ \t]+\*|\*)\)\"")
# Each part read separately and checked in code, since one pattern with a name on both sides of ADMIN backtracks badly on a long name.
_ADMIN_DSN = re.compile(r"\b(?:postgres(?:ql)?|mysql|mariadb|mongodb(?:\+srv)?|sqlserver|mssql|redis)://(postgres|root|sa|admin|superuser)(?::[^@\s\"/]{0,200})?@")
_ADMIN_USER = re.compile(r"\"(?:PGUSER|POSTGRES_USER|MYSQL_USER|DB_USER|DATABASE_USER)\"\s*:\s*\"(postgres|root|sa|admin)\"")
_ADMIN_PROFILE = re.compile(r"\"(?:AWS_PROFILE|AWS_DEFAULT_PROFILE|KUBECONFIG|KUBE_CONTEXT|KUBECONTEXT|CLOUDSDK_ACTIVE_CONFIG_NAME)\"\s*:\s*\"([^\"\n]{0,300})\"")
_ADMIN_WORD = re.compile(r"(?<![A-Za-z])admin(?![A-Za-z])", _I)
_VARIABLE_NAME = re.compile(r"\$\{?([A-Z0-9_]+)")
_ADMIN_SECRET = re.compile(r"(?:ADMIN|SUPERUSER|OWNER)\w*(?:TOKEN|PASSWORD|SECRET|PAT)$")
_WEB_SERVER = re.compile(r"^[ \t]*(?:server|location|upstream|http)\b[^;{}\n]*\{|^[ \t]*(?:proxy_pass|add_header|server_name)\b|^[ \t]*Header[ \t]+(?:always[ \t]+)?set\b", _M)
_REFLECTED_ORIGIN = re.compile(r"^[ \t]*(?:add_header|more_set_headers)[ \t]+[\"']?Access-Control-Allow-Origin:?[\"']?[ \t]+[\"']?\$http_origin\b"
                               r"|^[ \t]*Header[ \t]+(?:always[ \t]+)?set[ \t]+Access-Control-Allow-Origin[ \t]+[\"']?%\{HTTP_ORIGIN\}e", _M | _I)
_CREDENTIALS_ALLOWED = re.compile(r"Access-Control-Allow-Credentials:?[\"']?[ \t]+[\"']?true\b", _I)
_ORIGIN_CHECKED = re.compile(r"\bmap[ \t]+\$http_origin\b|\$http_origin[ \t]*!?~|SetEnvIf(?:NoCase)?[ \t]+Origin\b", _I)
_RESENDS_WRITES = re.compile(r"^[ \t]*(?:proxy|grpc|uwsgi|fastcgi|scgi|memcached)_next_upstream\b[^;\n]*\bnon_idempotent\b", _M)
_MAKE_SILENT_ALL = re.compile(r"^\.SILENT:[ \t]*(?:#[^\n]*)?$|^[ \t]*\.?MAKEFLAGS[ \t]*[+:?]?=[^\n]*(?:(?<![\w-])-s\b|--silent\b|--quiet\b|(?<![\w-])s\b)", _M)
_MAKE_SILENT_TARGETS = re.compile(r"^\.SILENT:[ \t]*([^\n#]+)", _M)
_MAKE_RULE = re.compile(r"^([^\s:=#][^:=\n]*?)[ \t]*::?(?!=)")
_MAKE_REFERENCE = re.compile(r"(?<!\$)\$[({]([A-Za-z_]\w*)[)}]")
_ON_DEMAND = re.compile(r"(^|/)\.claude/(?:commands|agents)/")
_DATA_FILE = re.compile(r"\.(?:json|ya?ml|toml|xml|md|markdown|mdx|rst|adoc|txt|log)$", _I)
_ROLLBACK_EMPTY = re.compile(r"^def downgrade\([^)\n]*\)[^:\n]*:[ \t]*\n(?:[ \t]*\"\"\"[^\n]*\"\"\"[ \t]*\n|[ \t]*#[^\n]*\n){0,5}[ \t]+pass[ \t]*$", _M)
_RUNPYTHON_ONE_WAY = re.compile(r"\bmigrations\.RunPython\(\s*[\w.]+\s*\)")
_DROPS = re.compile(r"\bDROP\s+(?:TABLE|COLUMN)\b|\bTRUNCATE\s+(?:TABLE\s+)?\w|\bop\.drop_(?:table|column)\(|\bmigrations\.(?:RemoveField|DeleteModel)\(|\b(?:remove_column|drop_table)\b|\.dropTable\(|\.dropColumn\(", _I)
_TAKES_A_LOCK = re.compile(r"\bCREATE\s+(?:UNIQUE\s+)?INDEX\s+(?!CONCURRENTLY\b)|\bADD\s+COLUMN\b[^;\n]*\bNOT\s+NULL\b(?![^;\n]*\bDEFAULT\b)|\bALTER\s+COLUMN\b[^;\n]*\bTYPE\b", _I)
_CREATES_TABLE = re.compile(r"\bCREATE\s+TABLE\b", _I)
_THE_WAY_BACK = re.compile(r"^(?:def downgrade\b|[ \t]*def down\b|exports\.down\b|[ \t]*(?:async\s+)?down\s*\()", _M)


def _line(text: str, offset: int) -> int:
    return text.count("\n", 0, offset) + 1


def line_finder(text: str) -> Callable[[int], int]:
    """Line numbers by bisecting the newline offsets once, for a check that may report many findings in one file."""
    newlines = [match.start() for match in re.finditer("\n", text)]
    return lambda offset: bisect.bisect_left(newlines, offset) + 1


def _allowed_to_fail(text: str) -> Iterator[tuple]:
    """Only on a step that runs a check, since a publish or an upload may be allowed to fail."""
    lines = text.split("\n")
    for match in _ALLOWED_TO_FAIL.finditer(text):
        line = _line(text, match.start())
        nearby = "\n".join(lines[max(0, line - 1 - LINES_AROUND_A_STEP):line + LINES_AROUND_A_STEP])
        if _RUNS_A_CHECK.search(nearby):
            yield "ci-check-disabled", line, f"The pipeline stays green here whatever the check does: `{match.group(0).strip()[:60]}`.", {}


def _ci_images(text: str) -> Iterator[tuple]:
    """A job's image or service with no tag, or :latest. GitLab, CircleCI and a GitHub job's container all name one this way."""
    for match in _IMAGE_LATEST.finditer(text):
        yield "container-unpinned-image", _line(text, match.start()), "`:latest` means whichever image is newest on the day the job runs.", {}
    for match in islice(_CI_IMAGE_UNTAGGED.finditer(text), MAX_PER_PATTERN):
        yield "container-unpinned-image", _line(text, match.start()), f"`{match.group(1)}` with no tag means whichever image is newest on the day the job runs.", {}


def _ci_scripts(path: str, text: str) -> Iterator[tuple]:
    """The shell a pipeline runs: each `run:` of a GitHub workflow, or the script lines of the others with their list dashes taken off."""
    from . import rules_scripts  # here, so the hook that imports this module for one pattern skips the shell reader

    # GitHub replaces a secret's value with *** in the log, so tracing a variable that holds one prints nothing. What's built from it isn't masked.
    masked_by_runner = frozenset(_RUNNER_MASKED.findall(text)) if GITHUB_WORKFLOW.search(path) else frozenset()
    if GITHUB_WORKFLOW.search(path):
        lines = text.split("\n")
        index = 0
        pieces = []
        while index < len(lines):
            match = _RUN_LINE.match(lines[index])
            index += 1
            if match:
                body, first, index = _run_body(lines, index, match)
                pieces.append((first, "\n".join(body)))
    else:
        pieces = [(1, re.sub(r"^([ \t]*)-[ \t]", lambda found: found.group(1) + "  ", text, flags=_M))]
    for first, script in pieces:
        for line, message in rules_scripts.retried_writes(script):
            yield "retry-not-idempotent", first + line - 1, message, {}
        for line, message in rules_scripts.traced_secrets(script, masked_by_runner):
            yield "sensitive-log", first + line - 1, message, {}


def _remote_pipeline_files(text: str) -> Iterator[tuple]:
    """Pipeline code fetched when the pipeline starts: a GitLab remote include or component on a branch, or a CircleCI orb at volatile.
    A commit in the URL, or GitLab's integrity: hash, pins it."""
    for match in islice(_REMOTE_PIPELINE.finditer(text), MAX_PER_PATTERN):
        following = text[match.end():match.end() + 300]
        if _COMMIT.search(match.group(1)) or re.match(r"(?:\n[ \t]*[^\n-][^\n]*){0,3}?\n[ \t]*integrity:", following):
            continue
        host = match.group(1).split("/")[2]
        yield "ci-unpinned-action", _line(text, match.start()), f"This pipeline runs whatever {host} serves at this URL when it starts, with its variables and tokens. Pin a commit, or add integrity:.", {"confidence": "medium"}
    for match in islice(_MOVING_COMPONENT.finditer(text), MAX_PER_PATTERN):
        yield "ci-unpinned-action", _line(text, match.start()), f"{match.group(1)}@{match.group(2)} runs whatever that ref holds when the pipeline starts. Pin a version or commit.", {"confidence": "medium"}
    for match in islice(_VOLATILE_ORB.finditer(text), MAX_PER_PATTERN):
        yield "ci-unpinned-action", _line(text, match.start()), f"{match.group(1)}@volatile runs the newest orb published, with this pipeline's contexts. Pin a version.", {"confidence": "medium"}


def _workflow_findings(path: str, text: str) -> Iterator[tuple]:
    for pattern in _CI_DISABLED:
        for match in pattern.finditer(text):
            yield "ci-check-disabled", _line(text, match.start()), f"The pipeline stays green here whatever happens: `{match.group(0).strip()[:60]}`.", {}
    yield from _allowed_to_fail(text)
    yield from _ci_images(text)
    yield from _ci_scripts(path, text)
    if not GITHUB_WORKFLOW.search(path):
        yield from _remote_pipeline_files(text)
        return
    for match in _BRANCH_REF.finditer(text):
        yield "ci-unpinned-action", _line(text, match.start()), f"This runs whatever {match.group(1)} holds today, with this workflow's token.", {}
    for match in _TAG_REF.finditer(text):
        yield "ci-unpinned-action", _line(text, match.start()), f"{match.group(1)}@{match.group(2)} runs whatever that tag points to when the job starts, and its owner can move it.", {}
    yield from _run_injections(text)
    yield from _untrusted_code(text)
    for match in _WRITE_ALL.finditer(text):
        yield "ci-write-all", _line(text, match.start()), None, {}
    yield from _tests_on_production(text)
    for match in islice(_BUILD_ARG_SECRET.finditer(text), MAX_PER_PATTERN):
        yield "container-secret-arg", _line(text, match.start()), "A build argument is recorded in the image's history, so this secret ships with the image and its build cache. Pass it as a BuildKit secret.", {}


def _untrusted_code(text: str) -> Iterator[tuple]:
    """A workflow that runs with secrets and a write token, running code a pull request controls: by checking it out, or by executing what
    its build uploaded. A comment trigger that checks who commented is a maintainer's command, so it's left out."""
    trigger = _PRIVILEGED_TRIGGER.search(text)
    if not trigger:
        return
    name = next(group for group in trigger.groups() if group)
    if name == "issue_comment" and _CHECKS_COMMENTER.search(text):
        return
    for match in _HEAD_CHECKOUT.finditer(text):
        yield "ci-untrusted-checkout", _line(text, match.start()), f"{name} has secrets and write access, and this checks out the pull request's own code.", {}
    if name == "workflow_run":
        yield from _artifact_execution(text)


def _artifact_execution(text: str) -> Iterator[tuple]:
    """An artifact from the triggering run was built from the pull request, so a script inside it is the pull request's code."""
    for download in islice(_DOWNLOAD_ARTIFACT.finditer(text), MAX_PER_PATTERN):
        step_end = _step_end(text, download.start())
        step = text[download.start():step_end]
        place = _STEP_PATH.search(step)
        if not _FROM_ANOTHER_RUN.search(step) or not place or "${{" in place.group(1):
            continue
        folder = re.escape(place.group(1).removeprefix("./").strip("/"))
        found = re.compile(_EXECUTES.format(path=folder), _M).search(text, step_end) if folder else None
        if found:
            yield ("ci-untrusted-checkout", _line(text, found.start() + len(found.group(0)) - len(found.group(0).lstrip())),
                   f"This runs a file from {place.group(1)}, which the pull request's own build uploaded, with this workflow's secrets.", {})


def _step_end(text: str, offset: int) -> int:
    """Where the step holding offset ends: the next list item at its dash's indent, or anything shallower."""
    lines_before = text.rfind("\n", 0, offset) + 1
    dash = re.search(r"-[ \t]", text[lines_before:offset + 1])
    indent = (dash.start() if dash else len(text[lines_before:offset]) - len(text[lines_before:offset].lstrip()))
    for line in re.finditer(r"^([ \t]*)(\S)", text[offset:], _M):
        if line.start() == 0:
            continue
        depth = len(line.group(1))
        if depth < indent or (depth == indent and line.group(2) == "-"):
            return offset + line.start()
    return len(text)


def _production_secret(text: str) -> str | None:
    return next((match.group(1) for match in _SECRET_REFERENCE.finditer(text) if _PRODUCTION_NAME.search(match.group(1))), None)


def _blocks(lines: list[str], key: str) -> Iterator[tuple[int, int, int]]:
    """(key line, first line after the block, the key's indent) for each `key:` whose value is the indented lines below it."""
    for index, line in enumerate(lines):
        found = re.match(rf"^([ \t]*){key}:[ \t]*(?:#.*)?$", line)
        if not found:
            continue
        indent = len(found.group(1))
        end = index + 1
        while end < len(lines) and (not lines[end].strip() or len(lines[end]) - len(lines[end].lstrip()) > indent):
            end += 1
        yield index, end, indent


def _tests_on_production(text: str) -> Iterator[tuple]:
    """A step that runs the tests, given a production secret by the step, its job or the workflow. Fixtures create, migrate and delete.
    Only secrets count, since a var is a URL or a name. A smoke, health or read-only suite is meant to run against production, and only reads.
    One pass finds each line's parent key, so a workflow with thousands of jobs stays linear."""
    if "secrets." not in text or not _production_secret(text):
        return
    lines = text.split("\n")
    depth = [len(line) - len(line.lstrip()) if line.strip() else -1 for line in lines]
    parent = [-1] * len(lines)
    open_keys: list[int] = []
    env_by_owner: dict[int, list[str]] = {}
    items_by_steps: dict[int, list[int]] = {}
    steps_lines = []
    for index, indent in enumerate(depth):
        if indent < 0:
            continue
        while open_keys and depth[open_keys[-1]] >= indent:
            open_keys.pop()
        parent[index] = open_keys[-1] if open_keys else -1
        open_keys.append(index)
        line = lines[index]
        if re.match(r"[ \t]*env:[ \t]*(?:#.*)?$", line):
            end = index + 1
            while end < len(lines) and end - index < MAX_ENV_LINES and (depth[end] < 0 or depth[end] > indent):
                end += 1
            env_by_owner.setdefault(parent[index], []).append("\n".join(lines[index:end]))
        elif re.match(r"[ \t]*steps:[ \t]*(?:#.*)?$", line):
            steps_lines.append(index)
        elif line.lstrip().startswith("- ") and parent[index] >= 0 and re.match(r"[ \t]*steps:", lines[parent[index]]):
            items_by_steps.setdefault(parent[index], []).append(index)
    top_env = "\n".join(env_by_owner.get(-1, []))
    for steps in steps_lines:
        job = parent[steps]
        job_text = lines[job] if job >= 0 else ""
        job_env = "\n".join(env_by_owner.get(job, []))
        starts = items_by_steps.get(steps, [])
        for number, start in enumerate(starts):
            end = starts[number + 1] if number + 1 < len(starts) else _block_end(depth, start, depth[steps])
            step = "\n".join(lines[start:end])
            check = _RUNS_A_CHECK.search(step)
            if not check or _READS_ONLY.search(step) or _READS_ONLY.search(job_text):
                continue
            name = _production_secret(step) or _production_secret(job_env) or _production_secret(top_env)
            if name:
                yield "tests-use-production", start + 1 + step.count("\n", 0, check.start()), (
                    f"The tests run here with {name}, so their fixtures create, change and delete rows in production, on every run. Give tests their own database and credentials."), {}


def _block_end(depth: list[int], start: int, owner_depth: int) -> int:
    end = start + 1
    while end < len(depth) and (depth[end] < 0 or depth[end] > owner_depth):
        end += 1
    return end


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
    from . import rules_scripts  # here, so the hook that imports this module for one pattern skips the shell reader

    stages = {name.lower() for name in _STAGE_NAME.findall(text)}
    for match in _FROM.finditer(text):
        image, tag = match.group("image"), match.group("tag")
        if tag in (None, "latest") and image.split(":")[0].lower() not in stages and "$" not in image:
            yield "container-unpinned-image", _line(text, match.start()), f"`{image}` means whichever image is newest on the day it builds.", {}
    for match in islice(_ARG_OR_ENV.finditer(text), MAX_PER_PATTERN):
        for name, value in _declared(match.group(1).upper(), match.group(2)):
            if rules_scripts.credential_name(name) and not _SWITCH_NAME.search(name) and value.strip("\"'").lower() not in _FLAG_VALUES:
                kind = "build argument" if match.group(1).upper() == "ARG" else "ENV value"
                yield "container-secret-arg", _line(text, match.start()), f"{name} is a {kind}, which the image records in its history and config, so the secret ships with it. Mount it with RUN --mount=type=secret instead.", {}


def _declared(kind: str, declaration: str) -> list[tuple[str, str]]:
    """(name, value) pairs: `ARG NAME[=default]`, `ENV A=1 B=2`, and the old `ENV A 1`. A value not given is empty."""
    pairs = re.findall(r"([A-Za-z_]\w*)=(\"(?:\\.|[^\"\\])*\"|'[^']*'|\S*)", declaration)
    if kind == "ARG":
        return pairs[:1] or [(name, "\0") for name in re.findall(r"^\s*([A-Za-z_]\w*)", declaration)[:1]]
    if pairs:
        return pairs
    legacy = re.match(r"\s*([A-Za-z_]\w*)\s+(.*)$", declaration)
    return [(legacy.group(1), legacy.group(2))] if legacy else []


def _structured_findings(path: str, text: str) -> Iterator[tuple]:
    """Settings that read the same in YAML and JSON: an authorization filter told to let requests through when it fails, token revocation
    switched off, and Spring Boot's error and actuator settings in a profile that isn't for development."""
    # fail-open is in verify._BLOCKING, so this fails gate whatever its severity, and it should: ext_authz with failure_mode_allow lets an
    # outage through unchecked. Medium confidence keeps it from ever being a send-back at Stop.
    for match in islice(_FAILS_OPEN.finditer(text), MAX_PER_PATTERN):
        if _EXT_AUTHZ.search(text, max(0, match.start() - AUTHZ_CONTEXT), match.start()):
            yield "fail-open", _line(text, match.start()), "When the authorization service errors or times out, this lets the request through unchecked. Set it to false and fail closed.", {"severity": "high", "confidence": "medium"}
    for match in islice(_REVOCATION_OFF.finditer(text), MAX_PER_PATTERN):
        yield "disabled-control", _line(text, match.start()), "Token revocation is off, so signing out or disabling a user can't cut off a refresh token already issued.", {}
    spring = SPRING_CONFIG.search(path)
    if spring and not _DEVELOPMENT_PROFILE.search(spring.group("profile") or ""):
        for pattern, rule, message in _SPRING_EXPOSURE:
            for match in islice(pattern.finditer(text), MAX_PER_PATTERN):
                if not _in_development_section(text, match.start()):
                    yield rule, _line(text, match.start()), message, {}


def _in_development_section(text: str, offset: int) -> bool:
    """A multi-document application.yml can give a profile its own section, which `---` starts."""
    section = text[text.rfind("\n---", 0, offset) + 1:offset]
    return bool(re.search(r"(?:on-profile|profiles):[ \t]*[\"']?(?:dev|local|test|debug|development)\b", section))


def _yaml_findings(path: str, text: str) -> Iterator[tuple]:
    yield from _structured_findings(path, text)
    if not _KUBE_OR_COMPOSE.search(text):
        return
    yield from _cluster_admin(text)
    for match in _IMAGE_LATEST.finditer(text):
        yield "container-unpinned-image", _line(text, match.start()), "`:latest` means whichever image is newest on the day it starts.", {}
    for match in _PRIVILEGED.finditer(text):
        yield "container-privileged", _line(text, match.start()), f"{match.group(1)} gives this container much of the host.", {}


def _cluster_admin(text: str) -> Iterator[tuple]:
    """A Kubernetes binding to cluster-admin, or a role whose rules allow every verb on every resource."""
    for document in islice(re.finditer(r"(?:\A|^---[^\n]*\n)(.*?)(?=^---|\Z)", text, _M | re.S), 200):
        body = document.group(1)
        if re.search(r"^kind:[ \t]*(?:Cluster)?RoleBinding\b", body, _M):
            for match in islice(_BINDS_CLUSTER_ADMIN.finditer(body), MAX_PER_PATTERN):
                yield "iac-wildcard-permission", _line(text, document.start(1) + match.start()), "This binds cluster-admin, which can do anything to every resource in the cluster. Bind a role with the verbs and resources it uses.", {}
        elif re.search(r"^kind:[ \t]*(?:Cluster)?Role\b", body, _M) and _ALL_VERBS.search(body) and _ALL_RESOURCES.search(body):
            match = _ALL_VERBS.search(body)
            yield "iac-wildcard-permission", _line(text, document.start(1) + match.start()), "This role allows every verb on every resource. List the ones it uses.", {}


def terraform_findings(text: str) -> Iterator[tuple]:
    for rule, pattern in (("iac-open-ingress", _OPEN_INGRESS), ("iac-public-data", _PUBLIC_DATA), ("iac-data-loss-setting", _LOSES_DATA), ("iac-wildcard-permission", _WILDCARD_PERMISSION)):
        for match in pattern.finditer(text):
            yield rule, _line(text, match.start()), None, {}
    for match in islice(_REVOCATION_OFF.finditer(text), MAX_PER_PATTERN):
        yield "disabled-control", _line(text, match.start()), "Token revocation is off, so signing out or disabling a user can't cut off a refresh token already issued.", {}
    for match in islice(_NEVER_EXPIRES.finditer(text), MAX_PER_PATTERN):
        yield "disabled-control", _line(text, match.start()), "Refresh tokens that never expire stay usable after a user leaves or a device is lost. Give them an expiry and rotate them.", {}
    for match in islice(_TF_CLUSTER_ADMIN.finditer(text), MAX_PER_PATTERN):
        yield "iac-wildcard-permission", _line(text, match.start()), "This binds cluster-admin, which can do anything to every resource in the cluster.", {}
    for match in islice(_ADMINISTRATOR_POLICY.finditer(text), MAX_PER_PATTERN):
        yield "iac-wildcard-permission", _line(text, match.start()), "AdministratorAccess allows every action on every resource in the account. Attach a policy with the actions this role uses.", {}
    yield from _module_sources(text)


def _module_sources(text: str) -> Iterator[tuple]:
    """A module from git with no ref or a branch, or from a registry with no version. Neither is in the lock file, which pins providers only,
    so init takes whatever is there that day."""
    for module in islice(_TF_MODULE.finditer(text), MAX_PER_PATTERN):
        body = text[module.end():_closing_brace(text, module.end())]
        source = _TF_SOURCE.search(body)
        if not source:
            continue
        where = source.group(1)
        line = _line(text, module.end() + source.start())
        if where.startswith(("./", "../")):
            continue
        if re.match(r"(?:git::|hg::|git@|github\.com/|bitbucket\.org/|gitlab\.com/)", where):
            ref = re.search(r"[?&]ref=([^&\s]+)", where)
            if not ref or not _VERSION_LIKE.match(ref.group(1)):
                yield "dep-unpinned", line, (f"This module comes from {ref.group(1) if ref else 'the default branch'}, so every terraform init takes whatever it holds that day. "
                                             "Pin ?ref= to a tag or commit."), {}
        elif _REGISTRY_MODULE.match(where) and not _TF_VERSION.search(body):
            yield "dep-unpinned", line, f"{where} has no version, so terraform init takes the newest release. Add a version constraint.", {}


def _closing_brace(text: str, start: int) -> int:
    """Where the block opened just before start closes, skipping strings and comments. Bounded, since a block this long isn't a module call."""
    depth = 1
    index = start
    limit = min(len(text), start + 20_000)
    while index < limit:
        character = text[index]
        if character == '"':
            index += 1
            while index < limit and text[index] not in '"\n':
                index += 2 if text[index] == "\\" else 1
        elif character == "#" or text.startswith("//", index):
            index = text.find("\n", index)
            if index < 0:
                return limit
        elif character == "{":
            depth += 1
        elif character == "}":
            depth -= 1
            if depth == 0:
                return index
        index += 1
    return limit


def _package_json_findings(text: str) -> Iterator[tuple]:
    for section in _NODE_SECTIONS.finditer(text):
        for match in _NODE_ANYTHING.finditer(section.group("body")):
            yield "dep-unpinned", _line(text, section.start("body") + match.start()), f"{match.group(0)[:60]} installs whatever is newest, including a compromised release.", {}
    for match in _NODE_INSTALL_SCRIPT.finditer(text):
        yield "dep-install-script", _line(text, match.start()), f"A {match.group(1)} script runs on every machine that installs this.", {}


def _requirements_findings(text: str) -> Iterator[tuple]:
    for match in _EXTRA_INDEX.finditer(text):
        yield "dep-extra-index", _line(text, match.start()), "pip takes a name from whichever index offers it, so a public package can replace a private one.", {}
    yield from git_dependencies(text)


def git_dependencies(text: str) -> Iterator[tuple]:
    """A dependency installed from git at a branch or at no ref, or from a branch's archive. Nothing pins it, so each install takes what the
    branch holds that day. A tag or a commit stays; a commit is safest. Comments are left out."""
    for match in islice(_GIT_REQUIREMENT.finditer(text), MAX_PER_PATTERN):
        if text[text.rfind("\n", 0, match.start()) + 1:match.start()].lstrip().startswith("#"):
            continue
        url = match.group(0).split("#", 1)[0]
        path = url.split("://", 1)[1]
        path = path[path.find("/") + 1:] if "/" in path else ""
        ref = path.rsplit("@", 1)[1] if "@" in path else None
        if ref is None or not _VERSION_LIKE.match(ref):
            yield "dep-unpinned", _line(text, match.start()), (f"This installs whatever {ref or 'the default branch'} holds on the day it runs, so the build can change with no change here. "
                                                               "Pin it to a commit."), {}
    for match in islice(_ARCHIVE_ON_BRANCH.finditer(text), MAX_PER_PATTERN):
        yield "dep-unpinned", _line(text, match.start()), "This installs a branch's archive, which changes whenever the branch does. Pin a tag or commit.", {}


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
    # A command or subagent is the owner telling one task what to do, and "do not tell the user about style nits" is a fair order there.
    on_demand = bool(_ON_DEMAND.search(path))
    for match in (ADDRESSED_IN_DATA if on_demand else ADDRESSES_AN_AGENT).finditer(text):
        yield "instruction-injection", _line(text, match.start()), f"`{match.group(0)[:60]}` in a file agents obey. Check who wrote it and why.", {}
    lines = text.count("\n") + 1
    if lines > MAX_INSTRUCTION_LINES and not path.endswith("SKILL.md") and not on_demand:  # skills, commands and subagents load when used
        yield "instructions-bloated", 1, f"{lines} lines, read on every session whether or not they apply. Move what's rarely needed somewhere it loads on demand.", {}
    yield from _command_frontmatter(text)


def _command_frontmatter(text: str) -> Iterator[tuple]:
    """A slash command or skill pre-approves the tools in its allowed-tools, and runs each !`command` before the model reads anything. A
    subagent's tools: only limits what it has, so it isn't read."""
    head = re.match(r"---[ \t]*\n(.*?)\n---[ \t]*(?:\n|$)", text, re.S)
    if head:
        listed = re.search(r"^allowed-tools:[ \t]*([^\n]*(?:\n[ \t]+-[^\n]*){0,40})", head.group(1), _M)
        if listed:
            for tool in re.split(r"[,\n]|[ \t]+-[ \t]+|^-[ \t]*", listed.group(1)):
                if re.fullmatch(r"[ \t\-\"']*Bash(?:\(\*(?::\*)?\))?[\"' \t]*", tool):
                    yield "agent-permission-widened", _line(text, head.start(1) + listed.start()), "allowed-tools pre-approves every shell command whenever this runs. List the commands it needs, as Bash(git status:*).", {}
                    break
    for match in islice(_RUNS_ON_EXPANSION.finditer(text), MAX_PER_PATTERN):
        if _PIPES_TO_SHELL.search(match.group(1)):
            yield "curl-pipe-shell", _line(text, match.start()), "This runs a downloaded script every time the command is typed, before anyone sees it.", {"confidence": "medium"}


def _agent_settings_findings(text: str) -> Iterator[tuple]:
    for match in _WIDE_AGENT.finditer(text):
        yield "agent-permission-widened", _line(text, match.start()), f"`{match.group(0)[:60]}` lets an agent act without a person. Someone should choose that knowingly.", {}
    line_of = line_finder(text)
    for body_start, body in _allow_lists(text):
        for match in islice(_ALLOWS_EVERY.finditer(body), MAX_PER_PATTERN):
            yield ("agent-permission-widened", line_of(body_start + match.start()),
                   f"This pre-approves every {match.group(1)} command, so the agent can change shared infrastructure or data with no person seeing it. Allow the read-only subcommands it needs.", {})
    for where, what in islice(_admin_identities(text), MAX_PER_PATTERN):
        yield ("agent-permission-widened", line_of(where),
               f"This hands the agent an admin or superuser identity ({what}). Give it the narrowest role its task needs, such as a read-only database role or a repository-scoped token.", {})


def _allow_lists(text: str) -> Iterator[tuple[int, str]]:
    """(where the body starts, the body) of each "allow": [...] list. Strings are stepped over whole, so a `]` inside one doesn't end it, and an
    unclosed list is read no further than MAX_ALLOW_LIST."""
    for key in islice(_ALLOW_KEY.finditer(text), MAX_PER_PATTERN):
        for token in _STRING_OR_CLOSE.finditer(text, key.end(), min(len(text), key.end() + MAX_ALLOW_LIST)):
            if token.group(0) == "]":
                yield key.end(), text[key.end():token.start()]
                break


def _admin_identities(text: str) -> Iterator[tuple[int, str]]:
    for match in _ADMIN_DSN.finditer(text):
        yield match.start(), match.group(1)
    for match in _ADMIN_USER.finditer(text):
        yield match.start(), match.group(1)
    for match in _ADMIN_PROFILE.finditer(text):
        if _ADMIN_WORD.search(match.group(1)):
            yield match.start(), match.group(1)
    for match in _VARIABLE_NAME.finditer(text):
        if len(match.group(1)) <= 120 and _ADMIN_SECRET.search(match.group(1)):
            yield match.start(), match.group(1)


def _web_server_findings(text: str) -> Iterator[tuple]:
    """nginx, and Apache's header lines. Text only, so an origin check in an included file isn't seen, and its absence here counts."""
    if not _WEB_SERVER.search(text):
        return
    if _CREDENTIALS_ALLOWED.search(text) and not _ORIGIN_CHECKED.search(text):
        for match in islice(_REFLECTED_ORIGIN.finditer(text), MAX_PER_PATTERN):
            yield "permissive-cors", _line(text, match.start()), "This sends back whatever Origin asked, with credentials allowed, so any site can make requests as the signed-in user. Allow-list origins with a map.", {"severity": "high"}
    for match in islice(_RESENDS_WRITES.finditer(text), MAX_PER_PATTERN):
        yield "retry-not-idempotent", _line(text, match.start()), "non_idempotent lets nginx resend a POST to the next server after an error or timeout, when the first may have acted, so one order or payment happens twice.", {}


def _makefile_findings(text: str) -> Iterator[tuple]:
    """make prints each recipe line after expanding it, unless the line starts with @ or the target is silent. $$NAME reaches the shell
    unexpanded, so make prints the name."""
    from . import rules_scripts  # here, so the hook that imports this module for one pattern skips the shell reader

    if _MAKE_SILENT_ALL.search(text):
        return
    silent = set(" ".join(_MAKE_SILENT_TARGETS.findall(text)).split())
    lines = text.split("\n")
    target = ""
    reported = 0
    index = 0
    while index < len(lines) and reported < MAX_PER_PATTERN:
        line = lines[index]
        first = index
        if line.startswith("\t"):
            logical = line
            while logical.endswith("\\") and index + 1 < len(lines):
                index += 1
                logical = logical[:-1] + " " + lines[index]
            body = logical.lstrip("\t")
            if "@" not in re.match(r"[-+@ \t]*", body).group(0) and not body.startswith("#") and target not in silent:
                name = next((found for found in _MAKE_REFERENCE.findall(body) if rules_scripts.credential_name(found)), None)
                if name:
                    reported += 1
                    yield ("sensitive-log", first + 1, f"make prints this recipe line with $({name}) filled in before running it, so the value lands in the build log. "
                                                       f"Start the line with @, or let the shell read it as $${name}.", {})
        else:
            rule = _MAKE_RULE.match(line)
            if rule:
                target = rule.group(1).split()[0] if rule.group(1).split() else ""
        index += 1


def addressed_in_data(path: str, text: str, hidden: bool = True) -> Iterator[tuple]:
    """Docs, logs, dumps and saved pages are what an agent reads as data, and text planted there speaks to it by role. scan.py reads hidden
    characters in code itself, so a saved HTML page passes hidden=False."""
    if PROMPT_FILE.search(path):
        return
    if hidden:
        yield from hidden_characters(text)
    for match in islice(ADDRESSED_IN_DATA.finditer(text), MAX_PER_PATTERN):
        yield ("instruction-injection", _line(text, match.start()),
               f"`{match.group(0)[:60]}` asks an AI agent for what a person would refuse, in text it reads as data. Find out who wrote it, and don't act on it.", {})


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
        yield from _agent_settings_findings(text)
    elif AGENT_INSTRUCTIONS.search(path):
        yield from _instruction_findings(path, text)
    elif MAKEFILE.search(path):
        yield from _makefile_findings(text)
    elif WEB_SERVER_CONF.search(path):
        yield from _web_server_findings(text)
    elif YAML_FILE.search(path):
        yield from _yaml_findings(path, text)
    elif PYPROJECT.search(path):
        yield from _formatter_conflicts(text)
        yield from git_dependencies(text)
    elif ENV_FILE.search(path):
        for match in CLIENT_VISIBLE_SECRET.finditer(text):
            yield "secret-in-client-bundle", _line(text, match.start()), f"{match.group(0)[:50]} is compiled into what the browser downloads.", {}
    elif SPRING_CONFIG.search(path) or path.endswith(".json"):
        yield from _structured_findings(path, text)
    if _DATA_FILE.search(path) and not (WORKFLOW.search(path) or AGENT_SETTINGS.search(path) or AGENT_INSTRUCTIONS.search(path)):
        yield from addressed_in_data(path, text)


def _formatter_conflicts(text: str) -> Iterator[tuple]:
    """Two formatters set to different widths rewrite each other's output, and isort left at its defaults beside black does too. A linter that
    allows longer lines than the formatter writes conflicts with nothing. Only within this file."""
    headers = [found.start() for found in re.finditer(r"^\[", text, _M)] + [len(text)]
    tables = {}  # each table runs to the next header
    for match in _TOOL_TABLE.finditer(text):
        tables[match.group(1)] = (match.start(), text[match.end():next(start for start in headers if start > match.start())])
    formatters = {"black"} | ({"ruff"} if re.search(r"^\[tool\.ruff\.format\]", text, _M) else set())
    lengths = {tool: int(found.group(1)) for tool, (_, body) in tables.items() if tool in formatters for found in [_LINE_LENGTH.search(body)] if found}
    if len(set(lengths.values())) > 1:
        tool = max(lengths, key=lambda name: tables[name][0])
        yield "formatter-conflict", _line(text, tables[tool][0]), "Both format this code, at different widths: " + ", ".join(f"{name} {size}" for name, size in sorted(lengths.items())) + ". Use one value.", {}
    isort = tables["isort"][1] if "isort" in tables else ""
    if "black" in tables and isort and not _ISORT_PROFILE.search(isort) and not re.search(r"^multi_line_output\s*=", isort, _M):
        yield "formatter-conflict", _line(text, tables["isort"][0]), "black is set up here, and isort at its defaults wraps imports in a way black then rewrites. Set `profile = \"black\"`.", {}


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
