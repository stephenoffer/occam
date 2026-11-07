"""What a change should have reached and didn't, read from the diff and the rest of the repository. These are `gate` notes: each says what it saw, can be wrong, and holds nothing."""

from __future__ import annotations

import ast
import fnmatch
import json
import posixpath
import re
import time
import warnings
from collections import Counter, defaultdict
from collections.abc import Callable, Iterator
from pathlib import Path

from . import files as filesystem, manifests, query, query_code, query_graph, query_repo, rules_config
from .py_helpers import _complexity
from .source import is_test_path, language_of, says_it_is_generated

MAX_NAMES = 12            # names searched per check, since each costs a search of the repository
MAX_LISTED = 4
MAX_NAME_HITS = 80        # more than this and a name is too common to say anything about
MIN_NAME_LENGTH = 4
RUNTIME_LIMIT = 15        # seconds, on top of what gate has already spent, which also has to fit in the command line's own grace
MAX_FILES_FOR_SEARCHES = 60  # past this a change is a sweep, and a search per name would take longer than it tells
WIDE_REACH_FILES = 20
WIDE_REACH_DIRECT = 10
MAX_FILES_FOR_REACH = 5_000   # measured: 5 s at 2,900 files, over two minutes at 7,500
SNAPSHOT_FILES = 3
SNAPSHOT_LINES = 50
SCATTERED_FILES = 30
SCATTERED_FOLDERS = 6
COMPLEX_NOW = 12
COMPLEX_RISE = 5
MIN_SIBLINGS = 3
NAMED_SHARE = 0.8         # how many of a folder's files one file must name to count as listing them
MIN_TWIN_STATEMENTS = 3

_LOCKFILE = re.compile(r"(^|/)(package-lock\.json|npm-shrinkwrap\.json|yarn\.lock|pnpm-lock\.yaml|bun\.lockb?|poetry\.lock|uv\.lock|pdm\.lock|Pipfile\.lock|Cargo\.lock|go\.sum|Gemfile\.lock|composer\.lock)$")
_GENERATED_FROM = re.compile(r"\.(proto|thrift|graphql|gql|fbs|avsc|prisma|sql)$|openapi|swagger|sqlc\.|(^|/)buf\.|codegen|(^|/)Makefile$|(^|/)BUILD(\.bazel)?$|(^|/)generate|\.tmpl$|\.j2$", re.I)
_LOCKS_OF = {"package.json": ("package-lock.json", "npm-shrinkwrap.json", "yarn.lock", "pnpm-lock.yaml", "bun.lock", "bun.lockb"), "pyproject.toml": ("uv.lock", "poetry.lock", "pdm.lock"), "Pipfile": ("Pipfile.lock",),
             "Cargo.toml": ("Cargo.lock",), "go.mod": ("go.sum",), "Gemfile": ("Gemfile.lock",), "composer.json": ("composer.lock",)}
_GO_REQUIRE = re.compile(r"^[ \t]*(?:require[ \t]+)?([\w./-]+\.[\w./-]+)\s+v\d", re.M)
_GEM = re.compile(r"^[ \t]*gem[ \t]+[\"']([\w-]+)[\"'](.*)$", re.M)
_MODEL_FILE = re.compile(r"(^|/)(models?\.py|models?/[^/]+\.py|[^/]+\.entity\.ts|schema\.prisma|entities/[^/]+\.(py|ts|java|kt))$")
_MODEL_FIELD = re.compile(r"\bColumn\(|\bmapped_column\(|\bMapped\[|\bmodels\.\w+Field\(|\bmodels\.ForeignKey\(|@Column\b|@ManyToOne\b|@OneToMany\b|^\s+\w+\s+(?:String|Int|Boolean|DateTime|Float|Json|BigInt|Decimal)\b")
_PY_ENUM_BASES = {"Enum", "IntEnum", "StrEnum", "Flag", "IntFlag"}
_BRACED_ENUM = re.compile(r"\benum\s+(?:class\s+|struct\s+)?(\w+)[^{;\n]*\{([^{}]*)\}")
_ENUM_MEMBER = re.compile(r"^\s*(?:@\w+\s+)?([A-Za-z_]\w*)")
_BUILD_LISTS = re.compile(r"^(index\.\w+|__init__\.py|mod\.rs|lib\.rs|main\.rs|BUILD|BUILD\.bazel|CMakeLists\.txt|meson\.build|Android\.bp|registry\.\w+|routes?\.\w+|urls\.py|plugins?\.\w+)$")
_NOT_REGISTERED_STEMS = {"__init__", "index", "main", "mod", "lib", "conftest", "setup", "types", "constants", "utils"}
_SNAPSHOT = re.compile(r"(^|/)(__snapshots__|snapshots?|golden|goldens|approved)/|\.snap$|\.approved\.\w+$|\.golden$")
_ENV_READ = re.compile(r"""os\.environ(?:\.get\(|\[)\s*["'](\w+)|os\.getenv\(\s*["'](\w+)|process\.env\.(\w+)|process\.env\[["'](\w+)|os\.Getenv\("(\w+)|env::var\("(\w+)|System\.getenv\("(\w+)|ENV(?:\.fetch\(|\[)["'](\w+)""")
_ENV_READ_ANYWHERE = r"os\.environ|os\.getenv|process\.env|os\.Getenv|env::var|System\.getenv"
_ENV_EVERYONE_HAS = {"HOME", "PATH", "USER", "PWD", "CI", "DEBUG", "NODE_ENV", "PORT", "TMPDIR", "TEMP", "TERM", "LANG", "SHELL", "PYTHONPATH", "VIRTUAL_ENV", "HOSTNAME", "XDG_CONFIG_HOME", "XDG_CACHE_HOME", "XDG_DATA_HOME", "EDITOR", "PAGER", "TZ", "NO_COLOR", "GITHUB_ACTIONS", "GITHUB_TOKEN", "LOG_LEVEL"}
_ENV_IS_DECLARED_IN = re.compile(r"(^|/)(\.env\.(example|sample|template)|values\.ya?ml|docker-compose[^/]*\.ya?ml|compose\.ya?ml|Dockerfile[^/]*|app\.ya?ml)$|\.tf$")
_CONTRACT = re.compile(r"\.(proto|thrift|fbs|avsc)$|(^|/)[^/]*schema\.graphql$")
_CONTRACT_OUTPUT = re.compile(r"_pb2(_grpc)?\.py$|\.pb\.(go|cc|h)$|_generated\.\w+$|\.gen\.\w+$|\.g\.dart$")
_HISTORY_FILE = re.compile(r"(^|/)(CHANGELOG|CHANGES|HISTORY|NEWS|RELEASES?)[^/]*$", re.I)
_COMPARED_LITERAL = re.compile(r"""(?:===?|!==?|\bis\b|\bcase\b)\s*(?:(?P<q>["'])(?P<text>[^"'\n\\]{4,80})(?P=q)|(?P<number>\d{4,}))""")
_GUARD = re.compile(r"""^\s*@(?:login_required|\w*(?:auth|permission|admin|role|scope|jwt|token|owner|tenant|access)\w*_required|require[sd]?_\w+|permission_required|PreAuthorize|Secured|RolesAllowed|UseGuards|Authorize|IsAuthenticated|authenticated)\b
                        |(?<!def\s)(?<!function\s)(?<!func\s)\b(?:check|verify|ensure|require|validate|authorize|assert|enforce)_?(?:auth\w*|perm\w*|access|owner\w*|tenant\w*|admin|signature|csrf|token|jwt|role\w*|approval|scope\w*)\s*\(
                        |^\s*permission_classes\s*=|\bauthorize!|\bbefore_action\s+:\w*auth
                        |,\s*(?:requireAuth|verifyToken|isAuthenticated)\s*[,)]|\.use\(\s*(?:requireAuth|verifyToken)\b|(?<!def\s)\b\w*(?:human|require|needs)_?approval\w*\s*\(""", re.I | re.X)
_COMMENT_LINE = re.compile(r"^\s*(?:#|//|\*|/\*|--)")
_DEPRECATED_MARK = r"DeprecationWarning|@deprecated|@Deprecated|#\[deprecated|// Deprecated:"
_MARKS_WHAT_FOLLOWS = re.compile(r"^\s*(?:\*\s*|/\*\*\s*|//\s*)?(?:@deprecated|@Deprecated|#\[deprecated|Deprecated:)")
_ONLY_FILTERS_WARNINGS = re.compile(r"filterwarnings|simplefilter|catch_warnings|pytest\.warns|assertWarns")
_PY_DEF = re.compile(r"^\s*(?:async\s+)?def\s+(\w+)")
_DEFINES = re.compile(r"\b(?:def|function|func|fn|fun|class)\s+(?:\([^)]*\)\s*)?(\w+)|^\s*(?:public|protected|private|static|final|abstract|\s)*[\w<>\[\],.]+\s+(\w+)\s*\(")
_RELATIVE_IMPORT = re.compile(r"""(?:\bfrom\s+|\brequire\(\s*|\bimport\(\s*|^[ \t]*import\s+)["'](\.\.?/[^"']+)["']""", re.M)
_PY_PRIVATE_IMPORT = re.compile(r"^[ \t]*(?:from|import)[ \t]+([A-Za-z_]\w*)((?:\.\w+){0,8}\._[a-z]\w*)", re.M)
_HOST_CALL = re.compile(r"""(?:requests\.\w+|httpx\.\w+|urlopen|fetch|axios\.\w+|http\.(?:Get|Post)|curl|wget)\s*\(?\s*f?["'`]?https?://([\w.-]+)""")
_LOCAL_HOST = re.compile(r"^(?:localhost|127\.|0\.0\.0\.0|example\.|[\w.-]*\.example\.|[\w.-]*\.test$|[\w.-]*\.local$)")
_SQL_TABLE = re.compile(r"\bCREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?(?:\w+\.)?[\"']?(\w+)", re.I)
_RLS = "ENABLE ROW LEVEL SECURITY"
_GATE_STEERING = re.compile(r"(^|/)(\.husky/[^/]+|\.pre-commit-config\.ya?ml|lefthook\.ya?ml|\.git/hooks/[^/]+)$")
_JS_EXPECT = re.compile(r"\bexpect\((.+?)\)\.(not\.)?(\w+)\((.*?)\)")
_JS_LOOSE = {"toBeTruthy", "toBeDefined", "toBeFalsy", "toBeGreaterThan", "toBeGreaterThanOrEqual", "toBeLessThan", "toBeLessThanOrEqual", "toContain", "toMatch"}
_JS_STRICT = {"toBe", "toEqual", "toStrictEqual"}
_LOOSER_THAN_EQUALS = {"GtE", "LtE", "Gt", "Lt", "NotEq", "IsNot", "In", "truthy"}
_UNITTEST_EQUALS = {"assertEqual", "assertEquals", "assertIs", "assertListEqual", "assertDictEqual"}


class Change:
    """One change and what it needs read, each file once, since a sweep would otherwise run one `git show` per check per file."""

    def __init__(self, root: Path, base: str | None, changed: dict, deleted: list, renamed: dict, hunks: list, tracked: list, whole: bool) -> None:
        self.root, self.base, self.revision = root, base, base or "HEAD"
        self.changed, self.deleted, self.renamed, self.hunks, self.tracked, self.whole = changed, deleted, renamed, hunks, tracked, whole
        self._before: dict[str, str | None] = {}
        self._now: dict[str, str | None] = {}

    def before(self, path: str) -> str | None:
        if path not in self._before:
            self._before[path] = filesystem.file_at(self.root, self.revision, self.renamed.get(path, path))
        return self._before[path]

    def now(self, path: str) -> str | None:
        if path not in self._now:
            self._now[path] = filesystem.read_text(self.root / path)
        return self._now[path]

    def added(self, path: str) -> list[str]:
        """Lines this change added to a file. A new file git doesn't track yet has no hunks, so all of it counts."""
        lines = [line for hunk in self.hunks if hunk[0] == path for line in hunk[5]]
        return lines or ((self.now(path) or "").split("\n") if self.before(path) is None else [])

    def removed(self, path: str) -> list[str]:
        return [line for hunk in self.hunks if hunk[0] == path for line in hunk[4]]

    def source_files(self) -> list[str]:
        return [path for path in self.changed if language_of(path) and not is_test_path(path)]


def _note(rule: str, path: str, line: int, message: str, **extra) -> dict:
    return {"rule": rule, "path": path, "line": max(line, 1), "message": message, "category": "change", **extra}


def _listed(places: list[str]) -> str:
    more = f", and {len(places) - MAX_LISTED} more" if len(places) > MAX_LISTED else ""
    return ", ".join(places[:MAX_LISTED]) + more


# ---------------------------------------------------------------- files that aren't the place to edit

def _generated_and_vendored(change: Change) -> Iterator[dict]:
    sources_changed = any(_GENERATED_FROM.search(path) for path in change.changed)
    for path in change.changed:
        if _LOCKFILE.search(path):
            continue
        if rules_config.VENDORED_SOURCE.search(path):
            if change.before(path) is not None:
                yield _note("vendored-edited", path, 1, f"{path} is a vendored copy. The next update overwrites this, and upstream never gets the fix. Change it where it comes from, or say why not.")
        elif not sources_changed and (filesystem.GENERATED_NAMES.search(path) or says_it_is_generated(change.now(path) or "")) and change.before(path) is not None:
            yield _note("generated-edited", path, 1, f"{path} says it's generated, and nothing it could be generated from is in this change. A hand edit is lost at the next build, so change its source. If you regenerated it, say with what.")


def _declared(name: str, text: str) -> set[str]:
    """What a manifest asks for, to tell a dependency change from a script or metadata change. A peer range isn't locked, so it doesn't count, and a manifest that doesn't read as one says nothing."""
    if name in ("package.json", "composer.json"):
        document = json.loads(text)
        sections = ("dependencies", "devDependencies", "optionalDependencies", "require", "require-dev")
        tables = [(section, document.get(section)) for section in sections] if isinstance(document, dict) else []
        return {f"{section}:{key}:{value}" for section, table in tables if isinstance(table, dict) for key, value in table.items()}
    if name == "pyproject.toml":
        return set(manifests._pyproject(text))
    if name == "Cargo.toml":
        return set(manifests._cargo(text))
    if name == "go.mod":
        return set(_GO_REQUIRE.findall(text))
    if name == "Gemfile":
        return {" ".join(found) for found in _GEM.findall(text)}
    return set()


def _ancestors(path: str) -> Iterator[str]:
    folder = posixpath.dirname(path)
    while True:
        yield folder
        if not folder:
            return
        folder = posixpath.dirname(folder)


def _lockfiles(change: Change) -> Iterator[dict]:
    tracked = set(change.tracked)
    for path in change.changed:
        name = posixpath.basename(path)
        if name not in _LOCKS_OF:
            continue
        before, now = change.before(path), change.now(path)
        if before is None or now is None:
            continue
        old_set, new_set = _declared(name, before), _declared(name, now)
        if old_set == new_set or not (old_set and new_set):
            continue
        nearby = [posixpath.join(folder, lock) for folder in _ancestors(path) for lock in _LOCKS_OF[name] if posixpath.join(folder, lock) in tracked]
        if nearby and not any(lock in change.changed for lock in nearby):
            yield _note("lockfile-not-updated", path, 1, f"Dependencies in {path} changed and {nearby[0]} didn't, so a clean install gets something else. Regenerate it with the tool that wrote it.")
    for path in change.changed:
        if _LOCKFILE.search(path) and change.before(path) is None:
            others = [other for other in tracked if posixpath.dirname(other) == posixpath.dirname(path) and other != path and _LOCKFILE.search(other) and _same_family(other, path)]
            if others:
                yield _note("second-lockfile", path, 1, f"{path} is new beside {others[0]}, so this probably used the wrong package manager. Use the one {others[0]} belongs to.")


def _same_family(one: str, other: str) -> bool:
    return any(posixpath.basename(one) in locks and posixpath.basename(other) in locks for locks in _LOCKS_OF.values())


def _migrations(change: Change) -> Iterator[dict]:
    is_migration = rules_config.MIGRATION.search
    for path in change.changed:
        if is_migration(path) and posixpath.basename(path) != "__init__.py" and change.before(path) is not None and change.removed(path) + change.added(path):
            yield _note("migration-edited", path, 1, f"{path} already exists, and anywhere it has run won't run it again. Add a new migration instead, unless this one has never left your branch.")
    if any(is_migration(path) for path in change.changed) or not any(is_migration(path) for path in change.tracked):
        return
    for path in change.changed:
        if _MODEL_FILE.search(path) and any(_MODEL_FIELD.search(line) for line in change.added(path) + change.removed(path)):
            yield _note("model-no-migration", path, 1, f"{path} changes what's stored, and this repository has migrations, but none is in this change.")


# ---------------------------------------------------------------- everything a change must reach

def _bare_name(row_name: str) -> tuple[str, str | None]:
    """The name to search for, and the class it belongs to if any, from an `api` row such as `Client.send(a, b)`."""
    match = re.match(r"[\w.$]+", row_name)
    parts = (match.group(0) if match else row_name).split(".")
    return parts[-1], parts[-2] if len(parts) > 1 else None


def _places_still_using(change: Change, name: str, owner: str | None, defined_in: str, roles: tuple) -> list[str] | None:
    """Where unchanged code uses this name. None if it's too common to say anything about. A file with its own definition of the name means that one, and other files must also name where it comes from, since other things share a method's name."""
    found = query_code.find(change.root, name, None, MAX_LISTED + 4)
    if found["stopped_at_limit"] or found["total"] > MAX_NAME_HITS:
        return None
    stem = "" if posixpath.basename(defined_in).startswith("__init__") else posixpath.splitext(posixpath.basename(defined_in))[0]
    origin = owner or stem
    has_its_own = {row["where"].rsplit(":", 1)[0] for row in found["groups"].get("definition", [])}
    imported_in = {row["where"].rsplit(":", 1)[0] for role in ("import", "test import") for row in found["groups"].get(role, [])}
    places = []
    for role in roles:
        for row in found["groups"].get(role, []):
            path = row["where"].rsplit(":", 1)[0]
            if path in change.changed or path in change.deleted or path in has_its_own or _HISTORY_FILE.search(path):
                continue
            if path in imported_in or role == "text" or _says_where_it_comes_from(change.root / path, origin, name):
                places.append(row["where"])
    return places


def _says_where_it_comes_from(path: Path, origin: str, name: str) -> bool:
    """`billing.charge_card`, or a method of a class this file names. A bare mention of a module used for something else isn't enough."""
    text = filesystem.read_text(path) if origin else None
    if not text:
        return False
    return bool(re.search(rf"\b{re.escape(origin)}(?:\.|::|->){re.escape(name)}\b", text)) or (origin[:1].isupper() and bool(re.search(rf"\b{re.escape(origin)}\b", text)))


_USES = ("call", "reference", "import", "string", "test call", "test reference", "test import")


def _callers(change: Change) -> Iterator[dict]:
    """`query api` knows what became incompatible. Whether anything still depends on the old form is what makes it this change's problem."""
    data = query_code.api(change.root, None, change.revision, 50)
    budget = MAX_NAMES
    for row in data["changed"]:
        if not row["breaking"] or budget <= 0:
            continue
        name, owner = _bare_name(row["name"])
        if len(name) < MIN_NAME_LENGTH:
            continue
        budget -= 1
        places = _places_still_using(change, name, owner, row["where"].rsplit(":", 1)[0], _USES)
        if places:
            path, line = row["where"].rsplit(":", 1)
            yield _note("caller-not-updated", path, int(line), f"{row['name']} changed ({'; '.join(row['breaking'])}), and these use it and weren't touched: {_listed(places)}. Check each, or keep the old form working.")
    for row in data["removed"]:
        if budget <= 0:
            break
        name, owner = _bare_name(row["name"])
        if len(name) < MIN_NAME_LENGTH:
            continue
        budget -= 1
        path, line = row["where"].rsplit(":", 1)
        places = _places_still_using(change, name, owner, path, (*_USES, "text"))
        if places:
            yield _note("removed-still-named", path, int(line), f"{row['name']} is gone from {path}, and these still name it: {_listed(places)}. Update them, or say why they're fine, since a string or a doc fails later than an import.")


def _python_enums(text: str) -> dict[str, list[str]]:
    enums = {}
    for node in ast.walk(ast.parse(text)):
        if isinstance(node, ast.ClassDef) and {getattr(base, "attr", getattr(base, "id", "")) for base in node.bases} & _PY_ENUM_BASES:
            enums[node.name] = [target.id for item in node.body if isinstance(item, ast.Assign) for target in item.targets if isinstance(target, ast.Name) and not target.id.startswith("_")]
    return enums


def _braced_enums(text: str) -> dict[str, list[str]]:
    enums = {}
    for name, body in _BRACED_ENUM.findall(text):
        first_part = body.split(";")[0]  # a Java enum's methods come after the first semicolon
        members = [found.group(1) for piece in first_part.split(",") for found in [_ENUM_MEMBER.match(re.sub(r"//[^\n]*|/\*.*?\*/", "", piece, flags=re.S))] if found]
        enums[name] = members
    return enums


def _enums_in(path: str, text: str) -> dict[str, list[str]]:
    return _python_enums(text) if language_of(path) == "python" else _braced_enums(text)


def _new_cases(change: Change) -> Iterator[dict]:
    """A new enum member, and a file that already lists most of the old ones and not this. A change that updates only one list looks finished."""
    for path in change.source_files():
        before, now = change.before(path), change.now(path)
        if before is None or now is None:
            continue
        old, new = _enums_in(path, before), _enums_in(path, now)
        for enum, members in new.items():
            siblings = set(old.get(enum, ()))
            fresh = [member for member in members if member not in siblings]
            if enum in old and fresh and len(siblings) >= 2:
                yield from _unhandled(change, path, enum, siblings, fresh)


def _unhandled(change: Change, path: str, enum: str, siblings: set, fresh: list) -> Iterator[dict]:
    hits, _ = query.search(change.root, enum, None, fixed=True, word=True, limit=MAX_NAME_HITS)
    for other in sorted({hit.path for hit in hits} - set(change.changed)):
        text = filesystem.read_text(change.root / other) or ""
        used = set(re.findall(rf"\b{re.escape(enum)}(?:\.|::)(\w+)", text))
        missing = [member for member in fresh if member not in used]
        if missing and len(used & siblings) >= max(2, round(len(siblings) * 0.6)):
            yield _note("new-case-not-handled", other, 1, f"{other} handles {len(used & siblings)} of {enum}'s {len(siblings)} other members and not the new {missing[0]}. Check it doesn't need it.")


def _unregistered(change: Change) -> Iterator[dict]:
    """A new file in a folder whose files are all named somewhere, in a build list, a barrel or a registry, when this one isn't. Nothing then builds or calls it."""
    by_folder: dict[str, list[str]] = defaultdict(list)
    for path in change.tracked:
        by_folder[posixpath.dirname(path)].append(path)
    for path in change.changed:
        stem = posixpath.splitext(posixpath.basename(path))[0]
        if not language_of(path) or is_test_path(path) or stem in _NOT_REGISTERED_STEMS or change.before(path) is not None:
            continue
        folder = posixpath.dirname(path)
        siblings = [posixpath.splitext(posixpath.basename(other))[0] for other in by_folder[folder] if other != path and language_of(other) == language_of(path)]
        siblings = [name for name in siblings if name not in _NOT_REGISTERED_STEMS and len(name) >= 3]
        if len(siblings) < MIN_SIBLINGS:
            continue
        lists = [other for place in {folder, posixpath.dirname(folder)} for other in by_folder[place] if _BUILD_LISTS.match(posixpath.basename(other)) and other != path]
        for listing in lists:
            text = filesystem.read_text(change.root / listing) or ""
            named = sum(1 for name in siblings if re.search(rf"\b{re.escape(name)}\b", text))
            if named / len(siblings) >= NAMED_SHARE and not re.search(rf"\b{re.escape(stem)}\b", text) and not _named_elsewhere(change, path, stem):
                yield _note("unregistered-file", path, 1, f"{listing} names {named} of the {len(siblings)} other files here and not {posixpath.basename(path)}, and nothing else names it, so this may never be built or reached.")
                break


def _named_elsewhere(change: Change, path: str, stem: str) -> bool:
    hits, stopped = query.search(change.root, stem, None, fixed=True, word=True, limit=MAX_NAME_HITS)
    return stopped or any(hit.path != path for hit in hits)


def _strip_docstring(body: list) -> list:
    return body[1:] if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant) and isinstance(body[0].value.value, str) else body


class _WithoutAwait(ast.NodeTransformer):
    def visit_Await(self, node: ast.Await) -> ast.AST:
        return self.visit(node.value)


def _body_shape(function: ast.AST) -> str:
    return "\n".join(ast.dump(_WithoutAwait().visit(statement)) for statement in _strip_docstring(function.body))


def _python_functions(text: str) -> dict[str, ast.AST]:
    return {node.name: node for node in ast.walk(ast.parse(text)) if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))}


def _twin_names(name: str) -> list[str]:
    return [name, f"a{name}", f"async_{name}", f"{name}_async", f"{name}_sync", *([name[1:]] if name.startswith("a") else []), *([name[6:]] if name.startswith("async_") else []), *([name[:-6]] if name.endswith(("_async",)) else []), *([name[:-5]] if name.endswith("_sync") else [])]


def _changed_python_functions(change: Change) -> Iterator[tuple[str, str, str]]:
    for path in change.source_files():
        if language_of(path) != "python":
            continue
        before, now = change.before(path), change.now(path)
        if before is None or now is None:
            continue
        old, new = _python_functions(before), _python_functions(now)
        for name, function in old.items():
            if name in new and len(_strip_docstring(function.body)) >= MIN_TWIN_STATEMENTS and _body_shape(function) != _body_shape(new[name]):
                yield path, name, _body_shape(function)


def _twins(change: Change) -> Iterator[dict]:
    """The same body elsewhere, under this name or its sync or async sibling, that this change left as it was. A fix to one copy is often owed to the other."""
    for path, name, old_shape in list(_changed_python_functions(change))[:MAX_NAMES]:
        hits, _ = query.search(change.root, [f"def {candidate}" for candidate in _twin_names(name)], None, fixed=True, word=True, limit=MAX_NAME_HITS)
        for other in sorted({hit.path for hit in hits}):
            text = change.now(other) if language_of(other) == "python" else None
            for candidate, function in _python_functions(text).items() if text else ():
                is_itself = other == path and candidate == name
                if candidate in _twin_names(name) and not is_itself and _body_shape(function) == old_shape:
                    yield _note("twin-left-behind", path, 1, f"{name} changed here, and {other} has {candidate} with the old body. If this was a fix, that copy still has the bug.")


# ---------------------------------------------------------------- tests

def _assertions_of(function: ast.AST) -> list[tuple[str, str, ast.AST | None]]:
    """(what's checked, how, against what) for each simple assertion in one test."""
    found = []
    for node in ast.walk(function):
        if isinstance(node, ast.Assert):
            test = node.test
            if isinstance(test, ast.Compare) and len(test.ops) == 1:
                found.append((ast.unparse(test.left), type(test.ops[0]).__name__, test.comparators[0]))
            elif isinstance(test, (ast.Name, ast.Attribute, ast.Call)):
                found.append((ast.unparse(test), "truthy", None))
        elif isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.args:
            if node.func.attr in _UNITTEST_EQUALS and len(node.args) >= 2:
                found.append((ast.unparse(node.args[0]), "Eq", node.args[1]))
            elif node.func.attr in ("assertTrue", "assertIsNotNone", "assertGreater", "assertLess", "assertIn"):
                found.append((ast.unparse(node.args[0]), "truthy", None))
    return found


def _is_literal(node: ast.AST | None) -> bool:
    try:
        ast.literal_eval(node)
        return node is not None
    except (ValueError, TypeError, SyntaxError):
        return False


def _python_test_changes(change: Change, path: str, before: str, now: str) -> Iterator[dict]:
    old_functions, new_functions = _python_functions(before), _python_functions(now)
    for name, function in old_functions.items():
        if not name.startswith("test") or name not in new_functions or _body_shape(function) == _body_shape(new_functions[name]):
            continue
        new = _assertions_of(new_functions[name])
        for checked, how, expected in _assertions_of(function):
            if how not in ("Eq", "Is"):
                continue
            same = [item for item in new if item[0] == checked]
            kept = [item for item in same if item[1] in ("Eq", "Is")]
            if same and not kept and all(item[1] in _LOOSER_THAN_EQUALS for item in same):
                yield _note("assertion-loosened", path, new_functions[name].lineno, f"{name} used to pin {checked} to an exact value and now accepts more. Say what makes the looser check right.")
            elif kept and _is_literal(expected) and _is_literal(kept[0][2]) and ast.literal_eval(expected) != ast.literal_eval(kept[0][2]) and not any(ast.literal_eval(expected) == ast.literal_eval(item[2]) for item in kept if _is_literal(item[2])):
                yield _note("expected-value-rewritten", path, new_functions[name].lineno, f"{name} expected {ast.unparse(expected)[:40]} and now expects {ast.unparse(kept[0][2])[:40]}. Say why the old value was wrong, from the requirement rather than from what the code now prints.")


def _js_test_changes(change: Change, path: str) -> Iterator[dict]:
    old = {found.group(1): found for line in change.removed(path) for found in [_JS_EXPECT.search(line)] if found}
    for line in change.added(path):
        found = _JS_EXPECT.search(line)
        before = old.get(found.group(1)) if found else None
        if not before or before.group(3) not in _JS_STRICT:
            continue
        if found.group(3) in _JS_LOOSE or found.group(2):
            yield _note("assertion-loosened", path, 1, f"expect({found.group(1)[:40]}) used {before.group(3)} and now uses {found.group(3)}, which accepts more. Say what makes the looser check right.")
        elif found.group(3) in _JS_STRICT and found.group(4) != before.group(4):
            yield _note("expected-value-rewritten", path, 1, f"expect({found.group(1)[:40]}) expected {before.group(4)[:40]} and now expects {found.group(4)[:40]}. Say why the old value was wrong, from the requirement rather than from what the code now prints.")


def _test_changes(change: Change) -> Iterator[dict]:
    for path in change.changed:
        if not is_test_path(path):
            continue
        before, now = change.before(path), change.now(path)
        if before is None or now is None:
            continue
        if language_of(path) == "python":
            yield from _python_test_changes(change, path, before, now)
        elif language_of(path) in ("javascript", "typescript"):
            yield from _js_test_changes(change, path)


def _snapshots(change: Change) -> Iterator[dict]:
    files = [path for path in change.changed if _SNAPSHOT.search(path) and change.before(path) is not None]
    lines = sum(len(hunk[4]) + len(hunk[5]) for hunk in change.hunks if hunk[0] in files)
    if files and (len(files) >= SNAPSHOT_FILES or lines >= SNAPSHOT_LINES):
        yield _note("snapshots-rewritten", files[0], 1, f"{len(files)} snapshot or golden files changed, {lines} lines. A bulk update accepts whatever the code now does, so read each difference and say why it's right.")


def _looks_like_a_specific_input(literal: str) -> bool:
    """A plain word such as 'archived' is what a new feature compares with. An id or a phrase, less so."""
    return not literal.isalpha() or not literal.islower()


def _special_cased(change: Change) -> Iterator[dict]:
    """New code comparing with a value found elsewhere only in a test this change didn't touch. That's how a failing test gets passed without the behavior being there."""
    budget = MAX_NAMES
    for path in change.source_files():
        before = change.before(path) or ""
        for line in change.added(path):
            for found in _COMPARED_LITERAL.finditer(line):
                literal = found.group("text") or found.group("number")
                if literal in before or budget <= 0 or not _looks_like_a_specific_input(literal):
                    continue
                budget -= 1
                hits, _ = query.search(change.root, literal, None, fixed=True, limit=MAX_NAME_HITS)
                elsewhere = [hit for hit in hits if hit.path != path]
                tests = [hit for hit in elsewhere if is_test_path(hit.path)]
                if tests and len(tests) == len(elsewhere) and not any(hit.path in change.changed for hit in tests):
                    yield _note("test-input-special-cased", path, 1, f"This compares with {literal!r}, which appears elsewhere only in a test this change left alone ({tests[0].path}:{tests[0].line}). Check the code handles the behavior and not that one input.")


# ---------------------------------------------------------------- what the change takes away

def _squeezed(text: str) -> str:
    return re.sub(r"\s+", "", text)


def _guards(change: Change) -> Iterator[dict]:
    """A guard gone with nothing like it put back. Agents have dropped approval checks and auth decorators during refactors without saying so. A rename or a move shows up as something like it being added."""
    added_anywhere = _squeezed("\n".join(line for path in change.changed for line in change.added(path)))
    seen = set()
    for path, _, first_old, _, removed, added in change.hunks:
        if is_test_path(path) or not language_of(path) or any(_GUARD.search(line) for line in added):
            continue
        for offset, line in enumerate(removed):
            found = _GUARD.search(line)
            if not found or _COMMENT_LINE.match(line) or (path, found.group(0)) in seen or _squeezed(found.group(0)) in added_anywhere:
                continue
            seen.add((path, found.group(0)))
            yield _note("guard-removed", path, first_old + offset, f"This removes `{found.group(0).strip()[:50]}`, and nothing in the change puts it back. If that's intended, say so in your report and why it's safe.")


def _complexity_rose(change: Change) -> Iterator[dict]:
    for path in change.source_files():
        if language_of(path) != "python":
            continue
        before, now = change.before(path), change.now(path)
        if before is None or now is None:
            continue
        old = _python_functions(before)
        for name, function in _python_functions(now).items():
            if name in old and _complexity(function) >= COMPLEX_NOW and _complexity(function) - _complexity(old[name]) >= COMPLEX_RISE:
                yield _note("complexity-rose", path, function.lineno, f"{name} went from complexity {_complexity(old[name])} to {_complexity(function)}. Each small addition passes its checks while the whole gets harder to change. Could the new part be its own function?")


# ---------------------------------------------------------------- what the rest of the repository expects

def _env_vars(change: Change) -> Iterator[dict]:
    declares_elsewhere = any(_ENV_IS_DECLARED_IN.search(path) for path in change.tracked)
    budget = MAX_NAMES
    for path in change.source_files():
        before = change.before(path) or ""
        for line in change.added(path):
            for found in _ENV_READ.finditer(line):
                name = next(group for group in found.groups() if group)
                if name in _ENV_EVERYONE_HAS or name in before or budget <= 0 or not declares_elsewhere:
                    continue
                budget -= 1
                hits, _ = query.search(change.root, name, None, fixed=True, word=True, limit=MAX_NAME_HITS)
                if not [hit for hit in hits if hit.path != path and (not language_of(hit.path) or language_of(hit.path) in ("shell", "terraform") or hit.path.endswith(".md"))]:
                    yield _note("env-var-undeclared", path, 1, f"This reads {name}, and no config, deployment file or doc here mentions it, so a deployment won't know to set it.")
    yield from _config_bypassed(change)


def _config_bypassed(change: Change) -> Iterator[dict]:
    """If almost every read of the environment is in one or two files, those are the config layer, and a new read elsewhere goes around it."""
    new_reads = [path for path in change.source_files() if any(_ENV_READ.search(line) for line in change.added(path))]
    if not new_reads:
        return
    hits, stopped = query.search(change.root, _ENV_READ_ANYWHERE, None, limit=MAX_NAME_HITS * 5)
    counts = Counter(hit.path for hit in hits if not is_test_path(hit.path) and hit.path not in new_reads)
    total = sum(counts.values())
    if stopped or total < 5:
        return
    top = counts.most_common(2)
    if sum(count for _, count in top) / total >= 0.8:
        for path in new_reads:
            yield _note("config-bypassed", path, 1, f"This reads the environment directly, and nearly every other read is in {top[0][0]}. Add it there.")


def _reach(change: Change) -> Iterator[dict]:
    if not change.whole or len(change.tracked) > MAX_FILES_FOR_REACH:
        return
    data = query_graph.impact(change.root, None, True, change.base, 3)
    if data["source_total"] >= WIDE_REACH_FILES or data["direct_total"] >= WIDE_REACH_DIRECT:
        path = next(iter(change.changed))
        yield _note("wide-reach", path, 1, f"This reaches {data['source_total']} other source files and {data['tests_total']} tests. `occam query impact --changed` lists them. Run those, not only the tests beside it.")


def _contracts(change: Change) -> Iterator[dict]:
    if not any(_CONTRACT_OUTPUT.search(path) for path in change.tracked) or any(_CONTRACT_OUTPUT.search(path) for path in change.changed):
        return
    for path in change.changed:
        if _CONTRACT.search(path):
            yield _note("schema-not-regenerated", path, 1, f"{path} changed and no generated code did, though this repository tracks some. Regenerate it, and check who else reads this format.")


def _name_deprecated_by(hit: query.Hit, lines: list[str]) -> str | None:
    """A mark above a definition names what follows it, and a warning inside a Python function names that function. Text that only mentions deprecation names nothing."""
    if _ONLY_FILTERS_WARNINGS.search(hit.text):
        return None
    if _MARKS_WHAT_FOLLOWS.search(hit.text):
        for line in lines[hit.line:hit.line + 6]:
            found = _DEFINES.search(line)
            if found:
                return next(group for group in found.groups() if group)
        return None
    if "DeprecationWarning" in hit.text:
        for line in reversed(lines[max(0, hit.line - 12):hit.line]):
            found = _PY_DEF.match(line)
            if found:
                return found.group(1)
    return None


def _deprecated_here(change: Change) -> Iterator[dict]:
    """New use of something this repository has marked deprecated. Agents copy the most common pattern in a repository, and mid-migration that's the old one."""
    calls = {path: {word for line in change.added(path) for word in re.findall(r"\b([A-Za-z_]\w{3,})\s*\(", line)} for path in change.source_files()}
    if not any(calls.values()):
        return
    hits, _ = query.search(change.root, _DEPRECATED_MARK, None, limit=MAX_NAME_HITS * 3)
    deprecated: dict[str, str] = {}
    for hit in hits:
        if not is_test_path(hit.path):
            name = _name_deprecated_by(hit, (filesystem.read_text(change.root / hit.path) or "").split("\n"))
            if name:
                deprecated.setdefault(name, f"{hit.path}:{hit.line}")
    for path, words in calls.items():
        for name in sorted(words & set(deprecated)):
            if not deprecated[name].startswith(f"{path}:"):
                yield _note("uses-deprecated-here", path, 1, f"This calls {name}, which {deprecated[name]} marks deprecated. Use what replaced it.")


def _stale_base(change: Change) -> Iterator[dict]:
    behind = filesystem.run_git(change.root, "rev-list", "--count", "HEAD..@{upstream}", "--", *list(change.changed)[:50])
    if behind and behind.strip() not in ("", "0"):
        yield _note("stale-base", next(iter(change.changed)), 1, f"Your upstream has {behind.strip()} commits you don't, touching files in this change, as of your last fetch. Bring them in before calling this done, since they may have moved what you built on.")


def _owners(change: Change) -> Iterator[dict]:
    owners = {path: query_repo.codeowners(change.root, path) for path in list(change.changed)[:200]}
    distinct = sorted({owner for owner in owners.values() if owner})
    if len(distinct) > 1:
        yield _note("crosses-owners", next(iter(change.changed)), 1, f"This touches code owned by {_listed(distinct)}. Each of them has to accept it, so check it isn't really several changes.")


_ONLY_SOMETIMES_ABOUT_AGENTS = re.compile(r"(^|/)\.vscode/settings\.json$|\.code-workspace$")
_ABOUT_AGENTS = re.compile(r"chat\.|copilot|\bmcp\b|autoApprove|\.tools\.", re.I)


def _agent_settings(change: Change) -> Iterator[dict]:
    for path in change.changed:
        if not (rules_config.AGENT_SETTINGS.search(path) or _GATE_STEERING.search(path)):
            continue
        if _ONLY_SOMETIMES_ABOUT_AGENTS.search(path) and not any(_ABOUT_AGENTS.search(line) for line in change.added(path) + change.removed(path)):
            continue
        yield _note("agent-config-changed", path, 1, f"{path} decides what agents may do or which checks run before a commit. A person should see this change.")


def _boundaries(change: Change) -> Iterator[dict]:
    packages = {posixpath.dirname(path) for path in change.tracked if posixpath.basename(path) == "package.json"}
    top_folders = {path.split("/")[0] for path in change.tracked if "/" in path}

    def package_of(path: str) -> str | None:
        return next((folder for folder in _ancestors(path) if folder in packages), None)

    for path in change.source_files():
        language = language_of(path)
        for line in change.added(path):
            if language in ("javascript", "typescript"):
                for spec in _RELATIVE_IMPORT.findall(line):
                    target = posixpath.normpath(posixpath.join(posixpath.dirname(path), spec))
                    mine, theirs = package_of(path), package_of(target + "/")
                    if mine is not None and theirs is not None and mine != theirs and not target.startswith(".."):
                        yield _note("crosses-boundary", path, 1, f"{spec} reaches into {theirs or 'the root package'} from {mine or 'the root package'} by relative path. Import it as a declared dependency, or a hermetic build fails.")
            elif language == "python":
                for top, private in _PY_PRIVATE_IMPORT.findall(line):
                    if path.split("/")[0] != top and top in top_folders:
                        yield _note("crosses-boundary", path, 1, f"This imports {top}{private}, a private part of another package. Use its public API, or give it one.")


def _new_hosts(change: Change) -> Iterator[dict]:
    budget = MAX_NAMES
    for path in change.source_files():
        for line in change.added(path):
            found = _HOST_CALL.search(line)
            if not found or _LOCAL_HOST.match(found.group(1)) or budget <= 0:
                continue
            budget -= 1
            hits, _ = query.search(change.root, found.group(1), None, fixed=True, limit=MAX_NAME_HITS)
            if not [hit for hit in hits if hit.path != path]:
                yield _note("new-outbound-host", path, 1, f"This sends a request to {found.group(1)}, which nothing else here mentions. Check it's meant to, since code told to do this by a page or an issue looks just the same.")


def _row_level_security(change: Change) -> Iterator[dict]:
    is_sql = [path for path in change.changed if path.endswith(".sql") or rules_config.MIGRATION.search(path)]
    new_tables = [(path, table) for path in is_sql for line in change.added(path) for table in _SQL_TABLE.findall(line)]
    if not new_tables:
        return
    hits, _ = query.search(change.root, _RLS, None, fixed=True, ignore_case=True, limit=5)
    if not hits:
        return
    everything_here = "\n".join(change.now(path) or "" for path in is_sql)  # a later migration in the same change can enable it
    for path, table in new_tables:
        if not re.search(rf"\b{re.escape(table)}\b[^;]*{_RLS}", everything_here, re.I | re.S):
            yield _note("table-without-rls", path, 1, f"This creates {table}, and other tables here enable row level security. Without it, this one is readable by anyone with the client key.")


def _scattered(change: Change) -> Iterator[dict]:
    source = [path for path in change.source_files() if not path.endswith(".md")]
    folders = {path.split("/")[0] for path in source if "/" in path}
    if len(source) >= SCATTERED_FILES or len(folders) >= SCATTERED_FOLDERS:
        yield _note("scattered-change", source[0], 1, f"{len(source)} source files across {len(folders)} top-level folders. Oversized changes get rejected for size alone and reviewed less closely. Split it by concern if you can.")


# Reading only the diff and files it names, so these stay true on a partial read, when "nothing else mentions it" can't be known. They're cheap, so they run first.
WITHIN_THE_DIFF: tuple[Callable[[Change], Iterator[dict]], ...] = (_agent_settings, _scattered, _guards, _generated_and_vendored, _lockfiles, _migrations, _test_changes, _snapshots, _complexity_rose, _stale_base)
ACROSS_THE_REPOSITORY: tuple[Callable[[Change], Iterator[dict]], ...] = (_callers, _new_cases, _unregistered, _twins, _special_cased, _env_vars, _contracts, _deprecated_here, _owners, _boundaries, _new_hosts, _row_level_security, _reach)
CHECKS = (*WITHIN_THE_DIFF, *ACROSS_THE_REPOSITORY)


def _label(check: Callable) -> str:
    return check.__name__.strip("_").replace("_", " ")


def _silenced(note: dict, config: dict) -> bool:
    """`.occam.json` speaks for these as for the scanner's rules."""
    return note["rule"] in config.get("disable", []) or any(fnmatch.fnmatch(note["path"], pattern) or note["path"].startswith(pattern.rstrip("/") + "/") for pattern in config.get("ignore", []))


def notes(root: Path, base: str | None, changed: dict, deleted: list, renamed: dict, whole: bool = True, checks: tuple = CHECKS, budget: float = RUNTIME_LIMIT) -> tuple[list[dict], list[str]]:
    """What this change seems to have left out, and which checks couldn't run. A check that breaks is listed as not run, and doesn't take the gate with it."""
    hunks = filesystem.diff_hunks(root, base)
    if hunks is None or not changed:
        return [], []
    change = Change(root, base, changed, deleted, renamed, hunks, filesystem.tracked_files(root) or [], whole)
    config = filesystem.load_config(root)
    found: list[dict] = []
    not_run: list[str] = []
    started = time.monotonic()
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", SyntaxWarning)  # a repository's own bad escapes aren't this tool's output
        for check in checks:
            needs_everything = (len(changed) > MAX_FILES_FOR_SEARCHES or not whole) and check in ACROSS_THE_REPOSITORY  # on a partial read, "nothing else uses it" can't be known
            if needs_everything or time.monotonic() - started > budget:
                not_run.append(_label(check))
                continue
            try:
                found += list(check(change))
            except Exception:  # occam: ignore[swallowed-exception] reported as not run, so a broken check says so rather than passing
                not_run.append(_label(check))
    return [note for note in found if not _silenced(note, config)], not_run
