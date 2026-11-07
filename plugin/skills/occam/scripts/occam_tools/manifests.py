"""Reading dependency manifests without third-party parsers, and deciding what an import name refers to."""

from __future__ import annotations

import ast
import json
import re
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path

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
_ARRAY_START = re.compile(r"^\s*(?:dependencies|requires|optional-dependencies|dev|test|docs|all|[\w-]+)\s*=\s*\[")
_QUOTED = re.compile(r"""["']([^"']+)["']""")


def normalize_dist(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def _requirement(line: str) -> str | None:
    line = line.strip()
    if not line or line.startswith(("#", "-", "git+", "http://", "https://")):
        return None
    match = _REQUIREMENT_NAME.match(line)
    return normalize_dist(match.group(1)) if match else None


def _closes_array(text: str) -> bool:
    """A bracket that isn't inside a requirement like "httpx[socks]" or in a comment."""
    return "]" in _QUOTED.sub("", text).split("#", 1)[0]


def _pyproject(text: str) -> set[str]:
    """Dependency names from pyproject.toml, by line, so it works on Python versions without tomllib."""
    names: set[str] = set()
    section = ""
    in_array = False
    for line in text.split("\n"):
        heading = _SECTION.match(line)
        if heading and not in_array:
            section = heading.group(1).strip().lower()
            continue
        if in_array:
            for quoted in _QUOTED.findall(line):
                name = _requirement(quoted)
                if name:
                    names.add(name)
            if _closes_array(line):
                in_array = False
            continue
        relevant = section in ("project", "build-system", "project.optional-dependencies", "dependency-groups", "tool.uv") or "dependencies" in section
        if not relevant:
            continue
        if section.endswith(("dependencies", "dev-dependencies")) and "." in section and not section.endswith("optional-dependencies"):
            key = line.split("=", 1)[0].strip().strip('"')
            if "=" in line and key and key.lower() != "python":
                names.add(normalize_dist(key))
            continue
        if _ARRAY_START.match(line):
            key = line.split("=", 1)[0].strip()
            if (section == "project" and key != "dependencies") or (section == "tool.uv" and key != "dev-dependencies"):
                continue
            for quoted in _QUOTED.findall(line.split("=", 1)[1]):
                name = _requirement(quoted)
                if name:
                    names.add(name)
            if not _closes_array(line.split("=", 1)[1]):
                in_array = True
    return names


def _locked(folder: Path) -> set[str]:
    """Everything a Python lockfile beside a manifest resolves to, including what arrives through other packages."""
    names: set[str] = set()
    for lock in ("uv.lock", "poetry.lock", "pdm.lock"):
        candidate = folder / lock
        if candidate.is_file() and not candidate.is_symlink():
            names.update(normalize_dist(name) for name in re.findall(r'^name = "([^"]+)"', candidate.read_text(errors="replace"), re.M))
    return names


def _cargo(text: str) -> set[str]:
    names: set[str] = set()
    section = ""
    for line in text.split("\n"):
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
        if section.endswith("dependencies") and "=" in line and not line.lstrip().startswith("#"):
            names.add(line.split("=", 1)[0].strip().strip('"'))
    return names


def looks_frozen(root: Path | None, name: str) -> bool:
    """`pip freeze` output lists everything installed, so most of it was never meant to be imported."""
    if root is None or not name.endswith((".txt", ".in")):
        return False
    try:
        lines = [line for line in (root / name).read_text(errors="replace").split("\n") if line.strip() and not line.startswith(("#", "-"))]
    except OSError:
        return False
    return len(lines) >= 30 and sum("==" in line for line in lines) >= 0.8 * len(lines)


def read_manifests(root: Path, files: list[str], read: Callable[[str], str] | None = None) -> dict:
    """Everything the repository declares it depends on, by ecosystem. `read` gives a file's text by its name, from disk unless told otherwise,
    and raises OSError for one that isn't there."""
    read = read or (lambda name: (root / name).read_text(errors="replace"))
    python: dict[str, str] = {}
    python_locked: set[str] = set()
    node: dict[str, str] = {}
    rust: dict[str, str] = {}
    go_modules: dict[str, str] = {}
    go_own: set[str] = set()
    aliases: set[str] = set()
    seen = []
    for name in files:
        base = name.rsplit("/", 1)[-1]
        path = root / name
        try:
            if base == "pyproject.toml":
                python.update(dict.fromkeys(_pyproject(read(name)), name))
                python_locked |= _locked(path.parent)
            elif re.fullmatch(r"(?:.*requirements.*|constraints.*)\.(?:txt|in)", base) or name.startswith("requirements/"):
                for line in read(name).split("\n"):
                    requirement = _requirement(line)
                    if requirement:
                        python[requirement] = name
            elif base in ("setup.py", "setup.cfg"):
                text = read(name)
                region = re.search(r"install_requires\s*[=:]\s*(\[.*?\]|\n(?:[ \t]+.*\n)+)", text, re.S)
                if region:
                    for quoted in _QUOTED.findall(region.group(1)) or region.group(1).split("\n"):
                        requirement = _requirement(quoted)
                        if requirement:
                            python[requirement] = name
                elif base == "setup.py" and re.search(r"install_requires\s*=", text):
                    python.update(_computed_requirements(path, name))
            elif base in ("Pipfile", "environment.yml", "environment.yaml", "conda.yaml"):
                for line in read(name).split("\n"):
                    match = re.match(r"\s*-?\s*([A-Za-z][\w.-]+)\s*(?:=|$|[<>~!])", line)
                    if match:
                        python[normalize_dist(match.group(1))] = name
            elif base == "package.json":
                document = json.loads(read(name))
                for key in ("dependencies", "devDependencies", "peerDependencies", "optionalDependencies") if isinstance(document, dict) else ():
                    table = document.get(key)
                    node.update(dict.fromkeys(table if isinstance(table, (dict, list)) else (), name))
            elif base in ("tsconfig.json", "jsconfig.json"):
                text = re.sub(r"(?m)^\s*//.*$", "", read(name))
                aliases.update(key.split("/")[0] for key in re.findall(r'"([@~#$\w/-]+)/\*"\s*:', text))
            elif base == "Cargo.toml":
                rust.update(dict.fromkeys(_cargo(read(name)), name))
            elif base == "go.mod":
                text = read(name)
                module = re.search(r"^module\s+(\S+)", text, re.M)
                if module:
                    go_own.add(module.group(1))
                for found in re.findall(r"^\s*(?:require\s+)?([\w.-]+\.[\w./-]+)\s+v", text, re.M):
                    go_modules[found] = name
            else:
                continue
            seen.append(name)
        except (OSError, ValueError):
            continue
    return {"python": python, "python_locked": python_locked, "node": node, "rust": rust, "go": go_modules, "go_own": go_own, "aliases": aliases, "files": seen}


def _computed_requirements(setup: Path, name: str) -> dict[str, str]:
    """`install_requires=dependencies['install_requires']`: the lists usually live in a module beside setup.py, which is read, never run."""
    found: dict[str, str] = {}
    for module in sorted(setup.parent.glob("*.py")):
        if module.name != "setup.py" and re.search(r"depend|require", module.stem, re.I):
            try:
                strings = [item.value for node in ast.walk(ast.parse(module.read_text(errors="replace"))) if isinstance(node, (ast.List, ast.Tuple, ast.Set))
                           for item in node.elts if isinstance(item, ast.Constant) and isinstance(item.value, str)]  # list items, not the extras' names keying them
            except (OSError, SyntaxError, ValueError, RecursionError):
                continue
            for quoted in strings:
                requirement = _requirement(quoted) if re.match(r"[A-Za-z][\w.-]*(?:\[[\w,\s-]*\])?\s*(?:[<>=!~;]|$)", quoted) else None
                if requirement:
                    found[requirement] = f"{name.rsplit('/', 1)[0]}/{module.name}" if "/" in name else module.name
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


def missing_stdlib_attributes(uses: dict[str, list[list[str]]], timeout: int = 30) -> list:
    """Attributes used on standard library modules that don't exist, checked in an isolated subprocess.

    Isolated mode and a neutral working directory mean a project file named like a stdlib module can't run here.
    """
    if not uses:
        return []
    try:
        done = subprocess.run([sys.executable, "-I", "-c", _ATTR_PROBE], input=json.dumps(uses), capture_output=True, text=True, timeout=timeout, cwd="/")
    except (OSError, subprocess.TimeoutExpired):
        return []
    if done.returncode != 0:
        return []
    try:
        return json.loads(done.stdout)
    except ValueError:
        return []
