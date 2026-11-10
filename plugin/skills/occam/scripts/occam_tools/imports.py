"""Do the things this code imports exist? Checked against the repository, its manifests and the standard library."""

from __future__ import annotations

import re
import sys
from collections import defaultdict
from pathlib import Path

from . import manifests
from .files import SKIP_DIRS
from .source import is_test_path

RUST_ROOTS_SET = manifests.RUST_ROOTS
_BUILT = {"dist", "build", "target", "out", ".next", ".nuxt"}
JS_EXTENSIONS = (".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs", ".vue", ".svelte", ".json", ".d.ts")


def python_imports(project) -> None:
    paths = project._python_paths()
    if not paths:
        return
    manifest = project._manifests()
    declared = manifest["python"]
    has_manifest = bool(declared) or any(f.rsplit("/", 1)[-1] in ("pyproject.toml", "setup.py", "setup.cfg") or "requirements" in f for f in project.files)
    stdlib = manifests.stdlib_modules()
    modules, tops = project._local_modules()
    installed = manifests.installed_packages(project.root) if project.root else set()
    reported: set[tuple[str, str]] = set()
    for path in paths:
        for item in (project.facts.get(path) or {}).get("imports", []):
            _python_import(project, path, item, declared, has_manifest, stdlib, modules, tops, installed, reported)


def _python_import(project, path, item, declared, has_manifest, stdlib, modules, tops, installed, reported) -> None:
    module, level, line = item["module"], item.get("level", 0), item["line"]
    if level:
        dotted = project._resolve_relative(path, module, level)
        if dotted is None:
            return
        target = modules.get(dotted)
        if target is None and module and not item.get("optional"):
            if project.root is not None and not _unlisted(project, dotted.replace(".", "/")):
                project.add("phantom-local-import", path, line, f"Relative import of '{module}' finds no such file.")
            return
        _local_name_check(project, path, item, dotted, target, modules)
        return
    top = module.split(".")[0]
    if not top or top in stdlib:
        return
    dist = manifests.normalize_dist(manifests.IMPORT_TO_DIST.get(top, top))
    is_declared = _declares(declared, top)
    if top in tops or module in modules:
        if is_declared:  # a local folder named alembic doesn't make `from alembic import op` local
            return
        if module in modules:
            _local_name_check(project, path, item, module, project.python_target(path, module), modules)
        elif "." in module and top in {p.split("/")[0] for p in project.files if p.endswith(".py")} and modules.get(top) and not item.get("optional") and not _unlisted(project, _package_folder(modules.get(top), module)):
            project.add("phantom-local-import", path, line, f"'{module}' isn't a module in this repository.")
        return
    private = next((part for part in [*module.split("."), *(item.get("names") or [])] if part.startswith("_") and not part.startswith("__")), None)
    if private and not is_test_path(path):
        project.add("private-import", path, line, f"{private} is internal to {top}, so any release can change or remove it. Use its public API, or pin the version and test the workaround.")
    if is_declared or item.get("optional") or (top, path) in reported:
        return
    reported.add((top, path))
    if dist in project._manifests()["python_locked"]:
        project.add("undeclared-dependency", path, line, f"'{top}' is here only because another package needs it, per the lockfile. Declare it if this code relies on it.")
        return
    if top in installed:
        if has_manifest:
            project.add("undeclared-dependency", path, line, f"'{top}' works here only because it happens to be installed.")
        return
    if top in manifests.WELL_KNOWN:  # real, so the question is only whether it's declared, and with nothing declared, as in a cell or script, that isn't one
        if has_manifest:
            project.add("undeclared-dependency", path, line, f"'{top}' isn't declared or installed here, so a clean install won't have it.")
    elif has_manifest:
        lazy = {"confidence": "medium"} if item.get("lazy") else {}
        project.add("phantom-import", path, line, f"'{top}' isn't local, declared or installed. Check it exists before installing anything of that name.", **lazy)
    else:
        project.add("phantom-import", path, line, f"'{top}' isn't local or installed, and this repository declares no dependencies.", confidence="medium")


def _declares(declared, top: str) -> bool:
    if top == "google" and any(d.startswith("google-") or d == "protobuf" for d in declared):  # a namespace many distributions share
        return True
    dist = manifests.normalize_dist(manifests.IMPORT_TO_DIST.get(top, top))
    return dist in declared or manifests.normalize_dist(top) in declared or any(d.startswith(dist + "-") or dist.startswith(d + "-") for d in declared)


def _names_an_object(project, importer: str, dotted: str) -> bool:
    """`from shared.config import settings`, when the package's __init__ binds settings to an instance rather than the submodule."""
    parent, _, name = dotted.rpartition(".")
    target = project.python_target(importer, parent) if parent else None
    return bool(target and target.endswith("__init__.py") and name in ((project.facts.get(target) or {}).get("top_names") or []))


def _local_name_check(project, path, item, dotted, target, modules) -> None:
    if not target or not project.root:
        return
    facts = project.facts.get(target) or {}
    if not facts or facts.get("has_star") or facts.get("has_getattr"):
        return
    top_names = set(facts.get("top_names") or [])
    for name in item.get("names") or []:
        if name == "*" or name in top_names:
            continue
        if f"{dotted}.{name}" in modules:
            continue
        if target.endswith("__init__.py") and (any(p.startswith(target[:-len("__init__.py")] + name + "/") or p.startswith(target[:-len("__init__.py")] + name + ".") for p in project.files)
                                               or _unlisted(project, target[:-len("__init__.py")] + name)):
            continue
        if not item.get("optional"):
            project.add("phantom-local-import", path, item["line"], f"{target} defines no '{name}'.")


def foreign_imports(project) -> None:
    manifest = project._manifests()
    node, rust, go_modules, go_own, aliases = manifest["node"], manifest["rust"], manifest["go"], manifest["go_own"], manifest["aliases"]
    has_package_json = any(f.rsplit("/", 1)[-1] == "package.json" for f in project.files)
    files = set(project.files)
    for path, language in project.languages.items():
        imports = (project.facts.get(path) or {}).get("imports", [])
        if language in ("javascript", "typescript"):
            for item in imports:
                _js_import(project, path, item, node, aliases, has_package_json, files)
        elif language == "rust" and rust:
            for item in imports:
                crate = item["module"]
                # Crates are snake_case. Anything else here is an enum or a macro's name brought into scope.
                if re.fullmatch(r"[a-z][a-z0-9_]*", crate) and crate not in RUST_ROOTS_SET and crate.replace("_", "-") not in rust and crate not in rust:
                    if not _rust_local(path, crate, files):
                        project.add("phantom-import", path, item["line"], f"Crate '{crate}' isn't in Cargo.toml.", confidence="medium")
        elif language == "go" and go_modules:
            for item in imports:
                module = item["module"]
                if "." in module.split("/")[0] and not any(module == m or module.startswith(m + "/") for m in [*go_modules, *go_own]):
                    project.add("phantom-import", path, item["line"], f"'{module}' isn't required by go.mod.")


def _unlisted(project, target: str, built: bool = False) -> bool:
    """The file listing leaves out build/, vendor/ and the like, so a target inside one of those folders that exists can't be seen to be missing.
    `built` is for JavaScript, whose package often imports its own dist/ before anything is built."""
    parts = target.split("/")
    return project.root is not None and any(part in SKIP_DIRS and ((built and part in _BUILT) or project.root.joinpath(*parts[:index + 1]).is_dir())
                                            for index, part in enumerate(parts))


def _package_folder(top_file: str | None, module: str) -> str:
    """Where `pkg.vendor.qr` would live, from where the package `pkg` is."""
    return top_file[:-len("__init__.py")] + "/".join(module.split(".")[1:]) if top_file and top_file.endswith("__init__.py") else ""


def _rust_local(path: str, crate: str, files: set[str]) -> bool:
    folder = path.rsplit("/", 1)[0] if "/" in path else ""
    prefix = folder + "/" if folder else ""
    return f"{prefix}{crate}.rs" in files or f"{prefix}{crate}/mod.rs" in files or any(f.endswith(f"/{crate}.rs") or f.endswith(f"/{crate}/mod.rs") or f.endswith(f"/{crate}/Cargo.toml") for f in files)


def _js_import(project, path, item, node, aliases, has_package_json, files) -> None:
    module, line = item["module"], item["line"]
    if module.startswith("."):
        base = str(Path(path).parent / module)
        base = re.sub(r"(^|/)\./", r"\1", base)
        parts: list[str] = []
        for part in base.split("/"):
            if part == ".." and parts:
                parts.pop()
            elif part not in (".", ""):
                parts.append(part)
        target = "/".join(parts)
        stripped = re.sub(r"\.(js|jsx|mjs|cjs)$", "", target)
        options = [target, *(f"{target}{e}" for e in JS_EXTENSIONS), *(f"{stripped}{e}" for e in JS_EXTENSIONS), *(f"{target}/index{e}" for e in JS_EXTENSIONS),
                   f"{target}/package.json"]  # a folder with its own package.json resolves through its "main"
        if not any(option in files for option in options) and not _unlisted(project, target, built=True) and not re.search(r"\.(css|scss|svg|png|jpg|json|sass|less|html|md|yaml|yml|txt|wasm|graphql|vue|svelte)(\?|$)", module) and "?" not in module:
            project.add("phantom-local-import", path, line, f"'{module}' resolves to no file.")
        return
    head = module.split("/")[0]
    name = "/".join(module.split("/")[:2]) if module.startswith("@") else head
    if module.startswith("node:") or head in manifests.NODE_BUILTINS or head in aliases or head in ("@", "~", "#", "$") or "$" in module or module.startswith(("http:", "https:", "data:", "virtual:", "bun:", "/", "#")):
        return
    if has_package_json and name not in node and f"@types/{name}" not in node:
        project.add("phantom-import", path, line, f"'{name}' isn't in package.json. Check it exists before installing anything of that name.")


def local_attributes(project) -> None:
    """`helpers.do_thing()` where helpers is this repository's module and it defines no do_thing."""
    modules, _ = project._local_modules()
    declared = project._manifests()["python"]
    stdlib = manifests.stdlib_modules()
    for path in project._python_paths():
        for use in (project.facts.get(path) or {}).get("attr_uses", []):
            top = use["module"].split(".")[0]
            external = top in stdlib or _declares(declared, top) or _names_an_object(project, path, use["module"])
            target = None if external else project.python_target(path, use["module"])
            facts = project.facts.get(target) if target else None
            if not facts or not use["chain"] or use.get("guarded") or facts.get("has_star") or facts.get("has_getattr"):
                continue
            name = use["chain"][0]
            is_submodule = f"{use['module']}.{name}" in modules or (target.endswith("__init__.py") and (any(p.startswith(target[:-len("__init__.py")] + name) for p in project.files)
                                                                                               or _unlisted(project, target[:-len("__init__.py")] + name)))
            if name not in (facts.get("top_names") or []) and not name.startswith("__") and not is_submodule:
                project.add("phantom-local-import", path, use["line"], f"{target} defines no '{name}'.")


def stdlib_attributes(project) -> None:
    stdlib = manifests.stdlib_modules()
    uses: dict[str, set[tuple]] = defaultdict(set)
    sites: dict[tuple, list] = defaultdict(list)
    for path in project._python_paths():
        for use in (project.facts.get(path) or {}).get("attr_uses", []):
            module = use["module"]
            if module.split(".")[0] not in stdlib or not use["chain"] or module.startswith("_") or use.get("guarded") or use["chain"][-1].startswith("_"):
                continue
            chain = tuple(use["chain"][:3])
            uses[module].add(chain)
            sites[(module, chain)].append((path, use["line"]))
    missing = manifests.missing_stdlib_attributes({m: [list(c) for c in chains] for m, chains in uses.items()})
    version = f"{sys.version_info.major}.{sys.version_info.minor}"
    for module, chain, part, close in missing:
        # What an OS-facing module offers depends on the platform, so absence alone proves little unless it's a near miss.
        platform_sensitive = module.split(".")[0] in manifests.PLATFORM_MODULES and chain[0] != "path"
        if platform_sensitive and not close:
            continue
        hint = f" Did you mean '{close}'?" if close else ""
        overrides = {"confidence": "medium"} if platform_sensitive else {}
        for path, line in sites.get((module, tuple(chain)), [])[:3]:
            project.add("phantom-attribute", path, line, f"{module}.{'.'.join(chain)}: '{part}' doesn't exist on Python {version}.{hint}", **overrides)
