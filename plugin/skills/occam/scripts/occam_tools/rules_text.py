"""Rules that work on text in any language, plus lightweight structure for languages without a parser here."""

from __future__ import annotations

import ast
import bisect
import re
from typing import Iterable, NamedTuple

from .py_helpers import PLACEHOLDER_NAME, _has_sql
from .rules_shell import shell_findings
from .rules_config import CLIENT_VISIBLE_SECRET
from .source import C_FAMILY, DOCKERFILE, Source

JS = ("javascript", "typescript")
PY = ("python",)
BRACED = C_FAMILY
ALL = None
SQL_HOSTS = ("sql", "python", "javascript", "typescript", "go", "java", "kotlin", "csharp", "php", "ruby", "rust")


class TextRule(NamedTuple):
    rule: str
    languages: tuple | None
    pattern: re.Pattern
    view: str = "code"       # code, raw or comment
    tests: str = "skip"      # skip, include or only
    scripts: bool = True     # also applies under scripts/, examples/ and similar
    overrides: dict = {}     # severity or confidence that differ from the catalog for this pattern


def _r(rule, languages, pattern, view="code", tests="skip", flags=0, scripts=True, **overrides) -> TextRule:
    return TextRule(rule, languages, re.compile(pattern, flags), view, tests, scripts, overrides)


_I = re.I
_M = re.M
# Saying when deferred work comes due. Wording can't prove it. "when" alone is too common to count: "handle errors when reading" names no
# due date, so it has to open a later clause, as in the convention `<the limit>, <when to revisit>`.
_DUE_CLAUSE = re.compile(r",[^,]*\b(?:when|once|until|unless|after|before|if|above|past|beyond)\b", _I)
SHORTCUT_MARK = re.compile(r"^\W*shortcut:(?!\s*(?:ctrl|cmd|command|alt|shift|option)\b)", _I)


TEXT_RULES: list[TextRule] = [
    # Incomplete work
    _r("truncation-marker", ALL,
       # `...rest props go to the input` is about a spread. An elision stops there, or says what it left out.
       r"^\W*(?:\.{3}|…)\s*(?:rest|remaining|existing|other|previous|same)\b"
       r"(?:\W*$|\s+of\s+(?:(?:the|your|this)\s+)?\w+\W*$|\s+(?:of\s+)?(?:(?:the|your|this)\s+)?(?:code|file|function|implementation|logic|class|method|script|methods|functions)\b|.*\b(?:unchanged|omitted)\b|\s+as\s+(?:above|before)\b)"
       r"|^\W*(?:rest|remainder) of (?:the |your )?(?:code|file|function|implementation|logic|class|method|script)\b"
       r"|^\W*(?:existing|previous|remaining|unchanged|other) (?:code|implementation|logic|methods|functions)\s*(?:\.{3}|…|remains?|unchanged|here|goes|stays?|omitted|as before)?\W*$"
       r"|\bomitted for brevity\b|\b(?:your|add|put|insert) (?:your |more |the |actual )*(?:code|logic|implementation) here\b"
       r"|\bimplementation (?:goes|omitted|left as)\b|\bleft as an exercise\b",
       view="comment", tests="include", flags=_I),
    _r("placeholder-comment", ALL,
       r"\b(?:TODO|FIXME|XXX|HACK)\b[^\n]*\b(?:implement|finish|complete|real|actual|replace|properly)\b"
       r"|\bin an? (?:real|production|full|complete|actual)[- ](?:app|application|implementation|system|environment|scenario|world|version|deployment)\b"
       r"|\bplaceholder\b|\bsimplified (?:version|implementation|logic|approach)\b"
       r"|\bnot (?:yet )?implemented\b|\bdummy (?:implementation|data|value)\b"
       r"|\bmock(?:ed)? (?:implementation|data|response)\b|\bhard-?coded for\b"
       r"|\bwould (?:normally|typically)\b|\bnormally (?:you|we|this) would\b"
       r"|\btemporary (?:fix|solution|workaround|hack)\b|\bquick (?:fix|hack)\b",
       view="comment", flags=_I),
    _r("placeholder-comment", ALL, r"\bfor now\b|\bshould be replaced\b|\bshould (?:ideally|really)\b", view="comment", flags=_I, confidence="low"),
    _r("stub-raise", JS, r"""throw\s+new\s+\w*Error\(\s*["'`](?:not\s+implemented|todo|unimplemented)""", view="raw", flags=_I),
    _r("stub-raise", ("rust",), r"\b(?:unimplemented|todo)!\s*\("),
    _r("stub-raise", ("go",), r"""\bpanic\(\s*["'`](?:not\s+implemented|todo|unimplemented)""", view="raw", flags=_I),
    _r("stub-raise", ("java", "kotlin", "scala"), r"""UnsupportedOperationException\(\s*["'](?:not\s+implemented|todo)""", view="raw", flags=_I),
    _r("stub-raise", ("kotlin",), r"\bTODO\s*\("),
    _r("stub-raise", ("csharp",), r"\bNotImplementedException\b"),
    _r("stub-raise", ("swift",), r"""\bfatalError\(\s*["'](?:not\s+implemented|todo|unimplemented)""", view="raw", flags=_I),
    _r("fake-success", JS,
       r"(?:function\s+|const\s+|async\s+function\s+)(?:verify|validate|authenticate|authorize|isValid|isAuthenticated|isAuthorized|isAllowed|hasPermission|checkAuth|checkPermission|checkAccess)\w*"
       # Given nothing, it had nothing to ignore: `const validateForm = () => { return true; }` is a stub of something else.
       r"(?:\s*:[^=\n]*)?(?:\s*=\s*(?:async\s+)?(?:function\b[^(\n]*)?)?(?:\(\s*[^)\s][^)\n]*\)|[A-Za-z_$][\w$]*\s*(?==>))"
       r"[^{\n]*\{\s*return\s+true;?\s*\}"),
    _r("fake-data", ALL, r"\b(?:MOCK|FAKE|DUMMY|STUB)_[A-Z][A-Z_]+\b", scripts=False),
    _r("fake-data", ALL, r"""["'](?:John Doe|Jane Doe|test@test\.com|foo@bar\.com|lorem ipsum[^"']*)["']""", view="raw", flags=_I, scripts=False),

    # Security
    _r("tls-disabled", ALL,
       r"\brejectUnauthorized\s*:\s*false\b|\bInsecureSkipVerify\s*:\s*true\b"
       r"|NODE_TLS_REJECT_UNAUTHORIZED|CURLOPT_SSL_VERIFYPEER\s*,\s*(?:0|false)\b|\bssl\._create_unverified_context\b"
       r"|\bcheck_hostname\s*=\s*False\b|\b(?:verify_mode|cert_reqs)\s*=\s*(?:ssl\.)?CERT_NONE\b(?!\s*,)|\bdanger_accept_invalid_certs\(\s*true\b"
       r"|\bTrustAllCerts\b|\bcurl\b[^\n|]*(?:\s-[a-zA-Z]*k\b|\s--insecure\b)", view="code"),
    # `verify=False` is only TLS on an HTTP client: the Python rules can see the call, and `session.verify = False` says so here.
    _r("tls-disabled", PY, r"\b(?:s|(?:session|sess|client|http|requests)\w*)\.verify\s*=\s*False\b", flags=_I),
    _r("jwt-unverified", ALL, r"""verify_signature["']?\s*:\s*False|\balgorithms?\s*[=:]\s*\[?\s*["']none["']|jwt\.decode\([^)\n]*verify\s*=\s*False""", view="raw", flags=_I),
    _r("sql-injection", ("go",), r"""\.(?:Query|QueryRow|Exec)(?:Context)?\((?:\w+,\s*)?(?:fmt\.Sprintf\(|"[^"\n]*"\s*\+)""", view="raw"),
    _r("sql-injection", ("java", "kotlin", "scala", "csharp"), r"""(?:executeQuery|executeUpdate|prepareStatement|createQuery|ExecuteReader|ExecuteNonQuery)\(\s*"[^"\n]*"\s*\+""", view="raw"),
    _r("sql-injection", ("rust",), r"""\.(?:execute|query)\(\s*&?format!\(""", view="raw"),
    _r("sql-injection", ("ruby",), r"""\.(?:where|find_by_sql|execute)\(\s*"[^"\n]*#\{""", view="raw"),
    _r("sql-injection", ("php",), r"""(?:mysqli_query|->query)\([^)\n]*\$_(?:GET|POST|REQUEST)""", view="raw"),
    _r("dynamic-eval", JS + ("php", "ruby"), r"(?<![\w.])eval\s*\(|\bnew\s+Function\s*\("),
    # A bare exec, or child_process's. `RE.exec(...)` runs a regex and `db.exec(...)` runs SQL.
    _r("shell-injection", JS, r"""(?<![\w.])(?:child_process\.|childProcess\.|cp\.)?exec(?:Sync)?\(\s*(?:`[^`\n]*\$\{|["'][^"'\n]*["']\s*\+)""", view="raw"),
    _r("shell-injection", ("go",), r"""exec\.Command\(\s*"(?:sh|bash)"\s*,\s*"-c\"""", view="raw"),
    _r("shell-injection", ("java", "kotlin"), r"Runtime\.getRuntime\(\)\.exec\("),
    _r("shell-injection", ("rust",), r"""Command::new\(\s*"(?:sh|bash)"\s*\)""", view="raw"),
    _r("shell-injection", ("c", "cpp"), r"(?<![\w.])system\s*\("),
    _r("shell-injection", ("php",), r"\b(?:shell_exec|passthru|system|popen)\s*\("),
    _r("xss-sink", ("javascript", "typescript", "html"), r"""\.(?:innerHTML|outerHTML)\s*=(?!=)(?!\s*(?:"[^"\n]*"|'[^'\n]*')\s*(?:;|$))|dangerouslySetInnerHTML|document\.write\(|\bv-html=|\{@html\b""", flags=re.M),
    _r("xss-sink", PY, r"\bmark_safe\(|\bMarkup\("),
    _r("weak-crypto", JS, r"""createHash\(\s*["'](?:md5|sha1)["']""", view="raw"),
    _r("weak-crypto", ("java", "kotlin", "scala"), r"""getInstance\(\s*"(?:MD5|SHA-?1)"\s*\)""", view="raw"),
    _r("weak-crypto", ("go",), r"\b(?:md5|sha1)\.(?:New|Sum)\b"),
    _r("insecure-random", JS, r"(?i:token|secret|password|session|nonce|salt|otp)\w*[^\n]{0,60}Math\.random\(\)|Math\.random\(\)[^\n]{0,60}(?i:token|secret|password|nonce|salt)"),
    _r("permissive-cors", ALL,
       r"""Access-Control-Allow-Origin["']?\s*[:,]\s*["']\*|\borigin\s*:\s*["']\*["']|\ballow_origins\s*=\s*\[\s*["']\*"""
       r"""|\bCORS_(?:ORIGIN_ALLOW_ALL|ALLOW_ALL_ORIGINS)\s*=\s*True\b|\bALLOWED_HOSTS\s*=\s*\[\s*["']\*""", view="raw"),
    _r("debug-exposed", ("python", "javascript", "typescript"), r"^[ \t]*DEBUG\s*=\s*True\b|\.run\([^)\n]*\bdebug\s*=\s*True|\bapp\.debug\s*=\s*True\b|\bintrospection\s*[:=]\s*[Tt]rue\b", flags=_M, scripts=False),
    _r("mock-in-production", PY, r"^[ \t]*(?:from unittest(?:\.mock)? import\b[^\n]*\b(?:mock|Mock|MagicMock|patch)\b|import unittest\.mock\b|from mock import\b|import mock\b)", flags=_M, scripts=False),
    _r("test-detection-in-code", PY, r"""["']pytest["']\s+in\s+sys\.modules|PYTEST_CURRENT_TEST|["']unittest["']\s+in\s+sys\.modules""", view="raw", scripts=False),
    _r("test-detection-in-code", JS, r"""process\.env\.NODE_ENV\s*[!=]==?\s*["']test["']|JEST_WORKER_ID|process\.env\.VITEST\b|typeof\s+(?:jest|describe)\s*[!=]==?""", view="raw", scripts=False),
    _r("test-detection-in-code", ("go",), r"""\btesting\.Testing\(\)|flag\.Lookup\("test\.v"\)""", view="raw", scripts=False),
    _r("log-injection", JS, r"\bconsole\.(?:log|info|warn|error)\([^)\n]*\breq\.(?:body|query|params|headers)\b|\blogger\.\w+\([^)\n]*\breq\.(?:body|query|params|headers)\b"),
    _r("open-redirect", JS, r"\bres\.redirect\(\s*(?:\d+\s*,\s*)?req\.(?:query|body|params)\b"),
    _r("mass-assignment", JS, r"\.(?:create|update|updateOne|findByIdAndUpdate|findOneAndUpdate|insertOne)\(\s*(?:[^,()\n]*,\s*)?req\.body\s*[,)]|\bnew\s+[A-Z]\w*\(\s*req\.body\s*\)|\bObject\.assign\(\s*\w+\s*,\s*req\.body\s*\)"),
    _r("mass-assignment", PY, r"""^[ \t]*fields\s*=\s*["']__all__["']""" , view="raw", flags=_M, confidence="low"),
    _r("mass-assignment", ("ruby",), r"\bparams\.permit!"),
    _r("weak-path-check", ("python", "javascript", "typescript"), r"""\.replace\(\s*["']\.\./?["']\s*,\s*["']["']\s*\)""", view="raw"),
    _r("insecure-cookie", JS, r"""\bres\.cookie\((?![^)]*\bsecure\b)"""),
    _r("token-in-browser-storage", JS, r"""\b(?:localStorage|sessionStorage)\.setItem\(\s*["'`][^"'`\n]*(?i:token|jwt|secret|password|auth)""", view="raw"),
    _r("secret-in-client-bundle", ("javascript", "typescript", "html"), CLIENT_VISIBLE_SECRET.pattern, view="raw"),
    _r("llm-prompt-from-request", PY, r"""\b(?:prompt|content)\s*[=:]\s*f["'][^"'\n]*\{\s*(?:request|req)\.""", view="raw"),
    _r("llm-prompt-from-request", JS, r"""\b(?:prompt|content)\s*:\s*`[^`\n]*\$\{\s*req\.""", view="raw"),
    _r("format-string", ("c", "cpp"), r"\b(?:printf|syslog)\(\s*[a-z_]\w*\s*\)|\bfprintf\(\s*\w+\s*,\s*[a-z_]\w*\s*\)|\bsn?printf\(\s*\w+\s*,\s*(?:\w+\s*,\s*)?[a-z_]\w*\s*\)"),
    _r("hidden-cycle", PY, r"""^[ \t]+#[^\n]*\b(?i:circular|cycl\w*)\b[^\n]*\n[ \t]+(?:from\s+\S+\s+)?import\b|^[ \t]+(?:from\s+\S+\s+)?import\b[^\n]*#[^\n]*\b(?i:circular|cycl\w*)\b""", view="raw", flags=_M),
    _r("react-index-key", JS, r"\bkey=\{\s*(?:index|idx|i)\s*\}"),
    _r("effect-no-cleanup", JS, r"\buseEffect\(\s*(?:async\s*)?\(\s*\)\s*=>\s*\{(?:(?!\breturn\b)[^{}]|\{[^{}]*\}){0,400}?\b(?:setInterval|addEventListener|subscribe)\((?:(?!\breturn\b)[^{}]|\{[^{}]*\}){0,400}?\}\s*,"),
    _r("generic-link-text", ("javascript", "typescript", "html"), r""">\s*(?i:click here|read more|here|link|learn more)\s*</(?:a|button|Link)>""", view="raw"),
    _r("failure-reported-as-success", JS, r"""\bcatch\s*(?:\([^)]*\))?\s*\{[^{}]{0,200}\breturn\s*\{[^{}]{0,80}\b(?:success|ok)\s*:\s*true\b"""),
    _r("fallback-fake", JS, r"""\bcatch\s*(?:\([^)]*\))?\s*\{[^{}]{0,200}\breturn\s+\w*(?i:mock|fake|dummy|stub|sample|placeholder)\w*"""),
    _r("disabled-control", ALL,
       r"@csrf_exempt\b|\bWTF_CSRF_ENABLED\s*=\s*False\b"
       r"|\b(?:auth|authn|authz|security|csrf|ssl|tls|signature|validation)_?(?:enabled|required|check)\s*[:=]\s*(?:False|false|0)\b"
       r"|\bskip_?(?:auth|verification|validation|signature)\s*[:=]\s*(?:True|true|1)\b", flags=_I),
    _r("disabled-control", ALL, r"^nosec\b(?!\s*\S)", view="comment"),
    _r("path-traversal", PY, r"\b(?:open|send_file|FileResponse|os\.path\.join)\([^)\n]*\brequest\.(?:args|form|json|GET|POST|query_params|files)\b"),
    _r("path-traversal", JS, r"\b(?:readFile(?:Sync)?|sendFile|createReadStream)\([^)\n]*\breq\.(?:params|query|body)\b"),
    _r("ssrf", PY, r"\b(?:requests\.\w+|httpx\.\w+|urlopen)\([^)\n]*\brequest\.(?:args|form|json|GET|POST|query_params)\b"),
    _r("ssrf", JS, r"(?<![\w.])(?:fetch|axios\.\w+|got)\([^)\n]*\breq\.(?:params|query|body)\b"),
    _r("unsafe-c-string", ("c", "cpp"), r"(?<![\w.])(?:strcpy|strcat|sprintf|vsprintf|gets)\s*\("),
    _r("unsafe-c-string", ("c", "cpp"), r"""\bscanf\(\s*"%s""", view="raw"),
    _r("world-writable", ALL, r"\bchmod\s+(?:-R\s+)?(?:0)?777\b|\bchmod\([^)\n]*0o?777\b", view="code"),
    # `| python3 -m json.tool` and `| python3 -c ...` read the download as data, and only otherwise is it the program.
    _r("curl-pipe-shell", ("shell",), r"\b(?:curl|wget)\b[^\n|]*\|\s*(?:sudo\s+(?:-\S+\s+)*)?(?:\S*/)?(?:(?:(?:ba|z|da|k)?sh\b)|python[\d.]*(?![\w.])(?!\s+-[mc]\b))"),
    _r("curl-pipe-shell", ("shell",), r"""^[^#\n]*?(?:\b(?:ba|z|da|k)?sh\b|\beval\b|\bsource\b)[^;&|\n]{0,200}(?:<\(|\$\(|`)\s*(?:curl|wget)\b""", view="raw", flags=_M),

    # Error masking
    # Raw text, because a comment inside the block is the author saying why, and the code view blanks comments.
    _r("swallowed-exception", ("javascript", "typescript", "java", "kotlin", "scala", "csharp", "php", "swift"), r"\bcatch\s*(?:\([^)]{0,500}\))?\s*\{\s*\}", view="raw", tests="include"),
    _r("swallowed-exception", JS, r"\.catch\(\s*(?:\(\s*\w*\s*\)|\w+)\s*=>\s*(?:\{\s*\}|null|undefined)\s*\)", view="raw", tests="include"),
    _r("swallowed-exception", ("ruby",), r"\brescue\b[^\n]*\n\s*end\b"),
    _r("ignored-error", ("go",), r"\bif\s+err\s*!=\s*nil\s*\{\s*return\s+nil\s*\}|\b\w+\s*,\s*_\s*:?=\s*[\w.]+\("),
    _r("ignored-error", ("shell",), r"\|\|\s*true\b"),
    _r("ignored-error", ("rust",), r"\blet\s+_\s*=\s*[^;\n]+\?;|\.ok\(\);"),
    _r("panic-in-library", ("rust",), r"\.unwrap\(\)|\.expect\(|(?<![\w:])panic!\("),
    _r("panic-in-library", ("go",), r"(?<![\w.])panic\("),
    _r("panic-in-library", ("kotlin",), r"\w!!(?:\.|\s|$)", flags=_M),
    _r("suppression-comment", PY + ("shell", "ruby"), r"^(?:type:\s*ignore|noqa|pylint:\s*disable\S*|pragma:\s*no cover)[ \t]*$", view="comment", flags=_I),
    _r("suppression-comment", BRACED, r"(?:@ts-ignore|@ts-nocheck|eslint-disable(?:-next-line|-line)?|nolint(?::\w+)?)\s*(?:\*/)?[ \t]*$", view="comment"),
    _r("suppression-comment", ("rust",), r"#!?\[allow\(", confidence="low"),
    _r("suppression-comment", ("java", "kotlin"), r"@SuppressWarnings\b|@Suppress\b"),

    # Tests
    _r("test-skipped", BRACED, r"\b(?:it|test|describe)\.(?:skip|todo)\(|\bxit\(|\bxdescribe\(|\bt\.Skip(?:f|Now)?\(|#\[ignore\]|@Disabled\b|@Ignore\b", tests="only"),
    _r("test-focused", JS, r"\b(?:it|test|describe)\.only\(|\bfit\(|\bfdescribe\(", tests="only"),
    _r("test-tautology", BRACED, r"expect\(\s*(true|1)\s*\)\.toBe\(\s*\1\s*\)|\bassert(?:True)?\(\s*true\s*\)|\bassert!\(\s*true\s*\)|\bassertEquals\(\s*(\w+)\s*,\s*\2\s*\)", tests="only"),
    _r("test-sleep", BRACED, r"\btime\.Sleep\(|\bThread\.sleep\(|\bsetTimeout\(\s*r(?:esolve)?\b", tests="only"),

    # Bloat
    _r("debug-leftover", ALL, r"(?<!\w)breakpoint\(\)|\bpdb\.set_trace\(\)|\bipdb\.set_trace\(\)|^[ \t]*import i?pdb\b|^[ \t]*debugger\s*;?[ \t]*$|\bdbg!\(|\.printStackTrace\(\)", flags=_M, tests="include", scripts=False),
    _r("debug-leftover", JS, r"\bconsole\.(?:log|debug)\(", scripts=False),
    _r("debug-leftover", ALL, r"""\b(?:print|println|fmt\.Print(?:ln|f)?|System\.out\.print(?:ln)?|console\.log)\(\s*f?["'`](?:DEBUG|debug|here|HERE|>>>|XXX|---|TEST)\b""", view="raw", scripts=False),

    # Comments
    _r("ai-residue", ALL,
       r"^[\W_]*(?:here(?:'s| is) (?:the (?:updated|fixed|new|corrected|complete|refactored|final)|your)\b|as an ai\b"
       r"|i(?:'ve| have) (?:added|updated|changed|fixed|implemented|refactored|created|removed)\b|let me\b"
       r"|we(?:'ve| have) (?:added|updated|fixed|changed|refactored)\b|this (?:new|updated|fixed|improved|refactored) (?:function|code|version|method|implementation)\b"
       r"|sure[,!]|certainly[,!])",
       view="comment", flags=_I, confidence="high"),
    _r("ai-residue", ALL, r"^[\W_]*(?:(?:new|updated|changed|fixed|added|removed|modified|refactored)\s*:\s|(?:changed|updated|renamed|replaced) (?:from|the old)\b|note to (?:self|user|reviewer)\b|fix(?:ed)? for (?:the )?(?:user|bug)\b)",
       view="comment", flags=_I),
    _r("ai-residue", ALL, r"^[\W_]*(?:let'?s (?:add|create|implement|fix|update|now|first)\b|now (?:we|uses?|handles?|supports?|returns?)\b|the (?:fix|bug) (?:is|was)\b|step \d+\s*[:.)])",
       view="comment", flags=_I, confidence="low"),
    _r("ai-residue", ALL, "[✅❌⚠✨\U0001F680\U0001F389\U0001F525\U0001F527\U0001F4DD\U0001F4A1\U0001F6E0\U0001F449\U0001F50D\U0001F4CC]", view="comment"),

    # Naming
    _r("rest-verb-route", ALL,
       r"""(?:@\w+\.(?:get|post|put|delete|patch|route)|\bapp\.(?:get|post|put|delete|patch)|\brouter\.(?:get|post|put|delete|patch))\(\s*["'`]/(?:[\w/{}:<>-]*/)?(?:get|create|update|delete|fetch|add|remove|list)[A-Z_-]\w*""",
       view="raw"),

    # Performance and scale
    _r("select-star", SQL_HOSTS, r"\bSELECT\s+\*\s+FROM\b", view="raw", flags=_I, scripts=False),
    _r("not-in-subquery", SQL_HOSTS, r"\bNOT\s+IN\s*\(\s*SELECT\b", view="raw", flags=_I),
    _r("unbounded-write", ("sql",), r"^[ \t]*(?:DELETE\s+FROM\s+[\w.\"`]+|UPDATE\s+[\w.\"`]+\s+SET\s+[^;\n]*?)\s*;", flags=_I | _M),
    _r("unbounded-concurrency", JS, r"\bPromise\.all\(\s*[\w.]+\.map\(", tests="skip"),
    _r("unbounded-concurrency", ("go",), r"\bfor\b[^{\n]*\{\s*go\s+func\b"),
    _r("query-in-loop", JS, r"\bfor\s*\([^)]{0,500}\)\s*\{[^}]{0,400}?\bawait\s+[\w.]*(?:query|find\w*|fetch|save|update|axios\.\w+)\("),
    _r("missing-timeout", ("go",), r"\bhttp\.(?:Get|Post|PostForm|Head)\(|\bhttp\.DefaultClient\b"),
    _r("hardcoded-host", ALL, r"""["'`](?:https?://(?:localhost|127\.0\.0\.1|0\.0\.0\.0)(?:[:/"'`])|(?:localhost|127\.0\.0\.1|0\.0\.0\.0):\d+)""", view="raw", scripts=False),
    _r("absolute-path", ALL, r"""["'`](?:/Users/\w|/home/\w|[A-Z]:\\Users\\)""", view="raw", scripts=False),
    _r("a11y-missing", ("javascript", "typescript", "html"), r"<img\b(?![^>]*\balt=)[^>]*>|<div\b(?![^>]*\brole=)[^>]*\bonClick=", view="raw"),

    # Reinvention
    _r("handrolled-helper", JS, r"JSON\.parse\(\s*JSON\.stringify\("),

    # Language practice
    _r("deprecated-api", PY,
       r"\bdatetime\.utcnow\(|\butcfromtimestamp\(|\bpkg_resources\b|^[ \t]*import imp\b|\bdistutils\b|\bcollections\.(?:Mapping|MutableMapping|Iterable|Sequence|Callable)\b"
       r"|\bopenai\.(?:ChatCompletion|Completion)\.create\b|\bnp\.(?:float|int|bool|object)\b(?!\d)|\btf\.Session\(|\.assertEquals\(|\blogging\.warn\(|\blogger\.warn\(|\.iteritems\(\)"
       r"|^[ \t]*import (?:cgi|asyncore|asynchat|smtpd|nose)\b|^[ \t]*from (?:cgi|asyncore|asynchat|smtpd|nose)\b|\bpd\.np\b|\bdf\.append\(",
       flags=_M, tests="include"),
    _r("deprecated-api", JS, r"\bnew\s+Buffer\(|\.substr\(|\bcomponentWill(?:Mount|ReceiveProps|Update)\b|\burl\.parse\(|\bfs\.exists\(|\bcrypto\.createCipher\("),
    _r("deprecated-api", ("go",), r"\bioutil\.\w+|\brand\.Seed\(|\bstrings\.Title\("),
    _r("deprecated-api", ("java",), r"\bnew\s+(?:Integer|Long|Double|Boolean)\(|\bThread\.stop\(|\.finalize\(\)"),
    _r("deprecated-api", ("rust",), r"\btry!\("),
    _r("float-money", ("java", "kotlin", "csharp", "scala"), r"\b(?:double|float|Double|Float)\s+(?:price|amount|total|balance|cost|fee|tax)\w*", flags=_I),
    _r("float-money", ("sql",), r"\b(?:price|amount|total|balance|cost|fee|tax)\w*\s+(?:FLOAT|REAL|DOUBLE)\b", flags=_I),
    _r("async-foreach", JS, r"\.forEach\(\s*async\b", tests="include"),
    # Only when assigned: returning the promise, or passing it down a .then chain, is correct.
    _r("missing-await", JS, r"(?<![=!<>])=\s*(?:response|resp|res|r)\.(?:json|text|blob|arrayBuffer)\(\)(?!\s*\.(?:then|catch))", tests="include"),
    _r("ts-any", ("typescript",), r":\s*any\b|\bas\s+any\b|<any>"),
    _r("ts-double-cast", ("typescript",), r"""\bas\s+(?:unknown|any)\s+as\s+(?:[A-Z_({\['"`]|(?:string|number|boolean|bigint|symbol|object|never|void|null|undefined)\b)"""),
    _r("useless-except", JS, r"\bcatch\s*\(\s*(\w+)\s*\)\s*\{\s*throw\s+\1\s*;?\s*\}"),
    _r("go-defer-in-loop", ("go",), r"\bfor\b[^{\n]*\{[^{}]*?\bdefer\b"),
    _r("shell-unquoted-rm", ("shell",), r"""\brm\s+-[a-zA-Z]*[rf][a-zA-Z]*\s+(?:--\s+)?\$\w+"""),
    _r("structured-concurrency-escape", ("kotlin",), r"\bGlobalScope\."),
]


# Deliberately broad, since `query` keeps what this matches out of its output and a finding's evidence is withheld on it. What's worth a lead is _LIVE_TOKENS.
_SECRET_TOKENS = re.compile(
    r"\bAKIA[0-9A-Z]{16}\b|\bgh[pousr]_[A-Za-z0-9]{36,}\b|\bsk-(?:ant-|proj-)?[A-Za-z0-9_-]{24,}\b|\bxox[baprs]-[A-Za-z0-9-]{12,}\b"
    r"|-----BEGIN (?:RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----|\bAIza[0-9A-Za-z_-]{35}\b|\beyJ[A-Za-z0-9_-]{20,}\.eyJ[A-Za-z0-9_-]{20,}\."
)
# The logic of SECRET_SHAPES in plugin/hooks/occam_evidence.py, which can't import this: AWS's documented example isn't a key, an sk- token has a digit and a capital so a slug isn't one,
# and a private key has a body after its marker, written out or with its line breaks escaped. Old-style encrypted keys put two header lines first.
_LIVE_TOKENS = re.compile(
    r"\b(?:AKIA|ASIA)(?![0-9A-Z]*EXAMPLE)[0-9A-Z]{16}\b|\bgh[pousr]_[A-Za-z0-9]{36,}\b|\bgithub_pat_[A-Za-z0-9_]{22,}\b|\bglpat-[A-Za-z0-9_-]{20,}\b"
    r"|\bsk-(?:ant-|proj-)?(?=[A-Za-z0-9_-]*\d)[A-Za-z0-9_-]{24,}\b|\b[sr]k_live_[A-Za-z0-9]{16,}\b|\bxox[abprs]-[A-Za-z0-9-]{12,}\b|\bnpm_[A-Za-z0-9]{36}\b"
    r"""|-----BEGIN (?:[A-Z]+ )*PRIVATE KEY-----(?:\s|\\[nr]|["'+,])*(?:Proc-Type:[^\n]{0,80}\n(?:DEK-Info:[^\n]{0,120}\n)?\s*)?[A-Za-z0-9+/=]{20,}"""
    r"|\bAIza[0-9A-Za-z_-]{35}\b|\beyJ[A-Za-z0-9_-]{20,}\.eyJ[A-Za-z0-9_-]{20,}\."
)
_SECRET_DEFAULT = re.compile(r"""(?:getenv|environ\.get|process\.env\.\w{1,60}\s{0,4}\|\|)\(?\s{0,4}["']?[\w-]{0,60}(?:KEY|SECRET|TOKEN|PASSWORD|PASSWD|CREDENTIAL)[\w-]{0,60}["']?\s{0,4},?\s{0,4}["']([^"'\s]{8,200})["']""", re.I)
_URL_CREDENTIALS = re.compile(r"""\b[a-z][a-z0-9+.-]{0,20}://[^/\s:@"'`]{1,120}:([^@/\s"'`{}<>$%]{4,200})@[\w.-]{1,120}""", re.I)
_CREDENTIAL_WORD = r"password|passwd|pwd|secret|api[_-]?key|apikey|auth[_-]?token|access[_-]?token|private[_-]?key"
_ASSIGNS_LITERAL = r"""["']?\s{0,4}\]?\s{0,4}(?::\s{0,4}\w{1,40}\s{0,4})?(?::|=|:=|=>)\s{0,4}f?["']([^"'\s]{%d,200})["']"""
_SECRET_ASSIGN = re.compile(rf"""\b([\w.-]{{0,60}}(?:{_CREDENTIAL_WORD})\w{{0,60}}){_ASSIGNS_LITERAL % 6}""", re.I)
# `token` alone names too many things that aren't credentials, so its value has to look like one.
_TOKEN_ASSIGN = re.compile(rf"""\b[\w.-]{{0,60}}token{_ASSIGNS_LITERAL % 20}""", re.I)
_AUTH_HEADER = re.compile(r"""\b(?:Proxy-)?Authorization["']?\s{0,4}[:=,]\s{0,4}f?["'`](?:Bearer|Basic|token)\s+([A-Za-z0-9._~+/=-]{12,200})["'`]""", re.I)
_SHELL_ASSIGN = re.compile(rf"""^[ \t]*(?:export[ \t]+)?([A-Za-z0-9_]*(?:{_CREDENTIAL_WORD}|access[_-]?key|token)[A-Za-z0-9_]*)=([^\s"'$`{{(;|&<>]{{6,200}})(?=[\s;]|$)""", re.I | re.M)
# Named for what it describes, as in private_key_path or password_policy.
_DESCRIBES_A_CREDENTIAL = re.compile(r"(?:[_-](?i:path|file|dir|url|uri|name|arn|ttl|min|max|len|length|prefix|header|env|policy|regex|pattern|field)|[a-z0-9](?:Path|File|Dir|Url|URL|Uri|URI|Name|Arn|ARN|Ttl|TTL|Min|Max|Len|Length|Prefix|Header|Env|Policy|Regex|Pattern|Field))$")
_ENDS_IN_CREDENTIAL = re.compile(rf"(?:{_CREDENTIAL_WORD})$", re.I)
# What can't be a value yet, by its whole shape, since `$` or `%` or `test` inside a real password says nothing: `P@ss%w0rd99`, `Latest#2024`.
_NOT_A_SECRET = re.compile(
    r"\$\{|\$\(|^\$\w+$|(?-i:\$[A-Z_][A-Z0-9_]{2,})|#\{|\{[^{}\s]*\}|<\w[\w -]*>|%[sd(]"  # a template to fill in. One `$k` inside a value is just a character
    r"|\*{3}|x{4,}"                                                               # a mask
    r"|^(?:example|changeme|change_me|change-me|your|xxx|placeholder|dummy|fake|sample|redacted|replace)|^(?:test|secret|password|none|null|true|false)\d*$"
    r"|^(?:AKIA|ASIA)[0-9A-Z]*EXAMPLE$"                                           # AWS's documented key
    r"|^[a-z]+(?:[_.-][a-z]+)+$|^[A-Za-z_]+(?:\.[A-Za-z_]+)+$|(?-i:^[A-Z][A-Z0-9]*(?:_[A-Z][A-Z0-9]*)+$)"  # the name of something, or of an environment variable. A digit in every part reads as a value
    r"|^\.{0,2}/|^\w+://|^arn:"                                                   # where something is
    r"|^\^|\$$|\(\?|\\[dwsb]|\[[^\]]*-[^\]]*\]",                                  # a pattern
    re.I,
)
_IDENT = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
_NARRATION_START = re.compile(
    r"^(?:increment|decrement|loop (?:through|over)|iterate (?:over|through)|initiali[sz]e|create (?:a|an|the)|define (?:a|an|the)|import\b"
    r"|return(?:s|ing)? (?:the )?|set (?:the )?\w+ to|check (?:if|whether)|call(?:ing)?\b|get (?:the )?|print (?:the )?|add (?:the )?)",
    re.I,
)
_BANNER = re.compile(r"^\W*[=\-*#_~]{10,}\W*$|^\W*[=\-*#_~]{4,}\s*\w[\w ]*\s*[=\-*#_~]{4,}\W*$")
_DOC_COMMENT = ("///", "//!", "/**", "/*!")
_COMMENT_LEAD = re.compile(r"^[ \t]*(?://+|/\*+|\*+/?|#+!?|--+)\s?")
_LOOKS_LIKE_CODE = {
    "c_like": re.compile(r"[;{}][ \t]*$|^[ \t]*(?:if|for|while|return|const|let|var|function|func|fn|int|void|public|private|class|import)\b.*[({;]"),
    "hash": re.compile(r"^[ \t]*(?:def |class |if .*:$|for .*:$|while .*:$|return\b|import \w|from \w+ import|try:$|except\b.*:$|else:$|elif .*:$|\w+(?:\.\w+)*\(.*\)$|[\w.]+\s*=\s*\S)"),
}
_STOP_WORDS = {"the", "a", "an", "of", "to", "for", "in", "on", "and", "or", "with", "this", "that", "is", "it", "we", "by", "from", "at"}


def _visible(comment: str) -> str:
    return _COMMENT_LEAD.sub("", comment).strip()


def _view_text(source: Source, view: str) -> str:
    return source.text if view == "raw" else source.code


def text_findings(source: Source, is_test: bool, is_script: bool) -> Iterable[tuple]:
    """Yield (rule, line, message or None, overrides) for every text rule on this file."""
    language = source.language
    for rule in TEXT_RULES:
        if rule.languages is not None and language not in rule.languages:
            continue
        if (rule.tests == "skip" and is_test) or (rule.tests == "only" and not is_test) or (is_script and not rule.scripts):
            continue
        if rule.view == "comment":
            for line, comment in source.comments:
                if rule.rule == "ai-residue" and comment.startswith(_DOC_COMMENT):
                    continue  # published documentation can use any style it likes
                if rule.rule == "placeholder-comment" and SHORTCUT_MARK.search(_visible(comment)) and _DUE_CLAUSE.search(_visible(comment)):
                    continue  # a limit with a stated way out
                if rule.pattern.search(_visible(comment)):
                    yield rule.rule, line, None, rule.overrides
        else:
            for match in rule.pattern.finditer(_view_text(source, rule.view)):
                yield rule.rule, source.line_of(match.start()), None, rule.overrides
    yield from _secrets(source, is_test)
    if language in JS and not is_test:
        yield from _js_sql_findings(source)
    yield from _comment_shape(source, is_test)
    if language == "shell":
        yield from _shell_file_rules(source)
    if language in ("c", "cpp") and source.path.endswith((".h", ".hpp", ".hh")):
        for match in re.finditer(r"^[ \t]*using\s+namespace\s+\w+", source.code, re.M):
            yield "namespace-in-header", source.line_of(match.start()), None, {}


def has_secret_shape(text: str) -> bool:
    return bool(_SECRET_TOKENS.search(text) or _LIVE_TOKENS.search(text) or _URL_CREDENTIALS.search(text))


def has_secret_assignment(line: str) -> bool:
    return any(not _NOT_A_SECRET.search(match.groups()[-1]) for pattern in (_SECRET_ASSIGN, _SECRET_DEFAULT, _TOKEN_ASSIGN, _AUTH_HEADER) for match in pattern.finditer(line))


def _is_worth_a_lead(value: str, name: str = "secret") -> bool:
    """One word reads as a label or a setting, as in `"password": "required"`, unless it's long and what it's assigned to is the credential itself."""
    if _NOT_A_SECRET.search(value):
        return False
    return not value.isalpha() or (value.islower() and len(value) >= 12 and bool(_ENDS_IN_CREDENTIAL.search(name)))


def _looks_random(value: str) -> bool:
    if not re.fullmatch(r"[A-Za-z0-9_+/=.~-]+", value):
        return False
    if re.fullmatch(r"[a-fA-F0-9]+", value) or all(re.search(kind, value) for kind in ("[a-z]", "[A-Z]", "[0-9]")):
        return True
    return bool(re.fullmatch(r"[a-z0-9]{24,}", value)) and sum(character.isdigit() for character in value) >= 6


def _token_findings(source: Source) -> Iterable[tuple]:
    """What's unmistakable from the text alone, in any file."""
    for match in _LIVE_TOKENS.finditer(source.text):
        yield "hardcoded-secret", source.line_of(match.start()), "Credential-shaped token in source (value withheld).", {"confidence": "high"}
    for match in _URL_CREDENTIALS.finditer(source.text):
        if _is_worth_a_lead(match.group(1), "password"):
            yield "hardcoded-secret", source.line_of(match.start()), "A URL with an embedded password (value withheld).", {"confidence": "high"}


def _secrets(source: Source, is_test: bool) -> Iterable[tuple]:
    if is_test:
        return
    seen = set()
    for finding in _token_findings(source):
        if finding[2].startswith("Credential"):
            seen.add(finding[1])
        yield finding
    for match in _SECRET_ASSIGN.finditer(source.text):
        line = source.line_of(match.start())
        name, value = match.groups()
        if line in seen or _DESCRIBES_A_CREDENTIAL.search(name) or not _is_worth_a_lead(value, name):
            continue
        seen.add(line)
        yield "hardcoded-secret", line, "Literal assigned to a credential-named variable (value withheld).", {}
    for match in _TOKEN_ASSIGN.finditer(source.text):
        line = source.line_of(match.start())
        if line not in seen and _looks_random(match.group(1)) and not _NOT_A_SECRET.search(match.group(1)):
            seen.add(line)
            yield "hardcoded-secret", line, "Literal assigned to a credential-named variable (value withheld).", {}
    for match in _AUTH_HEADER.finditer(source.text):
        line = source.line_of(match.start())
        if line not in seen and not match.group(1).isalpha() and not _NOT_A_SECRET.search(match.group(1)):
            seen.add(line)
            yield "hardcoded-secret", line, "An Authorization header with its credential written out (value withheld).", {"confidence": "high"}
    if source.language == "shell":
        for match in _SHELL_ASSIGN.finditer(source.code):  # unquoted, so the code view has it and has dropped comments
            name, value = match.groups()
            line = source.line_of(match.start())
            if line not in seen and not value.isdigit() and not _DESCRIBES_A_CREDENTIAL.search(name) and _is_worth_a_lead(value, name):
                seen.add(line)
                yield "hardcoded-secret", line, "Literal assigned to a credential-named variable (value withheld).", {}
    for match in _SECRET_DEFAULT.finditer(source.text):
        if _is_worth_a_lead(match.group(1)):
            yield "hardcoded-secret", source.line_of(match.start()), "A credential's fallback value is committed here (value withheld).", {"confidence": "high"}


def secrets_only_findings(source: Source) -> Iterable[tuple]:
    """For a config file or Dockerfile: no name-based guessing, since `password: required` is a schema there, and a Dockerfile's RUN lines are shell."""
    seen = set()
    for finding in _token_findings(source):
        if finding[:3] not in seen:
            seen.add(finding[:3])
            yield finding
    if DOCKERFILE.search(source.path):
        for rule in TEXT_RULES:
            if rule.rule == "curl-pipe-shell":
                for match in rule.pattern.finditer(_view_text(source, rule.view)):
                    yield rule.rule, source.line_of(match.start()), None, rule.overrides


# ---------------------------------------------------------------- SQL in JavaScript, which needs more than a pattern: multi-line templates, and values built earlier

_JS_SQL_CALL = re.compile(r"\.(query|execute|raw|\$queryRawUnsafe|\$executeRawUnsafe)\s*(?:<[^()\n]{0,100}>\s*)?\(")
_JS_ASSIGNMENT = re.compile(r"(?<![\w.$])(?:(?:const|let|var)\s+)?([A-Za-z_$][\w$]*)\s*(\+?=)(?![=>])")
_JS_IDENTIFIER = re.compile(r"[A-Za-z_$][\w$]*")
_JS_MARKER_TEXT = re.compile(r"""["'`](?:\?|\$\$\{|\$\d|%s)|\b\w*(?:[Pp]laceholder|[Mm]arks)\w*\(""")
_NOT_SQL = re.compile(r"\s*(?:(?:query|mutation|subscription|fragment)\b|\{)")  # a GraphQL document, which can say `where:`
_JS_VALUE_LIMIT = 8000


def _js_string_end(text: str, start: int, limit: int, literal: list[str], spliced: list[str]) -> int:
    """Past the string or template opening at `start`, noting its written-out text and what's interpolated."""
    quote = text[start]
    index = piece = start + 1
    while index < limit:
        character = text[index]
        if character == "\\":
            index += 2
        elif character == quote or (character == "\n" and quote != "`"):
            literal.append(text[piece:index])
            return index + 1
        elif quote == "`" and text.startswith("${", index):
            literal.append(text[piece:index])
            depth, inner = 1, index + 2
            while inner < limit and depth:
                depth += {"{": 1, "}": -1}.get(text[inner], 0)
                inner += 1
            spliced.append(text[index + 2:inner - 1].strip())
            index = piece = inner
        else:
            index += 1
    literal.append(text[piece:min(index, limit)])
    return index


class _JsValue(NamedTuple):
    literal: str     # written-out text
    spliced: list    # what a template interpolates
    rest: str        # the code around the strings
    end: int


def _js_value(text: str, start: int, whole_statement: bool) -> _JsValue:
    """One expression, up to the end of an argument, or of a statement when `whole_statement`. A line break ends a statement unless a `+` carries it on."""
    literal: list[str] = []
    spliced: list[str] = []
    rest: list[str] = []
    depth = 0
    index = start
    limit = min(len(text), start + _JS_VALUE_LIMIT)
    while index < limit:
        character = text[index]
        if character in "\"'`":
            index = _js_string_end(text, index, limit, literal, spliced)
            rest.append(" ")
            continue
        if character in "([{":
            depth += 1
        elif character in ")]}":
            if depth == 0:
                break
            depth -= 1
        elif depth == 0 and character in ",;":
            break
        elif depth == 0 and character == "\n" and whole_statement:
            before = "".join(rest).rstrip()
            ahead = text[index:index + 200].lstrip()
            if (before or literal) and not before.endswith("+") and not ahead.startswith("+"):
                break
        rest.append(character)
        index += 1
    return _JsValue(" ".join(literal), spliced, "".join(rest), index)


def _js_is_built(value: _JsValue) -> list[str] | None:
    """What's put into this text at runtime, or None if nothing is."""
    if "=>" in value.rest or "function" in value.rest:
        return None  # a callback, not a query's text
    operands = [part.strip() for part in value.rest.split("+") if part.strip()] if "+" in value.rest and value.literal else []
    return (value.spliced + operands) or None


def _js_is_only_markers(text: str, expression: str, assignments: dict[str, list[tuple]], position: int) -> bool:
    if _JS_MARKER_TEXT.search(expression):
        return True
    if not PLACEHOLDER_NAME.fullmatch(expression):
        return False
    earlier = _js_assigned_before(assignments, expression, position)  # the name is a claim, so whatever sets it has to back that up
    return not earlier or bool(_JS_MARKER_TEXT.search(text[earlier[-1][0]:earlier[-1][0] + _JS_VALUE_LIMIT].split("\n", 1)[0]))


def _js_assignments(code: str) -> dict[str, list[tuple]]:
    assignments: dict[str, list[tuple]] = {}
    for match in _JS_ASSIGNMENT.finditer(code):
        assignments.setdefault(match.group(1), []).append((match.end(), match.group(2)))
    return assignments


def _js_assigned_before(assignments: dict[str, list[tuple]], name: str, position: int) -> list[tuple]:
    """Its last `=` before this point, and any `+=` since, up to a few. What came before that `=` no longer counts."""
    listed = assignments.get(name, [])
    end = bisect.bisect_left(listed, (position,))
    start = end
    while start > 0 and end - start < 8:
        start -= 1
        if listed[start][1] == "=":
            break
    return listed[start:end]


def _js_sql_findings(source: Source) -> Iterable[tuple]:
    text = source.text
    assignments: dict[str, list[tuple]] | None = None
    budget = 4 * len(text) + _JS_VALUE_LIMIT  # enough for real code, while calls packed together can't make this quadratic
    for match in _JS_SQL_CALL.finditer(source.code):
        if budget <= 0:
            return
        start = match.end()
        while start < len(text) and text[start] in " \t\r\n":
            start += 1
        if text[start:start + 1] in ("{", "["):
            continue  # an options object, as in { text, values }
        unsafe_api = match.group(1).endswith("Unsafe")
        value = _js_value(text, start, whole_statement=False)
        budget -= value.end - start + 1
        if assignments is None:
            assignments = _js_assignments(source.code)
        line = source.line_of(match.start())
        built = _js_is_built(value)
        if built:
            if (unsafe_api or _is_js_sql(value.literal)) and not all(_js_is_only_markers(text, part, assignments, match.start()) for part in built):
                yield "sql-injection", line, f".{match.group(1)}() receives SQL built from runtime values.", {}
            continue
        name = value.rest.strip()
        if value.literal or not _JS_IDENTIFIER.fullmatch(name):
            continue
        earlier = _js_assigned_before(assignments, name, match.start())
        if not earlier:
            if unsafe_api:
                yield "sql-injection", line, f".{match.group(1)}() runs whatever {name} holds.", {"confidence": "medium"}
            continue
        pieces = [_js_value(text, offset, whole_statement=True) for offset, _ in earlier]
        budget -= sum(piece.end - offset for piece, (offset, _) in zip(pieces, earlier))
        parts = [part for piece in pieces for part in (_js_is_built(piece) or [])]
        whole = " ".join(piece.literal for piece in pieces)
        if parts and (unsafe_api or _is_js_sql(whole)) and not all(_js_is_only_markers(text, part, assignments, match.start()) for part in parts):
            yield "sql-injection", line, f".{match.group(1)}() receives SQL built from runtime values, by way of {name}.", {"confidence": "medium"}


def _is_js_sql(text: str) -> bool:
    return _has_sql(text) and not _NOT_SQL.match(text)


def _comment_shape(source: Source, is_test: bool) -> Iterable[tuple]:
    """Commented-out code, narration, banners and comment density."""
    if not source.comments:
        return
    hash_style = source.language in ("python", "shell", "ruby")
    looks_like_code = _LOOKS_LIKE_CODE["hash" if hash_style else "c_like"]
    banners = 0
    run: list[int] = []

    def close_run() -> Iterable[tuple]:
        if len(run) >= 3 and (source.language != "python" or _parses(run, comment_at)):
            yield "commented-out-code", run[0], f"{len(run)} consecutive lines of commented-out code.", {}

    previous_line = None
    code_lines = source.code.split("\n")
    comment_only = 0
    comment_at = dict(source.comments)
    for line, comment in source.comments:
        text = _visible(comment)
        if source.line_text(line).strip().startswith(comment[:2]):
            comment_only += comment.count("\n") + 1
        if comment.startswith(_DOC_COMMENT):  # examples in documentation are meant to look like code
            yield from close_run()
            run.clear()
            previous_line = None
            continue
        if _BANNER.match(comment.strip()):
            banners += 1
        if text and looks_like_code.search(text) and "\n" not in comment and not text.endswith((".", ":", "?", "!")) or (
                text and hash_style and text.endswith(":") and looks_like_code.search(text)):
            if previous_line is not None and line != previous_line + 1:
                yield from close_run()
                run.clear()
            run.append(line)
            previous_line = line
        else:
            yield from close_run()
            run.clear()
            previous_line = None
        next_code = code_lines[line].strip() if line < len(code_lines) else ""
        if next_code and "\n" not in comment and _narrates(text, next_code):
            yield "narration-comment", line, None, {}
    yield from close_run()
    if banners >= 3:
        yield "banner-comment", source.comments[0][0], f"{banners} banner comments in this file.", {}
    total = len(source.line_starts)
    if total >= 60 and not is_test and comment_only / total > 0.4:
        yield "comment-flood", 1, f"{comment_only} of {total} lines are comments.", {}


def _parses(lines: list[int], comment_at: dict[int, str]) -> bool:
    """Do these commented lines form Python? Prose rarely does. Fragments of a block count, so try them dedented and wrapped."""
    body = [_COMMENT_LEAD.sub("", comment_at[line], count=1) for line in lines]
    indent = min((len(text) - len(text.lstrip()) for text in body if text.strip()), default=0)
    block = "\n".join(text[indent:] for text in body)
    for candidate in (block, "if x:\n" + "\n".join("    " + text[indent:] for text in body)):
        try:
            ast.parse(candidate)
            return True
        except (SyntaxError, ValueError):
            continue
    return False


def _narrates(comment: str, code: str) -> bool:
    words = [w.lower() for w in re.findall(r"[A-Za-z]{2,}", comment) if w.lower() not in _STOP_WORDS]
    if not 1 <= len(words) <= 8:
        return False
    parts: set[str] = set()
    for identifier in _IDENT.findall(code):
        pieces = re.findall(r"[A-Z]?[a-z]+|[A-Z]+(?![a-z])", identifier)
        parts.update(piece.lower() for piece in pieces)
    if not parts:
        return False
    overlap = sum(word in parts or word.rstrip("s") in parts for word in words) / len(words)
    return overlap >= 0.75 or (overlap >= 0.5 and bool(_NARRATION_START.match(comment)))


def _shell_file_rules(source: Source) -> Iterable[tuple]:
    yield from shell_findings(source)
    if len(source.line_starts) >= 10 and not re.search(r"^[ \t]*set\s+-[a-zA-Z]*e|^[ \t]*set\s+-o\s+errexit", source.code, re.M):
        yield "shell-no-strict", 1, None, {}


# ---------------------------------------------------------------- structure for languages without a parser here

_FUNCTION_HEADS = {
    "go": re.compile(r"^func\s+(?P<receiver>\([^)]{0,500}\)\s*)?(?P<name>\w+)\s*(?:\[[^\]]*\])?\((?P<params>[^)]{0,500})\)(?:interface\{\}|struct\{\}|[^{\n])*\{", re.M),
    "rust": re.compile(r"^[ \t]*(?:pub(?:\([^)]{0,500}\))?\s+)?(?:async\s+)?(?:unsafe\s+)?fn\s+(?P<name>\w+)\s*(?:<[^>]*>)?\((?P<params>[^)]{0,500})\)[^{;\n]*\{", re.M),
    "javascript": re.compile(
        r"^[ \t]*(?:export\s+)?(?:default\s+)?(?:async\s+)?function\s*\*?\s*(?P<name>\w+)\s*\((?P<params>[^)]{0,500})\)[^{\n]*\{"
        r"|^[ \t]*(?:export\s+)?(?:const|let|var)\s+(?P<name2>\w+)\s*=\s*(?:async\s*)?\((?P<params2>[^)]{0,500})\)\s*(?::[^=\n]+)?=>\s*\{"
        r"|^[ \t]+(?:public\s+|private\s+|protected\s+|static\s+|async\s+)*(?P<name3>[a-zA-Z_]\w*)\s*\((?P<params3>[^)]{0,500})\)\s*(?::[^{\n]+)?\{", re.M),
    "java": re.compile(r"^[ \t]*(?:(?:public|private|protected|static|final|abstract|synchronized|override|suspend|open|internal)\s+)*(?:fun\s+|[\w<>\[\],.]+\s+)(?P<name>[a-zA-Z_]\w*)\s*\((?P<params>[^)]{0,500})\)[^{;\n]*\{", re.M),
    "c": re.compile(r"^[a-zA-Z_][\w\s\*:<>,&]*?\s\*?(?P<name>[a-zA-Z_][\w:~]*)\s*\((?P<params>[^)]{0,500})\)\s*(?:const\s*)?(?:noexcept\s*)?\{", re.M),
}
_FUNCTION_HEADS["typescript"] = _FUNCTION_HEADS["javascript"]
_FUNCTION_HEADS["kotlin"] = _FUNCTION_HEADS["java"]
_FUNCTION_HEADS["scala"] = _FUNCTION_HEADS["java"]
_FUNCTION_HEADS["csharp"] = _FUNCTION_HEADS["java"]
_FUNCTION_HEADS["swift"] = _FUNCTION_HEADS["java"]
_FUNCTION_HEADS["cpp"] = _FUNCTION_HEADS["c"]
_FUNCTION_HEADS["php"] = _FUNCTION_HEADS["java"]
_NOT_FUNCTIONS = {"if", "for", "while", "switch", "catch", "return", "else", "do", "try", "function", "foreach", "using", "lock", "sizeof", "constructor"}
_BRANCH = re.compile(r"\b(?:if|for|while|case|catch|except|elif|when|foreach|match)\b|&&|\|\||\?(?=\s*[\w(\"'])")
_ASSERTING = re.compile(r"\b(?:expect|assert\w*|should|check\w*|verify|require|must\w*)\b|\b\w*assert\w*!|\bmatches!|\bt\.(?:Error|Fatal|Fail)\w*|\bcmp\.Diff|\bc\.(?:Assert|Check)\b|\(t\s*[,)]", re.I)
_RUST_FAILS = re.compile(r"\.unwrap\(\)|\.expect\(|\bpanic!|\?\s*;|\bunwrap_err\(")
_RUST_TEST_ATTRIBUTE = re.compile(r"#\[[\w:]*test[^\]]*\]\s*(?:#\[[^\]]*\]\s*)*(?:pub\s+)?(?:async\s+)?$")
_TEST_FUNCTION_NAME = re.compile(r"^(?:Test[A-Z_]|test_?[a-zA-Z]|should[A-Z])")
_JS_TEST_BLOCK = re.compile(r"""\b(?:it|test)\(\s*["'`][^"'`\n]*["'`]\s*,\s*(?:async\s*)?(?:\(\s*\)|function\s*\(\s*\))\s*(?:=>\s*)?\{""")
_PARAM_SPLIT = re.compile(r",(?![^<>()\[\]{}]*[>)\]}])")


def _matching_brace(code: str, opening: int) -> int:
    depth = 0
    for index in range(opening, len(code)):
        character = code[index]
        if character == "{":
            depth += 1
        elif character == "}":
            depth -= 1
            if depth == 0:
                return index
    return -1


def _max_depth(body: str) -> int:
    depth = deepest = 0
    for character in body:
        if character == "{":
            depth += 1
            deepest = max(deepest, depth)
        elif character == "}":
            depth -= 1
    return deepest


def _function_list(source: Source) -> list[tuple[str, int, int, str, str]]:
    """(name, start offset, end offset, params, body) for every function in a braced language."""
    head = _FUNCTION_HEADS.get(source.language or "")
    if head is None:
        return []
    found = []
    budget = 4 * len(source.code)  # enough for real nesting; unbalanced input can't make this quadratic
    for match in head.finditer(source.code):
        if budget <= 0:
            break
        groups = match.groupdict()
        name = groups.get("name") or groups.get("name2") or groups.get("name3")
        if not name or name in _NOT_FUNCTIONS:
            continue
        params = groups.get("params") or groups.get("params2") or groups.get("params3") or ""
        opening = match.end() - 1
        closing = _matching_brace(source.code, opening)
        budget -= (closing if closing > 0 else len(source.code)) - opening
        if closing < 0:
            continue
        found.append((name, match.start(), closing, params, source.code[opening + 1:closing]))
    return found


def _test_checks_something(source: Source, start: int, end: int) -> bool:
    body = source.text[start:end]
    if _ASSERTING.search(body):
        return True
    # In Rust, a test fails on a panic or a returned error, so these are how many tests check things.
    return source.language == "rust" and bool(_RUST_FAILS.search(body) or "should_panic" in source.text[max(0, start - 200):start])


def _is_test_function(source: Source, name: str, start: int) -> bool:
    if source.language == "rust":
        return bool(_RUST_TEST_ATTRIBUTE.search(source.text[max(0, start - 200):start]))
    return source.language in ("go", "java", "kotlin", "csharp") and bool(_TEST_FUNCTION_NAME.match(name))


def structure_findings(source: Source, is_test: bool) -> tuple[list[tuple], dict]:
    """Complexity and test rules for braced languages, and the facts cross-file passes need."""
    findings: list[tuple] = []
    defs = []
    for name, start, end, params, body in _function_list(source):
        line = source.line_of(start)
        end_line = source.line_of(end)
        length = end_line - line + 1
        branches = len(_BRANCH.findall(body)) + 1
        depth = _max_depth(body)
        count = len([p for p in _PARAM_SPLIT.split(params) if p.strip()])
        defs.append({"name": name, "line": line, "end": end_line, "kind": "function", "statements": body.count(";") + body.count("\n"), "complexity": branches, "params": count})
        if not is_test:
            if branches >= 15:
                findings.append(("high-complexity", line, f"{name} has about {branches} branch points.", {"severity": "high"} if branches >= 30 else {}))
            if length > 100:
                findings.append(("long-function", line, f"{name} is {length} lines.", {"severity": "high"} if length > 250 else {}))
            if depth > 4:
                findings.append(("deep-nesting", line, f"{name} nests {depth} levels.", {}))
            if count > 7:
                findings.append(("many-params", line, f"{name} takes {count} parameters.", {}))
            if not body.strip() and source.language not in ("javascript", "typescript", "java", "kotlin", "csharp", "swift", "php", "cpp"):
                # An empty method often satisfies an interface or trait on purpose. A free function rarely does.
                is_method = source.text[start:start + 1] in (" ", "\t") or source.text[start:start + 6] == "func ("
                findings.append(("stub-body", line, f"{name} has an empty body.", {"confidence": "low" if is_method else "medium"}))
        elif _is_test_function(source, name, start) and not _test_checks_something(source, start, end) and length > 2:
            findings.append(("test-no-assert", line, f"{name} doesn't assert anything.", {}))
    if is_test and source.language in ("javascript", "typescript"):
        for match in _JS_TEST_BLOCK.finditer(source.code):
            closing = _matching_brace(source.code, match.end() - 1)
            if closing > 0 and not _ASSERTING.search(source.code[match.end():closing]):
                findings.append(("test-no-assert", source.line_of(match.start()), "This test doesn't assert anything.", {}))
    return findings, {"defs": defs, "classes": _class_facts(source)}


_CLASS_HEAD = re.compile(
    r"^[ \t]*(?:export\s+)?(?:public\s+|abstract\s+|final\s+|open\s+|sealed\s+|data\s+|internal\s+)*(?P<kind>class|interface)\s+(?P<name>[A-Z]\w*)"
    r"(?:<[^>{]*>)?(?P<rest>[^{\n]*)", re.M)


def _class_facts(source: Source) -> list[dict]:
    if source.language not in ("javascript", "typescript", "java", "kotlin", "scala", "csharp", "swift", "php"):
        return []
    classes = []
    for match in _CLASS_HEAD.finditer(source.code):
        rest = match.group("rest")
        bases = [w for w in re.findall(r"[A-Z]\w*", re.sub(r"<[^>]*>", "", rest))]
        classes.append({"name": match.group("name"), "kind": match.group("kind"), "line": source.line_of(match.start()),
                        "bases": bases, "abstract": match.group("kind") == "interface" or "abstract " in match.group(0)})
    return classes


# ---------------------------------------------------------------- imports for languages without a parser here

_JS_IMPORT = re.compile(r"""(?:\bimport\s+(?:[^'"\n;]+?\s+from\s+)?|\bexport\s+[^'"\n;]*?\sfrom\s+|\brequire\(\s*|\bimport\(\s*)["']([^"'\n]+)["']""")
_GO_IMPORT = re.compile(r"""^[ \t]*(?:import\s+)?(?:[\w.]+\s+)?"([\w./-]+)"[ \t]*$""", re.M)
_RUST_LOCAL_NAME = re.compile(r"\bmod\s+(\w+)|::(\w+)\s*;|\bas\s+(\w+)\s*;")
_RUST_USE = re.compile(r"^[ \t]*(?:pub\s+)?(?:use|extern crate)\s+([a-zA-Z_]\w*)", re.M)


def import_facts(source: Source) -> list[dict]:
    language = source.language
    found = []
    if language in ("javascript", "typescript"):
        for match in _JS_IMPORT.finditer(source.text):
            if source.code[match.start()] not in ("i", "e", "r"):
                continue
            found.append({"module": match.group(1), "line": source.line_of(match.start())})
    elif language == "go":
        block = re.search(r"^import\s*\((.*?)^\)", source.text, re.M | re.S)
        region = block.group(1) if block else "\n".join(m for m in re.findall(r"^import\s+.*$", source.text, re.M))
        for match in _GO_IMPORT.finditer(region):
            found.append({"module": match.group(1), "line": 1})
    elif language == "rust":
        local = {name for group in _RUST_LOCAL_NAME.findall(source.code) for name in group if name}
        for match in _RUST_USE.finditer(source.code):
            if match.group(1) not in local:
                found.append({"module": match.group(1), "line": source.line_of(match.start())})
    return found


def identifiers(text: str) -> dict[str, int]:
    """Identifier counts, used for cross-file reference checks."""
    counts: dict[str, int] = {}
    for word in _IDENT.findall(text):
        if len(word) >= 3:
            counts[word] = counts.get(word, 0) + 1
    return counts

