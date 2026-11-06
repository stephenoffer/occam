"""Dependencies: what's declared, what's used, what's phantom, and whether a package is real before anyone installs it."""

from __future__ import annotations

import datetime as dt
import json
import re
import urllib.error
import urllib.parse
import urllib.request

from . import files as filesystem, manifests, scan as scanner

USER_AGENT = "occam-deps/2 (dependency existence check)"
_REGISTRIES = {
    "pypi": "https://pypi.org/pypi/{name}/json",
    "npm": "https://registry.npmjs.org/{name}",
    "crates": "https://crates.io/api/v1/crates/{name}",
    "go": "https://proxy.golang.org/{name}/@latest",
}
_NAME = re.compile(r"^[A-Za-z0-9@][A-Za-z0-9._/@-]{0,200}$")
_YOUNG_DAYS = 90


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


def check_package(registry: str, name: str) -> dict:
    """Is this name real, and does it look established? Sends only the name. Never installs anything."""
    if registry not in _REGISTRIES or not _NAME.match(name):
        return {"registry": registry, "name": name, "status": "invalid request"}
    code, document = _fetch(_REGISTRIES[registry].format(name=urllib.parse.quote(name, safe="@/")))
    if code == 404:
        return {"registry": registry, "name": name, "status": "not found", "warning": "No such package. This may be a hallucinated name, and it could be registered later by someone malicious."}
    if code != 200:
        return {"registry": registry, "name": name, "status": "unknown", "warning": f"Registry check failed (HTTP {code or 'error'}). Not verified."}
    first, latest, summary, repository, versions = None, None, "", "", 0
    if registry == "pypi":
        info = document.get("info", {})
        summary = info.get("summary") or ""
        repository = (info.get("project_urls") or {}).get("Source") or info.get("home_page") or ""
        releases = [file["upload_time_iso_8601"] for files in document.get("releases", {}).values() for file in files if file.get("upload_time_iso_8601")]
        versions = len(document.get("releases", {}))
        first, latest = (min(releases), max(releases)) if releases else (None, None)
    elif registry == "npm":
        times = document.get("time", {})
        summary = document.get("description") or ""
        repository = (document.get("repository") or {}).get("url", "") if isinstance(document.get("repository"), dict) else ""
        first, latest, versions = times.get("created"), times.get("modified"), len(document.get("versions", {}))
    elif registry == "crates":
        crate = document.get("crate", {})
        summary, repository = crate.get("description") or "", crate.get("repository") or ""
        first, latest = crate.get("created_at"), crate.get("updated_at")
        versions = len(document.get("versions", []))
    else:
        latest = document.get("Time")
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
    return result


def report(root, online: bool = False, names: list[str] | None = None) -> tuple[str, int]:
    lines: list[str] = []
    exit_code = 0
    for spec in names or []:
        registry, _, name = spec.partition(":")
        if not name:
            lines.append(f"{spec}: use the form pypi:name, npm:name, crates:name or go:path")
            exit_code = 2
            continue
        result = check_package(registry, name)
        lines.append(_render(result))
        if result["status"] == "not found":
            exit_code = 1
    if names:
        return "\n".join(lines), exit_code
    result = scanner.run_scan(root)
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
    phantoms = sorted({m.group(1) for f in findings if f["rule"] == "phantom-import" for m in [re.search(r"'([^']+)'", f["message"])] if m})
    if online and phantoms:
        lines += ["", "Registry check for phantom imports (package names only are sent):"]
        for name in phantoms[:25]:
            registry = "pypi" if any(f["path"].endswith((".py", ".ipynb")) and name in f["message"] for f in findings) else "npm"
            lines.append("  " + _render(check_package(registry, name)))
    elif phantoms:
        lines += ["", "Add --online to check whether these exist on the registries. Don't install a guessed name to find out."]
    return "\n".join(lines), exit_code


def _render(result: dict) -> str:
    head = f"{result['registry']}:{result['name']}: {result['status']}"
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
    return head
