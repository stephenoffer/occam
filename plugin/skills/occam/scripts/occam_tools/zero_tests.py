"""Did a test command run any tests? Exit code 0 doesn't say, because these runners can all pass with nothing to run.

The hook and the tools both ask this, so they can't disagree about what counts as having tested something.
"""

from __future__ import annotations  # the stock macOS python3 is 3.9

import re

# A fully skipped or fully deselected run exits 0, or looks like it behind a pipe. `, ` before the count means something else ran.
_NOTHING_RAN = re.compile(r"collected 0 items|no tests ran|no tests collected|\bRan 0 tests\b"
                          r"|(?<!, )\b[1-9]\d* deselected in \d|(?<!, )\b[1-9]\d* skipped\b[^=\n]{0,40} in \d"
                          r"|\bRan (\d+) tests?\b[^\n]*\n+OK \(skipped=\1\)"
                          r"|\bNo tests? (?:files? )?found\b|\bNo tests were found\b|\bNo tests executed\b"  # jest, vitest, ctest, phpunit
                          r"|\b0 examples, 0 failures\b|\b0 passing\b", re.I)  # rspec, mocha
_CARGO_RESULT = re.compile(r"^test result: \w+\. (\d+) passed; (\d+) failed", re.M)
_GO_NOTHING = re.compile(r"\[no test files\]|\[no tests to run\]")
_GO_RAN = re.compile(r"^ok\b(?!.*\[no tests to run\])|^FAIL\b|^--- ", re.M)


def ran_no_tests(output: str) -> bool:
    if _NOTHING_RAN.search(output):
        return True
    # One binary with no tests is normal for cargo and go, so these two count only if nothing ran anywhere.
    cargo = _CARGO_RESULT.findall(output)
    if cargo and not any(int(passed) + int(failed) for passed, failed in cargo):
        return True
    return bool(_GO_NOTHING.search(output)) and not _GO_RAN.search(output)
