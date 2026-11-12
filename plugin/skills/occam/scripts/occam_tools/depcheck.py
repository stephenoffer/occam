"""Dependencies: what's declared, what's used, what's phantom, and whether a package is real before anyone installs it."""

from __future__ import annotations

import datetime as dt
import json
import re
import urllib.error
import urllib.parse
import urllib.request

from . import files as filesystem, manifests, scan as scanner
from .query import printable
from .report import partial_note

USER_AGENT = "occam-deps/2 (dependency existence check)"
_REGISTRIES = {
    "pypi": "https://pypi.org/pypi/{name}/json",
    "npm": "https://registry.npmjs.org/{name}",
    "crates": "https://crates.io/api/v1/crates/{name}",
    "go": "https://proxy.golang.org/{name}/@latest",
}
# A pinned version, by its own URL. The Go proxy's @v/list leaves out pseudo-versions such as v0.0.0-20240101000000-abcdef123456, and .info answers for both.
_GO_VERSION = "https://proxy.golang.org/{name}/@v/{version}.info"
_BY_LANGUAGE = {"python": "pypi", "notebook": "pypi", "javascript": "npm", "typescript": "npm", "rust": "crates", "go": "go"}
_NAME = re.compile(r"^[A-Za-z0-9@][A-Za-z0-9._/@-]{0,200}$")
_YOUNG_DAYS = 90
_WITH_VERSION = re.compile(r"^(?P<name>.+?)(?:==|@(?=v?\d))(?P<version>[\w.+-]+)$")


def _fetch(url: str) -> tuple[int, dict]:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            return response.status, json.loads(response.read(5_000_000).decode("utf-8", "replace"))
    except urllib.error.HTTPError as error:
        return error.code, {}
    except (urllib.error.URLError, TimeoutError, ValueError, OSError):
        return 0, {}


def _parse_time(text: str | None) -> dt.datetime | None:
    if not text:
        return None
    try:
        return dt.datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None


def _go_path(path: str) -> str:
    """The proxy's spelling of a module path or version: each capital letter becomes ! and its lowercase, as the Go module protocol requires."""
    return re.sub(r"[A-Z]", lambda capital: "!" + capital.group(0).lower(), path)


def _url(registry: str, name: str) -> str:
    return _REGISTRIES[registry].format(name=urllib.parse.quote(_go_path(name) if registry == "go" else name, safe="@/!"))


def _has_version(registry: str, name: str, version: str, document: dict) -> bool | None:
    """Whether the release exists, or None if that couldn't be told. The name's own document lists the releases, except on the Go proxy."""
    if registry == "go":
        code, _ = _fetch(_GO_VERSION.format(name=urllib.parse.quote(_go_path(name), safe="/!"), version=urllib.parse.quote(_go_path(version), safe="!")))
        return True if code == 200 else False if code in (404, 410) else None
    listed = document.get("releases" if registry == "pypi" else "versions")
    if registry == "crates" and isinstance(listed, list):
        return _has_release(registry, version, {item.get("num") for item in listed if isinstance(item, dict)})
    return _has_release(registry, version, set(listed)) if isinstance(listed, dict) else None


def check_package(registry: str, spec: str) -> dict:
    """Is this name real, is that version if one is given (`name==1.2`, `name@1.2`, `path@v1.2.3`), and does it look established? Sends only the name
    and version. Never installs anything. A Go package path is checked as the module holding it."""
    pinned = _WITH_VERSION.match(spec)
    name, version = (pinned.group("name"), pinned.group("version")) if pinned else (spec, None)
    result, document = _check_name(registry, name)
    above = name
    for _ in range(max(0, name.count("/") - 1)) if registry == "go" else ():  # an import path names a package; its module is the path or a folder above it
        above = above.rpartition("/")[0]
        if result["status"] != "not found" or "/" not in above:
            break
        found, found_document = _check_name(registry, above)
        if found["status"] != "not found":
            result, document = found, found_document
    if version and result["status"] == "exists":
        known = _has_version(registry, result["name"], version, document)
        if known is False:
            result.update(status="not found", warning=f"{result['name']} exists, and it has no release {version}. Agents often invent version numbers.")
        elif known is None:
            result["unverified"] = f"version {version} not verified"
    return result


def _has_release(registry: str, version: str, known: set) -> bool:
    """As the installer reads the pin: pip pads a release with zeros, so ==2.31 is 2.31.0, while npm and Cargo read 1.2 as any 1.2.x."""
    if version in known:
        return True
    if registry == "pypi":
        return _padded(version) in {_padded(str(release)) for release in known}
    return version.count(".") < 2 and any(str(release).startswith(version + ".") for release in known)


def _padded(version: str) -> tuple:
    match = re.match(r"v?(\d+(?:\.\d+)*)(.*)", version.lower())
    if not match:
        return ((), version)
    numbers = [int(number) for number in match.group(1).split(".")]
    while len(numbers) > 1 and numbers[-1] == 0:
        numbers.pop()
    return (tuple(numbers), match.group(2))


def verified(result: dict) -> bool:
    """Whether the registry answered the whole question: the name, and the version if one was given."""
    return result["status"] in ("exists", "not found") and not result.get("unverified")


def _described(registry: str, document: dict) -> tuple:
    """First and latest release, summary, source repository and number of versions, as each registry spells them."""
    if registry == "pypi":
        info = document.get("info", {})
        releases = [file["upload_time_iso_8601"] for files in document.get("releases", {}).values() for file in files if file.get("upload_time_iso_8601")]
        first, latest = (min(releases), max(releases)) if releases else (None, None)
        return first, latest, info.get("summary") or "", (info.get("project_urls") or {}).get("Source") or info.get("home_page") or "", len(document.get("releases", {}))
    if registry == "npm":
        times = document.get("time", {})
        repository = (document.get("repository") or {}).get("url", "") if isinstance(document.get("repository"), dict) else ""
        return times.get("created"), times.get("modified"), document.get("description") or "", repository, len(document.get("versions", {}))
    if registry == "crates":
        crate = document.get("crate", {})
        return crate.get("created_at"), crate.get("updated_at"), crate.get("description") or "", crate.get("repository") or "", len(document.get("versions", []))
    return None, document.get("Time"), "", "", 0


def _check_name(registry: str, name: str) -> tuple[dict, dict]:
    if registry not in _REGISTRIES or not _NAME.match(name):
        known = ", ".join(_REGISTRIES)
        return {"registry": registry, "name": name, "status": "invalid request", "warning": f"Not a name this registry accepts, or not one of {known}. Not verified."}, {}
    code, document = _fetch(_url(registry, name))
    if code == 404 or (registry == "go" and code == 410):  # the Go proxy answers 410 Gone for a module it can't find
        return {"registry": registry, "name": name, "status": "not found", "warning": "No such package. This may be a hallucinated name, and it could be registered later by someone malicious."}, {}
    if code != 200:
        return {"registry": registry, "name": name, "status": "unknown", "warning": f"Registry check failed (HTTP {code or 'error'}). Not verified."}, {}
    first, latest, summary, repository, versions = _described(registry, document)
    result = {"registry": registry, "name": name, "status": "exists", "summary": summary[:160], "repository": repository, "first_release": first, "latest_release": latest, "versions": versions}
    warnings = []
    created = _parse_time(first)
    if created is not None and created.tzinfo and (dt.datetime.now(dt.timezone.utc) - created).days < _YOUNG_DAYS:
        warnings.append(f"First published under {_YOUNG_DAYS} days ago, so check it isn't squatting a hallucinated or similar name.")
    if versions == 1:
        warnings.append("Only one version has ever been released.")
    if not repository and registry != "go":
        warnings.append("No source repository listed.")
    if warnings:
        result["warning"] = " ".join(warnings)
    return result, document


def report(root, online: bool = False, names: list[str] | None = None, seconds: int | None = None) -> tuple[str, int]:
    """Exit 1 if a name or version doesn't exist, else 2 if one couldn't be checked, so a script never reads an unanswered check as a pass."""
    lines: list[str] = []
    missing = unchecked = 0
    for spec in names or []:
        registry, _, name = spec.partition(":")
        if not name:
            lines.append(f"{spec}: use the form pypi:name, npm:name, crates:name or go:path. Not verified.")
            unchecked += 1
            continue
        result = check_package(registry, name)
        lines.append(_render(result))
        missing += result["status"] == "not found"
        unchecked += not verified(result)
    if names:
        if unchecked:
            lines.append(f"{unchecked} not verified: the registry didn't answer, or couldn't be asked. Check again before relying on them.")
        return "\n".join(lines), 1 if missing else 2 if unchecked else 0
    # Every rule asked for here needs the whole repository, so if that's too much to read, reading part of it would only cost time.
    result = scanner.run_scan(root, seconds=seconds, focus=[])
    lines += partial_note(result.stats)
    wanted = {"phantom-import", "undeclared-dependency", "unused-dependency", "competing-dependencies"}
    findings = [f for f in result.findings if f["rule"] in wanted]
    manifest = manifests.read_manifests(root, filesystem.list_files(root, None, filesystem.load_config(root)))
    counts = {key: len(manifest[key]) for key in ("python", "node", "rust", "go")}
    lines.append(f"Manifests: {', '.join(manifest['files']) or 'none'}. Declared: " + ", ".join(f"{k} {v}" for k, v in counts.items() if v) + ("" if any(counts.values()) else "nothing"))
    for rule in ("phantom-import", "undeclared-dependency", "unused-dependency", "competing-dependencies"):
        group = [f for f in findings if f["rule"] == rule]
        if group:
            lines += ["", f"{rule} ({len(group)}):"]
            lines += [f"  {f['path']}:{f['line']}  {f['message']}" for f in group[:25]]
    # Each name goes to the registry of the language importing it: a Go module to the Go proxy, a crate to crates.io.
    phantoms = sorted({(result.project.languages.get(f["path"]) or "", m.group(1)) for f in findings if f["rule"] == "phantom-import" for m in [re.search(r"'([^']+)'", f["message"])] if m})
    code = 0
    if online and phantoms:
        lines += ["", "Registry check for phantom imports (package names only are sent):"]
        for language, name in phantoms[:25]:
            registry = _BY_LANGUAGE.get(language)
            checked = check_package(registry, name) if registry else None
            lines.append("  " + (_render(checked) if checked else f"{name}: not checked, since occam knows no registry for {language or 'this language'}."))
            # as for --name: 1 if a registry says a name doesn't exist, else 2 if one couldn't be answered, so no script reads it as a pass
            code = 1 if checked and checked["status"] == "not found" else code or (0 if checked and verified(checked) else 2)
    elif phantoms:
        lines += ["", "Add --online to check whether these exist on the registries. Don't install a guessed name to find out."]
    return "\n".join(lines), code


def _render(result: dict) -> str:
    head = f"{result['registry']}:{result['name']}: {result['status']}" + (f"; {result['unverified']}" if result.get("unverified") else "")
    if result["status"] == "exists":
        when = (result.get("latest_release") or "")[:10]
        first = (result.get("first_release") or "")[:10]
        head += f", first released {first or '?'}, latest {when or '?'}, {result.get('versions') or '?'} versions"
        if result.get("repository"):
            head += f", {result['repository']}"
        if result.get("summary"):
            head += f". {result['summary']}"
    if result.get("warning"):
        head += f"  WARNING: {result['warning']}"
    return printable(head)  # a registry's summary and repository URL come from the network, and a terminal acts on control codes
