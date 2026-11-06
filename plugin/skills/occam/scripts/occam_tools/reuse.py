"""Before writing something: does the repository, the standard library or an installed dependency already do it?"""

from __future__ import annotations

import re

from . import files as filesystem, manifests, scan as scanner
from .source import is_test_path

SYNONYMS = [
    {"get", "fetch", "retrieve", "load", "read", "find", "lookup", "query", "pull"},
    {"create", "make", "build", "generate", "new", "construct"},
    {"delete", "remove", "destroy", "drop", "purge", "clear"},
    {"update", "modify", "change", "patch", "edit", "set"},
    {"validate", "verify", "check", "ensure", "assert", "sanitize"},
    {"parse", "decode", "deserialize", "unmarshal", "extract"},
    {"format", "render", "serialize", "encode", "marshal", "stringify", "dump"},
    {"compute", "calculate", "calc", "sum", "total"},
    {"send", "dispatch", "emit", "publish", "post", "notify"},
    {"retry", "backoff", "attempt"}, {"cache", "memoize", "memo", "lru"}, {"date", "datetime", "time", "timestamp"},
    {"user", "account", "customer", "member"}, {"auth", "login", "authenticate", "token", "session"},
    {"money", "price", "amount", "currency", "invoice"}, {"email", "mail"}, {"http", "request", "client", "api"},
    {"config", "settings", "conf", "options"}, {"log", "logger", "logging"}, {"csv", "tsv"}, {"json", "yaml", "toml"},
]
# Capability table: what to reach for before writing it. Purpose-built code comes after these.
CAPABILITIES = [
    ({"retry", "backoff"}, "tenacity or stamina; HTTP clients often have it built in (urllib3 Retry, httpx transports)", "p-retry", "cenkalti/backoff"),
    ({"cache", "memoize", "lru"}, "functools.cache or lru_cache; cachetools for TTL", "lru-cache", "hashicorp/golang-lru"),
    ({"csv", "tsv"}, "csv (stdlib); polars or pandas for large data", "csv-parse", "encoding/csv"),
    ({"parse", "date", "datetime", "timestamp"}, "datetime.fromisoformat (stdlib); dateutil or pendulum", "date-fns or Temporal", "time (stdlib)"),
    ({"validate", "schema"}, "pydantic, or dataclasses plus checks", "zod", "go-playground/validator"),
    ({"email"}, "email-validator; email.utils (stdlib)", "validator", "net/mail (stdlib)"),
    ({"url", "query", "uri"}, "urllib.parse (stdlib)", "URL and URLSearchParams (built in)", "net/url (stdlib)"),
    ({"json"}, "json (stdlib); orjson for speed", "JSON (built in)", "encoding/json (stdlib)"),
    ({"yaml"}, "PyYAML with safe_load", "yaml", "gopkg.in/yaml.v3"),
    ({"toml"}, "tomllib (stdlib 3.11+)", "smol-toml", "BurntSushi/toml"),
    ({"html", "scrape"}, "html.parser (stdlib); beautifulsoup4 or lxml", "cheerio", "golang.org/x/net/html"),
    ({"sanitize", "xss"}, "nh3", "DOMPurify", "bluemonday"),
    ({"password", "hash"}, "argon2-cffi or bcrypt", "argon2", "golang.org/x/crypto/argon2"),
    ({"jwt", "token"}, "pyjwt; secrets (stdlib) for random tokens", "jose", "golang-jwt/jwt"),
    ({"encrypt", "decrypt", "crypto"}, "cryptography", "node:crypto (built in)", "crypto (stdlib)"),
    ({"argument", "args", "cli", "command"}, "argparse (stdlib); typer or click", "commander", "flag (stdlib); cobra"),
    ({"config", "env", "settings"}, "pydantic-settings; python-dotenv", "dotenv", "viper"),
    ({"rate", "limit", "throttle"}, "limits; your gateway may already do this", "bottleneck", "golang.org/x/time/rate"),
    ({"queue", "job", "worker"}, "the task queue already in use; concurrent.futures (stdlib) for local work", "bullmq", "worker pool (stdlib)"),
    ({"http", "client", "request"}, "whichever client is already declared; httpx", "fetch (built in)", "net/http (stdlib)"),
    ({"pdf"}, "pypdf", "pdf-lib", "pdfcpu"), ({"image", "resize"}, "pillow", "sharp", "image (stdlib)"),
    ({"slug"}, "python-slugify", "slugify", "gosimple/slug"), ({"uuid", "guid"}, "uuid (stdlib)", "crypto.randomUUID (built in)", "google/uuid"),
    ({"chunk", "batch", "flatten", "group"}, "itertools (stdlib); more-itertools", "lodash-es, or built-in array methods", "slices (stdlib)"),
    ({"diff", "fuzzy", "levenshtein", "similar"}, "difflib (stdlib); rapidfuzz", "fastest-levenshtein", "agnivade/levenshtein"),
    ({"log", "logger", "logging"}, "logging (stdlib), or the logger already in use", "pino", "log/slog (stdlib)"),
    ({"test", "property", "fuzz"}, "hypothesis", "fast-check", "testing/quick and native fuzzing (stdlib)"),
]


_FILLER = {"with", "for", "the", "and", "from", "into", "that", "this", "using", "use", "of", "to", "in", "on", "by", "an", "or", "it", "is", "at", "as"}


def _words(text: str) -> list[str]:
    spaced = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", text)
    return [w.lower() for w in re.findall(r"[A-Za-z][a-z0-9]*|[A-Z]+", spaced) if len(w) >= 2 and w.lower() not in _FILLER]


def _expand(words: list[str]) -> dict[str, float]:
    expanded = {word: 1.0 for word in words}
    for family in SYNONYMS:
        if family & set(words):
            for member in family:
                expanded.setdefault(member, 0.6)
    return expanded


def _symbols(project) -> list[tuple[str, str, int, str, str]]:
    found = []
    for path, facts in project.facts.items():
        for definition in (facts or {}).get("defs", []):
            if not definition["name"].startswith("__"):
                found.append((definition["name"], path, definition["line"], definition["kind"], definition.get("class") or ""))
        for item in (facts or {}).get("classes", []):
            found.append((item["name"], path, item["line"], "class", ""))
    return found


def search(root, query: str, limit: int = 10, language: str | None = None) -> str:
    result = scanner.run_scan(root)
    project = result.project
    words = _words(query)
    terms = _expand(words)
    references = project.identifier_counts
    scored: list[tuple[float, tuple]] = []
    for symbol in _symbols(project):
        name, path, _, _, owner = symbol
        if language and project.languages.get(path) != language:
            continue
        symbol_words = set(_words(name))
        if not symbol_words:
            continue
        hits = sum(terms.get(word, 0.0) for word in symbol_words)
        hits += 0.25 * sum(terms.get(word, 0.0) for word in set(_words(path.rsplit("/", 1)[-1])) | set(_words(owner)))
        if hits < 0.6:
            continue
        coverage = hits / max(len(words), 1)
        precision = hits / len(symbol_words)
        test_penalty = 0.3 if is_test_path(path) else 1.0
        scored.append((coverage * (0.5 + precision) * test_penalty, symbol))
    scored.sort(key=lambda item: -item[0])
    scored = [item for item in scored if item[0] >= 0.25]
    lines = [f"Looking for: {query}", ""]
    if scored:
        lines.append("Already in this repository:")
        for score, (name, path, line, kind, owner) in scored[:limit]:
            label = f"{owner}.{name}" if owner else name
            lines.append(f"  {path}:{line}  {kind} {label}  (mentions {references.get(name, 0)}, relevance {score:.2f})")
        lines.append("Read the likely ones. A similar name doesn't mean the same semantics, so check validation, ordering, errors and edge cases.")
    else:
        lines.append("Nothing in this repository matches by name. Also search for how it's used, since names vary. A name search isn't proof of absence.")
    manifest = manifests.read_manifests(root, filesystem.list_files(root, None, filesystem.load_config(root)))
    lines += ["", *_capabilities(set(words), manifest)]
    declared = sorted(manifest["python"]) + sorted(manifest["node"]) + sorted(manifest["rust"]) + sorted(manifest["go"])
    if declared:
        shown = ", ".join(declared[:40]) + (f" and {len(declared) - 40} more" if len(declared) > 40 else "")
        lines += ["", f"Declared dependencies (check each one's docs before adding another): {shown}"]
    lines += ["", "Order to look: this repository, standard library, installed dependencies, mature libraries, then your own code.",
              "`occam deps --online --name pypi:NAME` checks a package is real before anyone installs it."]
    return "\n".join(lines)


def _capabilities(words: set[str], manifest: dict) -> list[str]:
    usable = []
    for keys, python, node, go in CAPABILITIES:
        if keys & words:
            parts = []
            if manifest["python"] or not (manifest["node"] or manifest["go"]):
                parts.append(f"Python: {python}")
            if manifest["node"] or not (manifest["python"] or manifest["go"]):
                parts.append(f"JS/TS: {node}")
            if manifest["go"]:
                parts.append(f"Go: {go}")
            usable.append("  " + "; ".join(parts))
    if not usable:
        return ["No common library comes to mind for those words. Check the ecosystem before writing it."]
    return ["Common existing solutions (verify current status, license and fit):", *list(dict.fromkeys(usable))]

