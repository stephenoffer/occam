"""What a request or a path says about the work: read-only or not, audit, security, scale, code or prose, which language.

Patterns on wording, so they're best effort. docs/claude-code.md says what that means for each one.
"""

from __future__ import annotations  # the stock macOS python3 is 3.9

import re
from pathlib import Path

import scale_notes

REVIEWER = "code-reviewer"
OWN_AGENTS = {REVIEWER, "auditor"}  # they carry their own briefs, so the rule card isn't repeated to them
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
# A missed defect here is a breach, so these get a fresh reviewer. The rest of HIGH_CONSEQUENCE gets a self-review of the whole diff, which
# Superpowers measured as catching about as much as a review subagent at a fraction of the time (its v5.0.6 release notes). Unmeasured here.
_SECURITY_CRITICAL_WORDS = r"auth|authn|authz|oauth|login|sessions?|tokens?|passwords?|secrets?|credentials?|permissions?|acl|rbac|tenants?|tenancy|crypto|signatures?"
_MONEY_AND_DATA_WORDS = r"billing|payments?|invoices?|checkout|refunds?|ledgers?|migrations?|migrate|webhooks?"
SECURITY_CRITICAL = re.compile(rf"(^|[/_.\-])({_SECURITY_CRITICAL_WORDS})([/_.\-]|$)", re.I)
HIGH_CONSEQUENCE = re.compile(rf"(^|[/_.\-])({_SECURITY_CRITICAL_WORDS}|{_MONEY_AND_DATA_WORDS})([/_.\-]|$)", re.I)
# Over-matching only brings back the reviewer agent, which every high-consequence file got until 2026-11-06, so this errs wide.
ASKS_FOR_REVIEW = re.compile(r"\b(?:fresh|independent|second|separate|outside)[- ](?:review(?:er)?|look|opinion|pair of eyes)\b|\bcode[- ]?review(?:er|s)?\b"
                             r"|\bindependently reviewed\b|\b(?:a|the|another) reviewer\b|\breview(?:ed)?\s+(?:it\s+|this\s+|them\s+)?(?:with|by)\s+(?:a\s+|an\s+)?(?:sub)?agent\b"
                             r"|\b(?:get|have)\s+(?:it|this|that|them|the\s+(?:changes?|diff|code|fix|pr))\s+reviewed\b", re.I)
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
# Semantics in each language that commonly go wrong. An edit touching one isn't small, whatever its size, so it needs the core skill.
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


def is_code(file_path: str) -> bool:
    if DEPENDENCY_MANIFEST.search(file_path):
        return True
    return Path(file_path).suffix.lower() not in DOC_SUFFIXES


def visible_prompt(prompt: str) -> str:
    """The user's own words, without pasted material or quoted code."""
    text = re.sub(r"```.*?```", " ", scale_notes.without_pasted(prompt), flags=re.S)
    return re.sub(r"`[^`\n]*`", " ", text)


def reads_as_read_only(words: str) -> bool:
    explicit = EXPLICIT_READ_ONLY.search(words)
    if BUILD_REQUEST.search(words) and not explicit:
        return False
    audit_only = bool(AUDIT_ONLY.search(words)) and not AUDIT_WITH_REPAIR.search(words)
    lifted = READ_ONLY_LIFTED.search(re.sub(r"go ahead and (?:audit|assess)\b", "", words, flags=re.I))
    return bool(explicit or READ_ONLY.search(words) or audit_only) and not lifted
