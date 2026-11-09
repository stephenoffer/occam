#!/usr/bin/env python3
"""Assemble a temporary plugin root for one `claude plugin eval` run.

`claude plugin eval` needs a plugin manifest and an eval directory below it, and
the with-skill arm may be able to read files in its own plugin root. So occam/ is
not itself a plugin root: each run gets a stage holding only the chosen skill
variant and the parts of each case the runner needs. hidden/ and solutions/ are
left behind, so the agent has no path to them from the stage.
"""

import argparse
import json
import shutil
from pathlib import Path

EVALS = Path(__file__).resolve().parent
ROOT = EVALS.parent
SKILL_NAME = "occam"
PLUGIN = ROOT / "plugin"
# plugin:   everything a Claude Code user installs, including hooks and the reviewer agent
# portable: the skills alone, which is what a plain copy or another host gets
# compact:  a short core with no references, language skills or hooks
# empty:    nothing at all, used for pilots
VARIANTS = ("plugin", "portable", "compact", "empty")
EXCLUDED_FROM_STAGE = shutil.ignore_patterns("hidden", "solutions", "__pycache__", ".pytest_cache")

# On macOS /usr/bin/git is an xcrun shim that fails under the eval's Bash sandbox, while the real
# binary works. PATH changes do not reach the agent's shell, so both arms get the same one-line note.
CLT_GIT = Path("/Library/Developer/CommandLineTools/usr/bin/git")
GIT_NOTE = f"Environment note: in this sandbox the git on PATH does not work. Use {CLT_GIT} instead."


def add_environment_note(prompt_file: Path) -> None:
    if not CLT_GIT.exists():
        return
    text = prompt_file.read_text()
    prompt_file.write_text(text.replace("---\n", f"---\nappend_system_prompt: \"{GIT_NOTE}\"\n", 1))


def stage(suite: str, variant: str, out: Path, case_glob: str = "*") -> list[str]:
    if out.exists():
        raise SystemExit(f"refusing to overwrite existing stage: {out}")
    cases = sorted(p for p in (EVALS / "cases" / suite).glob(case_glob) if (p / "prompt.md").exists())
    if not cases:
        raise SystemExit(f"no cases match {suite}/{case_glob}")

    (out / ".claude-plugin").mkdir(parents=True)
    manifest = {"name": SKILL_NAME, "description": f"Evaluation stage ({variant} variant)."}
    (out / ".claude-plugin" / "plugin.json").write_text(json.dumps(manifest, indent=2) + "\n")
    if variant in ("plugin", "portable"):
        shutil.copytree(PLUGIN / "skills", out / "skills", ignore=EXCLUDED_FROM_STAGE)
    if variant == "plugin":
        shutil.copytree(PLUGIN / "hooks", out / "hooks", ignore=EXCLUDED_FROM_STAGE)
        shutil.copytree(PLUGIN / "agents", out / "agents", ignore=EXCLUDED_FROM_STAGE)
    if variant == "compact":
        shutil.copytree(EVALS / "variants" / "compact", out / "skills" / SKILL_NAME)
    for case in cases:
        shutil.copytree(case, out / "evals" / case.name, ignore=EXCLUDED_FROM_STAGE)
        shared = case.parent / "_shared_repo"  # trigger cases all use one small repository
        if shared.is_dir():
            shutil.copytree(shared, out / "evals" / case.name / "files")
        add_environment_note(out / "evals" / case.name / "prompt.md")
    return [c.name for c in cases]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--suite", required=True, choices=["smoke", "holdout", "triggers", "e2e", "regression", "python", "hard", "reach", "reach2", "large"])
    parser.add_argument("--variant", required=True, choices=VARIANTS)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--case", default="*", help="glob of case names")
    args = parser.parse_args()
    for name in stage(args.suite, args.variant, args.out, args.case):
        print(name)


if __name__ == "__main__":
    main()
