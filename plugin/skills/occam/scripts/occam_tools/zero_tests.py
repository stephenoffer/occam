"""Did a test command run any tests? Exit code 0 doesn't say, because these runners can all pass with nothing to run.

The hook and the tools both ask this, so they can't disagree about what counts as having tested something.
"""

from __future__ import annotations  # the stock macOS python3 is 3.9

import re

_ANSI = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")
# Summary lines, so a test whose name or output mentions these phrases can't trip them. pytest prints them on their own line, with or without `=== `.
_NOTHING_RAN = re.compile(r"^[ \t]*collected 0 items\b|^[= ]*no tests ran\b|^[= ]*no tests collected\b|^[ \t]*Ran 0 tests\b"
                          r"|^[= ]*[1-9]\d* deselected\b[^=\n]{0,40} in \d|^[= ]*[1-9]\d* skipped\b[^=\n]{0,40} in \d"
                          r"|^[ \t]*Ran (\d+) tests?\b[^\n]*\n{1,3}OK \(skipped=\1\)"
                          r"|^(?:\S+:\s*)?No tests? (?:files? )?found\b|^No tests were found\b|^No tests executed\b"  # jest, vitest, ctest, phpunit
                          r"|\b0 examples, 0 failures\b|^[ \t]*0 passing\b"  # rspec, mocha
                          r"|\bTests run: 0, Failures: 0\b|\bStarting 0 tests across\b|^1\.\.0\b"  # mvn, nextest, TAP
                          r"|^Tests:\s+(?:0 passed, )?0 total\b|\b0 runs, 0 assertions\b|\bNo test is available\b|^ok \| 0 passed"  # jest, rake, dotnet, deno
                          r"|\bExecuted 0 tests\b|^[ \t]*0 tests, 0 failures\b|^DONE 0 tests\b|^[ \t]*0 pass[ \t]*\n[ \t]*0 fail\b|^(?:#|ℹ)[ \t]*tests 0\b"  # xcodebuild, exunit, gotestsum, bun, node
                          r"|^0 features passed\b|^0 scenarios\b|^0 specs, 0 failures\b"  # behave, cucumber, jasmine
                          r"|^[= ]*[1-9]\d* xfailed\b[^=\n]{0,40} in \d|^[= ]*[1-9]\d* tests? collected\b[^=\n]{0,20} in \d", re.I | re.M)  # pytest: all expected failures, or --collect-only
# Anything here means something did run, which settles it for a monorepo where one package had no tests.
_SOMETHING_RAN = re.compile(r"\b[1-9]\d* (?:passed|xpassed|passing|failed|failing)\b|^--- (?:PASS|FAIL)\b|(?-i:^ok\b)(?! \| 0 passed)(?!.*\[no tests to run\])|\b[1-9]\d* examples?, |\bTests run: [1-9]|^[ \t]*Ran [1-9]\d* tests?\b(?![^\n]*\n{1,3}OK \(skipped=)", re.I | re.M)
_CARGO_RESULT = re.compile(r"^test result: \w+\. (\d+) passed; (\d+) failed", re.M)
_GO_NOTHING = re.compile(r"\[no test files\]|\[no tests to run\]")
_GO_RAN = re.compile(r"^ok\b(?!.*\[no tests to run\])|^FAIL\b|^--- ", re.M)


def ran_no_tests(output: str) -> bool:
    output = _ANSI.sub("", output)
    if _SOMETHING_RAN.search(output):
        return False
    if _NOTHING_RAN.search(output):
        return True
    # One binary with no tests is normal for cargo and go, so these two count only if nothing ran anywhere.
    cargo = _CARGO_RESULT.findall(output)
    if cargo and not any(int(passed) + int(failed) for passed, failed in cargo):
        return True
    return bool(_GO_NOTHING.search(output)) and not _GO_RAN.search(output)
