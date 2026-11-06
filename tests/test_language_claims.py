"""The Go and Rust skills state how their test tools report nothing as success. Those claims are run, not recalled."""

import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SKILLS = ROOT / "plugin" / "skills"
GO = shutil.which("go")
CARGO = shutil.which("cargo")


@pytest.mark.parametrize("skill", ["occam-typescript", "occam-go", "occam-rust"])
def test_main_languages_cover_structure_naming_and_test_results(skill):
    text = (SKILLS / skill / "SKILL.md").read_text()
    for heading in ("**Structure:**", "**Naming:**"):
        assert heading in text, f"{skill} lost {heading}"
    assert re.search(r"\*\*Test(s| results):\*\*", text), skill


@pytest.fixture
def go_module(tmp_path):
    if not GO:
        pytest.skip("Go isn't installed, so its claims weren't run")
    (tmp_path / "go.mod").write_text("module example.invalid/demo\n\ngo 1.22\n")
    (tmp_path / "a.go").write_text("package demo\n\nfunc Add(x, y int) int { return x + y }\n")
    (tmp_path / "a_test.go").write_text('package demo\n\nimport "testing"\n\nfunc TestAdd(t *testing.T) { if Add(1, 2) != 3 { t.Fatal("bad") } }\n')
    return tmp_path


def go_test(folder, *args):
    return subprocess.run([GO, "test", *args], cwd=folder, capture_output=True, text=True, timeout=120)


def test_go_reports_success_when_run_matches_nothing(go_module):
    done = go_test(go_module, "-run", "NoSuchTest", ".")
    assert done.returncode == 0 and "no tests to run" in done.stdout


def test_go_reports_success_for_a_package_with_no_tests(go_module):
    (go_module / "a_test.go").unlink()
    done = go_test(go_module, ".")
    assert done.returncode == 0 and "no test files" in done.stdout


def test_go_import_cycles_do_not_compile(go_module):
    for name, other in (("x", "y"), ("y", "x")):
        (go_module / name).mkdir()
        (go_module / name / f"{name}.go").write_text(f'package {name}\n\nimport _ "example.invalid/demo/{other}"\n')
    done = subprocess.run([GO, "build", "./x"], cwd=go_module, capture_output=True, text=True, timeout=120)
    assert done.returncode != 0 and "import cycle" in done.stderr


def test_go_caches_results_and_count_forces_a_run(go_module):
    go_test(go_module, ".")
    assert "(cached)" in go_test(go_module, ".").stdout
    assert "(cached)" not in go_test(go_module, "-count=1", ".").stdout


@pytest.fixture
def crate(tmp_path):
    if not CARGO:
        pytest.skip("Rust isn't installed, so its claims weren't run")
    (tmp_path / "Cargo.toml").write_text('[package]\nname = "demo"\nversion = "0.1.0"\nedition = "2021"\n')
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "lib.rs").write_text("#[test]\nfn adds() { assert_eq!(1 + 2, 3); }\n\n#[test]\n#[ignore]\nfn ignored() { assert!(false); }\n")
    (tmp_path / "src" / "orphan.rs").write_text('#[test]\nfn orphan_fails() { assert!(false, "no mod names this file"); }\n')
    return tmp_path


def cargo_test(folder, *args):
    return subprocess.run([CARGO, "test", "--offline", *args], cwd=folder, capture_output=True, text=True, timeout=240,
                          env={**__import__("os").environ, "CARGO_TARGET_DIR": str(folder / "target")})


def test_rust_never_compiles_a_file_no_mod_names_and_exits_0_with_a_failing_test_ignored(crate):
    done = cargo_test(crate)
    assert done.returncode == 0, done.stderr
    assert "orphan_fails" not in done.stdout and "1 ignored" in done.stdout


def test_rust_reports_success_when_a_filter_matches_nothing(crate):
    done = cargo_test(crate, "no_such_test")
    assert done.returncode == 0 and "filtered out" in done.stdout and "1 passed" not in done.stdout
