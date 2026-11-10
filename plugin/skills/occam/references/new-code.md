# New code

The switch for this turns on when a request asks to build or add something, for reviews and plans, or when a sizable edit, past the small path's 20 lines, adds a file, a definition, an import or a dependency.

Before adding anything new:

- **It needs to exist.** Leave out any feature or option nobody asked for, and say so in a line.
- **Existing capabilities were compared:** repository code, standard library and platform, installed dependencies, mature external options, then purpose-built code. Not a ranking: a helper with the wrong semantics isn't reuse, and a maintained library can beat a short homemade parser. Check a familiar pattern's preconditions first.
- **APIs are real.** Recall goes stale, and stating a version doesn't fix it: confirm against what's installed or that release's docs. Don't install a guessed package to see if it exists.
- **New structure earns its place.** Each new service, abstraction, hierarchy, plugin point, option, queue or cache names the requirement, invariant, boundary or measurement it serves. Where a requirement needs an abstraction or sophisticated algorithm, a naive version is unfinished, not simple. Don't handle states the code can't reach. If a draft could be a quarter of its size, rewrite it. Mark a limit the request allows: `shortcut: <the limit>, <when to revisit>`.
- **Rewrites keep what worked.** Compare old and new on the same inputs, awkward ones included, as soon as the new version runs. Passing tests don't show equivalence.
