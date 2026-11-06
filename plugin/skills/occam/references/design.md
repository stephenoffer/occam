# Design decisions

Read the section you need. Stop researching once the decision is adequately supported.

## Reuse, dependency or new code

Search for the capability, related concepts and alternate terminology before writing a replacement. Check call sites, generated sources and extension points. A text search is useful evidence, not proof that dynamic callers or external consumers don't exist.

Compare candidates on fitness and total cost, including maintenance and review:

| Candidate | Usually wins when | Watch for |
|---|---|---|
| Repository code | Its contract matches, and sharing keeps one source of truth | A similar name with different semantics; an insecure or obsolete habit |
| Standard library | The task is common and the semantics fit | Version support across the project's runtimes |
| Installed dependency | It already solves this and is supported here | Features behind an optional extra; pinned old versions |
| Mature library or service | Security primitives, complex protocols and formats, anything with many edge cases | Footprint, transitive dependencies, data handling |
| Purpose-built code | The above don't fit, or the need is genuinely trivial | Reproducing a third-party engine behind a novel API |

**A familiar pattern has preconditions.** A fix that worked on something similar may not fit here, so state what has to be true for it to work and check that. Read the request literally before matching it to a problem you recognize. If a premise is false or the task can't be done as stated, say so instead of producing something plausible.

Use established libraries for cryptography, authentication, parsing of standard protocols and similar. Prefer a thin adapter at a real domain boundary to wrapping every function of a dependency.

For substantial choices, record the options and the reason in a line or two. Skip this for standard-library imports and small tasks.

## Vetting a meaningful new dependency

Follow repository policy and existing authorization rather than a blanket approval prompt. Check:

- **Identity:** the name in the documentation is the package you would install, and the publisher is who you think. A registry entry alone doesn't prove legitimacy, and similar names are a known attack.
- **Actual support:** the API you need exists in the version you would get, on the project's runtimes and platforms. What you remember of an API describes some earlier release, and stating the version doesn't correct that. Read the lockfile, the installed source or `--help`, or that release's documentation, and make one small real call before building on it.
- **Health:** maintenance activity, license, relevant advisories.
- **Cost:** transitive dependencies, install scripts, footprint, lockfile policy.

Don't install a guessed package to find out whether it is real. For a service, also consider authentication, data handling, rate limits, cost, outages, portability and a realistic exit path. Ask before unapproved paid usage or sending private data to a provider, and don't upload proprietary code to analysis services by default.

## Adding structure

Short code that hides state or failure modes isn't simple. Choose the least complicated design that meets the actual requirements and credible operating envelope, weighing human comprehension and future change alongside runtime behavior.

A new abstraction needs a present requirement, a stable invariant, a meaningful boundary or a measured constraint. Legitimate correctness, isolation or performance needs can justify structure before multiple implementations exist. Speculative extensibility and pass-through layers can't.

**Sharing.** Remove duplicated knowledge and business rules, not similar-looking lines. Before consolidating, check that validation, ordering, error handling and edge cases survive. Reject a generic utility bucket, or a parameter-heavy universal function whose flags select between unrelated behaviors.

**Inheritance and interfaces.** Prefer composition and small interfaces. Use an abstract base class for a genuine substitutable family with shared lifecycle or behavior, and a protocol or interface when the contract is the useful commonality. Avoid inheritance just to reach helpers, parallel competing hierarchies, deep trees, boolean-controlled subclasses, and methods that can't honor their base contract. Respect existing well-designed base classes.

**Algorithms.** Pick the right algorithm and data structure before micro-optimizing. State time and space complexity for material hot paths, counting repeated I/O and data movement, since fewer source lines isn't less work. Avoid needless cleverness, and use a sophisticated approach when the workload demands it and a standard implementation exists.

**Dependencies between parts.** Keep dependency direction, ownership, transaction boundaries and lifecycles clear. Avoid circular imports, hidden global state, import-time work, and domain logic tied needlessly to transport or storage. Start from the repository's architecture.

**When a fix reveals an architecture problem,** explain the evidence and the smallest adequate correction. Reuse and simplicity aren't reasons to preserve a known broken design. The correction table in the main skill decides whether to implement or ask.

## Contracts between components

Inspect contracts, not just files: schema versions, serialization, errors, identity, state transitions, retries, configuration and deployment order. Refactors preserve intended semantics unless a behavior change is the goal. Look for places that enumerate the same thing, such as a second dispatcher, an allow-list or a completion file, because a change that updates only one looks finished.

## Which layers to examine

Consider only layers that matter here, and for each one name the assumption, the plausible failure and the evidence you would need. Work downward only as the requirement, a profiler, an incident or the risk justifies. A kernel tweak doesn't repair a quadratic algorithm or an unnecessary network round trip, and an algorithmic gain doesn't establish end-to-end performance if data conversion dominates.

| Layer | Consider when relevant |
|---|---|
| User and API | Discoverability, naming, consistency, error recovery, accessibility, compatibility |
| Domain and architecture | Invariants, state ownership, isolation, transactions, component contracts |
| Algorithms | Complexity, adversarial inputs, streaming versus materialization, correctness of approximations |
| Runtime | Allocation, garbage collection, serialization, event-loop blocking, interpreter and native boundaries |
| Concurrency | Races, deadlocks, cancellation, queue bounds, process or thread choice, contention |
| Storage and network | Query plans, indexes, N+1 calls, batching, connection pools, deadlines, consistency, recovery |
| Operating system | File descriptors, process limits, signals, filesystem semantics, memory limits, I/O pressure |
| Hardware | Cache locality, memory bandwidth, vectorization, NUMA, GPU transfer cost, disk and network limits |
| Operations | Configuration, rollout, rollback, observability, dependency failures, capacity and cost |

## Usability, naming and comments

Use the vocabulary of the domain and ecosystem, and compare names with existing APIs before inventing new ones. Keep singular and plural, verbs, units, sync and async semantics, error types and return conventions consistent. Prefer a precise role to Manager, Helper or Processor.

Make common operations discoverable with safe defaults and explicit advanced options. Avoid parameter soup, surprising mutation, silent coercion, inconsistent return types and nearly identical entry points. Make invalid states hard to express where practical, without forcing a type framework on a small task.

Preserve compatibility deliberately. Don't rename a public API because another name looks nicer: consider callers, deprecation, migration effort and permission.

Comments explain non-obvious intent, invariants, units, constraints, workarounds or measured tradeoffs. Public docstrings cover behavior, inputs, outputs, errors and side effects to the depth a caller needs. Don't narrate lines or restate types. Remove stale comments your change creates and keep useful existing rationale.

Examples in public documentation should actually run. Errors should be actionable without leaking secrets. Add observability at operational boundaries, not noisy logging in every function. Remove abandoned code, imports, debug artifacts, obsolete flags and scaffolding that your change orphaned, and leave pre-existing dead code unless asked.

## File size and large codebases

Size is a prompt to look, not a defect in itself. A very large file usually holds several responsibilities and costs every later reader, human or agent, but moving lines to reach a number only spreads the same coupling around. Use the limits the repository configures, and otherwise the defaults of the language's common linter. `occam-python` lists Python's.

- **New code with its own responsibility** goes in a new file named for that responsibility. A small fix stays where it is.
- **Splitting existing code** is a separate change to propose, unless the request asks for it. Cut where calls across the boundary are few and each side has a name. Lock behavior with tests first, move without changing anything else, and keep old import paths working if anything outside could use them.
- **Finding your way.** Start from entry points and follow dependencies, rather than reading everything. `occam query` lists entry points, outlines, callers and what a change reaches. Registries, reflection, plugins and framework autodiscovery mean a text search can't prove that nothing uses something.
- **Boundaries.** Give each component a small public surface and one-way dependencies, and give shared code an owner. Enforce a boundary with a tool where the repository has one, because a convention alone erodes.
- **Modules before services.** A module boundary costs nothing at runtime. A network boundary adds latency, partial failure, versioning and deployment order, so a new service names the scaling, isolation or ownership need it serves.
- **Change incrementally.** Across a large repository, a flag day rarely lands. Let old and new coexist, record a baseline that can only shrink, and raise strictness one area at a time. Use a syntax-aware codemod for mechanical changes.
