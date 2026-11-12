"""What a request or a path says about the work: read-only or not, audit, security, scale, code or prose, which language.

Patterns on wording, so they're best effort. docs/claude-code.md says what that means for each one.
"""

from __future__ import annotations  # the stock macOS python3 is 3.9

import itertools
import os
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
# "review-only" naming a kind of account or setting describes the code, not the request.
_THINGS = r"(?:role|user|mode|access|token|permission|flag|field)s?\b"
_NAMES_A_THING = r"(?!\s+" + _THINGS + ")"
READ_ONLY = re.compile(
    r"(?<![\w-])(review|plan|planning|audit)[- ]only\b" + _NAMES_A_THING +
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
    # "how we apply the changes" describes the work, it doesn't ask for it
    r"|\b(go ahead|you can (edit|change|fix)|feel free to (edit|change|fix)|(?<!\bwe )(?<!\bthey )(?<!\bhow )(?<!\bi )(?:make the (change|fix|edit)s?|apply (the|your) (change|fix|edit)s?))\b",
    re.I,
)
AUDIT_REQUEST = re.compile(r"\b(audit|deslop|vibe[- ]coded|ai[- ]generated (?:code|codebase|app)|clean ?up (?:this|the) (?:code|codebase|repo)|pay down)\b", re.I)
AUDIT_ONLY = re.compile(r"^\W*(?:(?:please|hey|ok|okay|can you|could you|would you|just|go ahead and|let'?s)\W+)*(?:audit|assess)\b(?!\s+(?:trail|log\w*|entries)\b|[- ]only\s+" + _THINGS + ")"
                        r"|\b(?:run|do|perform|conduct|want|need)\s+(?:an?\s+)?(?:\w+\s+){0,2}audit\b(?!\s+(?:trail|log\w*)\b)|^\W*what'?s wrong with\b", re.I)
AUDIT_WITH_REPAIR = re.compile(r"\b(?:fix(?:es|ing)?|repair\w*|clean(?:ing)? ?up|harden\w*|refactor\w*|deslop\w*|remediat\w*|resolve|rewrite|improve|update|implement|add|patch|change|make|build|create|write)\b", re.I)
# A request that opens by asking for work keeps its restrictions as restrictions. "Fix the bug. Don't change any APIs" isn't read-only.
BUILD_REQUEST = re.compile(r"(?:^|[.!?\n]\s*)(?:(?:please|can you|could you|would you|let'?s)\s+)*(?:fix|refactor|add|implement|write|build|create|update|change|remove|delete|rename|migrate|speed up|optimi[sz]e|make|improve|port|convert|clean up|harden)\b"
                           r"(?!\s+(?:nothing\b|no\b|up\b|an?\s+(?:plan|review|report|summary|analysis|audit|assessment)\b(?!-)))", re.I)
EXPLICIT_READ_ONLY = re.compile(r"(?<![\w-])(?<!\ba\s)(?<!\ban\s)(?:review|plan|planning|audit)[- ]only\b" + _NAMES_A_THING +
                                r"|\b(?:fix|change|touch|edit|modify|update)\s+nothing\b(?!\s+else)", re.I)
NOT_FROM_THE_USER = re.compile(r"\s*(<task-notification\b|<agent-message\b|<cross-session-message\b|Another Claude session sent a message)", re.I)
REVIEW_OR_PLAN = re.compile(r"\b(review|audit|pull request|merge|plan how|how would you (add|build|change)|architecture)\b", re.I)
# Security and money get a fresh reviewer: a missed defect there is a breach or a wrong charge, and the reviewer's one observed catch was on a money
# path (Opus, invoice-ledger-totals, a post-hoc probe on 2026-11-06). The rest of HIGH_CONSEQUENCE gets a self-review of the whole diff, which
# Superpowers measured as catching about as much as a review subagent at a fraction of the time (its v5.0.6 release notes). Unmeasured here.
_SECURITY_CRITICAL_WORDS = r"auth|authn|authz|oauth|login|sessions?|tokens?|passwords?|secrets?|credentials?|permissions?|acl|rbac|tenants?|tenancy|crypto|signatures?"
_MONEY_WORDS = r"billing|payments?|invoices?|checkout|refunds?|ledgers?"
_DATA_WORDS = r"migrations?|migrate|webhooks?"
SECURITY_CRITICAL = re.compile(rf"(^|[/_.\-])({_SECURITY_CRITICAL_WORDS})([/_.\-]|$)", re.I)
MONEY = re.compile(rf"(^|[/_.\-])({_MONEY_WORDS})([/_.\-]|$)", re.I)
HIGH_CONSEQUENCE = re.compile(rf"(^|[/_.\-])({_SECURITY_CRITICAL_WORDS}|{_MONEY_WORDS}|{_DATA_WORDS})([/_.\-]|$)", re.I)
# Over-matching only brings back the reviewer agent, which every high-consequence file got until 2026-11-06, so this errs wide.
ASKS_FOR_REVIEW = re.compile(r"\b(?:fresh|independent|second|separate|outside)[- ](?:review(?:er)?|look|opinion|pair of eyes)\b|\bcode[- ]?review(?:er|s)?\b"
                             r"|\bindependently reviewed\b|\b(?:a|the|another) reviewer\b|\breview(?:ed)?\s+(?:it\s+|this\s+|them\s+)?(?:with|by)\s+(?:a\s+|an\s+)?(?:sub)?agent\b"
                             r"|\b(?:get|have)\s+(?:it|this|that|them|the\s+(?:changes?|diff|code|fix|pr))\s+reviewed\b", re.I)
# A request naming security or money work loads the core skill, by the owner's decision of 2026-11-09; other work runs without it,
# and the edit hold still brings the core in for consequential files. Names count inside snake_case and CamelCase (`payment_service`,
# PaymentService), so a word ends at anything but a lowercase letter. Left out on purpose: "tokens" and "sessions", as often an LLM's or a
# terminal's as a login's; "checkout" after git; "migrate" for code or tools, as against a database migration; "subscriptions", as often
# a websocket's as a customer's.
_REQUEST_WORDS = (r"secur[a-z]*|vulnerab[a-z]*|xss|csrf|cve|(?<!dependency )(?<!dependency-)(?<!constructor )(?<!setter )injection|admins?|admin-only|administrators?"
                  r"|privileg[a-z]*|(?:session|auth|login|secure|httponly|samesite) cookies?|cookie flags?|httponly|samesite|bcrypt|argon2|authenticat[a-z]*|authori[sz][a-z]*|o?auth(?:[nz]|2)?|jwt|sso|saml|mfa|2fa|log[ -]?ins?|sign[ -]?(?:ins?|ups?)|passwords?|secrets?"
                  r"|credentials?|api[ _-]?keys?|permissions?|access control|rbac|acl|tenan[a-z]*|crypto[a-z]*|encrypt[a-z]*|decrypt[a-z]*"
                  r"|billing|payments?|invoic[a-z]*|(?<!git )checkout|refunds?|ledgers?|money|currenc[a-z]*|prices?|pricing|tax|taxes|vat|wallets?"
                  r"|migrations?|alembic|(?:add|drop|rename|remove)[a-z]* (?:a |an |the )?(?:new )?columns? (?:to|from|on|in) (?:the )?[a-z_]+ tables?|alter table|(?:schema|database|db|data|table)s? migrat[a-z]*|migrat[a-z]* (?:the |a |our )?(?:[a-z_]+ )?(?:schema|database|db|data|tables?)")
CONSEQUENTIAL_REQUEST = re.compile(rf"(?<![A-Za-z])(?i:{_REQUEST_WORDS})(?![a-z])")
# Paths whose edits wait for the core skill, by the owner's decision of 2026-11-09: auth, secrets, tenancy, money, pricing and migrations.
# A shell command writing one gets a note instead, since shell commands are held only for destructive actions.
# CONSEQUENTIAL_TEXT is the same work as the code says it: removing `@login_required` or editing `total_price` in app.py is still auth or money.
# It's the auth and money words of scale_notes.NOT_SMALL_TEXT, without its SQL, deletion, process, async and file-write words, which the owner
# chose to let go ahead, and without "session", which in code is as often a database's.
CONSEQUENTIAL_TEXT = re.compile(r"(?i:passw|secret|api_?key|credential|token(?!i[sz])|auth(?!or(?![ia]))|log(?:ged)?[ _]?ins?(?-i:(?![a-z]))|logout|cookie|csrf|permission|admin|is_staff|forbidden"
                                r"|crypt|price|pricing|amount|balance(?!r)|payment|invoice|refund|currency|tenant|billing|ledger|migrat)")
CONSEQUENTIAL_PATH = re.compile(r"auth(?!or(?![ia]))|login|logout|passw|secret|token(?!i[sz])|credential|permission|admin|rbac|(^|[/_.\-])(acl|iam|sso)([/_.\-]|$)|(?<!main)tenan|crypto"
                                r"|encrypt|secur|jwt|saml|signature|billing|payment|invoice|checkout|refund|pricing|wallet|subscription|ledger|migrat|alembic|schema", re.I)


def names_consequential_work(paths: list[str], written: str, entries: list[dict]) -> bool:
    """Auth, secrets, tenancy, money, pricing or migrations, by a path, a request this session named it in, or what an edit writes or removes
    (`written`, old and new together, since taking something out matters as much). Only this work waits for the core skill, by the owner's
    decision of 2026-11-09; async, SQL, deletion, performance and the rest go ahead on the rule card, since each hold costs a denied call."""
    if len(written) > scale_notes.CONSEQUENCE_CHARS:  # bounds the pattern's work, and an edit this large isn't ordinary anyway
        return True
    named = any(entry.get("kind") == "prompt" and entry.get("named") for entry in entries)  # judged on the whole prompt when it arrived
    return any(CONSEQUENTIAL_PATH.search(path) for path in paths) or named or bool(CONSEQUENTIAL_TEXT.search(written))


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
# The language skills are routed, not listed (disable-model-invocation), so a review, which makes no edit to show its language, finds
# its guidance from what the request names: the language, a tool only it uses, or a file's suffix. Bare "go" and "C" are ordinary
# words, and so are "react" and "spring", so they need company or a capital. A wrong match costs one pointer, about 200 characters,
# and adds to the project's languages rather than replacing them.
LANGUAGE_PROMPTS = {
    "occam-python": PYTHON_PROMPT,
    "occam-typescript": re.compile(r"(?i:\b(?:typescript|javascript|node\.?js|deno|npm|pnpm)\b|\breact(?:\.js|[- ](?:app|apps|component|components|hooks?|native|router|query|frontend))\b)|\bReact\b|\.(?:[mc]?[jt]s|[jt]sx)\b"),
    "occam-rust": re.compile(r"(?i:\brust\b)|\bcargo (?:build|test|run|check|clippy)\b|\bCargo\.toml\b|\.rs\b"),
    "occam-go": re.compile(r"\b(golang|goroutines?|go (?:code|module|service|package|program)s?)\b|\.go\b|\bgo\.mod\b", re.I),
    "occam-jvm": re.compile(r"(?i:\b(?:java|kotlin|gradle|jvm|maven)\b|\bspring[- ](?:boot|mvc|data|security)\b)|\.(?:java|kts?)\b"),
    "occam-cpp": re.compile(r"(?<![\w+])(?i:c\+\+|cpp|cmake)(?![\w+])|\b[Ii]n C\b(?![#+\\/]|:[\\/])|\bC (?:code|library|extension|program)s?\b|\.(?:c|h|cc|cpp|cxx|hpp|hh)\b"),
    "occam-sql": re.compile(r"\b(sql|postgres(?:ql)?|mysql|sqlite)\b|\.sql\b", re.I),
    "occam-shell": re.compile(r"\b(bash|zsh|shell ?scripts?)\b|\.(?:sh|bash|zsh)\b", re.I),
}
# A review that names no language gets the project's, from the files that declare one.
LANGUAGE_MARKERS = {
    "occam-python": ("pyproject.toml", "setup.py", "setup.cfg", "requirements.txt", "Pipfile"),
    "occam-typescript": ("package.json", "tsconfig.json"),
    "occam-rust": ("Cargo.toml",),
    "occam-go": ("go.mod",),
    "occam-jvm": ("pom.xml", "build.gradle", "build.gradle.kts"),
    "occam-cpp": ("CMakeLists.txt",),
}


def is_code(file_path: str) -> bool:
    if DEPENDENCY_MANIFEST.search(file_path):
        return True
    return Path(file_path).suffix.lower() not in DOC_SUFFIXES


# occam's typed commands name the request, so they read as its words: `/occam:review x` as review-only, and `/occam:audit x` as an audit,
# which stays read-only unless it asks for a fix. The colon keeps "review-only user.py" from reading as a kind of user.
_TYPED_COMMAND = re.compile(r"^\s*/occam:(review|audit)(?![\w:-])", re.I)
_COMMAND_WORDS = {"review": "review-only:", "audit": "audit"}


# Whether a typed command holds edits goes by its name, not by the free-text rules, because its arguments are mostly paths and those
# collide with them: `/occam:audit logging/` reads as an audit log, and `src/add.py` as asking to add. A review never edits. An audit
# edits only when its arguments, paths set aside, ask for a fix, as audit.md says.
_COMMAND_FIX = re.compile(r"\b(?:fix(?:es|ing)?|repair\w*|clean(?:ing)? ?up|harden\w*|remov\w*|delet\w*|deslop\w*|remediat\w*)\b", re.I)
_PATH_LIKE = re.compile(r"\S+")  # each word, kept unless it holds a / or a . (see _without_paths), so a long word can't go quadratic


def _unquoted(prompt: str) -> str:
    return re.sub(r"`[^`\n]*`", " ", re.sub(r"```.*?```", " ", scale_notes.without_pasted(prompt), flags=re.S))


def visible_prompt(prompt: str) -> str:
    """The user's own words, without pasted material or quoted code, with a typed occam command read as the request it names. Runs of
    blanks become one, which reads the same and keeps patterns that start at a line break from trying every one of a long run."""
    words = re.sub(r" ?\n\s*", "\n", re.sub(r"[ \t]+", " ", _unquoted(prompt)))
    return _TYPED_COMMAND.sub(lambda typed: _COMMAND_WORDS[typed.group(1).lower()], words, count=1)


def command_read_only(prompt: str) -> bool | None:
    """Whether a typed `/occam:review` or `/occam:audit` holds edits this turn, or None when the prompt isn't one."""
    text = _unquoted(prompt)
    typed = _TYPED_COMMAND.match(text)
    if not typed:
        return None
    return typed.group(1).lower() == "review" or not _COMMAND_FIX.search(without_denials(asked_to_do(_without_paths(text[typed.end():]))))


def _without_paths(text: str) -> str:
    return _PATH_LIKE.sub(lambda word: " " if "/" in word.group(0) or "." in word.group(0) else word.group(0), text)


# A denial names what not to do, so "Do not go ahead with edits", "you must not edit anything", "I'll make the changes myself" and "fix
# it later" can't read as leave to. It runs to the end of its clause: in "don't change the tests, fix the code" only the first half is denied.
_DENYING = (r"do not|don'?t|dont|never|no need to|not to|without|avoid(?:ing)?|shouldn'?t|should not|won'?t|will not|mustn'?t|must not|may not|can(?:'?t|not| not)|"
            r"under no circumstances|in no case|"
            r"(?:i|we) (?:don'?t|do not) want (?:you )?to|(?:it'?s |is )?not (?:okay|ok|allowed|permitted|authori[sz]ed) to")
_EDIT_VERBS = (r"go(?:ing)? ahead|fix\w*|implement\w*|repair\w*|apply\w*|chang\w*|edit\w*|writ\w*|touch\w*|modif\w*|mak\w*|remov\w*|delet\w*|"
               r"clean\w*(?: ?up)?|harden\w*|refactor\w*|patch\w*|updat\w*|add\w*|commit\w*|proceed\w*")
# A few words may sit between the denial and its verb ("Do NOT, under any circumstances, go ahead"), but not a new clause: "Let me know,
# then fix it" and "stop the leaks by fixing them" ask for the fix. "Later" defers only the few words before it.
# Only filler words between a denial and its verb ("Do NOT, under any circumstances, go ahead"): "without breaking anything, fix the bugs"
# asks for the fix.
_GAP = r"(?:(?:you|ever|any|under|circumstances|for|reason|this|stage|point|yet|now|please|really|actually|at|all|just|even|try|to|be|going|go|that)\W+){0,4}?"
_CLAUSE = r"(?:(?!\s(?:but|then|and|or|so)\b)[^.!?\n;,])*"  # to the end of the clause, which "but", "then" or "and" ends too
# What takes a go-ahead back, in its sentence after any "but": a denial right before it ("Do NOT, under any circumstances, go ahead", "don't
# go ahead or make the changes"); the person deciding ("once I've approved the plan, go ahead", "ask me before you make the changes",
# "wait for me to say go ahead"); someone else acting, unless it's a go-ahead naming the work ("I'll make the changes", "the team will
# make the changes", but "we'll go ahead and fix it" asks); a deferral after it ("go ahead later"); "go ahead and" a step that only reads;
# and for a bare go-ahead, one naming no work, a condition or a question ("If it looks fine, go ahead", "whether it's safe to go ahead").
# A limit or condition on a fix it names keeps it: "Without changing the API, go ahead and fix the bug", "If anything looks off, go ahead
# and fix it", "It's okay to go ahead and fix it", "No need to ask, just go ahead".
_DENIED_RIGHT_BEFORE = re.compile(rf"\b(?:{_DENYING}|stop)\W+{_GAP}(?:go(?:ing)? ahead\s+and\s+|(?:{_EDIT_VERBS})\b(?:\s+[\w'-]+){{0,3}}?\s+(?:or|nor)\s+)?$", re.I)
_I = r"(?:i|we)(?:'ve|'m|'d| have| am)?"
_SOMEONE_ELSE_DECIDES = re.compile(rf"\b(?:once|after|when(?:ever)?|until|till|if|before)\s+{_I}\s+(?:\w+\s+){{0,2}}?(?:approv|confirm|say|said|agree|sign|review|ok|give|decid|tell|let|seen|see|read|check)\w*\b"
                                   r"|\b(?:ask|tell|show|check with|confirm with)\s+(?:me|us)\s+(?:first\s+)?before\b|\bwait\s+(?:for|until)\s+(?:me|us|my|our|i|we)\b"
                                   r"|\blet\s+(?:me|us)\s+(?:see|review|read|check|look)\b|\bto\s+say\s+$", re.I)
_SOMEONE_ELSE_ACTS = re.compile(rf"\b(?:{_I}|(?!you\b)[a-z][\w-]*)(?:'ll| will| am going to|'m going to| is going to| are going to| should| would)\s+(?:\w+\s+)?(?:go(?:ing)? ahead\s+and\s+)?$", re.I)
_WE_WILL = re.compile(r"\bwe(?:'ll| will| are going to|'re going to)\s+(?:\w+\s+)?$", re.I)
_ASKED_ABOUT = re.compile(rf"\bwhether\b|\b(?:safe|okay|ok|wise|fine|allowed)\s+to\s+$|\b(?:if|unless|once|when)\b|\b(?:before|until|till)\s+{_I}\s+$", re.I)
_NAMES_THE_WORK = re.compile(rf"^\W*(?:and\s+|with\s+(?:the\s+|your\s+|these\s+|those\s+|all\s+)?)(?:{_EDIT_VERBS})", re.I)
_THEN_FIXES = (r"(?:\b(?:and|then)\s+(?:then\s+)?|,\s*)(?!(?:fixes|changes|edits|updates|patches|modifications|deletions|removals|rewrites|refactors|implementations)\b)"
               r"(?:fix|chang|edit|modif|refactor|repair|patch|implement|apply|remov|delet|rewrit|updat)\w*")  # "the bugs and fixes" names them
# "go ahead and look into it" asks for reading, unless a fix follows: "go ahead and look into it and fix the bug"
_ONLY_READS = re.compile(r"^\W*and\s+(?:audit|assess|read|look|review|check|go through|scan|explore|investigate|examine|inspect|study|analy[sz]e)\b"
                         rf"(?![^.!?;\n]*?{_THEN_FIXES})", re.I)
# Within its sentence: "go ahead later", "you can go ahead once I've had a look", not "so when we upload a file it doesn't crash"
_DEFERRED = (r"^(?:[^\w.!?;\n]+[\w'-]+(?:\.\w[\w'-]*)*){0,6}?[^\w.!?;\n]+(?:later|myself|ourselves|next (?:time|week|sprint)|tomorrow|after (?:my|our|the review)|in a follow-?up"
             r"|(?:when|until@ONCE@)\s+(?:i|we)(?:'ve|'m| have)?\s+(?:\w+\s+)?(?:had a look|looked|look (?:at|over|through) (?:it|this|that|the|your)|give (?:the|my) (?:word|go-ahead|ok)|approv\w*|review\w*|check(?:ed|s)?(?!\s+out)|seen|confirm\w*"
             r"|sign(?:ed|s)?\s+off|said|say|meet|discuss\w*)@AFTER@)\b")
_AFTER_A_LIFT = re.compile(_DEFERRED.replace("@ONCE@", "").replace("@AFTER@", r"|(?:after|once)\s+(?:i|we)\b"), re.I)
# After a go-ahead naming the work, "after I log in" can describe the bug, so only "after I've…" or a step of the person's defers it.
_AFTER_A_NAMED_LIFT = re.compile(_DEFERRED.replace("@ONCE@", "|after|once").replace("@AFTER@", r"|(?:after|once)\s+(?:i|we)(?:'ve| have)\b"), re.I)
# A go-ahead naming the work, asked as a request: "can you go ahead and fix it?", "why don't you go ahead and fix it?"
_ASKS_FOR_IT = re.compile(r"\b(?:can|could|would|will)\s+(?:you|we)\b|\bhow about\b|\bwhy (?:don'?t you|not)\b|\b(?:mind|please)\b", re.I)
_INSIDE_WHETHER = re.compile(r"\bwhether\b[^,;:]*$", re.I)  # "check whether I can make the changes", not "not sure whether it's a race, so go ahead"
_WILL = re.compile(r"(?:'ll| will| am going to|'m going to| is going to| are going to)\s+(?:\w+\s+)?(?:go(?:ing)? ahead\s+and\s+)?$", re.I)
_CONTRAST = re.compile(r".*\b(?:but|however|anyway|though)\b", re.I | re.S)
_LIFTS_READ = 64  # go-aheads looked at per prompt, which keeps one made of thousands of them fast


def _cancelled(words: str, lift: re.Match) -> bool:
    """Whether what's around a lifting phrase in its sentence takes it back (see _DENIED_RIGHT_BEFORE). The look back is bounded."""
    reach = max(0, lift.start() - 300)
    start = max(max(words.rfind(mark, reach, lift.start()) for mark in ".!?;\n") + 1, reach)
    before, after = words[start:lift.start()], words[lift.end():lift.end() + 120]
    contrast = _CONTRAST.match(before)
    before = before[contrast.end():] if contrast else before  # "I'm not sure if I agree, but go ahead and fix it"
    go_ahead = lift.group(0).lower() == "go ahead"
    bare = go_ahead and not _NAMES_THE_WORK.match(after)
    named = go_ahead and not bare  # "go ahead and fix it" asks for the work in its own words, so less around it takes it back
    end = re.search(r"[.!?\n]", after)
    if end and end.group(0) == "?" and (bare or not _ASKS_FOR_IT.search(before)):
        return True  # "should we go ahead with this PR?" and "can we go ahead with this PR?" ask; "can you go ahead and fix it?" asks for it
    if not named and _INSIDE_WHETHER.search(before):
        return True
    denial = _DENIED_RIGHT_BEFORE.search(re.sub(r"\bwhy\s+(?:don'?t|not)\b", " ", before[-160:], flags=re.I))  # "why don't you go ahead" asks
    acting = _SOMEONE_ELSE_ACTS.search(before) and (not named or _WILL.search(before) and not _WE_WILL.search(before))  # "I'll go ahead and make the changes"
    return bool(denial or acting or (_AFTER_A_NAMED_LIFT if named else _AFTER_A_LIFT).match(after) or _SOMEONE_ELSE_DECIDES.search(before) or go_ahead and _ONLY_READS.match(after)
                or go_ahead and _REPORT_WORK.match(after) or bare and _ASKED_ABOUT.search(before))


_DENIAL = re.compile(rf"\b(?:{_DENYING})\W+{_GAP}(?:{_EDIT_VERBS})\b{_CLAUSE}|\bstop\s+(?:{_EDIT_VERBS})\b{_CLAUSE}|\b(?:make\s+)?no\s+(?:code\s+)?(?:changes|edits|fixes)\b"
                     r"|\b(?:fix|change|touch|edit|modify|update|apply)\s+nothing\b(?!\s+else)"
                     rf"|\b(?:i|we)(?:'ll| will)\s+(?:\w+\s+){{0,2}}?(?:{_EDIT_VERBS})\b(?:\s+[\w'-]+){{0,6}}?\s+(?:myself|ourselves)\b"
                     rf"|\b(?:{_EDIT_VERBS})\b(?:\s+[\w'-]+){{0,2}}?\s+later\b", re.I)  # "fix it later", not "fix what could break later"
# A report, summary or plan is what an audit or review hands back, not a change to the code it read, and neither is what it's about.
_REPORT_NOUNS = r"report|summary|summaries|write-?up|findings|notes|plan|list|memo|analysis|assessment|review|checklist|results|recommendations|issues|observations|table"
WRITES_A_REPORT = re.compile(rf"\b(?:writ\w*|creat\w*|mak\w*|produc\w*|generat\w*|put|sav\w*|draft\w*|compil\w*|list\w*|record\w*)\s+(?:up\s+)?"
                             rf"(?:(?:a|an|the|your|my|our|its|all|these|those)\s+)?(?:(?:[\w-]+\s+){{0,2}}?(?:{_REPORT_NOUNS})s?\b|[\w./-]+\.(?:md|markdown|txt|rst)\b)"
                             # and what it's for, when that's a fix: "a plan to fix the bugs" is a plan, "recommendations for fixes" a list
                             r"(?:\s+(?:to|for|on|about)\s+(?:how\s+to\s+|what\s+to\s+)?(?:the\s+)?(?:fix\w*|repair\w*|address\w*|resolv\w*|handl\w*|clean\w* up)(?:\s+(?!and\b|then\b|but\b)[\w'-]+){0,3})?", re.I)
# "go ahead and write the findings to REVIEW.md" lets the report be written (asked_for_this_document), not the code changed
_REPORT_WORK = re.compile(rf"^\W*and\s+(?:{WRITES_A_REPORT.pattern}|add\s+(?:(?:your|the|my|these|those)\s+)?(?:[\w-]+\s+)?(?:{_REPORT_NOUNS})\b|summari[sz]\w*|document\w*)"
                          rf"(?![^.!?;\n]*?{_THEN_FIXES})", re.I)
_ABOUT_FIXES = re.compile(r"\b(?:what|which|things|everything|anything|issues?|bugs?|parts?|places?)\s+(?:\w+\s+){0,3}?(?:to (?:fix|change|improve|repair)|needs? (?:fixing|changing|work)|"
                          r"should (?:be fixed|change)|to be fixed)\b|\b(?:suggested|recommended|proposed|needed|possible|required|potential)\s+(?:fix|change|repair)(?:es|s)?\b"
                          r"|\b(?:fix|change)(?:es|s)? (?:needed|required|to make)\b|\b(?:propos\w*|suggest\w*|recommend\w*|outlin\w*)\s+(?:\w+\s+){0,2}?(?:fix|change|repair)(?:es|s)?\b"
                          r"|\b(?:(?:tell|show|teach)\s+(?:me|us)|explain|describe|suggest|outline)\s+(?:to\s+(?:me|us)\s+)?(?:how|what|where|which|why|whether)\b(?:\s+(?!and\b|then\b|but\b)[\w'-]+){0,8}", re.I)
# Applying them asks for them: "apply the suggested fixes" isn't about fixes the way "list the suggested fixes" is. Not "how we apply the changes".
_APPLIES_FIXES = re.compile(r"(?<!\bwe )(?<!\bthey )(?<!\bhow )(?<!\bhow to )(?<!\bhow you )\b(?:(?:apply|implement|make|carry out)\s+(?:(?:the|any|all|these|those|your|each)\s+)?"
                            r"(?:(?:suggested|recommended|proposed|needed|required|necessary)\s+)?(?:fix|change|repair|edit)(?:es|s)?(?:\s+(?:needed|required|suggested|recommended|proposed))?"
                            r"|(?:action|act on|address|apply|implement)\s+(?:the|all|these|those|your|its|each)\s+(?:recommendations|suggestions|findings))\b", re.I)
# A clause that says what some code does isn't asking for it: "the migration code that applies the fixes to old rows".
_DESCRIBES_CODE = re.compile(r"\b(?:that|which)\s+(?:(?:will|would|should|can|could|must|is|are)\s+)?(?:appl|mak|fix|chang|writ|add|updat|creat|remov|delet|patch|repair)\w*\b(?:\s+(?!(?:and|then|but|or)\b)[^\s.!?;,]+){0,10}", re.I)


def without_denials(words: str) -> str:
    return _DENIAL.sub(" ", words)


def asked_to_do(words: str) -> str:
    """What a request asks to have done to the code: without the report it asks for and what that report is about. A denial can only
    keep a hold, never make one, so it's taken out where a hold is lifted, not here: "don't touch the tests but fix the bugs" asks for a fix."""
    return _ABOUT_FIXES.sub(" ", WRITES_A_REPORT.sub(" ", _APPLIES_FIXES.sub(" repair ", _DESCRIBES_CODE.sub(" ", words))))


def reads_as_read_only(words: str) -> bool:
    explicit = EXPLICIT_READ_ONLY.search(words)
    asked_for = asked_to_do(words)
    if BUILD_REQUEST.search(asked_for) and not explicit:
        return False
    audit_only = bool(AUDIT_ONLY.search(words)) and not AUDIT_WITH_REPAIR.search(without_denials(asked_for))  # "do not fix the bugs" asks for none
    lifted = any(not _cancelled(words, lift) for lift in itertools.islice(READ_ONLY_LIFTED.finditer(words), _LIFTS_READ))
    return bool(explicit or READ_ONLY.search(words) or audit_only) and not lifted


# "Continue" carries on the task as it was, so it keeps that task's hold instead of reading as a new request. Narrow on purpose:
# a hold carried into a new task makes the agent redo work, so anything more than carrying on is read afresh.
CONTINUES = re.compile(r"^\W*(?:(?:ok(?:ay)?|thanks|thank you|great|good|please)\W+)*(?:continue|keep going|go on|carry on|resume|next|keep at it|more)"
                       r"(?:\s+(?:with\s+)?(?:the\s+|your\s+)?(?:review(?:ing)?|audit(?:ing)?|analysis|investigation|read-?through|rest(?:\s+of\s+(?:the\s+)?(?:review|audit|files|modules|code))?))?"
                       r"(?:\W+(?:please|then|thanks|(?:from )?where you (?:left off|stopped)))*\W*$", re.I)
# A plain yes, and nothing more: a condition, a hedge or a "no" anywhere ("Yes, but not yet", "Okay, don't", "Yes, and don't touch the
# tests") keeps the hold, and the person can say "go ahead". Wording rules for qualified answers kept letting a "no" through.
_YES_WORDS = r"yes|yeah|yep|yup|sure|ok(?:ay)?|go ahead|go for it|do it|please do|approved?|lgtm|sounds good|absolutely|of course|please|thanks|thank you|recommended"
_PLAIN_YES = re.compile(rf"^\W*(?:yes|yeah|yep|yup|sure|ok(?:ay)?|go ahead|go for it|do it|please do|approved?|lgtm|sounds good|absolutely|of course)"
                        rf"(?:\W+(?:{_YES_WORDS}|(?:fix|apply|implement|make) (?:it|them|these|those|the (?:fix|change|edit)e?s?)(?: all| all of them)?))*\W*$", re.I)


def approves(tool_name: str, tool_input: dict, tool_response) -> bool:
    """A person approving the work: a plan accepted, or a plain yes to a question that asked whether to change the code. Any other
    answer, or one that can't be read, isn't approval, so a review-only turn stays held and the person can say "go ahead"."""
    if tool_name == "ExitPlanMode":
        return True
    for answers in (tool_input.get("answers"), tool_response.get("answers") if isinstance(tool_response, dict) else None):
        for question, answer in (answers.items() if isinstance(answers, dict) else ()):
            if isinstance(question, str) and isinstance(answer, str) and len(answer) <= 120 and asks_to_change(question) and _PLAIN_YES.match(answer):
                return True
    return False


# Where a request asks for a document to be written: a path in the dozen words after a writing verb. "Follow CONTRIBUTING.md and write a
# report" or "write a report using the format in docs/fmt.md" names a file to read, not to change. Read word by word, so it stays linear.
# Asking to write, not saying something was written: "was written up in DESIGN.md" or "the recently updated GUIDE.md" names a file to read.
# Asking, so the verb's plain form only: "the steps for creating a release in README.md" or "everything this PR adds" describes.
_WRITE_VERB = re.compile(r"\b(?:write|save|put|create|draft|record|store|output|dump|add|append|update)\b(?!\s+(?:nothing|none|no)\b)", re.I)
_POLITE_ASK = re.compile(r"\b(?:can|could|would|will)\s+you\s+(?:(?:please|also|just|kindly)\s+){0,2}$", re.I)
# "the functions we add", "the update in docs/setup.md": a subject or an article before the verb describes, it doesn't ask
_DESCRIBED = re.compile(r"\b(?:we|they|i|he|she|it|who|which|that|the|an?|this|each|every|any)\s+$|(?<!\bcan )(?<!\bcould )(?<!\bwould )(?<!\bwill )\byou\s+$"
                        r"|\b(?:whether|if\s+(?:the|this|that|these|those|any|all|each|every|its|our|their)\b)[^,;.!?]*$", re.I)
_DOCUMENT = re.compile(r"\.(?:md|markdown|txt|rst|adoc)$", re.I)
_FOLLOWS = {"following", "follow", "template", "style", "format", "guidelines", "guide", "per", "according", "based", "like", "conventions"}
_FOLLOWS_RIGHT_BEFORE = {"from", "using", "see", "read"}
# Files that steer agents or builds: a new one isn't a report, whatever the request said.
_NOT_A_REPORT = re.compile(r"(?:^|/)(?:CLAUDE|AGENTS|GEMINI|SKILL|CONVENTIONS|CMakeLists)(?:\.[\w-]+)*\.\w+$|(?:^|/)\.(?:cursor|github|claude|windsurf|clinerules)", re.I)


def _write_targets(prompt: str) -> set[str]:
    text, paths = without_denials(prompt), set()
    for verb in _WRITE_VERB.finditer(text):
        words = text[verb.end():verb.end() + 240].split()[:12]
        sentence_end = re.search(r"[.!?\n](?=\s|$)", text[verb.end():verb.end() + 400])
        just_before = text[max(0, verb.start() - 40):verb.start()]
        if _DESCRIBED.search(just_before) or sentence_end and sentence_end.group(0) == "?" and not _POLITE_ASK.search(just_before):
            continue  # "did this add anything that isn't documented in API.md?" asks about it; "Can you write it to REVIEW.md?" asks for it
        for index, word in enumerate(words):
            token = word.lstrip("`'\"<>([{").rstrip("`'\"<>)]},;:!?.").replace("\\", "/")
            if not _DOCUMENT.search(token):
                continue
            before = [each.lower().strip(",") for each in words[:index]]
            if not (set(before) & _FOLLOWS or before[-1:] and before[-1] in _FOLLOWS_RIGHT_BEFORE):
                token = token[2:] if token.startswith("./") else token
                if not token.startswith("../"):
                    paths.add(os.path.normpath(token).lower())
            break
    return paths


def asked_for_this_document(relative: str, absolute: str, prompt: str, new: bool, suffixes: set[str]) -> bool:
    """On a review-only turn, the request asked for this document: it asks for it to be written by its path in the project or its full
    path (a bare name only for a file at the top of the project, not one of the same name in another folder), or it asks for a report
    without naming one and this is a new Markdown file, so nothing that exists changes."""
    if os.path.splitext(relative)[1].lower() not in suffixes:
        return False
    named = _write_targets(prompt)
    if new and not named and WRITES_A_REPORT.search(prompt) and os.path.splitext(relative)[1].lower() in (".md", ".markdown", ".rst") and not _NOT_A_REPORT.search(relative):
        return True
    return os.path.normpath(relative).lower() in named or os.path.normpath(absolute).lower() in named


# "Shall I implement it?" "No." An agent going ahead anyway is a widely shared complaint (Hacker News, March 2026, 1,563 points).
# A bare "no" is only a refusal after a question that asks, as its own verb, to do work. After "Should I keep the old API?" or
# "Should I wait for your review before I commit?" a "no" means go ahead, so the verb has to come straight after the asking words.
_WORK_VERBS = (r"(?:implement|apply|make|proceed|go ahead|start|fix|change|edit|write|add|update|commit|push|create|build|refactor|remove|"
               r"delete|rename|migrate|patch|replace|rewrite|continue|install|deploy|merge|do (?:it|that|this|so|the)|"
               r"open (?:a |the )?(?:pr|pull request|merge request)|take care of|handle (?:it|that|this))\b")
_ASKING = r"\b(?:(?:shall|should|can|may) (?:I|we)|(?:do you want|would you like|want) me to|ok(?:ay)? (?:if I|to|for me to)|ready (?:for me )?to)"
_ASKS_TO_DO = re.compile(rf"(?:{_ASKING}\s+|^\s*)(?:(?:now|just|then|quickly|go ahead and)\s+)*" + _WORK_VERBS + rf"|{_ASKING}\s*\?$", re.I)
# A step before or beside the work: after "Should I create a branch first?" a "no" means skip it and carry on.
_EXTRA_STEP = re.compile(r"\b(?:first|before|beforehand|after each|too|also|as well|additionally|in addition)\b", re.I)
_DECLINE = r"(?:no|nope|nah|not yet|not now|not right now|no thanks|no thank you|don'?t|do not|hold off|hold on|wait|stop|never ?mind)"
# Free words in a tail can't be work verbs, so "no, just tell me why and then fix it" stays a request.
_FREE_WORD = r" (?!(?:fix|add|implement|change|update|write|make|build|create|remove|delete|use|apply|commit|push|then|and|but|instead)\b)[\w'-]+"
_DECLINE_TAIL = (rf"(?:{_DECLINE}|thanks|thank you|please|for now|not that|(?:just )?leave it(?: as(?: it)? is| alone| for now)?|i don'?t want (?:that|it|this)|"
                 r"keep it(?: as(?: it)? is)?|i'?ll (?:do|handle|take care of) it(?: myself)?|let'?s (?:talk|discuss)(?: it| this| that)?(?: first)?|"
                 rf"(?:just|only) (?:explain|answer|tell me|describe|show me)(?:{_FREE_WORD}){{0,6}}|that'?s (?:fine|ok(?:ay)?)|it'?s fine|"
                 r"(?:do not|don'?t) (?:change|touch|implement|do|edit|make|apply|fix)(?: (?:it|that|this|them|anything|any of it|the change|yet|now|for now|just yet)){0,2})")
REFUSAL = re.compile(rf"^\W*{_DECLINE}(?:\W+{_DECLINE_TAIL})*\W*$", re.I)
REFUSAL_LENGTH = 120  # a bare refusal is short, and the bound keeps the pattern's backtracking small

# A request that could want a report, summary or notes file written. Generous on purpose: missing a hold costs less than a wrong one.
ASKS_FOR_A_DOCUMENT = re.compile(r"\b(?:report|summar\w*|write[- ]?up|notes|document\w*|docs?|changelog|readme|markdown|status|progress)\b|\.(?:md|txt)\b", re.I)
# The names agents give their own progress reports: upper case, Markdown, with a report word. Narrower than the scanner's `ai-report-file`
# lead on purpose, since a wrong hold makes the agent write a real document twice: docs/workflow.md, REVIEW_CHECKLIST.md and test fixtures stay out.
WORK_REPORT_NAME = re.compile(r"(?:^|/)(?:[A-Z0-9-]+_)*(?:SUMMARY|REPORT|COMPLETED?|COMPLETION|PROGRESS|STATUS)\.md$")
NOT_A_WORK_REPORT = re.compile(r"(^|/)(tests?|testing|spec|__tests__|fixtures?|testdata|golden|\.github)/|(^|/)src/SUMMARY\.md$", re.I)


def _last_question(message: str) -> str:
    tail = (message or "")[-2000:].rstrip("*_` \t\r\n")[-400:]
    if not tail.endswith("?"):
        return ""
    question = re.split(r"(?<=[.!?])\s+|\n+", tail)[-1]
    return "" if re.search(r"\bor\b", question, re.I) or _EXTRA_STEP.search(question) else question


def asks_to_act(message: str) -> bool:
    """The message ends by asking whether to go ahead with work. An either-or question doesn't count, since "no" doesn't pick one."""
    question = _last_question(message)
    return bool(question and _ASKS_TO_DO.search(question))


# Asking to change the code, as against asking to go on reviewing or to write up what was found: "Shall I continue with the rest?" or
# "Should I put the findings in REVIEW.md?" asks about the review, so a yes or a "continue" to it doesn't lift a review-only hold.
_CHANGE_VERBS = (r"(?:implement|apply|fix|change|edit|patch|refactor|rewrite|update|remove|delete|rename|migrate|commit|address|resolve|correct|"
                 r"make (?:the|these|those|that|this|all|any)?\s*(?:change|fix|edit)s?)\b")  # not "proceed" or "go ahead", which can mean the review
_ASKS_TO_CHANGE = re.compile(rf"(?:{_ASKING}\s+|^\s*)(?:(?:now|just|then|quickly|go ahead and|continue and|keep going and)\s+)*(?:{_CHANGE_VERBS}"
                             r"|(?:go ahead|proceed|carry on|continue)\s+with\s+(?:(?:the|these|those|all|my|your|them)\s+)?(?:\w+\s+){0,2}?(?:fix|change|edit|patch|refactor|rewrite|implementation)(?:es|s)?\b)", re.I)
# Editing the write-up itself isn't changing the code: "Should I update the report?" "Shall I edit the summary?"
# Changing the write-up itself isn't changing the code: a rewording verb right before it ("Should I update the plan to include the
# migration?", "commit the review notes", "rename the report file"), text in it ("fix the typo in the report", "remove the duplicate
# finding from the report"), changes made to it ("make these changes to the report") or a document named ("Should I update REVIEW.md?").
# Fixes it lists are the code's: "apply the fixes from the review", "fix the bugs listed in the report", "fix the items on the checklist".
_WRITE_UP = (r"(?:review\s+|audit\s+)?(?:report|review|summary|notes|write-?up|plan|analysis|checklist|todo(?:\s+list)?|readme|docs|documentation|changelog)\b"
             r"(?!\s+(?:generator|module|code|builder|service|parser|function|class|endpoint|script|api|page|template|job|tool|field|column|attribute|property|model|table|schema|build)s?\b)")
_DOCUMENT_NAMED = r"[\w./-]+\.(?:md|markdown|txt|rst|adoc)\b"
_THE = r"(?:(?:the|this|that|my|your|our|a|an|these|those|any|all)\s+)?"
_EDITS_THE_REPORT = re.compile(rf"\b(?:update|edit|change|rewrite|revise|reword|add\s+to|commit|rename|shorten|expand|reorder|reformat)\s+{_THE}(?:{_WRITE_UP}|{_DOCUMENT_NAMED})"
                               rf"|\b(?:fix(?:\s+up)?|correct|tidy(?:\s+up)?|polish)\s+{_THE}(?:{_WRITE_UP}|{_DOCUMENT_NAMED})(?:\s+(?:wording|document|doc|file|text|formatting|layout|title|headings?))?\s*(?:[?.!,;]|$)"
                               r"|\b(?:update|edit|rewrite|revise|reword|add\s+to)\s+" + _THE + r"(?:review\s+|audit\s+)?findings\b"
                               rf"|\b(?:fix|correct|remove|delete|add|update|edit|change|rewrite|reword|move)\s+{_THE}(?:[\w-]+\s+)?(?:typos?|wording|formatting|spelling|grammar|sections?|headings?|titles?"
                               rf"|sentences?|paragraphs?|lines?|entr(?:y|ies)|links?|tables?|numbers?|dates?|intro\w*|conclusions?)\s+(?:in|to|from|of|on|into)\s+{_THE}(?:{_WRITE_UP}|findings\b|{_DOCUMENT_NAMED})"
                               # a finding is the write-up's to remove or move, the code's to fix: "remove the duplicate finding from the report"
                               rf"|\b(?:remove|delete|add|move|reword|rewrite|merge)\s+{_THE}(?:[\w-]+\s+)?findings?\s+(?:in|to|from|of|on|into)\s+{_THE}(?:{_WRITE_UP}|{_DOCUMENT_NAMED})"
                               rf"|\b(?:make|apply|proceed\s+with|go\s+ahead\s+with)\s+{_THE}(?:changes|edits|corrections)\s+to\s+{_THE}(?:{_WRITE_UP}|{_DOCUMENT_NAMED})", re.I)
# A question that defers or empties the change isn't asking to make it: "Should I fix them later?", "Should I change nothing for now?"
_DEFERS = re.compile(r"\b(?:later|afterwards|follow-?up|next (?:time|week|sprint|release)|tomorrow|for now|eventually|separately|another time|"
                     r"(?:after|once|when|until)\s+(?:you|i|we|ci|it'?s|the (?:review|release|merge|tests?|build))\b|"
                     r"(?:fix|chang|apply|edit|touch|updat|implement|mak|do)\w*\s+(?:nothing|none)\b|none of\b|no changes\b|instead of (?:fix|chang|apply|edit)\w*|"
                     r"in (?:the|a|another) (?:next|separate|later|different|new|future|follow-?up) (?:pr|pull request|change|commit|branch|ticket|release|session)\b|"
                     r"after (?:lunch|the meeting|the break|standup))", re.I)


def asks_to_change(message: str) -> bool:
    question = _last_question(message)
    return bool(question and _ASKS_TO_CHANGE.search(question) and not _EDITS_THE_REPORT.search(question) and not _DEFERS.search(question))


def declines(words: str, asked_to_act: bool) -> bool:
    """A prompt that only says no, in answer to a question about doing work."""
    words = words.strip()
    return asked_to_act and len(words) <= REFUSAL_LENGTH and bool(REFUSAL.match(words))
