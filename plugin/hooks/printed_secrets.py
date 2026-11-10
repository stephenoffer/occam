"""Commands that put a credential into the conversation: printing a credential file, or a value from a secret store or a cluster secret
where the terminal shows it. A value piped into something that counts or tests it, saved to a file, or captured into a variable isn't
printed. The owner's credential-file ask of 2026-11-07, extended to secret stores: a value printed is in the conversation and its logs for good.
"""

from __future__ import annotations  # the stock macOS python3 is 3.9

import re
from typing import Callable

from occam_commands import subcommand


# Options of grep and rg that take the next word as their value, so that word is neither the pattern nor a file.
_TAKES_NEXT = {"-A", "-B", "-C", "-e", "-f", "-m", "-t", "-T", "-g", "-M", "-j", "-E", "--include", "--exclude", "--exclude-dir", "--glob", "--iglob", "--type",
               "--type-not", "--max-count", "--regexp", "--file", "--context", "--before-context", "--after-context", "--max-columns", "--threads", "--encoding"}
_COUNT_LETTERS = {"grep": set("clLq"), "ag": set("clLq"), "rg": set("clq")}  # rg's -L follows links, and prints lines
_SCANS_FOR = {"grep", "rg", "ag"}
FIXTURE_FOLDER = re.compile(r"(?:^|/)(?:tests?|testdata|fixtures|__fixtures__|node_modules|vendor|examples?)/")
# Files that hold credentials. Reading one puts the values in the conversation and its logs, so a person confirms it, by the owner's decision of 2026-11-07.
SECRET_FILE = re.compile(r"(^|/)(\.env(?![^/]*(?:example|sample|template|dist))(\.[^/]+|[*?])?|\.envrc|\.netrc|\.pypirc|\.pgpass|\.git-credentials|\.kube/config|id_rsa|id_ed25519"
                         r"|credentials(\.json)?|\.aws/credentials|[^/]*(?:private|secret)[^/]*\.(?:pem|key)|service[-_]account[^/]*\.json)$")
_PRINTS_A_FILE = {"cat", "less", "more", "head", "tail", "grep", "rg", "ag", "bat", "xxd", "strings", "nl", "od", "jq", "sed", "awk", "Get-Content", "get-content", "gc", "type"}
_COUNTS_ONLY = {"--quiet", "--count", "--files-with-matches", "--files-without-match"}  # grep's and rg's, which print no lines


def _files_named(name: str, args: list[str]) -> list[str]:
    """The files a reading command is given: its plain arguments, past an option's value and past grep's or rg's pattern unless -e or -f named one."""
    plain, skip_next = [], False
    for arg in args:
        if skip_next:
            skip_next = False
        elif arg.startswith("-"):
            skip_next = name in _SCANS_FOR and arg in _TAKES_NEXT
        else:
            plain.append(arg.replace("\\", "/"))  # PowerShell's `.\.env`
    pattern_given = any(arg in ("-e", "-f", "--regexp", "--file") or arg.startswith(("--regexp=", "--file=")) for arg in args)
    return plain[1:] if name in _SCANS_FOR and not pattern_given else plain


def _only_counts(name: str, args: list[str]) -> bool:
    """grep's and rg's counting options print counts or names, not lines. Other programs' -c and -l mean something else."""
    letters = _COUNT_LETTERS.get(name, set())
    return bool(letters) and any(arg in _COUNTS_ONLY or (re.fullmatch(r"-[A-Za-z]+", arg) and set(arg[1:]) & letters) for arg in args)


def _a_sample(path: str) -> bool:
    """A fixture or a dependency's copy, judged on a relative path only, since an absolute one names the folders above the project too."""
    return not path.startswith(("/", "~")) and not re.match(r"^[A-Za-z]:/", path) and bool(FIXTURE_FOLDER.search(path))


def credential_printed(programs: list[tuple[str, list[str]]]) -> str | None:
    return next((path for name, args in programs if name in _PRINTS_A_FILE and not _only_counts(name, args)
                 for path in _files_named(name, args) if SECRET_FILE.search(path) and not _a_sample(path)), None)


# ---------------------------------------------------------------- a secret's value printed where the conversation sees it (F263)

_PASSES_ON = {"cat", "tee", "sort", "uniq", "head", "tail", "sed", "awk", "gawk", "tr", "column", "fold", "less", "more", "cut", "xxd", "od", "strings", "nl", "fx",
              "gron", "json_pp", "jless", "bat", "rev", "paste", "base64", "yq", "envsubst"}
_JQ_TAKES_TWO = {"--arg", "--argjson", "--slurpfile", "--rawfile"}
_JQ_TAKES_ONE = {"--indent", "-L", "--args", "--jsonargs"}
_JQ_REDUCES = re.compile(r"\b(?:keys|keys_unsorted|length|utf8bytelength|has|test|empty)\b")
MAX_SUBSTITUTION_DEPTH = 3
_CLUSTER_SECRET = "a cluster secret"
_TERRAFORM_OUTPUTS = "Terraform's outputs, which show sensitive ones in plain text"
# Fields of what a store prints that hold no secret, so picking out only these shows none. Terraform's outputs are named by whoever wrote
# them, so there it's each output's name that's read, and one that sounds like a credential counts as one.
_PLAIN_FIELDS = {_CLUSTER_SECRET: {"metadata", "type", "kind", "apiversion"}, "AWS Secrets Manager": {"arn", "name", "versionid", "versionstages", "createddate"}}
_SECRET_NAME = re.compile(r"pass|secret|token|key|cred|private|auth|cert|dsn|conn|database_url|db_url|session|cookie|signing|salt|seed|webhook", re.I)
_JQ_PATH = re.compile(r"(?:\.(?:[A-Za-z_]\w*|\"[^\"]*\")\??|\.?\[[^\]]*\]\??)+")
_JQ_KEY = re.compile(r"\.([A-Za-z_]\w*)|\.?\"([^\"]*)\"|\[\s*\"([^\"]*)\"\s*\]")
# A kubectl template shows a secret's value when it reads `.data` or `.stringData`, or prints whole objects, or reads none of the plain fields.
_TEMPLATE_DATA = re.compile(r"(?<![a-z])(?:string)?data\b")
_TEMPLATE_WHOLE = re.compile(r"@|\{\{-?\s*\.\s*-?\}\}|\{\.\}")
_TEMPLATE_PLAIN = re.compile(r"\.(?:metadata|type|kind|apiversion)\b")


def _kubectl_output(lowered: list[str]) -> str:
    for index, arg in enumerate(lowered):
        if arg in ("-o", "--output") and index + 1 < len(lowered):
            return lowered[index + 1]
        if arg.startswith("--output="):
            return arg.split("=", 1)[1]
        if arg.startswith("-o") and len(arg) > 2 and not arg.startswith("--"):
            return arg[2:].lstrip("=")
    return ""


def secret_store(name: str, args: list[str]) -> str | None:
    """The secret store this command prints a value from, not just names or metadata. The owner's credential-file ask of 2026-11-07,
    extended to secret stores and cluster secrets: a value printed is in the conversation and its logs for good."""
    lowered = [arg.lower() for arg in args]
    words = set(lowered)
    plain = [arg for arg in lowered if not arg.startswith("-")]
    return next((found for reads in _SECRET_STORES.get(name, ()) for found in [reads(lowered, words, plain)] if found), None)


def _all_of(needed: set[str], store: str) -> Callable[[list[str], set[str], list[str]], str | None]:
    return lambda lowered, words, plain: store if needed <= words else None


def _ssm_decrypted(lowered: list[str], words: set[str], plain: list[str]) -> str | None:
    return "SSM Parameter Store" if "ssm" in words and words & {"get-parameter", "get-parameters", "get-parameters-by-path"} and "--with-decryption" in words else None


def _vault_value(lowered: list[str], words: set[str], plain: list[str]) -> str | None:
    return "Vault" if plain[:2] == ["kv", "get"] or (plain[:1] == ["read"] and not _vault_system_path(plain[1:2])) else None


def _onepassword_value(lowered: list[str], words: set[str], plain: list[str]) -> str | None:
    revealed = plain[:2] == ["item", "get"] and any(arg == "--reveal" or arg.startswith("--field") for arg in lowered)
    return "1Password" if plain[:1] == ["read"] or revealed else None


def _doppler_value(lowered: list[str], words: set[str], plain: list[str]) -> str | None:
    values = plain[1:2] in ([], ["get"]) or (plain[1:2] == ["download"] and "--no-file" in words)
    return "Doppler" if plain[:1] == ["secrets"] and values and "--only-names" not in words else None


def _cluster_secret_value(lowered: list[str], words: set[str], plain: list[str]) -> str | None:
    if subcommand("kubectl", lowered) != "get" or not any(arg in ("secret", "secrets") or arg.startswith(("secret/", "secrets/")) for arg in plain):
        return None
    output, _, template = _kubectl_output(lowered).partition("=")
    if output in ("json", "yaml") or output.endswith("file") or (output.startswith(("jsonpath", "go-template", "template", "custom-columns")) and _template_shows_a_value(template)):
        return _CLUSTER_SECRET  # a template in a file can't be read from here
    return None


def _sops_decrypted(lowered: list[str], words: set[str], plain: list[str]) -> str | None:
    printed = not words & {"-i", "--in-place", "--output"} and not any(arg.startswith("--output=") for arg in lowered)
    return "sops" if words & {"-d", "--decrypt"} and printed else None


def _terraform_outputs(lowered: list[str], words: set[str], plain: list[str]) -> str | None:
    return _TERRAFORM_OUTPUTS if plain == ["output"] and "-json" in words else None


# Each program's ways of printing a stored secret's value, read from its arguments lowered, as a set, and without options.
_SECRET_STORES = {
    "aws": (_all_of({"secretsmanager", "get-secret-value"}, "AWS Secrets Manager"), _ssm_decrypted),
    "gcloud": (_all_of({"secrets", "versions", "access"}, "Secret Manager"),),
    "az": (_all_of({"keyvault", "secret", "show"}, "Key Vault"),),
    "vault": (_vault_value,),
    "op": (_onepassword_value,),
    "doppler": (_doppler_value,),
    "kubectl": (_cluster_secret_value,),
    "sops": (_sops_decrypted,),
    "terraform": (_terraform_outputs,),
    "tofu": (_terraform_outputs,),
}


def _vault_system_path(path: list[str]) -> bool:
    """Vault's own state, such as `sys/health`, which holds no secret. `sys/raw` reads storage itself, so it isn't one."""
    where = path[0].lstrip("/") if path else ""
    return where.startswith("sys/") and not where.startswith("sys/raw")


def _template_shows_a_value(template: str) -> bool:
    return bool(_TEMPLATE_DATA.search(template) or _TEMPLATE_WHOLE.search(template) or not _TEMPLATE_PLAIN.search(template))


def _picks_only_plain_fields(program: str, store: str) -> bool:
    """Does this jq program pick out only fields of the store's output that hold no secret? Read from its first stage, `.a.b, .c`, which is all
    that reaches the rest of the program. Anything else there, a filter, a function or the whole input, may carry the value."""
    if store not in _PLAIN_FIELDS and store != _TERRAFORM_OUTPUTS:
        return False
    return all(_a_plain_field(part.strip(), store) for part in program.split("|", 1)[0].split(","))


def _a_plain_field(path: str, store: str) -> bool:
    if not path.startswith(".") or not _JQ_PATH.fullmatch(path):
        return False
    keys = [next(group for group in found if group) for found in _JQ_KEY.findall(path) if any(found)]
    if store == _CLUSTER_SECRET and keys[:1] == ["items"]:
        keys = keys[1:]  # each secret in a list
    if not keys:
        return False
    return not _SECRET_NAME.search(keys[0]) if store == _TERRAFORM_OUTPUTS else keys[0].lower() in _PLAIN_FIELDS[store]


def _passes_on(name: str, args: list[str], store: str = "") -> bool:
    """Does what comes in from `store` still come out, rather than being counted, tested, consumed, or narrowed to fields holding no secret?"""
    if name in ("jq", "gojq", "jaq"):
        index, program = 0, "."
        while index < len(args):
            arg = args[index]
            if arg in _JQ_TAKES_TWO:
                index += 3
            elif arg in _JQ_TAKES_ONE or arg in ("-f", "--from-file"):
                if arg in ("-f", "--from-file"):
                    return True  # a program in a file can't be read from here
                index += 2
            elif arg.startswith("-"):
                index += 1
            else:
                program = arg
                break
        return "@base64d" in program or not (_JQ_REDUCES.search(program) or _picks_only_plain_fields(program, store))
    if name in ("grep", "egrep", "fgrep", "rg"):
        return not _only_counts("rg" if name == "rg" else "grep", args)
    if re.fullmatch(r"python[\d.]*", name):
        return args[:2] == ["-m", "json.tool"]
    return name in _PASSES_ON


def _word_carries(word: str | None, depth: int, captured: dict[str, str] | None = None) -> str | None:
    """The secret a word holds: what a substitution in it prints, or a variable `captured` names."""
    if not word or depth >= MAX_SUBSTITUTION_DEPTH:
        return None
    held = next((captured[name] for name in _REFERENCE.findall(word) if name in captured), None) if captured and "$" in word else None
    if held or ("$(" not in word and "`" not in word):
        return held
    from shell_reading import pipelines, substitutions

    for inner in substitutions(word):
        for stages in pipelines(inner):
            found = _carried_to_the_end(stages, depth + 1, captured)
            if found:
                return found
    return None


def _carried_to_the_end(stages: list, depth: int, captured: dict[str, str] | None = None) -> str | None:
    from occam_commands import head

    carried = None
    for stage in stages:
        name, args = head(stage.words)
        fed = _word_carries(stage.fed, depth, captured)
        own = secret_store(name, args)
        if own:
            carried = own
        elif (carried or fed) and _passes_on(name, args, carried or fed):
            carried = carried or fed
        elif name in ("echo", "printf"):
            carried = next((found for word in stage.words[1:] for found in [_word_carries(word, depth, captured)] if found), None)
        else:
            carried = None
        if stage.saved:
            carried = None
    return carried


def secret_printed(command: str) -> str | None:
    """Where the secret value this command prints comes from, when the value reaches the terminal. Piped into something that counts or tests
    it, or saved to a file, it doesn't. Captured into a variable, as `X=$(op read ...)`, it does when the command then echoes that variable."""
    from shell_reading import pipelines

    captured: dict[str, str] = {}
    for stages in pipelines(command):
        _capture(stages, captured)
        found = _carried_to_the_end(stages, 0, captured)
        if found:
            return found
    return None


_REFERENCE = re.compile(r"\$\{?([A-Za-z_]\w*)")
_ASSIGNS = ("", "export", "local", "declare", "readonly", "typeset")  # a lone assignment, or one of these before it


def _capture(stages: list, captured: dict[str, str]) -> None:
    """Note what a lone assignment sets to a secret's value, and forget a variable set to something else."""
    from occam_commands import head

    if len(stages) != 1 or head(stages[0].words)[0] not in _ASSIGNS:
        return
    for word in stages[0].words:
        name, equals, value = word.partition("=")
        if equals and re.fullmatch(r"[A-Za-z_]\w*", name):
            held = _word_carries(value, 0, captured)
            if held:
                captured[name] = held
            else:
                captured.pop(name, None)
