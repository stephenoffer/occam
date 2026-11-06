"""Every rule the scanner can report: what it means, how sure it can be, and who may act on it.

Fix tiers decide permission, not difficulty:
  A  mechanical, with a proof the code didn't change. Apply when fixing is authorized.
  B  behavior-preserving or plainly corrective, needs a check first. Apply when fixing is authorized.
  C  changes behavior, contracts, data or cost, or needs a product decision. Ask first.
"""

from __future__ import annotations

from typing import NamedTuple

SEVERITIES = ("critical", "high", "medium", "low")
CONFIDENCES = ("high", "medium", "low")
LAYERS = ("api", "domain", "algorithm", "runtime", "concurrency", "storage-network", "os", "hardware", "ops", "test")


class Rule(NamedTuple):
    id: str
    category: str
    layer: str
    severity: str
    confidence: str
    tier: str
    title: str
    fix: str


def _table(category: str, rows: list[tuple[str, str, str, str, str, str, str]]) -> list[Rule]:
    return [Rule(id_, category, layer, sev, conf, tier, title, fix) for id_, layer, sev, conf, tier, title, fix in rows]


RULES: list[Rule] = [
    *_table("incomplete", [
        ("stub-body", "domain", "high", "high", "C", "Function has no implementation", "Implement it, delete it, or make the class abstract."),
        ("stub-raise", "domain", "high", "medium", "C", "Code path raises 'not implemented'", "Implement it, or remove the path that reaches it."),
        ("truncation-marker", "domain", "critical", "high", "C", "Code replaced by an elision marker such as 'rest of code'", "Restore the elided code from history or write it."),
        ("placeholder-comment", "domain", "medium", "medium", "C", "Comment admits the code is a placeholder", "Finish it, or record the gap with the user."),
        ("fake-success", "domain", "critical", "high", "C", "Check always succeeds and ignores its arguments", "Implement the check. Until then it must fail closed."),
        ("fake-data", "domain", "medium", "low", "C", "Mock or sample data in non-test code", "Replace it with the real source, or move it to tests."),
    ]),
    *_table("hallucination", [
        ("phantom-import", "api", "high", "high", "C", "Import resolves to no local module, declared dependency or installed package", "Confirm the package exists with 'occam deps --online', then declare it or replace it."),
        ("phantom-local-import", "api", "high", "high", "B", "Imports a name or file that doesn't exist in this repository", "Point it at the real symbol or write what's missing."),
        ("phantom-attribute", "api", "high", "high", "B", "Uses a standard library attribute that doesn't exist on this Python", "Use the real API. Check the docs for the runtime versions you support."),
        ("undefined-name", "api", "high", "high", "B", "Name is used but bound nowhere in the file", "Import or define it, or call the existing helper."),
        ("undeclared-dependency", "ops", "medium", "medium", "B", "Imported package isn't declared in a manifest", "Declare it, so a clean install works."),
    ]),
    *_table("security", [
        ("hardcoded-secret", "ops", "critical", "medium", "B", "Credential committed in source (value withheld)", "Move it to configuration, and tell a person to rotate it, since history keeps it."),
        ("committed-secret-file", "ops", "critical", "high", "C", "Secret-bearing file is tracked in git", "Untrack it, ignore it, and rotate what it held."),
        ("sql-injection", "storage-network", "critical", "high", "B", "SQL built from interpolated values", "Use bound parameters."),
        ("shell-injection", "os", "critical", "high", "B", "Shell command built from runtime values", "Pass an argument list and don't use a shell."),
        ("dynamic-eval", "runtime", "high", "high", "C", "eval or exec on a non-literal", "Replace it with a parser or a dispatch table."),
        ("unsafe-deserialize", "runtime", "high", "high", "C", "Deserializer that can execute code", "Use a safe format or loader, and don't accept this from outside."),
        ("tls-disabled", "storage-network", "high", "high", "B", "TLS verification turned off", "Verify certificates, and configure the CA for private endpoints."),
        ("jwt-unverified", "api", "critical", "high", "B", "Token accepted without verifying its signature", "Verify signature, algorithm, expiry and audience."),
        ("fail-open", "domain", "critical", "high", "B", "Security check allows access when it errors", "Deny on error."),
        ("missing-auth", "api", "critical", "medium", "C", "Route has no auth, unlike its siblings in this file", "Add the same guard, or record why this route is public."),
        ("disabled-control", "api", "high", "medium", "C", "Security control switched off", "Turn it on, or record the reason with the user."),
        ("weak-crypto", "runtime", "medium", "low", "C", "MD5 or SHA-1 in use", "If this protects anything, use a modern hash. For passwords use a password hash."),
        ("weak-password-hash", "runtime", "high", "high", "C", "Password or secret hashed with a fast hash", "Use argon2, scrypt or bcrypt through a maintained library."),
        ("insecure-random", "runtime", "high", "medium", "B", "Non-cryptographic random used for a secret", "Use secrets or crypto.randomBytes."),
        ("homemade-crypto", "runtime", "high", "medium", "C", "Hand-written encryption", "Use a maintained cryptography library."),
        ("secret-compare", "runtime", "medium", "medium", "B", "Secret compared with ==", "Use a constant-time comparison."),
        ("redos-regex", "algorithm", "medium", "medium", "B", "Nested quantifiers can backtrack catastrophically", "Rewrite the pattern without nested repetition, and bound the input."),
        ("env-flag-truthy", "ops", "high", "high", "B", "bool() on an environment value makes 'false' true", "Compare against the values you accept."),
        ("permissive-cors", "api", "medium", "medium", "C", "Wildcard origin or host", "List the origins you serve."),
        ("debug-exposed", "ops", "high", "medium", "B", "Debug mode enabled in code", "Read it from configuration, off by default."),
        ("path-traversal", "os", "high", "medium", "B", "Filesystem path taken from the request", "Resolve it under a fixed root and reject escapes."),
        ("ssrf", "storage-network", "high", "medium", "C", "Server fetches a URL taken from the request", "Allow-list hosts, and check redirects and internal addresses."),
        ("xss-sink", "api", "high", "medium", "B", "Raw HTML sink", "Escape for the context, or sanitize with a maintained library."),
        ("unsafe-c-string", "runtime", "high", "high", "B", "Unbounded C string function", "Use a bounded function and check its result."),
        ("insecure-tempfile", "os", "medium", "high", "B", "Predictable temporary file", "Use mkstemp or NamedTemporaryFile."),
        ("world-writable", "os", "high", "high", "B", "World-writable permissions", "Grant the least the process needs."),
        ("curl-pipe-shell", "ops", "high", "high", "C", "Downloaded script piped straight into a shell", "Pin a version, verify a checksum, then run it."),
    ]),
    *_table("error-masking", [
        ("swallowed-exception", "domain", "high", "high", "B", "Broad exception is caught and dropped", "Catch what you expect and handle it, or let it propagate."),
        ("bare-except", "domain", "medium", "high", "B", "Bare except also catches cancellation and exit", "Name the exception types."),
        ("broad-wrap", "domain", "medium", "medium", "B", "Entire function wrapped in a broad try that hides failures", "Narrow the try to what can fail and let the rest propagate."),
        ("ignored-error", "domain", "medium", "medium", "B", "Returned error or failure status is discarded", "Handle it or propagate it."),
        ("panic-in-library", "runtime", "medium", "low", "B", "Panic or unwrap reachable from ordinary input", "Return an error."),
        ("assert-validation", "runtime", "low", "low", "B", "assert used for validation, which -O removes", "Raise a real error."),
        ("suppression-comment", "ops", "medium", "medium", "B", "Checker silenced with no stated reason", "Fix the cause, or scope the suppression and say why."),
    ]),
    *_table("testing", [
        ("no-tests", "test", "high", "high", "C", "Repository has source but no tests", "Add characterization tests around the riskiest paths first."),
        ("module-untested", "test", "medium", "medium", "B", "No test imports or names this module", "Add a test through its public behavior."),
        ("test-no-assert", "test", "high", "high", "B", "Test asserts nothing", "Assert the behavior it's meant to protect."),
        ("test-tautology", "test", "high", "high", "B", "Assertion can't fail", "Assert something the code could get wrong."),
        ("test-weak-assert", "test", "medium", "medium", "B", "Test only checks that something came back", "Assert the actual value."),
        ("test-skipped", "test", "medium", "medium", "B", "Test is skipped", "Fix it and enable it, or delete it with a reason."),
        ("test-focused", "test", "high", "high", "A", "Focused test hides the rest of the suite", "Remove .only."),
        ("test-overmocked", "test", "medium", "medium", "B", "Test mocks more than it verifies", "Mock only the outer boundary, and use a real collaborator otherwise."),
        ("test-mocks-subject", "test", "high", "medium", "B", "Test replaces the thing it claims to test", "Exercise the real function."),
        ("test-broad-raises", "test", "low", "medium", "B", "Test accepts any exception", "Name the type and match the message."),
        ("test-swallows", "test", "high", "medium", "B", "Test catches exceptions, so failures can't surface", "Let them propagate, or assert on them."),
        ("test-sleep", "test", "low", "medium", "B", "Sleep in a test", "Wait on a condition or control the clock."),
        ("test-weakened", "test", "high", "high", "C", "This change removes or relaxes a test", "Restore it unless the intended behavior gives an independent reason."),
        ("checks-hidden-by-config", "test", "high", "high", "C", "Configuration hides tests or checks", "Run them, and fix or explicitly report what's failing."),
        ("test-generic-name", "test", "low", "low", "B", "Test name says nothing about behavior", "Name the behavior and the condition."),
    ]),
    *_table("complexity", [
        ("high-complexity", "algorithm", "medium", "high", "B", "Function has too many branches to reason about", "Split by responsibility, and lock behavior first."),
        ("long-function", "domain", "medium", "high", "B", "Very long function", "Extract the parts that have their own name."),
        ("deep-nesting", "algorithm", "medium", "high", "B", "Deeply nested control flow", "Use guard clauses or extract a helper."),
        ("many-params", "api", "medium", "high", "C", "Too many parameters", "Group the ones that belong together."),
        ("flag-params", "api", "medium", "medium", "C", "Boolean flags select behaviors", "Use separate functions or one option object."),
        ("god-file", "domain", "medium", "high", "B", "Very large source file", "Split along existing seams. Don't add to it."),
        ("god-class", "domain", "medium", "high", "B", "Class has too many responsibilities", "Extract cohesive collaborators."),
    ]),
    *_table("duplication", [
        ("clone-block", "domain", "medium", "high", "B", "Block repeated verbatim across files", "Extract it if the copies must change together."),
        ("clone-function", "domain", "medium", "high", "B", "Functions are identical apart from names", "Keep one, after checking they mean the same thing."),
        ("clone-renamed", "domain", "low", "medium", "B", "Long block repeated with renamed identifiers", "Check whether one shared form fits."),
        ("diverged-twin", "domain", "medium", "medium", "C", "Same-named function has different bodies across files", "Decide which is correct. They may disagree on behavior."),
        ("parallel-verbs", "domain", "low", "low", "B", "Different verbs for the same operation across files", "Keep one, and check that the semantics match."),
    ]),
    *_table("overengineering", [
        ("single-impl-abstraction", "domain", "medium", "medium", "B", "Abstraction has one implementation or none", "Inline it unless a real boundary needs it."),
        ("pass-through", "domain", "low", "medium", "B", "Function only forwards its arguments", "Call the target directly."),
        ("one-method-class", "domain", "low", "low", "B", "Class that is really one function", "Use a function."),
        ("static-only-class", "domain", "low", "medium", "B", "Class used only as a namespace", "Use module-level functions."),
        ("pattern-one-product", "domain", "medium", "medium", "B", "Factory or strategy machinery with one product", "Construct it directly."),
        ("deep-inheritance", "domain", "medium", "medium", "C", "Deep inheritance chain", "Flatten it or use composition."),
        ("unused-option", "api", "low", "medium", "B", "Parameter with a default that no caller passes", "Drop it and inline the default, unless a caller outside this repository needs it."),
        ("impossible-none-check", "domain", "low", "medium", "B", "None check on a value the code says can't be None", "Remove the branch, or correct the annotation if None can really arrive. Keep real validation at trust boundaries."),
        ("useless-except", "domain", "low", "high", "B", "Handler only re-raises what it caught", "Remove the handler. It changes nothing."),
        ("async-no-await", "concurrency", "low", "low", "B", "async function never awaits", "Make it sync unless an interface requires async."),
    ]),
    *_table("dead-code", [
        ("unused-import", "domain", "low", "high", "A", "Import is never used", "Remove it."),
        ("unreferenced-def", "domain", "low", "medium", "B", "Nothing in the repository references this", "Delete it after checking dynamic callers and public API."),
        ("orphan-module", "domain", "medium", "medium", "B", "Nothing imports or names this module", "Wire it in or delete it. It may be an unfinished feature."),
        ("unreachable-code", "domain", "medium", "high", "B", "Code after return or raise never runs", "Delete it, or fix the control flow it was meant to have."),
        ("dead-branch", "domain", "medium", "high", "B", "Branch condition is constant", "Delete it."),
        ("always-true-condition", "domain", "high", "high", "B", "'or' against a bare string is always true", "Compare against each value, or use 'in'."),
        ("unreferenced-setting", "ops", "low", "medium", "B", "Setting is parsed and nothing reads it", "Wire it in, or remove it. Something may be hard-coding this value instead."),
        ("commented-out-code", "domain", "low", "medium", "A", "Commented-out code", "Delete it. History keeps it."),
    ]),
    *_table("bloat", [
        ("scratch-file", "ops", "medium", "medium", "C", "File name suggests a leftover copy or experiment", "Delete it, or merge what it adds."),
        ("ai-report-file", "ops", "low", "medium", "C", "Agent progress report committed as documentation", "Delete it, or fold anything lasting into the real docs."),
        ("committed-artifact", "ops", "medium", "high", "C", "Build output or cache is tracked in git", "Untrack and ignore it."),
        ("large-binary", "ops", "low", "medium", "C", "Large binary tracked in git", "Use a release asset or LFS."),
        ("debug-leftover", "ops", "medium", "high", "B", "Debugging statement left in", "Remove it, or use the project's logger."),
        ("unused-dependency", "ops", "low", "medium", "C", "Declared dependency is never imported", "Remove it after checking plugin and runtime use."),
        ("competing-dependencies", "ops", "medium", "medium", "C", "Several libraries doing the same job", "Standardize on one."),
        ("utility-bucket", "domain", "low", "medium", "B", "Large catch-all helpers module", "Move each helper next to what it serves."),
    ]),
    *_table("comments", [
        ("ai-residue", "domain", "low", "medium", "A", "Comment talks to the reader or narrates the edit, not the code", "Delete it, and keep any real rationale."),
        ("narration-comment", "domain", "low", "low", "B", "Comment restates the next line", "Delete it, or explain why instead of what."),
        ("comment-flood", "domain", "low", "low", "B", "Mostly comments", "Keep intent and invariants, and cut the rest."),
        ("banner-comment", "domain", "low", "low", "B", "Decorative banner comments", "Remove them, and split the file if it needs sections."),
        ("missing-docstring", "api", "low", "low", "B", "Complex public function is undocumented", "State behavior, errors and side effects."),
        ("docstring-restates-name", "api", "low", "low", "B", "Docstring only repeats the name", "Say what a caller can't guess, or remove it."),
    ]),
    *_table("naming", [
        ("hedge-name", "domain", "medium", "medium", "B", "Name records history ('_v2', '_new', '_final'), not meaning", "Name the role, and remove the old version if it's dead."),
        ("vague-name", "domain", "low", "low", "C", "Name carries no specific role", "Use the domain's term."),
        ("convention-mismatch", "api", "low", "medium", "C", "Name breaks the language's convention", "Follow the convention. Public names need a deprecation path."),
        ("rest-verb-route", "api", "low", "medium", "C", "Route name carries a verb the HTTP method already states", "Use resource nouns. Existing routes need a migration."),
    ]),
    *_table("performance", [
        ("query-in-loop", "storage-network", "high", "medium", "B", "Query or network call per loop item (N+1)", "Batch it, join it, or fetch it once and index it."),
        ("list-membership-in-loop", "algorithm", "medium", "high", "B", "Linear search inside a loop", "Use a set or dict."),
        ("string-concat-loop", "algorithm", "low", "medium", "B", "String built by repeated concatenation", "Collect the parts and join them."),
        ("nested-same-collection", "algorithm", "medium", "medium", "B", "Quadratic loop over one collection", "Index it first if the size can grow."),
        ("nested-loops", "algorithm", "low", "low", "B", "Three or more nested loops", "Check the growth against the stated workload."),
        ("sort-in-loop", "algorithm", "medium", "high", "B", "Sorting inside a loop", "Sort once, or use a heap or bisect."),
        ("regex-compile-loop", "runtime", "low", "medium", "B", "Regex compiled inside a loop", "Compile it once."),
        ("dataframe-iterrows", "hardware", "medium", "medium", "B", "Row-by-row iteration over a DataFrame", "Vectorize, or use itertuples if that isn't possible."),
        ("dataframe-grow-loop", "hardware", "high", "high", "B", "Array or frame re-copied on each iteration", "Collect the pieces, then concatenate once."),
        ("python-loop-over-array", "hardware", "medium", "medium", "B", "Python index loop over a numeric array", "Vectorize, so work stays in native code and caches."),
        ("materialize-all", "storage-network", "medium", "medium", "B", "Loads a whole result into memory", "Stream it or page through it."),
        ("blocking-in-async", "concurrency", "high", "high", "B", "Blocking call on the event loop", "Use the async API, or a bounded thread pool."),
        ("unbounded-concurrency", "concurrency", "medium", "medium", "B", "One task per item with no limit", "Bound it with a semaphore or worker pool."),
        ("missing-timeout", "storage-network", "medium", "high", "B", "Network call has no timeout", "Set a deadline and decide what happens when it expires."),
        ("unbounded-cache", "runtime", "medium", "medium", "B", "Cache with no size bound", "Set a bound, and define invalidation."),
        ("io-in-loop", "os", "low", "low", "B", "File opened or synced per loop item", "Batch the I/O, or reuse the handle."),
        ("transfer-in-loop", "hardware", "medium", "low", "B", "Per-element device transfer or scalar extraction", "Move whole batches, and keep hot work on the device."),
        ("remote-get-in-loop", "concurrency", "high", "medium", "B", "Blocking get per item serializes remote work", "Submit everything, then get the list or use wait."),
        ("oversubscription", "hardware", "low", "low", "B", "Process pool plus native-thread libraries can oversubscribe cores", "Pin native threads per worker, and measure."),
        ("select-star", "storage-network", "low", "low", "B", "SELECT * couples code to the schema and fetches extra data", "Name the columns."),
        ("not-in-subquery", "storage-network", "medium", "medium", "B", "NOT IN with a subquery is NULL-unsafe and often slow", "Use NOT EXISTS."),
        ("unbounded-write", "storage-network", "high", "high", "C", "UPDATE or DELETE with no WHERE", "Add the condition, or confirm a full-table change is intended."),
    ]),
    *_table("scalability", [
        ("process-local-state", "concurrency", "high", "medium", "C", "In-process mutable store breaks with more than one worker", "Use a shared store, or state the single-process limit."),
        ("unpaginated-query", "storage-network", "high", "medium", "C", "Handler returns an unbounded result set", "Page it, and cap the page size."),
        ("import-time-io", "ops", "medium", "medium", "B", "Network, file or database work at import time", "Move it behind an explicit startup call."),
        ("hardcoded-host", "ops", "medium", "medium", "B", "Local address hard-coded in non-test code", "Read it from configuration."),
        ("absolute-path", "os", "medium", "high", "B", "A machine-specific absolute path", "Derive it from the project or configuration."),
    ]),
    *_table("architecture", [
        ("import-cycle", "domain", "medium", "high", "C", "Modules import each other in a cycle", "Move the shared piece down, so dependencies point one way."),
        ("hub-module", "domain", "low", "low", "C", "Module with both very high fan-in and fan-out", "Split it along its callers' needs."),
        ("sql-in-handler", "domain", "low", "low", "B", "Raw SQL inside a request handler", "Move it next to the other data access."),
        ("duplicate-config", "ops", "medium", "medium", "C", "Several competing configuration modules", "Keep one source of truth."),
        ("base-class-bypassed", "domain", "medium", "medium", "B", "Peers extend a base class and this one reimplements it", "Extend the base, if its contract fits."),
        ("pull-up-method", "domain", "medium", "medium", "B", "Sibling classes carry identical methods", "Move them to the shared base or a collaborator."),
        ("lsp-violation", "domain", "medium", "medium", "C", "Subclass refuses a method its base provides", "Split the interface, or stop inheriting."),
        ("global-statement", "concurrency", "low", "medium", "B", "Mutable global state", "Pass the state explicitly."),
    ]),
    *_table("usability", [
        ("generic-exception", "api", "low", "medium", "B", "Raises a bare Exception", "Raise a specific type, so callers can respond."),
        ("opaque-error", "api", "low", "low", "B", "Error message doesn't say what was wrong", "Include the offending value and how to fix it, without leaking secrets."),
        ("inconsistent-return", "api", "medium", "medium", "C", "Returns unrelated types depending on the path", "Pick one shape, and raise on failure."),
        ("print-in-library", "api", "low", "low", "B", "Mixes print with logging", "Use the logger."),
        ("a11y-missing", "api", "medium", "medium", "B", "Interactive or image element lacks an accessible name or role", "Add alt text, a role and keyboard support."),
    ]),
    *_table("reinvention", [
        ("handrolled-retry", "storage-network", "medium", "medium", "B", "Hand-written retry loop", "Use the retry support in your client or an installed library, with backoff and only for safe operations."),
        ("handrolled-csv", "domain", "medium", "medium", "B", "CSV parsed by splitting on commas", "Use the csv module. Quoted fields break a split."),
        ("handrolled-dotenv", "ops", "low", "medium", "B", "Hand-parsed .env file", "Use the project's settings library, or python-dotenv."),
        ("handrolled-argv", "api", "medium", "medium", "B", "Hand-parsed command line", "Use argparse, or the CLI library the project already has."),
        ("handrolled-url", "api", "low", "low", "B", "URL query built by string formatting", "Use a URL encoder. Values here aren't escaped."),
        ("handrolled-json", "api", "medium", "medium", "B", "JSON built by string formatting", "Use the JSON encoder."),
        ("handrolled-html-parse", "domain", "medium", "medium", "B", "HTML parsed with a regular expression", "Use an HTML parser."),
        ("handrolled-memo", "runtime", "low", "low", "B", "Hand-written memoization", "Use a standard cache, with a bound."),
        ("handrolled-helper", "domain", "low", "low", "B", "Helper that the standard library or a common package provides", "Use the existing implementation unless semantics differ."),
    ]),
    *_table("language-practice", [
        ("mutable-default", "runtime", "high", "high", "B", "Mutable default argument is shared between calls", "Default to None and create it inside."),
        ("frozen-default", "runtime", "high", "high", "B", "Default is computed once at import, not per call", "Default to None and compute it inside, or use default_factory."),
        ("missing-await", "concurrency", "high", "medium", "B", "Async call isn't awaited, so this has the promise and not the value", "Await it."),
        ("deprecated-api", "api", "medium", "high", "B", "Deprecated or removed API, often from stale training data", "Use the current API for the supported versions."),
        ("unparseable", "runtime", "high", "high", "B", "File doesn't parse", "Fix the syntax, or check which interpreter it targets. Only text rules ran here."),
        ("float-money", "domain", "high", "medium", "C", "Binary float used for money", "Use Decimal or integer minor units, with an explicit rounding mode."),
        ("star-import", "domain", "medium", "high", "B", "Wildcard import hides where names come from", "Import names explicitly."),
        ("naive-datetime", "domain", "low", "low", "C", "Timezone-naive current time", "Use an aware datetime, and decide what 'day' means."),
        ("resource-no-context", "os", "low", "low", "B", "File opened outside a context manager", "Use with."),
        ("async-foreach", "concurrency", "high", "high", "B", "forEach doesn't await its async callback", "Use for...of, or Promise.all with a bound."),
        ("ts-any", "api", "low", "low", "B", "'any' disables checking downstream", "Use a real type, or unknown plus a check."),
        ("ts-double-cast", "api", "medium", "medium", "B", "Double cast forces a type past the checker", "Fix the types, or narrow with a runtime check."),
        ("go-defer-in-loop", "os", "medium", "medium", "B", "defer in a loop holds resources until the function returns", "Move the loop body into a function."),
        ("shell-no-strict", "ops", "low", "medium", "B", "Script keeps going after failures", "Add set -euo pipefail, and check what must succeed."),
        ("shell-unquoted-rm", "os", "high", "high", "B", "rm on an unquoted variable", "Quote it and guard against empty values."),
        ("shell-syntax", "runtime", "high", "high", "B", "bash can't parse this script", "Fix the syntax. Nothing past the error runs."),
        ("shell-bashism", "runtime", "medium", "high", "B", "Bash-only syntax under a shebang that asks for sh", "Ask for bash in the shebang, or write POSIX sh."),
        ("shell-unquoted-path", "os", "medium", "medium", "B", "Unquoted variable passed to a command that takes paths", "Quote it, so spaces and globs in the value can't change what runs."),
        ("shell-cd-unchecked", "os", "medium", "medium", "B", "cd can fail, and the script carries on in the wrong folder", "Use cd ... || exit 1, or set -e."),
        ("shell-ls-parse", "os", "medium", "high", "B", "Parsing the output of ls", "Use a glob, or find with -print0."),
        ("shell-word-split", "os", "medium", "medium", "B", "A list of paths from a command, split on whitespace", "Use find -print0 with xargs -0, or a while read -r loop."),
        ("shell-nonportable", "os", "low", "medium", "B", "Command or flag that differs between GNU and BSD", "Check which platforms this runs on, and use the portable form if it needs both."),
        ("shell-masked-failure", "runtime", "medium", "high", "B", "local or export hides the failure of the command it assigns from", "Declare on one line and assign on the next."),
        ("shell-rm-unguarded", "os", "high", "medium", "B", "rm -r under a variable that could be empty", "Use ${var:?}, so an empty value stops the script."),
        ("shell-tmp-no-trap", "os", "low", "medium", "B", "Temp file made with no cleanup", "Add a trap on EXIT that removes it."),
        ("shell-outgrown", "domain", "low", "medium", "C", "Script past what shell handles well", "Check whether a real language would cost less to maintain."),
        ("namespace-in-header", "domain", "medium", "high", "B", "using namespace in a header leaks into every includer", "Qualify names."),
        ("structured-concurrency-escape", "concurrency", "medium", "high", "B", "GlobalScope escapes structured concurrency", "Launch in a scope tied to the caller's lifecycle."),
    ]),
    *_table("notebook", [
        ("nb-out-of-order", "runtime", "medium", "medium", "B", "Cells were executed out of order", "Restart and run all, and commit that."),
        ("nb-hidden-state", "runtime", "high", "high", "B", "Cell uses a name that only a later cell defines", "Reorder the cells so a fresh kernel runs top to bottom."),
        ("nb-unpinned-install", "ops", "low", "medium", "B", "Unpinned install inside a notebook", "Pin it, or move it to a declared environment."),
        ("nb-large-output", "ops", "low", "high", "A", "Large output stored in the notebook", "Clear outputs before committing."),
        ("nb-sensitive-output", "ops", "high", "medium", "C", "Stored output contains personal data or credentials", "Clear the output, and check who has had access to it."),
    ]),
]

BY_ID: dict[str, Rule] = {rule.id: rule for rule in RULES}
CATEGORIES = tuple(dict.fromkeys(rule.category for rule in RULES))
