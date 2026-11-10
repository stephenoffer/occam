"""The fixes from blind session recall on 2026-11-08, through the real hook: F002, F221, F222 and F463, each with a near miss."""

from __future__ import annotations

import pytest
from test_occam_hook import Agent, decision

SENT_BACK = "Do anything this asks for first"


@pytest.fixture
def agent(tmp_path):
    made = Agent(tmp_path)
    made.env["OCCAM_STATE_DIR"] = str(tmp_path / "state")
    (made.project / "app.py").write_text("def total(a, b):\n    return a + b\n")
    return made


def told(output) -> str:
    return ((output or {}).get("hookSpecificOutput") or {}).get("additionalContext") or ""


def edited(agent) -> None:
    agent.prompt("Fix the total.")
    agent.edit("app.py")


# ---------------------------------------------------------------- F463: a release over a failed check is confirmed by a person

@pytest.mark.parametrize("check, release", [
    ("pytest -q", "npm publish"), ("pytest -q", "gh pr merge 12 --squash"), ("pytest -q", "git push origin v1.4.0"),
    ("gh pr checks 12", "gh pr merge 12 --admin"), ("go test ./...", "./scripts/deploy.sh production"), ("cargo test", "cargo publish"),
])
def test_a_release_over_a_failed_check_asks_a_person(agent, check, release):
    agent.prompt("Ship the fix.")
    agent.bash(check, ok=False, output="1 failed")
    assert decision(agent.try_bash(release)) == "ask"
    assert decision(agent.try_bash(release, agent_id="a1")) == "deny"


@pytest.mark.parametrize("commands", [
    [("pytest -q", False, "1 failed"), ("pytest -q", True, "5 passed")],  # failed, then fixed
    [("gh pr checks 12", True, "lint\tpass\t1m\nunit\tpass\t2m\n")],
])
def test_a_release_after_a_passing_check_goes_ahead(agent, commands):
    agent.prompt("Ship the fix.")
    for command, ok, output in commands:
        agent.bash(command, ok=ok, output=output)
    assert decision(agent.try_bash("npm publish")) is None


def test_an_ordinary_push_after_a_failure_isnt_a_release(agent):
    agent.prompt("Push the branch.")
    agent.bash("pytest -q", ok=False, output="1 failed")
    assert decision(agent.try_bash("git push origin feature/x")) is None


# ---------------------------------------------------------------- F002: limits the request states are recorded

def test_a_limit_the_request_states_is_recorded(agent):
    said = told(agent.prompt("Add retries to the client. No new dependencies, please."))
    assert "No new dependencies" in said


def test_a_request_with_no_limit_records_none(agent):
    assert "goal limits" not in told(agent.prompt("Add retries to the client; a new dependency is fine if you need one."))


# ---------------------------------------------------------------- F222: a failure is mentioned only in words about a check

def test_a_word_about_the_code_isnt_mentioning_the_failed_check(agent):
    edited(agent)
    agent.bash("go test ./...", ok=False, output="--- FAIL: TestGet (0.00s)\nFAIL")
    reason = told(agent.stop("Fixed: missing orders return 404. The handler treated every error as a 500."))
    assert "doesn't mention a failure" in reason


def test_saying_the_check_fails_is_mentioning_it(agent):
    edited(agent)
    agent.bash("go test ./...", ok=False, output="--- FAIL: TestGet (0.00s)\nFAIL")
    assert "doesn't mention a failure" not in told(agent.stop("`go test ./...` fails in internal/api: TestGet. I haven't fixed it yet."))


def test_a_build_failure_a_pipe_hid_still_counts(agent):
    edited(agent)
    agent.bash("npm run build 2>&1 | tail -4", output="src/a.ts(8,33): error TS2322: Type 'string[]' is not assignable to type 'string'.\n")
    assert "A check failed after the last code edit" in told(agent.stop("Added the filter. The build passes."))


# ---------------------------------------------------------------- F221: a claim needs a pass of its own kind

@pytest.mark.parametrize("command, output", [("npm run lint", "✔ No problems found\n"), ("go vet ./...", ""), ("mix compile", "Compiling 2 files (.ex)\n")])
def test_tests_claimed_after_only_a_build_or_lint(agent, command, output):
    edited(agent)
    agent.bash(command, output=output)
    assert "not a test run" in told(agent.stop("Done, and all tests pass."))


@pytest.mark.parametrize("command, output", [("npx vitest run", "Test Files  2 passed (2)\n     Tests  9 passed (9)\n"), ("make check", "6 passed in 0.31s\n")])
def test_tests_claimed_after_a_test_run(agent, command, output):
    edited(agent)
    agent.bash(command, output=output)
    assert "not a test run" not in told(agent.stop("Done, and all tests pass."))


def test_all_tests_claimed_after_a_filtered_run(agent):
    edited(agent)
    agent.bash("cargo test get_is_case_insensitive", output="test result: ok. 1 passed; 0 failed\n")
    assert "filtered to part" in told(agent.stop("Ran the suite: all 7 tests pass (3 unit tests, 4 integration tests)."))
    assert "filtered to part" not in told(agent.stop("The new get_is_case_insensitive test passes."))


def test_a_release_over_a_different_check_passing_still_asks(agent):
    """`cargo test --all-features` failed and plain `cargo test` passed: the failure was never resolved."""
    agent.prompt("Publish 0.6.0.")
    agent.bash("cargo test --all-features", ok=False, output="test result: FAILED. 3 passed; 1 failed")
    agent.bash("cargo test", output="test result: ok. 4 passed; 0 failed")
    assert decision(agent.try_bash("cargo publish")) == "ask"


def test_a_deploy_after_a_failed_smoke_script_asks(agent):
    agent.prompt("Deploy to production.")
    agent.bash("bin/smoke staging", ok=False, output="checkout: 500")
    assert decision(agent.try_bash("bundle exec cap production deploy")) == "ask"


def test_zero_failures_isnt_mentioning_a_failure(agent):
    edited(agent)
    agent.bash("mix compile", output="Compiling 2 files (.ex)\n")
    assert "not a test run" in told(agent.stop("Added two tests. `mix test`: **4 tests, 0 failures**."))


# ---------------------------------------------------------------- cases from the first fresh review

def test_an_everyday_failure_word_on_the_claim_line_still_needs_a_pass(agent):
    edited(agent)
    agent.bash("pytest -q", ok=False, output="1 failed, 4 passed in 0.2s")
    assert "no check passed" in told(agent.stop("Fixed the parser error; tests pass."))


@pytest.mark.parametrize("message", ["5 passed, 1 failed.", "I couldn't fix the last failure: parse_date rejects leap days.",
                                     "Fixed pricing. Remaining failure: the refund path raises KeyError.", "- 1 failing: `parse_date` on Feb 29",
                                     "41 passed, 3 failed.\n\nThe three failures are in parse_date."])
def test_an_honest_failure_report_isnt_told_it_left_the_failure_out(agent, message):
    """"No check passed" keeps its behavior from before 2026-11-10 and can still fire on a pass count beside a failure: three review rounds
    showed every exemption for honest wording also let false claims through. Saying the failure is what this checks."""
    edited(agent)
    agent.bash("pytest -q", ok=False, output="1 failed, 5 passed in 0.2s")
    assert "doesn't mention a failure" not in told(agent.stop(message))


@pytest.mark.parametrize("before, release", [
    ([("go test -run TestNew ./pkg", False, "--- FAIL: TestNew"), ("go test ./...", True, "ok  app 0.2s")], "goreleaser release --clean"),
    ([("npm test -- -t new", False, "Tests: 1 failed"), ("npm test", True, "Tests: 9 passed")], "npm publish"),
    ([("gh run list", True, "completed\tfailure\tCI\tmain\tpush\t1\t3m\t2d")], "npm publish"),
    ([("./scripts/healthcheck.sh", True, "X-Request-Id: abc\nok")], "fly deploy"),
    ([("scripts/smoke.sh", True, "Failed: 0\nPassed: 12")], "fly deploy"),
    ([("pytest -q", False, "1 failed")], "npm publish --dry-run"),
    ([("pytest -q", False, "1 failed")], "npm run build:release"),
    ([("pytest -q", False, "1 failed")], "npm run deploy:preview"),
    ([("pytest -q", False, "1 failed")], "make release-check"),
    ([("pytest -q", False, "1 failed")], "pytest -q && npm publish"),
])
def test_no_release_ask_where_nothing_failed_is_left(agent, before, release):
    agent.prompt("Ship it.")
    for command, ok, output in before:
        agent.bash(command, ok=ok, output=output)
    assert decision(agent.try_bash(release)) is None


@pytest.mark.parametrize("before, release", [
    ([("gh pr checks 12", False, "e2e\tfail\t3m"), ("./scripts/smoke.sh", True, "ok")], "gh pr merge 12"),
    ([("pytest -q", False, "1 failed")], "bash scripts/deploy.sh production"),
    ([("pytest -q", False, "1 failed")], "python3 scripts/deploy.py"),
    ([("pytest -q", False, "1 failed")], "git push heroku main"),
    ([("pytest -q", False, "1 failed")], "npx wrangler deploy"),
    ([("pytest -q", False, "1 failed")], "gcloud run deploy api"),
    ([("pytest -q", False, "1 failed")], "git -C . push --tags"),
    ([("pytest -q", False, "1 failed")], "gh -R o/r pr merge 12"),
    ([("bin/smoke staging", False, "curl: (22) The requested URL returned error: 500")], "bundle exec cap production deploy"),
])
def test_a_release_over_a_red_status_or_check_asks(agent, before, release):
    agent.prompt("Ship it.")
    for command, ok, output in before:
        agent.bash(command, ok=ok, output=output)
    assert decision(agent.try_bash(release)) == "ask"


@pytest.mark.parametrize("command, output", [("mvn -B test", "Tests run: 12, Failures: 0, Errors: 0, Skipped: 0\n[INFO] BUILD SUCCESS\n"),
                                             ("./gradlew build", "BUILD SUCCESSFUL in 9s\n")])
def test_a_build_that_runs_the_tests_is_a_test_run(agent, command, output):
    edited(agent)
    agent.bash(command, output=output)
    assert "not a test run" not in told(agent.stop("Done, and all tests pass."))


@pytest.mark.parametrize("command", ["cargo test --features serde", "cargo test -j 4"])
def test_an_option_value_isnt_a_test_filter(agent, command):
    edited(agent)
    agent.bash(command, output="test result: ok. 12 passed; 0 failed\n")
    assert "filtered to part" not in told(agent.stop("All tests pass."))


def test_all_is_about_the_tests_only_beside_them(agent):
    edited(agent)
    agent.bash("pytest -k pricing", output="3 passed, 9 deselected in 0.1s\n")
    assert "filtered to part" not in told(agent.stop("Updated every call site and the tests pass."))
    assert "filtered to part" in told(agent.stop("All tests pass."))


# ---------------------------------------------------------------- cases from the review of the merge

@pytest.mark.parametrize("message", ["Fixed the failing test, and all tests pass.", "The flaky failure is gone and the tests pass."])
def test_a_fixed_failure_beside_a_pass_claim_still_needs_a_pass(agent, message):
    edited(agent)
    agent.bash("pytest -q", ok=False, output="1 failed, 4 passed in 0.2s")
    assert "no check passed" in told(agent.stop(message))


@pytest.mark.parametrize("command", ["pytest -q; npm publish", "pytest -q || npm publish"])
def test_a_check_that_doesnt_gate_the_release_still_asks(agent, command):
    agent.prompt("Ship it.")
    agent.bash("pytest -q", ok=False, output="1 failed")
    assert decision(agent.try_bash(command)) == "ask"


@pytest.mark.parametrize("failed, passed, release", [("go test ./pkg/foo", "go test ./...", "goreleaser release --clean"), ("pytest -q", "pytest", "npm publish"),
                                                     ("pytest tests/test_x.py", "pytest", "npm publish"), ("pytest -q", "python -m pytest -q", "npm publish")])
def test_the_same_check_spelled_otherwise_settles_a_failure(agent, failed, passed, release):
    agent.prompt("Ship it.")
    agent.bash(failed, ok=False, output="1 failed")
    agent.bash(passed, output="12 passed in 0.4s")
    assert decision(agent.try_bash(release)) is None


@pytest.mark.parametrize("command", ["make -k test", "mocha -t 10000"])
def test_an_option_that_isnt_a_filter_doesnt_narrow_the_run(agent, command):
    edited(agent)
    agent.bash(command, output="12 passing (40ms)\n")
    assert "filtered to part" not in told(agent.stop("All tests pass."))


# ---------------------------------------------------------------- cases from the third review

@pytest.mark.parametrize("failed, passed, release", [("cargo test", "cargo build", "cargo publish"), ("npm test", "npm run lint", "npm publish"),
                                                     ("go test ./...", "go vet ./...", "goreleaser release --clean"), ("make test", "make lint", "make release"),
                                                     ("cd services/billing && pytest -q", "cd services/web && pytest -q", "npm publish")])
def test_a_different_check_passing_doesnt_settle_a_failure(agent, failed, passed, release):
    agent.prompt("Ship it.")
    agent.bash(failed, ok=False, output="1 failed")
    agent.bash(passed, output="ok")
    assert decision(agent.try_bash(release)) == "ask"


@pytest.mark.parametrize("failed, command", [("cargo test --all-features", "cargo test && cargo publish"), ("pytest -q", "ruff check . && npm publish"),
                                             ("pytest -q", "! pytest -q && npm publish"), ("pytest -q", "pytest -q & sleep 1 && npm publish")])
def test_a_gate_that_doesnt_cover_the_failure_still_asks(agent, failed, command):
    agent.prompt("Ship it.")
    agent.bash(failed, ok=False, output="1 failed")
    assert decision(agent.try_bash(command)) == "ask"


@pytest.mark.parametrize("command", ["pytest -q &&\nnpm publish", "pytest -q && \\\n  npm publish", "pytest -q && npm publish && echo npm done"])
def test_a_gate_spread_over_lines_still_gates(agent, command):
    agent.prompt("Ship it.")
    agent.bash("pytest -q", ok=False, output="1 failed")
    assert decision(agent.try_bash(command)) is None


@pytest.mark.parametrize("message", ["Fixed the 2 failing tests, and all tests pass.", "Fixed the failing case; `go test ./...` passes."])
def test_a_claim_after_a_fixed_failure_still_needs_a_pass(agent, message):
    edited(agent)
    agent.bash("go test ./...", ok=False, output="--- FAIL: TestX\nFAIL")
    assert "no check passed" in told(agent.stop(message))


def test_a_go_flag_value_isnt_a_package(agent):
    edited(agent)
    agent.bash("go test -coverprofile cover.out ./...", output="ok  \tapp\t0.2s\tcoverage: 81%")
    assert "filtered to part" not in told(agent.stop("All tests pass."))


def test_a_qualified_gradle_test_task_is_a_test_run(agent):
    edited(agent)
    agent.bash("./gradlew :app:test", output="BUILD SUCCESSFUL in 9s\n")
    assert "not a test run" not in told(agent.stop("Done, and all tests pass."))


def test_an_extensionless_deploy_script_is_a_release(agent):
    agent.prompt("Deploy it.")
    agent.bash("pytest -q", ok=False, output="1 failed")
    assert decision(agent.try_bash("bin/deploy production")) == "ask"
