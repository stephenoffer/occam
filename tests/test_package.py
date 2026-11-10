"""The skill package follows the Agent Skills spec and its own design budgets."""

import json
import re
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
PLUGIN = ROOT / "plugin"
SKILLS = PLUGIN / "skills"
SKILL = SKILLS / "occam"
SKILL_MD = SKILL / "SKILL.md"
ALL_SKILLS = sorted(SKILLS.glob("*/SKILL.md"))
NON_LANGUAGE_SKILLS = {"occam", "occam-audit", "occam-docs"}
LANGUAGE_SKILLS = sorted(p for p in ALL_SKILLS if p.parent.name not in NON_LANGUAGE_SKILLS)
AUDIT = SKILLS / "occam-audit"
DOCS_SKILL = SKILLS / "occam-docs" / "SKILL.md"
SCRIPTS = SKILL / "scripts"
COMPACT = ROOT / "evals" / "variants" / "compact" / "SKILL.md"
SPEC_FIELDS = {"name", "description", "license", "compatibility", "metadata", "allowed-tools"}
# Tool and command names that exist on only one host. The core must stay portable.
HOST_SPECIFIC = re.compile(
    r"AskUserQuestion|TodoWrite|\bTask tool\b|\bAgent tool\b|CLAUDE_|\$ARGUMENTS|CLAUDE\.md|AGENTS\.md|codex exec|"
    r"claude -p|/hooks|PostToolUse|\bStop hook\b|apply_patch|\.claude/|\.codex/|\.agents/|Claude Code|Codex"
)

pytestmark = pytest.mark.skipif(not SKILL_MD.exists(), reason="skill not written yet")


def parts(path: Path) -> tuple[dict, str]:
    _, front, body = path.read_text().split("---\n", 2)
    return yaml.safe_load(front), body


@pytest.mark.parametrize("path", ALL_SKILLS, ids=lambda p: p.parent.name)
def test_frontmatter_follows_the_spec(path):
    front, _ = parts(path)
    assert front["name"] == path.parent.name
    assert re.fullmatch(r"[a-z0-9]+(-[a-z0-9]+)*", front["name"]) and len(front["name"]) <= 64
    assert 1 <= len(front["description"]) <= 1024
    # Other keys hard-error in strict validators such as skills-ref. The one exception, chosen by the user on 2026-11-08: the language
    # skills are helpers, routed by the hooks and the core instead of listed in every session, which only this Claude Code key does.
    allowed = SPEC_FIELDS | ({"disable-model-invocation"} if path in LANGUAGE_SKILLS else set())
    assert not set(front) - allowed, "other keys hard-error outside Claude Code"
    assert "<" not in front["description"] and ">" not in front["description"]


def test_core_skill_is_named_occam():
    assert parts(SKILL_MD)[0]["name"] == "occam"


def test_core_names_every_language_skill():
    """By the path to read, since a routed skill can't be loaded by name. Without hooks, as when only the skills are copied, this is the route."""
    _, body = parts(SKILL_MD)
    assert "`../occam-<name>/SKILL.md`" in body
    line = next(line for line in body.splitlines() if "`../occam-<name>/SKILL.md`" in line)
    for path in LANGUAGE_SKILLS:
        assert re.search(rf"\b{path.parent.name.removeprefix('occam-')}\b", line), path.parent.name
        assert (SKILL / ".." / path.parent.name / "SKILL.md").is_file(), "the core's relative path must reach it"


def test_helpers_are_routed_and_front_doors_are_listed():
    """Every session pays for each listed description, and the listing drops descriptions past about 1% of context, so a large
    set of skills can't all be listed. Helpers come off it and get a route instead; adding one costs no always-on text."""
    sys.path.insert(0, str(PLUGIN / "hooks"))
    from classify import LANGUAGE_PROMPTS, LANGUAGE_SKILLS as ROUTES
    for path in ALL_SKILLS:
        front, _ = parts(path)
        assert front.get("disable-model-invocation") is (True if path in LANGUAGE_SKILLS else None), path.parent.name
    for path in LANGUAGE_SKILLS:
        name = path.parent.name
        assert name in ROUTES.values() and name in LANGUAGE_PROMPTS, f"{name} is hidden but nothing routes to it"


def test_hook_maps_only_to_language_skills_that_exist():
    source = (PLUGIN / "hooks" / "classify.py").read_text()
    mapped = set(re.findall(r'"(occam-[a-z]+)"', source))
    assert mapped - NON_LANGUAGE_SKILLS == {path.parent.name for path in LANGUAGE_SKILLS}


@pytest.mark.parametrize("path", LANGUAGE_SKILLS, ids=lambda p: p.parent.name)
def test_language_skills_stay_short_and_say_when_they_apply(path):
    front, body = parts(path)
    assert len(body.split()) <= 800
    assert "occam" in front["description"]


def test_plugin_manifest_and_marketplace_agree():
    manifest = json.loads((PLUGIN / ".claude-plugin" / "plugin.json").read_text())
    market = json.loads((ROOT / ".claude-plugin" / "marketplace.json").read_text())
    assert manifest["name"] == "occam" and market["plugins"][0]["name"] == "occam"
    assert (ROOT / market["plugins"][0]["source"] / ".claude-plugin" / "plugin.json").exists()


COMMANDS = sorted((PLUGIN / "commands").glob("*.md"))


def test_the_three_commands_ship():
    assert {path.stem for path in COMMANDS} == {"razor", "review", "audit"}


@pytest.mark.parametrize("path", COMMANDS, ids=lambda p: p.stem)
def test_commands_run_only_when_typed_and_send_to_real_skills(path):
    """Typed commands are a front door, so the model mustn't start them itself, and the skills they hand to must exist."""
    front, body = parts(path)
    assert front["disable-model-invocation"] is True
    assert 1 <= len(front["description"]) <= 200
    named = re.findall(r"`(occam[\w-]*)` skill", body)
    assert named and all((SKILLS / name / "SKILL.md").exists() for name in named), named


def test_commands_name_only_real_tool_flags():
    """A wrong flag in a command reaches everyone who types it, so each `tool --flag` a command names must be in that tool's help."""
    tools = set(re.findall(r'add_parser\(allow_abbrev=False, name="(\w+)"', (SCRIPTS / "occam_tools" / "cli.py").read_text()))
    checked = set()
    for path in COMMANDS:
        for tool, rest in re.findall(r"`([a-z]+)((?: --[\w-]+(?: [^`\s-][^`\s]*)?)*)`", path.read_text()):
            if tool in tools:
                usage = subprocess.run([sys.executable, str(SCRIPTS / "occam.py"), tool, "--help"], capture_output=True, text=True, timeout=60, check=True).stdout
                flags = re.findall(r"--[\w-]+", rest)
                assert all(re.search(re.escape(flag) + r"(?![\w-])", usage) for flag in flags), (path.name, tool, flags)
                checked.add(tool)
    assert {"scan", "gate", "golden"} <= checked, checked


def test_reviewer_agent_has_no_edit_tools():
    front, _ = parts(PLUGIN / "agents" / "code-reviewer.md")
    assert front["name"] == "code-reviewer"
    assert not {"Edit", "Write", "NotebookEdit"} & {tool.strip() for tool in front["tools"].split(",")}


def test_size_budgets():
    _, body = parts(SKILL_MD)
    words = len(body.split())
    assert len(SKILL_MD.read_text().splitlines()) < 500
    assert 1000 <= words <= 1450, f"{words} words: the core routes to switched modules, so growth belongs in one of them"
    assert len(body) / 3.5 < 5000, "estimated tokens over budget, and only the first 5,000 survive compaction"


def references() -> list[str]:
    _, body = parts(SKILL_MD)
    return re.findall(r"\]\((references/[^)#]+)", body)


def test_links_resolve_and_every_reference_is_linked():
    linked = set(references())
    assert linked, "no references linked"
    assert all((SKILL / link).exists() for link in linked)
    assert {str(p.relative_to(SKILL)) for p in (SKILL / "references").glob("*.md")} == linked


def test_references_are_one_level_deep_and_navigable():
    for path in (SKILL / "references").glob("*.md"):
        text = path.read_text()
        assert "references/" not in text, f"{path.name} chains to another reference"
        if len(text.splitlines()) > 300:
            assert re.search(r"(?i)contents", text[:600]), f"{path.name} is long and has no table of contents"


@pytest.mark.parametrize("path", [*ALL_SKILLS, *sorted((SKILL / "references").glob("*.md"))], ids=lambda p: f"{p.parent.name}-{p.name}")
def test_no_host_specific_names_in_portable_core(path):
    hits = HOST_SPECIFIC.findall(path.read_text())
    assert not hits, f"{path.name}: {hits}"


def test_no_shouting():
    _, body = parts(SKILL_MD)
    assert not re.findall(r"\b(?:MUST|NEVER|ALWAYS|IMPORTANT|CRITICAL)\b", body), "plain wording: emphasis causes over-application"


def test_audit_skill_stays_small_and_links_resolve():
    _, body = parts(AUDIT / "SKILL.md")
    assert len(body.split()) <= 1400
    linked = set(re.findall(r"\]\((references/[^)#]+)", body))
    assert linked == {str(p.relative_to(AUDIT)) for p in (AUDIT / "references").glob("*.md")}
    assert all("references/" not in p.read_text() for p in (AUDIT / "references").glob("*.md"))


def test_audit_skill_has_no_host_specific_names():
    for path in [AUDIT / "SKILL.md", *sorted((AUDIT / "references").glob("*.md"))]:
        assert not HOST_SPECIFIC.findall(path.read_text()), path.name


def test_skills_only_mention_tool_commands_that_exist():
    from_cli = (SCRIPTS / "occam_tools" / "cli.py").read_text()
    commands = set(re.findall(r'add_parser\(allow_abbrev=False, name="(\w+)"', from_cli))
    for path in [SKILL_MD, AUDIT / "SKILL.md", *sorted((AUDIT / "references").glob("*.md")), DOCS_SKILL]:
        for mentioned in re.findall(r"`occam ([a-z]+)", path.read_text()):
            assert mentioned in commands, f"{path.name} mentions occam {mentioned}"


def test_docs_skill_stays_small_and_says_how_to_reach_the_tool():
    front, body = parts(DOCS_SKILL)
    assert len(body.split()) <= 950
    assert "human-voice" in front["description"] and "occam" in front["description"]
    assert (DOCS_SKILL.parent / "../occam/scripts/occam.py").exists() and "../occam/scripts/occam.py" in body


def test_tools_use_only_the_standard_library(monkeypatch):
    import ast
    monkeypatch.syspath_prepend(str(SCRIPTS))
    from occam_tools.manifests import stdlib_modules  # sys.stdlib_module_names is from 3.10, and CI runs 3.9
    stdlib = stdlib_modules()
    for path in SCRIPTS.rglob("*.py"):
        for node in ast.walk(ast.parse(path.read_text())):
            names = [a.name for a in node.names] if isinstance(node, ast.Import) else [node.module] if isinstance(node, ast.ImportFrom) and not node.level else []
            for name in names:
                assert name.split(".")[0] in stdlib | {"occam_tools"}, f"{path.name} imports {name}"


def test_tools_work_on_the_oldest_supported_python():
    import ast
    for path in SCRIPTS.rglob("*.py"):
        ast.parse(path.read_text(), feature_version=(3, 9))
        if path.name != "__init__.py" and path.name != "occam.py":
            assert "from __future__ import annotations" in path.read_text(), f"{path.name} needs it for 3.9"


def test_no_tool_module_passes_the_size_trigger_it_enforces():
    for path in SCRIPTS.rglob("*.py"):
        assert len(path.read_text().splitlines()) <= 1000, path.name


def test_codex_manifest_agrees_with_claude_manifest():
    codex = json.loads((PLUGIN / ".codex-plugin" / "plugin.json").read_text())
    claude = json.loads((PLUGIN / ".claude-plugin" / "plugin.json").read_text())
    assert codex["name"] == claude["name"] and codex["version"] == claude["version"]
    assert (PLUGIN / codex["skills"]).is_dir() and (PLUGIN / codex["hooks"]).is_file()


def test_only_expected_things_ship_in_the_skill():
    assert {p.name for p in SKILL.iterdir()} <= {"SKILL.md", "references", "scripts", "assets"}
    assert not list(SKILLS.rglob("hooks*")), "hooks belong to the plugin layer, so a plain copy of a skill activates nothing"


def test_text_every_run_pays_for_stays_small():
    """Every session pays for descriptions on every turn, and most code runs for the core and a language skill. Growing them should be a decision."""
    front = sum(len(parts(path)[0]["description"]) for path in ALL_SKILLS if not parts(path)[0].get("disable-model-invocation"))
    agents = sum(len(parts(path)[0]["description"]) for path in (PLUGIN / "agents").glob("*.md"))
    assert front + agents <= 1500, f"{front + agents}: 3,350 before the language skills were routed on 2026-11-08. A new skill is a routed helper unless people ask for it by name"
    assert len(parts(SKILL_MD)[1]) <= 9400, "13,000 before its modules moved behind switches on 2026-11-07"
    assert all(len(parts(path)[1]) <= 5500 for path in LANGUAGE_SKILLS)


def test_switched_modules_stay_short():
    """A module is stated whole, as context, when its switch turns on, so each one is paid in full by every run it fires in."""
    sys.path.insert(0, str(PLUGIN / "hooks"))
    import skill_switches as switches
    for name in switches.MODULES:
        assert len((SKILL / "references" / f"{name}.md").read_text()) <= 2000, name


def test_compact_variant_is_a_real_compact_core():
    front, body = parts(COMPACT)
    full_front, _ = parts(SKILL_MD)
    assert front["name"] == full_front["name"]
    assert front["description"] == full_front["description"], "same triggers, so only the body differs between arms"
    assert len(body.split()) <= 450
