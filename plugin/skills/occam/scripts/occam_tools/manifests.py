"""Reading dependency manifests without third-party parsers, and deciding what an import name refers to."""

from __future__ import annotations

import ast
import json
import os
import posixpath
import re
import shutil
import subprocess
import sys
from collections.abc import Callable, Iterable
from pathlib import Path

from . import files as filesystem

# Import names that differ from their distribution names.
IMPORT_TO_DIST = {
    "yaml": "pyyaml", "PIL": "pillow", "cv2": "opencv-python", "sklearn": "scikit-learn", "bs4": "beautifulsoup4", "dateutil": "python-dateutil",
    "dotenv": "python-dotenv", "jwt": "pyjwt", "Crypto": "pycryptodome", "OpenSSL": "pyopenssl", "attr": "attrs", "git": "gitpython",
    "serial": "pyserial", "magic": "python-magic", "docx": "python-docx", "pptx": "python-pptx", "multipart": "python-multipart", "jose": "python-jose",
    "psycopg2": "psycopg2-binary", "MySQLdb": "mysqlclient", "google": "google-api-core", "grpc": "grpcio", "skimage": "scikit-image",
    "fitz": "pymupdf", "pkg_resources": "setuptools", "ruamel": "ruamel.yaml", "zmq": "pyzmq", "win32api": "pywin32", "Levenshtein": "python-levenshtein",
    "slugify": "python-slugify", "faiss": "faiss-cpu", "tensorflow": "tensorflow", "wx": "wxpython", "nacl": "pynacl", "usb": "pyusb", "typing_extensions": "typing-extensions",
    "rest_framework": "djangorestframework", "github": "pygithub", "bson": "pymongo", "gridfs": "pymongo", "ldap": "python-ldap", "telegram": "python-telegram-bot",
    "cairo": "pycairo", "gi": "pygobject",
}
# Other distributions that install the same import name, so declaring any of them declares it.
DIST_VARIANTS = {
    "cv2": ("opencv-python-headless", "opencv-contrib-python", "opencv-contrib-python-headless"), "PIL": ("pillow-simd",), "faiss": ("faiss-gpu",),
    "magic": ("python-magic-bin",), "Crypto": ("pycrypto",), "tensorflow": ("tensorflow-cpu", "tensorflow-gpu", "tensorflow-macos", "tensorflow-intel"),
}
# Import names many distributions share, each named after it: azure-storage-blob installs azure.storage.blob. Only these match by prefix,
# since elsewhere flask-login installs flask_login, not flask.
NAMESPACE_ROOTS = {"google", "opentelemetry", "azure", "zope", "jaraco", "sphinxcontrib", "backports", "llama_index"}
# Python packages common enough that an import of one is a real package, missing or undeclared here, not an invented name. Short on purpose:
# an invented package is usually an obscure name, and `deps --online` checks the rest.
WELL_KNOWN = {
    "numpy", "pandas", "scipy", "matplotlib", "seaborn", "plotly", "requests", "httpx", "aiohttp", "urllib3", "flask", "django", "fastapi", "starlette",
    "uvicorn", "gunicorn", "pydantic", "sqlalchemy", "alembic", "psycopg", "pymysql", "redis", "celery", "boto3", "botocore", "jinja2", "click", "typer",
    "rich", "tqdm", "pytest", "hypothesis", "torch", "torchvision", "tensorflow", "keras", "jax", "transformers", "datasets", "tokenizers", "polars",
    "pyarrow", "dask", "ray", "numba", "networkx", "sympy", "statsmodels", "xgboost", "lightgbm", "openai", "anthropic", "langchain", "lxml", "openpyxl",
    "xlrd", "markdown", "docutils", "sphinx", "toml", "tomli", "msgpack", "orjson", "ujson", "protobuf", "websockets", "paramiko", "cryptography",
    "kubernetes", "docker", "pymongo", "elasticsearch", "kafka", "pika", "prometheus_client", "opentelemetry", "sentry_sdk", "structlog", "loguru",
    "marshmallow", "attrs", "cachetools", "tenacity", "filelock", "psutil", "packaging", "setuptools", "wheel", "pip", "six", "certifi", "chardet",
    "idna", "pytz", "tzdata", "arrow", "pendulum", "faker", "freezegun", "responses", "moto", "playwright", "selenium", "scrapy", "PyQt5", "PySide6",
    "pygame", "tkinter", "ipywidgets", "IPython", "nbformat", "jupyter", "streamlit", "gradio", "dash", "bokeh", "altair", "duckdb", "pyspark",
} | set(IMPORT_TO_DIST)
NODE_BUILTINS = {"assert", "async_hooks", "buffer", "child_process", "cluster", "console", "constants", "crypto", "dgram", "diagnostics_channel", "dns",
                 "domain", "events", "fs", "http", "http2", "https", "inspector", "module", "net", "os", "path", "perf_hooks", "process", "punycode",
                 "querystring", "readline", "repl", "stream", "string_decoder", "sys", "test", "timers", "tls", "trace_events", "tty", "url", "util", "v8",
                 "vm", "wasi", "worker_threads", "zlib"}
# Removed from recent Python versions, but a project may pin an older one, so these aren't invented packages.
REMOVED_STDLIB = {"aifc", "asynchat", "asyncore", "audioop", "cgi", "cgitb", "chunk", "crypt", "distutils", "imghdr", "imp", "lib2to3", "mailcap", "msilib", "nis", "nntplib",
                  "ossaudiodev", "pipes", "smtpd", "sndhdr", "spwd", "sunau", "telnetlib", "uu", "xdrlib"}
RUST_ROOTS = {"std", "core", "alloc", "crate", "self", "super", "proc_macro", "test"}
PLATFORM_MODULES = {"os", "sys", "signal", "socket", "select", "time", "io", "mmap", "fcntl", "termios", "resource", "curses", "ctypes", "asyncio", "subprocess", "errno",
                    "multiprocessing", "locale", "msvcrt", "winreg", "stat", "posix", "pty", "tty", "ssl", "shutil", "tempfile", "gc", "threading", "readline", "webbrowser"}
COMPETING = [
    ("HTTP clients", {"requests", "httpx", "aiohttp", "urllib3", "axios", "got", "node-fetch", "superagent", "ky", "reqwest", "hyper"}),
    ("web frameworks", {"flask", "fastapi", "django", "starlette", "tornado", "bottle", "express", "koa", "fastify", "hapi"}),
    ("date libraries", {"moment", "dayjs", "date-fns", "luxon", "arrow", "pendulum"}),
    ("validation libraries", {"joi", "zod", "yup", "ajv", "pydantic", "marshmallow", "cerberus", "voluptuous"}),
    ("test runners", {"jest", "mocha", "vitest", "ava", "jasmine", "nose", "nose2"}),
    ("ORMs", {"sqlalchemy", "peewee", "tortoise-orm", "pony", "prisma", "typeorm", "sequelize", "drizzle-orm", "knex"}),
    ("task queues", {"celery", "rq", "dramatiq", "huey", "bull", "bullmq", "agenda"}),
    ("utility libraries", {"lodash", "underscore", "ramda"}),
    ("state managers", {"redux", "zustand", "mobx", "recoil", "jotai"}),
    ("CSS frameworks", {"tailwindcss", "bootstrap", "bulma"}),
    ("formatters", {"black", "yapf", "autopep8", "prettier"}),
]
_REQUIREMENT_NAME = re.compile(r"^\s*([A-Za-z0-9][A-Za-z0-9._-]*)")
_SECTION = re.compile(r"^\s*\[+([^\]]+)\]+\s*$")
_QUOTED = re.compile(r""""([^"\n]*)"|'([^'\n]*)'""")
_CODE = re.compile(r"""(?:[^"'#]|"[^"\n]*"|'[^'\n]*')*""")  # a TOML line up to a comment, which can't start inside a string
_INLINE_TABLE = re.compile(r"\{[^{}]*\}")
# Arrays of requirement strings, by section and key. The sections with no key here hold one array per group or extra.
_ARRAYS = {("project", "dependencies"), ("build-system", "requires"), ("tool.uv", "dev-dependencies")}
_GROUPS = {"project.optional-dependencies", "dependency-groups", "tool.pdm.dev-dependencies"}
_DEV_SECTION = re.compile(r"^(?:build-system|dependency-groups|tool\.uv)$|(?:^|\.)dev-dependencies$|\.group\.(?!main\.)")
_DEV_FILE = re.compile(r"(?:^|[-_.])(?:dev|develop|development|tests?|testing|lint|docs?|ci|build|typing)(?:[-_.]|$)", re.I)
_MANIFEST_NAMES = {"pyproject.toml", "setup.py", "setup.cfg", "Pipfile", "environment.yml", "environment.yaml", "conda.yaml", "package.json", "tsconfig.json",
                   "jsconfig.json", "Cargo.toml", "go.mod"}
_REQUIREMENTS_FILE = re.compile(r"(?:^|/)(?:[^/]*requirements[^/]*|constraints[^/]*|requirements/[^/]+)\.(?:txt|in)$")
_PIP_OPTION = re.compile(r"^(?:(-[rce])\s*|(--requirement|--constraint|--editable)(?:\s*=\s*|\s+))(\S+)")
_EGG = re.compile(r"#egg=([A-Za-z0-9][\w.-]*)")
_PYTHON_FLOOR = re.compile(r"""^\s*(?:requires-python|python_requires|python)\s*[=:]\s*["']?([^"'\n#]+)""", re.M)
_SETUP_HELPER = re.compile(r"""["']([\w-]+?)(?:\.py)?["']|^\s*(?:from|import)\s+(\w+)""", re.M)
_INCLUDE_DEPTH = 5
_LOCK_BYTES = 50_000_000  # a large project's uv.lock passes the cap on other files, and only names are taken from it


def normalize_dist(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def owner(name: str) -> str:
    """The folder whose code a manifest declares dependencies for: its own, or the one holding a requirements/ folder."""
    folder = name.rpartition("/")[0]
    return folder.rpartition("/")[0] if folder.rpartition("/")[2] == "requirements" else folder


def _requirement(line: str) -> str | None:
    line = line.strip()
    if not line or line.startswith(("#", "-", "git+", "hg+", "svn+", "bzr+", "http://", "https://")):
        return None
    match = _REQUIREMENT_NAME.match(line)
    return normalize_dist(match.group(1)) if match else None


def _strings(text: str) -> list[str]:
    return [double or single for double, single in _QUOTED.findall(text)]


def _code(line: str) -> str:
    return _CODE.match(line).group(0)


def _closes_array(code: str) -> bool:
    """A bracket that isn't inside a requirement like "httpx[socks]"."""
    return "]" in _QUOTED.sub("", code)


def _put(names: dict[str, str], name: str, kind: str) -> None:
    if kind == "runtime" or name not in names:  # declared for runtime anywhere is a runtime dependency
        names[name] = kind


def _add(names: dict[str, str], code: str, kind: str) -> None:
    # PEP 735's {include-group = "test"} names another group, whose requirements are read where that group is.
    for quoted in _strings(_INLINE_TABLE.sub("", code)):
        name = _requirement(quoted)
        if name:
            _put(names, name, kind)


def _pyproject(text: str) -> dict[str, str]:
    """Dependency names in pyproject.toml, each "runtime" or "dev", by line, so it works on Python versions without tomllib.
    Build requirements, dependency groups and development tables are "dev". Optional extras install with the package, so they're "runtime"."""
    names: dict[str, str] = {}
    section, kind, in_array = "", "", False
    for line in map(_code, text.split("\n")):
        if in_array:
            _add(names, line, kind)
            in_array = not _closes_array(line)
            continue
        heading = _SECTION.match(line)
        if heading:
            section = heading.group(1).strip().lower()
            continue
        key, equals, value = line.partition("=")
        key, value = key.strip().strip("\"'"), value.strip()
        if not equals or not key:
            continue
        kind = "dev" if _DEV_SECTION.search(section) else "runtime"
        if section in _GROUPS or (section, key) in _ARRAYS:
            if value.startswith("["):
                _add(names, value, kind)
                in_array = not _closes_array(value)
        elif section.endswith("dependencies") and "." in section and key.lower() != "python":  # a table keyed by name, as Poetry's are
            _put(names, normalize_dist(key), kind)
    return names


def _pipfile(text: str) -> dict[str, str]:
    names: dict[str, str] = {}
    section = ""
    for line in map(_code, text.split("\n")):
        heading = _SECTION.match(line)
        if heading:
            section = heading.group(1).strip().lower()
        elif section in ("packages", "dev-packages") and "=" in line and line.split("=", 1)[0].strip().strip("\"'"):
            _put(names, normalize_dist(line.split("=", 1)[0].strip().strip("\"'")), "dev" if section == "dev-packages" else "runtime")
    return names


def _requirements(name: str, read: Callable[[str], str], kind: str, part: dict, seen: set[str], depth: int = 0) -> None:
    """A requirements file, following -r and -c into files inside the repository, each name credited to the file listing it, so a frozen
    include reads as frozen. `-e` of a folder is this repository's or a neighbour's own code."""
    seen.add(name)
    folder = posixpath.dirname(name)
    for line in read(name).split("\n"):
        line = re.sub(r"(?:^|\s)#.*", "", line).strip()  # pip's comments start a line or follow a space, so a URL's #egg= isn't one
        option = _PIP_OPTION.match(line)
        value = option.group(3) if option else line
        egg = _EGG.search(value) if "://" in value else None
        requirement = None
        if option and (option.group(1) or option.group(2)) in ("-e", "--editable"):
            requirement = normalize_dist(egg.group(1)) if egg else None
            path = posixpath.normpath(posixpath.join(folder, re.sub(r"^file:|\[.*$", "", value)))
            if not egg and "://" not in value and posixpath.basename(path) not in ("", ".", ".."):
                part["python_local"].add(normalize_dist(posixpath.basename(path)))
        elif option:
            target = posixpath.normpath(posixpath.join(folder, value))
            if not value.startswith("/") and "://" not in value and target != ".." and not target.startswith("../") and target not in seen and depth < _INCLUDE_DEPTH:
                try:
                    _requirements(target, read, kind, part, seen, depth + 1)
                except OSError:
                    pass
        else:  # `name @ url` names itself, and a bare URL is named by its #egg=
            requirement = _requirement(line) or (normalize_dist(egg.group(1)) if egg else None)
        if requirement:
            part["python"][requirement] = name
            if kind == "runtime":
                part["python_runtime"].add(requirement)


def _floor(text: str) -> tuple[int, int] | None:
    """The oldest Python a manifest allows, from requires-python, python_requires or Poetry's python entry."""
    spec = _PYTHON_FLOOR.search(text)
    minors = [int(minor) for minor in re.findall(r"(?:>=|~=|\^|==|~|>)\s*3\.(\d+)", spec.group(1))] if spec else []
    return (3, max(minors)) if minors else None


def _locked(folder: str, read: Callable[[str], str]) -> set[str]:
    """Everything a Python lockfile beside a manifest resolves to, including what arrives through other packages."""
    names: set[str] = set()
    for lock in ("uv.lock", "poetry.lock", "pdm.lock"):
        try:
            text = read(posixpath.join(folder, lock))
        except OSError:
            continue
        names.update(normalize_dist(name) for name in re.findall(r'^name = "([^"]+)"', text, re.M))
    return names


def _cargo(text: str) -> set[str]:
    names: set[str] = set()
    section = ""
    for line in map(_code, text.split("\n")):
        heading = _SECTION.match(line)
        if heading:
            section = heading.group(1).strip()
            match = re.search(r"dependencies\.([\w-]+)$", section)
            if match:
                names.add(match.group(1))
            continue
        own = re.match(r"\s*name\s*=\s*[\"']([\w-]+)[\"']", line)
        if own and section in ("package", "lib"):  # a crate's own tests and examples import it by name
            names.add(own.group(1))
        if section.endswith("dependencies") and "=" in line:
            names.add(line.split("=", 1)[0].strip().strip('"'))
    return names


def _inside(root: Path, path: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
    except (OSError, ValueError):
        return False
    return True


def _reader(root: Path, lockfile: bool = False) -> Callable[[str], str]:
    """Reads a plain file inside the repository by its name. A symlink could point anywhere, so it's refused like a missing file, and so is
    anything over the size cap: a lockfile's is larger than other files'."""
    def read(name: str) -> str:
        path = root / name
        text = None
        if _inside(root, path):
            if not lockfile:
                text = filesystem.read_text(path)
            elif filesystem.is_plain_file(path) and path.stat().st_size <= _LOCK_BYTES:
                text = path.read_text(errors="replace")
        if text is None:
            raise OSError(f"{name} isn't a plain file of readable size inside the repository")
        return text
    return read


def looks_frozen(root: Path | None, name: str) -> bool:
    """`pip freeze` output lists everything installed, so most of it was never meant to be imported."""
    if root is None or not name.endswith((".txt", ".in")):
        return False
    try:
        lines = [line for line in _reader(root)(name).split("\n") if line.strip() and not line.startswith(("#", "-"))]
    except OSError:
        return False
    return len(lines) >= 30 and sum("==" in line for line in lines) >= 0.8 * len(lines)


# The files read_manifests takes dependencies from, so a check that a manifest changed asks the same question it does.
DEPENDENCY_FILE = re.compile(r"(?:^|/)(?:pyproject\.toml|setup\.(?:py|cfg)|Pipfile|environment\.ya?ml|conda\.yaml|package\.json|Cargo\.toml|go\.mod"
                             r"|[^/]*requirements[^/]*\.(?:txt|in)|constraints[^/]*\.(?:txt|in))$|^requirements/")


def _empty() -> dict:
    return {"python": {}, "python_runtime": set(), "python_local": set(), "python_locked": set(), "python_floor": None,
            "node": {}, "node_runtime": set(), "rust": {}, "go": {}, "go_own": set(), "aliases": set(), "files": []}


def merge(parts: Iterable[dict]) -> dict:
    """Manifests read one at a time, as one. A Python floor comes from the last that states one, so parts go root first."""
    merged = _empty()
    for part in parts:
        for key, value in part.items():
            if isinstance(value, (dict, set)):
                merged[key].update(value)
            elif isinstance(value, list):
                merged[key] += value
            elif value is not None:
                merged[key] = value
    return merged


def _declare(part: dict, ecosystem: str, found: dict[str, str], where: str) -> None:
    part[ecosystem].update(dict.fromkeys(found, where))
    part[ecosystem + "_runtime"].update(name for name, kind in found.items() if kind == "runtime")


def _read_one(name: str, read: Callable[[str], str], read_lock: Callable[[str], str]) -> dict | None:
    base = name.rsplit("/", 1)[-1]
    part = _empty()
    if base == "pyproject.toml":
        text = read(name)
        _declare(part, "python", _pyproject(text), name)
        part["python_locked"], part["python_floor"] = _locked(posixpath.dirname(name), read_lock), _floor(text)
    elif _REQUIREMENTS_FILE.search(name):
        _requirements(name, read, "dev" if _DEV_FILE.search(base) else "runtime", part, set())
    elif base in ("setup.py", "setup.cfg"):
        text = read(name)
        part["python_floor"] = _floor(text)
        region = re.search(r"install_requires\s*[=:]\s*(\[.*?\]|\n(?:[ \t]+.*\n)+)", text, re.S)
        if region:
            _declare(part, "python", {found: "runtime" for found in map(_requirement, _strings(region.group(1)) or region.group(1).split("\n")) if found}, name)
        elif base == "setup.py" and re.search(r"install_requires\s*=", text):
            computed = _computed_requirements(name, text, read)
            part["python"].update(computed)
            part["python_runtime"].update(computed)
    elif base in ("Pipfile", "environment.yml", "environment.yaml", "conda.yaml"):
        text = read(name)
        if base == "Pipfile":
            _declare(part, "python", _pipfile(text), name)
        else:
            entries = map(re.compile(r"\s*-?\s*([A-Za-z][\w.-]+)\s*(?:=|$|[<>~!])").match, text.split("\n"))
            _declare(part, "python", {normalize_dist(entry.group(1)): "runtime" for entry in entries if entry}, name)
    elif base == "package.json":
        document = json.loads(read(name))
        for key in ("dependencies", "devDependencies", "peerDependencies", "optionalDependencies") if isinstance(document, dict) else ():
            table = document.get(key)
            _declare(part, "node", dict.fromkeys(table if isinstance(table, (dict, list)) else (), "dev" if key == "devDependencies" else "runtime"), name)
    elif base in ("tsconfig.json", "jsconfig.json"):
        text = re.sub(r"(?m)^\s*//.*$", "", read(name))
        part["aliases"].update(key.split("/")[0] for key in re.findall(r'"([@~#$\w/-]+)/\*"\s*:', text))
    elif base == "Cargo.toml":
        part["rust"].update(dict.fromkeys(_cargo(read(name)), name))
    elif base == "go.mod":
        text = read(name)
        module = re.search(r"^module\s+(\S+)", text, re.M)
        if module:
            part["go_own"].add(module.group(1))
        part["go"].update(dict.fromkeys(re.findall(r"^\s*(?:require\s+)?([\w.-]+\.[\w./-]+)\s+v", text, re.M), name))
    else:
        return None
    part["files"].append(name)
    return part


def read_each(root: Path, files: list[str], read: Callable[[str], str] | None = None) -> dict[str, dict]:
    """What each manifest among `files` declares, by its name. `read` gives a file's text by its name, from plain files inside the repository
    unless told otherwise, and raises OSError for one that isn't there. Everything, including a setup.py's helper module and a requirements
    file's includes, goes through it, so reading at another revision reads all of it there."""
    read_lock = read or _reader(root, lockfile=True)
    read = read or _reader(root)
    parts = {}
    for name in files:
        if name.rsplit("/", 1)[-1] not in _MANIFEST_NAMES and not _REQUIREMENTS_FILE.search(name):
            continue
        try:
            part = _read_one(name, read, read_lock)
        except (OSError, ValueError):
            continue
        if part is not None:
            parts[name] = part
    return parts


def read_manifests(root: Path, files: list[str], read: Callable[[str], str] | None = None) -> dict:
    """Everything the manifests among `files` declare, by ecosystem. "python" and "node" hold every declared name, and "python_runtime" and
    "node_runtime" those declared for runtime, not only for development or building."""
    return merge(read_each(root, files, read).values())


def _computed_requirements(name: str, text: str, read: Callable[[str], str]) -> dict[str, str]:
    """`install_requires=dependencies['install_requires']`: the lists usually live in a module beside setup.py that setup.py names, which is
    read through `read`, never run."""
    folder = posixpath.dirname(name)
    found: dict[str, str] = {}
    for stem in sorted({quoted or imported for quoted, imported in _SETUP_HELPER.findall(text)}):
        if stem == "setup" or not re.search(r"depend|require", stem, re.I):
            continue
        module = posixpath.join(folder, f"{stem}.py")
        try:
            strings = [item.value for node in ast.walk(ast.parse(read(module))) if isinstance(node, (ast.List, ast.Tuple, ast.Set))
                       for item in node.elts if isinstance(item, ast.Constant) and isinstance(item.value, str)]  # list items, not the extras' names keying them
        except (OSError, SyntaxError, ValueError, RecursionError):
            continue
        for quoted in strings:
            requirement = _requirement(quoted) if re.match(r"[A-Za-z][\w.-]*(?:\[[\w,\s-]*\])?\s*(?:[<>=!~;]|$)", quoted) else None
            if requirement:
                found[requirement] = module
    return found


def stdlib_modules() -> set[str]:
    names = set(getattr(sys, "stdlib_module_names", ()))
    if names:
        return names | REMOVED_STDLIB | {"__future__"}
    # Python 3.9 has no list of its own, so ask the standard library's directory. Modules there aren't imported.
    import sysconfig
    folder = Path(sysconfig.get_paths()["stdlib"])
    names = {p.stem for p in folder.glob("*.py")} | {p.name for p in folder.iterdir() if (p / "__init__.py").exists()}
    names |= {p.name.split(".")[0] for p in (folder / "lib-dynload").glob("*")}  # zlib and others, as extension modules
    return names | REMOVED_STDLIB | set(sys.builtin_module_names) | {"__future__", "_thread"}


def installed_packages(root: Path) -> set[str]:
    """Top-level names present in this interpreter or the project's virtualenv. Nothing is imported."""
    import importlib.machinery
    names = set()
    locations: list[str] = list(sys.path)
    for venv in (".venv", "venv", "env"):
        locations += [str(p) for p in (root / venv).glob("lib/python*/site-packages")]
    for location in locations:
        path = Path(location or ".")
        if not location or not path.is_dir() or path == root:
            continue
        try:
            for entry in path.iterdir():
                stem = entry.name.split(".")[0]
                if entry.is_dir() and not entry.name.endswith(("-info", ".libs")) or entry.suffix in importlib.machinery.all_suffixes():
                    names.add(stem)
        except OSError:
            continue
    return names


_ATTR_PROBE = r"""
import difflib, importlib, json, sys
SKIP = {"antigravity", "this", "idlelib", "tkinter", "turtle", "turtledemo", "test", "lib2to3", "pip", "ensurepip", "__main__"}
results = []
for module, chains in json.load(sys.stdin).items():
    if module.split(".")[0] in SKIP:
        continue
    try:
        root = importlib.import_module(module)
    except Exception:
        continue
    for chain in chains:
        obj, walked = root, module
        for part in chain:
            if hasattr(obj, part):
                obj = getattr(obj, part)
                walked += "." + part
                if not (isinstance(obj, type) or type(obj).__name__ == "module"):
                    break
                continue
            try:
                obj = importlib.import_module(walked + "." + part)
                walked += "." + part
                continue
            except Exception:
                names = [n for n in dir(obj) if not n.startswith("_")]
                close = difflib.get_close_matches(part, names, n=1, cutoff=0.8)
                results.append([module, chain, part, close[0] if close else ""])
                break
print(json.dumps(results))
"""


def interpreter_for(floor: tuple[int, int] | None) -> tuple[str, str, bool]:
    """The Python to ask about standard library attributes, its version, and whether it's older than the project's oldest, because no
    python3.N for that oldest one is on PATH. An older one lacks what was added since, so its answer can't block anything."""
    here = sys.version_info[:2]
    if floor is None or here == floor:
        return sys.executable, f"{here[0]}.{here[1]}", False
    # The oldest Python the project allows, when it's on PATH, whether this one is older or newer: a newer one has what was added since.
    found = shutil.which(f"python{floor[0]}.{floor[1]}")
    if found and os.path.isabs(found):  # a relative PATH entry would find a program in whatever folder this runs in
        return found, f"{floor[0]}.{floor[1]}", False
    return sys.executable, f"{here[0]}.{here[1]}", here < floor


def missing_stdlib_attributes(uses: dict[str, list[list[str]]], timeout: int = 30, executable: str | None = None) -> tuple[list, str | None]:
    """Attributes used on standard library modules that don't exist, checked in an isolated subprocess, and why the check didn't run if it didn't.

    Isolated mode and a neutral working directory mean a project file named like a stdlib module can't run here.
    """
    if not uses:
        return [], None
    python = executable or sys.executable
    try:
        done = subprocess.run([python, "-I", "-c", _ATTR_PROBE], input=json.dumps(uses), capture_output=True, text=True, timeout=timeout, cwd="/")
    except subprocess.TimeoutExpired:
        return [], f"{python} took over {timeout}s"
    except OSError as error:
        return [], f"{python} couldn't start: {error.strerror or error}"
    if done.returncode != 0:
        return [], f"{python} exited with status {done.returncode}" + (f": {done.stderr.strip().splitlines()[-1][:160]}" if done.stderr.strip() else "")
    try:
        found = json.loads(done.stdout)
    except ValueError:
        found = None
    return (found, None) if isinstance(found, list) else ([], f"{python} didn't answer with a list")
