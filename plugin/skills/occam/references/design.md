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

When the oldest runtime a project supports moves up, look again at what it wrote for older ones, such as a homemade TOML reader now that `tomllib` exists (3.11) or chunking now that `itertools.batched` does (3.12), and at subsystems a maintained library has since caught up with. Use established libraries for cryptography, authentication, parsing of standard protocols and similar. Prefer a thin adapter at a real domain boundary to wrapping every function of a dependency. A library's example shows the call, not where its client lives: make clients, sessions and pools once, with timeouts and credentials from configuration, and close them on shutdown, rather than copying the example's setup into each request.

For substantial choices, record the options and the reason in a line or two. Skip this for standard-library imports and small tasks.

## Vetting a meaningful new dependency

Follow repository policy and existing authorization rather than a blanket approval prompt. Check:

- **Identity:** the name in the documentation is the package you would install, and the publisher is who you think. A registry entry alone doesn't prove legitimacy, and similar names are a known attack.
- **Actual support:** the API you need exists in the version you would get, on the project's runtimes and platforms. What you remember of an API describes some earlier release, and stating the version doesn't correct that. Read the lockfile, the installed source or `--help`, or that release's documentation, and make one small real call before building on it.
- **Health:** maintenance activity, end of life or deprecation, license and whether it allows how this project is distributed, relevant advisories.
- **Cost:** transitive dependencies, install scripts, footprint, lockfile policy. After the install, read what the lockfile added, removed or moved a major version.

Don't install a guessed package to find out whether it is real. For a service, also consider authentication, data handling, rate limits, cost, outages, portability and a realistic exit path. Ask before unapproved paid usage or sending private data to a provider, and don't upload proprietary code to analysis services by default.

## Adding structure

Short code that hides state or failure modes isn't simple. Choose the least complicated design that meets the actual requirements and credible operating envelope, weighing human comprehension and future change alongside runtime behavior.

A new abstraction needs a present requirement, a stable invariant, a meaningful boundary or a measured constraint. Legitimate correctness, isolation or performance needs can justify structure before multiple implementations exist. Speculative extensibility and pass-through layers can't.

**Sharing.** Remove duplicated knowledge and business rules, not similar-looking lines. Before consolidating, check that validation, ordering, error handling and edge cases survive. Reject a generic utility bucket, or a parameter-heavy universal function whose flags select between unrelated behaviors.

**Inheritance and interfaces.** Prefer composition and small interfaces. Use an abstract base class for a genuine substitutable family with shared lifecycle or behavior, and a protocol or interface when the contract is the useful commonality. Avoid inheritance just to reach helpers, parallel competing hierarchies, deep trees, boolean-controlled subclasses, and methods that can't honor their base contract. Respect existing well-designed base classes.

**Algorithms.** Pick the right algorithm and data structure before micro-optimizing. State time and space complexity for material hot paths, counting repeated I/O and data movement, since fewer source lines isn't less work. Avoid needless cleverness, and use a sophisticated approach when the workload demands it and a standard implementation exists. Write down the invariant the algorithm keeps and the preconditions it assumes, such as sorted input or unique keys, and check them where the data comes in. Decide what duplicates mean, first, last, merged or an error, and test a repeated key.

**Keep what changes together.** A small feature that changes as one stays in one file, and the rest of the code base's layout decides the rest. Reflection, `getattr` dispatch, metaclasses and generated code hide control flow from readers and tools, so use them only for a variation plain functions and tables can't express.

**Dependencies between parts.** Keep dependency direction, ownership, transaction boundaries and lifecycles clear. Avoid circular imports, hidden global state, import-time work, and domain logic tied needlessly to transport or storage. Start from the repository's architecture.

**When a fix reveals an architecture problem,** explain the evidence and the smallest adequate correction. Reuse and simplicity aren't reasons to preserve a known broken design. The correction table in the main skill decides whether to implement or ask.

## Contracts between components

Name who reads an output, a person, a program or another service, and where, before choosing its shape. Readers outside this repository don't show in a search. Inspect contracts, not just files: schema versions, serialization, errors, identity, state transitions, retries, configuration and deployment order. Refactors preserve intended semantics unless a behavior change is the goal. Look for places that enumerate the same thing, such as a second dispatcher, an allow-list or a completion file, because a change that updates only one looks finished.

- **Stored data outlives the code.** Pickles, JSON blobs, cache entries and queued messages were written by the old version, so read old shapes or migrate them, and test with a saved sample. A new required field also needs adding to fixtures, seed data and examples.
- **Where it runs.** Know how many processes and machines run this, what they share, and that old and new versions run side by side during a rollout.
- **Which setting wins.** Trace defaults, config files, environment and flags to the value that actually takes effect, and edit that one.
- **Why it is this way.** Recent history, decision records and design notes explain choices that look odd. Read them before reversing one.
- **At a boundary between languages or systems,** state the encoding, line endings, integer width and time format, and test a round trip with the extreme values.
- **Order your own steps** so each builds on something that already exists and runs: contract, then producer, then consumer.

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

- **Signatures.** Keep parameter order the same across related functions, and make easily swapped arguments keyword-only. Accept one input shape, or a few named ones converted once at the edge, rather than guessing between a string, a list and a dict. Don't expose a dependency's types or exceptions in a public API unless that dependency is part of the contract. Size an interface to what its callers use.
- **Names and results that stay true.** When behavior changes, rename what no longer describes it. Say whether results come back in a defined order, the same order each call, without repeats, and the same for the same input. Name the unit, and for positions the frame or coordinate system.
- **Validation.** Check relations between fields as well as each field: start before end, both or neither, matching currencies.
- **Command-line tools.** Results go to stdout, and progress, warnings and errors to stderr, so a pipe gets only data. The exit code is nonzero when anything failed, including part of a batch.
- **Product UI.** A destructive action says what it will remove and offers a confirmation or an undo. User-facing text uses the users' words, not internal ones. Numbers, dates and money go through the locale's formatter, with storage kept separate from display.
- **Configuration.** Read and validate it at startup, failing with the key's name and what's wrong, rather than at first use.
- **Feature flags.** A new flag names its owner and when it comes out, in the code where it's read.

Preserve compatibility deliberately. Don't rename a public API because another name looks nicer: consider callers, deprecation, migration effort and permission.

Comments explain non-obvious intent, invariants, units, constraints, workarounds or measured tradeoffs. Public docstrings cover behavior, inputs, outputs, errors and side effects to the depth a caller needs. Don't narrate lines or restate types. Remove stale comments your change creates and keep useful existing rationale.

Examples in public documentation should actually run. Errors should be actionable without leaking secrets. Add observability at operational boundaries, not noisy logging in every function. Remove abandoned code, imports, debug artifacts, obsolete flags and scaffolding that your change orphaned, and leave pre-existing dead code unless asked.

## File size and large codebases

Size is a prompt to look, not a defect in itself. A very large file usually holds several responsibilities and costs every later reader, human or agent, but moving lines to reach a number only spreads the same coupling around. Use the limits the repository configures, and otherwise the defaults of the language's common linter. `../../occam-python/SKILL.md` lists Python's.

- **New code with its own responsibility** goes in a new file named for that responsibility. A small fix stays where it is.
- **Splitting existing code** is a separate change to propose, unless the request asks for it. Cut where calls across the boundary are few and each side has a name. Lock behavior with tests first, move without changing anything else, and keep old import paths working if anything outside could use them.
- **Finding your way.** Start from entry points and follow dependencies, rather than reading everything. `occam query` lists entry points, outlines, callers and what a change reaches. Past about 50,000 files, `occam map` gives a table of contents from file sizes, and `occam map FOLDER` and `occam scan FOLDER` work on the part the task names. Registries, reflection, plugins and framework autodiscovery mean a text search can't prove that nothing uses something.
- **Where a change goes.** Put it where the neighboring feature puts it: same layer, same helpers, same error types, same config. Fix a bug in the layer that owns it, rather than wherever the symptom shows. Prefer the repository's own libraries to public ones you remember better, and if nothing here does this yet, say so.
- **Changing what others use.** Find every use first, in every package, including strings, config, templates, reflection and test doubles: `occam query find` and `occam query api --base`. A rename or migration isn't done until a final search for the old name comes back empty. `occam gate` lists what it can see of this.
- **Generated and vendored code.** Change what it's generated from and rerun the tool that writes it. A vendored copy gets changed upstream.
- **Infrastructure.** `terraform validate` and a linter show it parses. Passing a validator isn't meeting a policy: who can reach it, what it can do and whether it's encrypted are still yours to check. Before relying on a staging result, name the configuration, versions and limits that differ in production.
- **Boundaries.** Give each component a small public surface and one-way dependencies, and give shared code an owner. Enforce a boundary with a tool where the repository has one, because a convention alone erodes.
- **Modules before services.** A module boundary costs nothing at runtime. A network boundary adds latency, partial failure, versioning and deployment order, so a new service names the scaling, isolation or ownership need it serves.
- **Change incrementally.** Across a large repository, a flag day rarely lands. Let old and new coexist, record a baseline that can only shrink, and raise strictness one area at a time. Use a syntax-aware codemod for mechanical changes.
