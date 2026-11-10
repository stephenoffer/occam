# Critique, then converge

The switch for this turns on once checks pass on work beyond a small change, before the report, and for reviews.

Beyond a small change, run `gate`, reread the request, and inspect the actual diff as a skeptical maintainer who calls out anything overcomplicated. Look for a concrete counterexample: omitted behavior, unreachable additions, needless dependencies, duplicated knowledge, hidden state, error gaps, security issues, resource growth, tests that can't fail. Don't manufacture findings or rewrite correct code to show effort.

For high-consequence work, self-review the whole diff before your report, labeled so, never as independent. For auth, tenancy, secrets, cryptography or money, or when asked, also use a fresh reviewer if available and authorized, with the requirements and diff, not your conclusion. If policy requires independent approval, report that gate as pending.

Fix confirmed in-scope defects, then re-verify, since a correction invalidates earlier approval. Allow about three rounds. If findings recur, oscillate or relocate, re-diagnose or ask one question. At the cap, report "capped, not converged" with what's unresolved.
