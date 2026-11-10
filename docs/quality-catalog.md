# Agent quality catalog

500 failure modes of coding agents, F001 to F500, and what occam has for each. For maintainers: this file isn't loaded during coding sessions. [`large-codebase-failures.md`](large-codebase-failures.md) is the earlier, overlapping catalog of 715, and its token vocabulary is used here.

The list, its IDs, titles and P0, P1 and P2 tiers come from a research report the owner supplied on 2026-11-06. The report says its order is an editorial adoption order, not a measured frequency, and that its 500 checks are an engineering synthesis rather than 500 validated findings. The titles are the report's. Everything else here is occam's own reading of its code and skills.

**A mechanism existing isn't the same as it helping.** Five read-only agents mapped 100 rows each against the repository, told to count a token only if it addresses that failure's mechanism and to say `partial` when occam has only general advice. The rules, gate checks and guidance this work then added were mapped by the session that wrote them, which is the weaker check. `tests/test_quality_catalog.py` checks that every mechanism named exists. No agent run has shown any of it changes outcomes, and earlier head-to-heads of the plugin found no measured benefit: see [`evaluation.md`](evaluation.md).

## How much of this occam can reach

Each row counts once, under the firmest thing it has.

| Level | All | P0 | What it means |
|---|---|---|---|
| Stops it or sends it back | 31 | 17 | A hook denies it, asks a person, holds it once, or sends the agent back. |
| Forces a step that can catch it | 25 | 11 | The agent is sent back until a check, scan or review has run, which may or may not catch this. |
| Finds it | 215 | 34 | `occam scan` or `occam gate` can report an instance from the code. Leads, not proof. |
| Says it at the moment | 43 | 3 | A hook adds one note when it applies, or `gate` asks the question. |
| A tool answers it, if run | 48 | 0 | An `occam` command answers it, if an agent or a person runs it and judges the result. |
| Guidance and tracking only | 138 | 0 | Text the agent may ignore, plus at most a record such as `goal`. |
| Nothing | 0 | 0 | No mechanism listed. |
| **Total** | **500** | **65** | |

**Fit** is designed coverage, not measured: the mapper's judgment of the row as a whole: 500 strong, 0 partial, 0 none. [Measured recall (P0)](#measured-recall-p0) below shows how much of each P0 failure the mechanisms caught on cases written blind to them. Strong means occam has something aimed at this failure itself, and for many rows that something is only a guidance sentence, which agents were measured opening in 1 of 21 and 1 of 15 runs. Partial means occam has only general advice, or covers some forms. 215 rows gained a mechanism in a first pass. A second pass gave the remaining 71 a rule, a gate or goal check, a hook note, an ask or a Stop rider, or a guidance sentence, and the owner decided which of those may ask or send the agent back. Nine rows no static check can reach count as done with their guidance, by the owner's decision. No P0 row is still open.


| Area | IDs | Rows | Strong | Partial | None |
|---|---|---|---|---|---|
| [Goals, scope and acceptance](#goal-goals-scope-and-acceptance) | F001–F020 | 20 | 20 | 0 | 0 |
| [Repository discovery and context](#disc-repository-discovery-and-context) | F021–F040 | 20 | 20 | 0 | 0 |
| [Planning and completing implementation](#plan-planning-and-completing-implementation) | F041–F060 | 20 | 20 | 0 | 0 |
| [Reuse, dependencies and integrations](#reuse-reuse-dependencies-and-integrations) | F061–F080 | 20 | 20 | 0 | 0 |
| [Simplicity, abstraction and structure](#simple-simplicity-abstraction-and-structure) | F081–F100 | 20 | 20 | 0 | 0 |
| [API design, naming and types](#api-api-design-naming-and-types) | F101–F120 | 20 | 20 | 0 | 0 |
| [Python semantics and idioms](#pysem-python-semantics-and-idioms) | F121–F140 | 20 | 20 | 0 | 0 |
| [Python environments, packaging and tooling](#pyenv-python-environments-packaging-and-tooling) | F141–F160 | 20 | 20 | 0 | 0 |
| [Domain correctness and algorithms](#domain-domain-correctness-and-algorithms) | F161–F180 | 20 | 20 | 0 | 0 |
| [Test objectives, oracles and coverage](#oracle-test-objectives-oracles-and-coverage) | F181–F200 | 20 | 20 | 0 | 0 |
| [Test realism, isolation and reliability](#real-test-realism-isolation-and-reliability) | F201–F220 | 20 | 20 | 0 | 0 |
| [Debugging, review and truthful verification](#verify-debugging-review-and-truthful-verification) | F221–F240 | 20 | 20 | 0 | 0 |
| [Application security and trust boundaries](#appsec-application-security-and-trust-boundaries) | F241–F260 | 20 | 20 | 0 | 0 |
| [Agent tools, supply chain and privacy](#agent-agent-tools-supply-chain-and-privacy) | F261–F280 | 20 | 20 | 0 | 0 |
| [Persistence, SQL and data migrations](#data-persistence-sql-and-data-migrations) | F281–F300 | 20 | 20 | 0 | 0 |
| [Asynchronous execution and concurrency](#async-asynchronous-execution-and-concurrency) | F301–F320 | 20 | 20 | 0 | 0 |
| [Distributed systems and resilience](#dist-distributed-systems-and-resilience) | F321–F340 | 20 | 20 | 0 | 0 |
| [Performance, algorithms and measurement](#perf-performance-algorithms-and-measurement) | F341–F360 | 20 | 20 | 0 | 0 |
| [Memory, streaming and large datasets](#mem-memory-streaming-and-large-datasets) | F361–F380 | 20 | 20 | 0 | 0 |
| [Hardware, native code and accelerators](#hw-hardware-native-code-and-accelerators) | F381–F400 | 20 | 20 | 0 | 0 |
| [Usability, accessibility and developer experience](#ux-usability-accessibility-and-developer-experience) | F401–F420 | 20 | 20 | 0 | 0 |
| [Cross-language correctness and conventions](#lang-cross-language-correctness-and-conventions) | F421–F440 | 20 | 20 | 0 | 0 |
| [Multi-agent coordination and shared work](#team-multi-agent-coordination-and-shared-work) | F441–F460 | 20 | 20 | 0 | 0 |
| [CI, delivery, deployment and operations](#ship-ci-delivery-deployment-and-operations) | F461–F480 | 20 | 20 | 0 | 0 |
| [Documentation, maintenance and agent quality controls](#docs-documentation-maintenance-and-agent-quality-controls) | F481–F500 | 20 | 20 | 0 | 0 |

## Measured recall (P0)

Static recall, 2026-11-08: how much of each P0 failure occam's scan, gate and hooks caught on cases written by agents who never saw occam. These cases put code or tool calls through the hooks, scan and gate in a fresh repository, and never run commands. A positive counts as caught only if a mechanism listed on its row stopped it (an ask, a deny, a Stop send-back or a gate FAIL naming the rule) or found it (a scan or gate lead). It measures detection, not whether an agent then fixes the code, and the case authors worked from the same failure list. The plan was fixed in `evals/PREREGISTRATION.md` before the held-out run. Six P0 rows that only a whole session shows (F001, F002, F181, F221, F222, F463) aren't in it.

| Set | Positives | Caught | Stopped | Found | Forced review | Note only | Missed | Near misses flagged |
|---|---|---|---|---|---|---|---|---|
| **Held-out, after** (306 cases, never read while fixing) | 188 | 88 | 34 | 54 | 17 | 11 | 72 | 31 of 118 |
| Held-out, before | 188 | 52 | 28 | 24 | 18 | 4 | 114 | 32 of 118 |
| Development, after (564 cases, the fixes were made against these) | 376 | 285 | 81 | 204 | 9 | 50 | 32 | 33 of 188 |
| Development, before | 376 | 90 | 46 | 44 | 33 | 8 | 245 | 42 of 188 |

Most flagged near misses are the Stop hook requiring a fresh review of a high-consequence file, which is a cost and not a claim of a defect: 14 of the 31 held-out ones. Of the rest, one is new since the fixes, a memory-safety reminder in `gate` on Go `unsafe`, and two earlier ones are gone. Rows that one file can't show, such as authorization decided in another file, revocation and durability, stay mostly guidance and review.

Held-out, by row (positives caught of written, near misses flagged of written):

| Row | Caught | Forced review | Note only | Near misses flagged |
|---|---|---|---|---|
| F066 | 1 of 3 | 0 | 0 | 1 of 2 |
| F130 | 2 of 3 | 0 | 0 | 1 of 2 |
| F210 | 1 of 4 | 0 | 2 | 0 of 2 |
| F241 | 0 of 3 | 0 | 0 | 1 of 2 |
| F242 | 1 of 3 | 0 | 0 | 1 of 2 |
| F243 | 0 of 3 | 2 | 0 | 0 of 2 |
| F244 | 2 of 3 | 0 | 0 | 0 of 2 |
| F245 | 2 of 3 | 0 | 0 | 0 of 2 |
| F246 | 3 of 3 | 0 | 0 | 0 of 2 |
| F247 | 0 of 3 | 0 | 0 | 0 of 2 |
| F248 | 2 of 3 | 0 | 0 | 0 of 2 |
| F249 | 2 of 3 | 0 | 0 | 1 of 2 |
| F250 | 3 of 3 | 0 | 0 | 1 of 2 |
| F251 | 1 of 3 | 0 | 0 | 0 of 2 |
| F252 | 1 of 3 | 2 | 0 | 1 of 2 |
| F253 | 2 of 3 | 1 | 0 | 1 of 2 |
| F254 | 3 of 3 | 0 | 0 | 1 of 2 |
| F255 | 1 of 3 | 0 | 0 | 0 of 2 |
| F257 | 2 of 3 | 0 | 0 | 0 of 2 |
| F258 | 0 of 3 | 2 | 0 | 1 of 2 |
| F259 | 1 of 3 | 1 | 0 | 2 of 2 |
| F260 | 0 of 3 | 3 | 0 | 2 of 2 |
| F261 | 0 of 3 | 0 | 0 | 0 of 2 |
| F262 | 2 of 3 | 0 | 0 | 0 of 2 |
| F263 | 2 of 4 | 0 | 0 | 0 of 2 |
| F264 | 2 of 3 | 0 | 0 | 0 of 2 |
| F265 | 4 of 4 | 0 | 0 | 1 of 2 |
| F266 | 2 of 4 | 0 | 0 | 0 of 2 |
| F267 | 3 of 3 | 0 | 0 | 0 of 2 |
| F268 | 1 of 3 | 0 | 0 | 1 of 2 |
| F269 | 1 of 3 | 0 | 0 | 0 of 2 |
| F270 | 0 of 4 | 0 | 2 | 0 of 2 |
| F271 | 2 of 3 | 1 | 0 | 0 of 2 |
| F273 | 0 of 4 | 0 | 3 | 0 of 2 |
| F274 | 0 of 3 | 0 | 0 | 0 of 2 |
| F275 | 1 of 4 | 0 | 0 | 0 of 2 |
| F276 | 1 of 4 | 0 | 2 | 0 of 2 |
| F278 | 3 of 4 | 0 | 0 | 2 of 2 |
| F280 | 2 of 3 | 0 | 0 | 0 of 2 |
| F281 | 2 of 3 | 0 | 0 | 0 of 2 |
| F282 | 0 of 3 | 2 | 0 | 1 of 2 |
| F283 | 1 of 3 | 0 | 0 | 0 of 2 |
| F291 | 3 of 3 | 0 | 0 | 1 of 2 |
| F294 | 0 of 3 | 0 | 0 | 0 of 2 |
| F295 | 0 of 3 | 1 | 0 | 0 of 2 |
| F299 | 3 of 4 | 0 | 0 | 1 of 2 |
| F305 | 1 of 3 | 0 | 0 | 0 of 2 |
| F324 | 1 of 3 | 1 | 0 | 2 of 2 |
| F329 | 1 of 3 | 1 | 0 | 1 of 2 |
| F336 | 0 of 3 | 0 | 0 | 0 of 2 |
| F386 | 2 of 3 | 0 | 0 | 0 of 2 |
| F387 | 3 of 3 | 0 | 0 | 2 of 2 |
| F388 | 2 of 3 | 0 | 0 | 2 of 2 |
| F426 | 3 of 3 | 0 | 0 | 0 of 2 |
| F429 | 3 of 3 | 0 | 0 | 2 of 2 |
| F435 | 2 of 3 | 0 | 0 | 0 of 2 |
| F436 | 1 of 3 | 0 | 0 | 1 of 2 |
| F437 | 2 of 3 | 0 | 0 | 0 of 2 |
| F447 | 2 of 4 | 0 | 2 | 0 of 2 |


## Reading a row

**Prevent** acts while the work happens. **Find and fix** works on code that already exists. Tokens are as in the large-codebase catalog: `hook:` stops or sends back, `note:` says it once, `scan:` is an `occam rules` rule, `gate:` is something `occam gate` reports on a diff, `query:` and `tool:` are `occam` commands, and `guide:` is a passage in a skill. **Same as** gives the large-codebase catalog's rows for the same failure. **What's missing** is the mapper's note for rows that aren't strong.


## GOAL: Goals, scope and acceptance

| ID | Tier | What goes wrong | Prevent | Find and fix | Fit | Same as | What's missing |
|---|---|---|---|---|---|---|---|
| F001 | P0 | Solving the wrong user problem | guide:know-done guide:state-assumptions gate:judgment guide:read-request-literally-before guide:find-the-problem-behind-it | none | strong | LOGIC-01 SCOPE-12 | - |
| F002 | P0 | Ignoring explicit constraints | tool:goal gate:judgment hook:read-only note:after-compaction guide:honor-explicit-restrictions-even gate:goal-limits | tool:goal gate:goal-limits | strong | SCOPE-01 SCOPE-02 SCOPE-16 SCOPE-17 SAFE-29 | - |
| F003 | P1 | Starting without completion criteria | guide:know-done tool:goal note:long-run guide:turn-request-into-checks guide:goal-recorded | none | strong | - | - |
| F004 | P1 | Treating examples as the entire specification | guide:no-silent-narrowing guide:edge-inputs gate:test-input-special-cased guide:examples-illustrate-a-rule | gate:test-input-special-cased | strong | LOGIC-28 | - |
| F005 | P1 | Inventing requirements to fill ambiguity | guide:state-assumptions guide:know-done guide:it-needs-to-exist guide:ask-decisions-about-ambiguity | none | strong | ARCH-20 | - |
| F006 | P1 | Optimizing output volume instead of outcomes | gate:size guide:quarter-size guide:no-test-count guide:at-lowest-total-cost | gate:size | strong | SHAPE-01 TEST-16 TEST-17 | - |
| F007 | P1 | Adding unrequested adjacent features | guide:it-needs-to-exist guide:surgical gate:judgment guide:leave-out-features-nobody | tool:goal | strong | SCOPE-10 SCOPE-12 PIPE-22 DATA-33 | - |
| F008 | P1 | Missing operational requirements | guide:know-done guide:layers guide:reliability gate:env-var-undeclared guide:add-observability-at-operational | gate:env-var-undeclared scan:missing-timeout scan:hardcoded-host scan:absolute-path | strong | ARCH-26 XF-20 | - |
| F009 | P1 | Ignoring existing users and workflows | guide:compat-deliberate guide:know-done guide:explain-deviations gate:caller-not-updated gate:removed-still-named | query:api gate:caller-not-updated gate:removed-still-named | strong | XF-06 BUILD-26 PIPE-23 | - |
| F010 | P1 | Confusing a prototype with production readiness | guide:run-at-size guide:no-silent-narrowing guide:appear-only-their-scope | scan:fake-data scan:mock-in-production scan:process-local-state scan:unpaginated-query scan:hardcoded-host | strong | PERF-31 | - |
| F011 | P1 | Treating a requested approach as an unquestionable goal | guide:suggestions-tested guide:false-premise guide:simpler-design guide:user-suggests-shortcut-would | none | strong | LOOP-24 LOOP-26 SCOPE-22 | - |
| F012 | P1 | Failing to prioritize requirements | tool:goal guide:complete-slices guide:no-silent-narrowing guide:sort-what-you-were-told | tool:goal | strong | SCOPE-21 SCOPE-29 | - |
| F013 | P1 | Ignoring non-goals | guide:know-done tool:goal guide:non-goal-could-reasonably | tool:goal | strong | SCOPE-03 | - |
| F014 | P1 | Changing observable behavior during cleanup | guide:rewrites-keep note:rewrite guide:cleanup-method gate:guard-removed guide:refactors-preserve-intended-semantics guide:lock-behavior-before-change | tool:golden tool:mutate | strong | SCOPE-08 XF-37 XF-39 SHAPE-19 DATA-34 | - |
| F015 | P1 | Ignoring error and cancellation journeys | guide:know-done guide:edge-inputs guide:reliability guide:failure-injection-timeouts-partial | scan:swallowed-exception scan:bare-except | strong | LOGIC-09 UI-09 ERR-01 | - |
| F016 | P1 | Failing to identify the real consumer | guide:know-done guide:contracts-between guide:search-not-proof gate:usual-partner guide:name-who-reads-an-output | query:find query:impact query:history | strong | XF-22 XF-12 | - |
| F017 | P1 | Accepting contradictory requirements silently | guide:false-premise guide:state-assumptions guide:ask-before-changing-what guide:name-conflicts | none | strong | GAME-01 GAME-02 CTX-27 | - |
| F018 | P2 | Treating every preference as a hard requirement | guide:state-assumptions guide:sort-what-you-were-told | none | strong | - | - |
| F019 | P1 | Continuing after user steering changes the goal | hook:read-only guide:follow-a-redirect | none | strong | LOOP-17 | - |
| F020 | P1 | Failing to define excluded environments | guide:know-done guide:pre-existing-named guide:name-where-it-runs | none | strong | - | - |

## DISC: Repository discovery and context

| ID | Tier | What goes wrong | Prevent | Find and fix | Fit | Same as | What's missing |
|---|---|---|---|---|---|---|---|
| F021 | P1 | Editing before reading neighboring code | guide:contracts-known guide:where-it-goes query:outline query:find | none | strong | CTX-18 CTX-19 CTX-20 | - |
| F022 | P1 | Ignoring repository instructions | guide:contracts-known note:nearby-instructions guide:before-a-pr gate:instructions-covering | query:commands gate:instructions-covering | strong | CTX-10 CTX-28 CTX-29 SCOPE-19 SCOPE-20 | - |
| F023 | P1 | Assuming an empty or clean worktree | guide:check-tree-first guide:shared-tree hook:git-guard tool:coord guide:unfamiliar-changes-working-tree | tool:coord | strong | SAFE-17 SAFE-18 TEAM-11 | - |
| F024 | P1 | Searching by only one guessed name | guide:search-not-proof gate:new-duplicate guide:search-capability-related-concepts | gate:new-duplicate scan:parallel-verbs | strong | LOC-02 LOC-18 | - |
| F025 | P1 | Reading summaries without source verification | guide:resume-check guide:delegate-claims guide:code-wins guide:where-code-disagree-about | tool:docs gate:design-drift | strong | CTX-22 CTX-24 TEAM-05 | - |
| F026 | P1 | Missing indirect callers and registrations | guide:search-not-proof guide:same-thing-listed gate:unregistered-file gate:removed-still-named guide:registries-reflection-plugins-framework | query:find gate:caller-not-updated gate:unregistered-file gate:removed-still-named | strong | XF-15 XF-42 XF-08 | - |
| F027 | P1 | Ignoring configuration precedence | gate:config-bypassed guide:same-thing-listed guide:check-how-change-behaves guide:which-setting-wins | gate:config-bypassed scan:duplicate-config scan:unreferenced-setting query:find | strong | XF-17 | - |
| F028 | P1 | Assuming dependency APIs from memory | guide:real-apis note:python-facts note:dependency-facts hook:check-after-edit guide:check-apis-against-what | scan:phantom-attribute scan:phantom-import scan:deprecated-api tool:tools | strong | API-03 API-04 API-07 API-10 BUILD-19 | - |
| F029 | P1 | Ignoring recent architectural decisions | tool:design note:design-decision gate:uses-deprecated-here guide:follow-accepted-decisions-supersede guide:why-it-is | gate:design-drift query:history | strong | ARCH-12 API-16 | - |
| F030 | P1 | Missing generated-file ownership | note:protected-file gate:generated-edited guide:change-what-generated-from | gate:generated-edited gate:schema-not-regenerated | strong | BUILD-12 XF-23 | - |
| F031 | P1 | Confusing vendored and project-owned code | note:protected-file gate:vendored-edited guide:vendored-copy-gets-changed | gate:vendored-edited | strong | LOC-11 LOC-25 | - |
| F032 | P1 | Using stale repository snapshots | gate:stale-base guide:check-tree-first guide:resume-check tool:coord | gate:stale-base | strong | LOC-13 TEAM-20 TEAM-11 CTX-18 API-18 | - |
| F033 | P1 | Dumping the entire repository into context | guide:finding-your-way guide:batch-reads tool:map query:outline query:size | none | strong | CTX-01 CTX-04 CTX-06 LOC-25 | - |
| F034 | P1 | Failing to preserve decisions across context resets | note:after-compaction tool:goal tool:design guide:handoff guide:compaction-not-a-reason guide:supersede-reason-stays-record | tool:goal tool:design | strong | CTX-08 CTX-09 CTX-10 CTX-11 CTX-12 SCOPE-34 | - |
| F035 | P1 | Importing assumptions from an unrelated earlier task | guide:pattern-preconditions note:long-run note:after-compaction guide:start-each-request-fresh | none | strong | - | - |
| F036 | P1 | Missing the actual execution path | guide:real-entry-point guide:finding-your-way guide:reproduce-first gate:twin-left-behind guide:trace-one-real-request | query:entry query:tests query:impact scan:diverged-twin scan:orphan-module | strong | LOC-12 BUILD-04 | - |
| F037 | P1 | Ignoring deployment topology | guide:layers guide:contracts-between guide:coexist guide:module-level-state-exists guide:where-it-runs | scan:process-local-state scan:migration-destroys-data | strong | PERF-25 XF-21 DATA-25 | - |
| F038 | P1 | Failing to establish a baseline | guide:contracts-known guide:pre-existing-named hook:speedup-claim gate:judgment tool:golden guide:run-untouched-code-first guide:red-baseline-itself-finding | tool:baseline tool:golden | strong | PERF-10 REPORT-17 | - |
| F039 | P2 | Repeatedly rediscovering stable project facts | tool:design note:design-decision query:commands tool:map | none | strong | CTX-21 | - |
| F040 | P1 | Overtrusting documentation over runtime evidence | guide:code-wins guide:resume-check guide:real-apis guide:where-code-disagree-about guide:make-one-small-real | tool:docs gate:docs-facts gate:design-drift | strong | CTX-24 CTX-25 CTX-26 | - |

## PLAN: Planning and completing implementation

| ID | Tier | What goes wrong | Prevent | Find and fix | Fit | Same as | What's missing |
|---|---|---|---|---|---|---|---|
| F041 | P1 | Skipping a plan for a coupled change | guide:everywhere-it-reaches guide:depth-by-effect tool:goal query:impact guide:one-per-step-longer guide:a-slice-is-one-behavior | none | strong | XF-30 | - |
| F042 | P1 | Writing a plan too detailed to adapt | tool:goal guide:drive-toward-checkable-end | none | strong | - | - |
| F043 | P1 | Treating the plan as immutable | guide:explain-deviations guide:false-premise guide:new-evidence-changes-plan | none | strong | SCOPE-22 REPORT-14 | - |
| F044 | P1 | Planning indefinitely without implementation | guide:stop-researching | none | strong | CTX-02 CTX-03 | - |
| F045 | P1 | Breaking work by files instead of behavior | guide:complete-slices guide:finish-check-one-slice guide:a-slice-is-one-behavior | none | strong | XF-52 | - |
| F046 | P1 | Ignoring dependency order | guide:contracts-between guide:coexist guide:integrate-dependency-order guide:order-steps | scan:migration-destroys-data | strong | XF-21 DATA-25 | - |
| F047 | P1 | Leaving stubs on reachable paths | guide:no-silent-narrowing note:scan-on-edit hook:scan-at-stop guide:never-put-mock-todo | scan:stub-body scan:stub-raise scan:placeholder-comment scan:truncation-marker scan:fake-success scan:fake-data | strong | LOGIC-15 LOGIC-16 LOGIC-17 GAME-21 | - |
| F048 | P1 | Implementing the core but omitting integration | guide:real-entry-point gate:new-unused gate:unregistered-file gate:judgment | scan:unreferenced-def scan:orphan-module query:entry | strong | XF-15 XF-16 TEAM-23 | - |
| F049 | P1 | Leaving callers on old signatures | gate:caller-not-updated guide:everywhere-it-reaches | gate:caller-not-updated scan:wrong-arg-count query:api query:find tool:tools | strong | XF-01 XF-04 XF-05 XF-26 | - |
| F050 | P1 | Forgetting fixtures and example migrations | guide:everywhere-it-reaches gate:model-no-migration gate:removed-still-named guide:including-strings-config-templates guide:examples-public-documentation-should guide:stored-data | gate:removed-still-named gate:model-no-migration tool:docs | strong | XF-24 XF-48 DATA-22 | - |
| F051 | P1 | Abandoning difficult requirements silently | guide:no-silent-narrowing hook:stop-short tool:goal gate:judgment note:listed-item-left-out | tool:goal | strong | SCOPE-29 SCOPE-36 LOGIC-14 XF-44 | - |
| F052 | P1 | Expanding a bug fix into a rewrite | note:rewrite guide:surgical guide:correctness-beats guide:targeted-edits gate:size gate:scope | gate:size gate:scope | strong | SCOPE-05 SCOPE-06 SCOPE-09 | - |
| F053 | P1 | Mixing unrelated formatting and semantic edits | gate:format-churn guide:surgical guide:diff-moves-code-changes | gate:format-churn | strong | SCOPE-07 XF-51 | - |
| F054 | P1 | Patching symptoms repeatedly | guide:cause-established guide:three-fails guide:layer-owns-it note:failed-streak | query:history scan:swallowed-exception | strong | LOGIC-47 LOOP-01 SCOPE-37 SEC-07 LOC-06 | - |
| F055 | P1 | Failing to revisit assumptions after experiments | guide:three-fails guide:earliest-error note:failed-streak note:repeated-failure guide:new-evidence-changes-plan | none | strong | LOOP-01 LOOP-02 LOOP-12 | - |
| F056 | P1 | Running open-ended repair loops | note:failed-streak note:repeated-failure guide:three-fails guide:critique-rounds guide:bound-long-runs note:long-run | none | strong | LOOP-02 LOOP-04 LOOP-06 LOOP-19 SAFE-51 | - |
| F057 | P1 | Ending after unit implementation alone | guide:real-entry-point guide:combined-behavior guide:project-suite guide:passing-not-requirement gate:wide-reach | query:impact query:tests query:entry | strong | XF-25 LOGIC-38 TEST-38 TEST-20 BUILD-04 | - |
| F058 | P1 | Leaving temporary scaffolding behind | guide:back-out gate:orphaned guide:remove-abandoned-code-imports | scan:scratch-file scan:debug-leftover scan:commented-out-code gate:orphaned | strong | BUILD-28 SHAPE-18 LOOP-15 | - |
| F059 | P2 | Creating excessive process artifacts | guide:it-needs-to-exist guide:design-doc-small guide:looks-like-report-work guide:generate-planning-files-trivial guide:rather-than-inventing-receipt | scan:ai-report-file | strong | BUILD-29 | - |
| F060 | P1 | Failing to reconcile the final result with the goal | gate:judgment tool:goal guide:report-format | tool:goal | strong | REPORT-14 XF-34 | - |

## REUSE: Reuse, dependencies and integrations

| ID | Tier | What goes wrong | Prevent | Find and fix | Fit | Same as | What's missing |
|---|---|---|---|---|---|---|---|
| F061 | P1 | Reimplementing existing repository behavior | guide:capabilities-compared gate:new-duplicate guide:what-exists-before-adding | scan:clone-function scan:clone-block scan:clone-renamed scan:diverged-twin scan:parallel-verbs | strong | REUSE-01 REUSE-02 REUSE-03 REUSE-04 REUSE-11 REUSE-15 CTX-17 | - |
| F062 | P1 | Ignoring standard library or platform capabilities | guide:capabilities-compared guide:what-exists-before-adding | scan:handrolled-helper scan:handrolled-csv scan:handrolled-json scan:handrolled-argv scan:handrolled-url scan:handrolled-memo scan:handrolled-html-parse | strong | API-20 REUSE-16 | - |
| F063 | P1 | Ignoring already-installed dependencies | guide:capabilities-compared note:dependency-facts gate:manifest-note guide:what-exists-before-adding | scan:competing-dependencies tool:deps | strong | REUSE-17 REUSE-18 ARCH-15 | - |
| F064 | P1 | Skipping a third-party solution assessment | guide:capabilities-compared guide:established-libraries guide:substantial-choices-record-options | scan:homemade-crypto scan:handrolled-csv scan:handrolled-html-parse scan:handrolled-retry | strong | REUSE-17 | - |
| F065 | P1 | Adding a dependency for trivial behavior | guide:capabilities-compared guide:vet-dependency gate:manifest-note note:dependency-facts guide:need-genuinely-trivial | none | strong | - | - |
| F066 | P0 | Installing hallucinated packages | guide:real-apis guide:vet-dependency note:dependency-facts gate:manifest-note note:undeclared-install gate:added-dependencies | scan:phantom-import tool:deps gate:added-dependencies | strong | BUILD-14 BUILD-15 | - |
| F067 | P1 | Choosing a library only from popularity | guide:vet-dependency guide:capabilities-compared guide:compare-candidates-fitness-total | tool:deps | strong | - | - |
| F068 | P1 | Ignoring transitive dependency impact | guide:vet-dependency note:dependency-facts guide:dep-lockfile-diff | none | strong | BUILD-20 BUILD-21 | - |
| F069 | P1 | Copying an example without adapting its lifecycle | guide:pattern-preconditions guide:one-way-deps guide:lang-resources guide:context-managers-files-sockets guide:example-shows-the-call | scan:resource-no-context scan:effect-no-cleanup scan:client-per-call | strong | API-13 ERR-14 | - |
| F070 | P1 | Wrapping an entire library without a concrete need | guide:new-structure guide:prefer-thin-adapter-at | scan:pass-through scan:single-impl-abstraction | strong | - | - |
| F071 | P1 | Depending on private library internals | gate:crosses-boundary | gate:crosses-boundary scan:private-import | strong | ARCH-07 | - |
| F072 | P1 | Maintaining duplicate validation rules | guide:duplicated-knowledge gate:new-duplicate guide:scatter-redundant-validation-through | scan:diverged-twin scan:clone-function scan:parallel-verbs | strong | REUSE-04 REUSE-05 REUSE-07 | - |
| F073 | P1 | Sharing code with incompatible semantics | guide:capabilities-compared guide:duplicated-knowledge guide:similar-name-different-semantics | scan:flag-params tool:golden | strong | - | - |
| F074 | P1 | Refusing useful duplication until semantics stabilize | guide:duplicated-knowledge guide:two-similar-bodies-justify | scan:flag-params scan:single-impl-abstraction | strong | - | - |
| F075 | P1 | Adding a package without a reproducible resolution | scan:dep-unpinned gate:lockfile-not-updated guide:vet-dependency guide:library-declares-ranges-application | scan:dep-unpinned scan:nb-unpinned-install gate:lockfile-not-updated | strong | BUILD-18 BUILD-10 | - |
| F076 | P1 | Ignoring dependency end-of-life or migration paths | guide:vet-dependency note:python-facts guide:dep-health-eol | scan:deprecated-api tool:deps | strong | API-15 BUILD-17 | - |
| F077 | P1 | Assuming SDK retries and timeouts are safe | guide:retries guide:reliability note:security-facts guide:rel-one-layer | scan:missing-timeout | strong | ERR-12 ERR-13 | - |
| F078 | P1 | Using incompatible async and sync integrations | note:scan-on-edit hook:scan-at-stop note:language-skill guide:anything-blocking-cpu-heavy | scan:blocking-in-async scan:missing-await scan:async-foreach scan:async-no-await | strong | PERF-11 PERF-12 PERF-13 | - |
| F079 | P1 | Failing to test replacement-library compatibility | guide:rewrites-keep tool:golden guide:differential-tests-against-old | tool:golden tool:mutate | strong | - | - |
| F080 | P2 | Never revisiting custom code after ecosystem changes | guide:revisit-custom-code | scan:handrolled-helper scan:deprecated-api | strong | - | - |

## SIMPLE: Simplicity, abstraction and structure

| ID | Tier | What goes wrong | Prevent | Find and fix | Fit | Same as | What's missing |
|---|---|---|---|---|---|---|---|
| F081 | P1 | Building a framework for one use case | guide:new-structure guide:simpler-design guide:speculative-extensibility-pass-through guide:abstract-production-concerns-make | scan:single-impl-abstraction scan:pattern-one-product scan:pass-through | strong | SHAPE-07 TEAM-26 | - |
| F082 | P1 | Creating speculative configuration flags | guide:it-needs-to-exist guide:new-structure | scan:unused-option scan:unreferenced-setting scan:flag-params | strong | SHAPE-13 | - |
| F083 | P1 | Introducing unnecessary service boundaries | guide:new-structure guide:module-boundary-costs-nothing | none | strong | - | - |
| F084 | P1 | Creating deep inheritance for code reuse | guide:new-structure guide:avoid-inheritance-just-reach | scan:deep-inheritance scan:lsp-violation | strong | - | - |
| F085 | P1 | Ignoring an existing appropriate base class | guide:capabilities-compared guide:respect-existing-well-designed guide:extend-existing-base-class | scan:base-class-bypassed scan:pull-up-method | strong | - | - |
| F086 | P1 | Creating one-method wrappers without policy | guide:new-structure guide:speculative-extensibility-pass-through | scan:pass-through scan:one-method-class | strong | SHAPE-10 | - |
| F087 | P1 | Building a generic engine around two unrelated cases | guide:new-structure guide:parameter-heavy-universal-function guide:flag-selects-between-them | scan:flag-params | strong | - | - |
| F088 | P1 | Concentrating unrelated responsibilities in one module | guide:size-prompt guide:goes-new-file-named guide:own-responsibility-belongs-own | scan:god-file scan:god-class scan:hub-module scan:utility-bucket | strong | ARCH-03 ARCH-06 | - |
| F089 | P1 | Splitting tiny cohesive logic across many files | guide:size-prompt guide:split-where-calls-across guide:keep-together | none | strong | - | - |
| F090 | P1 | Keeping old and new implementations indefinitely | guide:final-search guide:coexist gate:orphaned guide:remove-old-one-after | gate:orphaned scan:hedge-name scan:diverged-twin scan:competing-dependencies | strong | XF-47 | - |
| F091 | P1 | Adding fallback chains that hide broken invariants | guide:cause-established guide:failure-visible guide:no-silent-narrowing note:scan-on-edit | scan:fallback-fake scan:swallowed-exception scan:broad-wrap scan:failure-reported-as-success | strong | ERR-05 ERR-06 ERR-08 | - |
| F092 | P1 | Using metaprogramming for ordinary control flow | guide:avoid-unnecessary-metaclasses-decorators guide:signature-changing-decorators-hide guide:no-metaprogramming | scan:dynamic-eval | strong | - | - |
| F093 | P1 | Applying design patterns by name alone | guide:pattern-preconditions guide:new-structure | scan:pattern-one-product scan:single-impl-abstraction | strong | ARCH-23 | - |
| F094 | P1 | Centralizing everything in a generic utilities module | guide:reject-generic-utility-bucket guide:become-dumping-ground | scan:utility-bucket scan:vague-name | strong | - | - |
| F095 | P1 | Using global mutable singletons for convenience | guide:one-way-deps guide:mutable-state-shared-across | scan:global-statement scan:process-local-state | strong | PERF-25 PERF-18 | - |
| F096 | P1 | Overcompressing code into clever expressions | guide:maintainer-read guide:avoid-needless-cleverness guide:short-code-hides-state | scan:high-complexity scan:dense-comprehension | strong | SHAPE-02 | - |
| F097 | P1 | Deleting safeguards while simplifying | guide:safety-beats gate:guard-removed guide:some-things-get-simplified | gate:guard-removed tool:golden | strong | SAFE-35 SAFE-36 XF-37 PERF-29 | - |
| F098 | P2 | Abstracting hypothetical future backends | guide:new-structure guide:speculative-extensibility-pass-through | scan:single-impl-abstraction scan:pattern-one-product | strong | SHAPE-07 | - |
| F099 | P1 | Leaving unreachable or unused code | gate:new-unused gate:orphaned guide:surgical | scan:unreachable-code scan:dead-branch scan:unreferenced-def scan:orphan-module scan:unused-import scan:commented-out-code | strong | SHAPE-12 SHAPE-13 LOOP-11 | - |
| F100 | P1 | Measuring maintainability only by line count | guide:measure-cleanup guide:size-prompt guide:fewest-lines-most-abstractions | gate:complexity-rose tool:baseline | strong | REPORT-26 | - |

## API: API design, naming and types

| ID | Tier | What goes wrong | Prevent | Find and fix | Fit | Same as | What's missing |
|---|---|---|---|---|---|---|---|
| F101 | P1 | Inventing unconventional names for familiar operations | guide:vocabulary guide:check-what-package-already | scan:parallel-verbs | strong | ARCH-18 | - |
| F102 | P1 | Naming behavior inaccurately | guide:get-means-cheap-lookup guide:booleans-read-predicates guide:api-names-true | none | strong | - | - |
| F103 | P1 | Using vague classes such as Manager or Processor | guide:vocabulary guide:prefer-domain-word | scan:vague-name | strong | - | - |
| F104 | P1 | Inconsistent argument ordering across related APIs | guide:keep-singular-plural-verbs guide:make-flag-parameters-keyword guide:api-signatures | none | strong | - | - |
| F105 | P1 | Returning unrelated types on different paths | scan:inconsistent-return guide:inconsistent-return-types | scan:inconsistent-return | strong | - | - |
| F106 | P1 | Accepting many loosely specified input shapes | guide:silent-coercion guide:avoid-both-untyped-public guide:api-signatures | none | strong | - | - |
| F107 | P1 | Using booleans to select unrelated behaviors | scan:flag-params guide:flags-select-between-unrelated guide:make-flag-parameters-keyword | scan:flag-params | strong | - | - |
| F108 | P1 | Conflating missing null empty and zero | guide:null-undefined-missing-key guide:py-falsy | none | strong | - | - |
| F109 | P1 | Leaking implementation details into public APIs | guide:boundaries guide:package-exposes-small-surface guide:api-signatures | query:api | strong | - | - |
| F110 | P1 | Changing public defaults without compatibility analysis | guide:compat-deliberate guide:incompatible-api-schema-changes | query:api | strong | - | - |
| F111 | P1 | Using Any or casts to silence type errors | hook:weakened-check guide:honest-checks guide:any-at-boundary-spreads gate:types-silenced | scan:suppression-comment scan:ts-any scan:ts-double-cast query:markers gate:types-silenced | strong | GAME-29 GAME-30 | - |
| F112 | P1 | Treating annotations as runtime validation | guide:annotation-input-validation-security guide:typescript-type-assertion-validates | none | strong | - | - |
| F113 | P1 | Creating broad interfaces that callers barely use | guide:prefer-composition-small-interfaces guide:accept-small-interfaces-return guide:api-signatures | none | strong | - | - |
| F114 | P1 | Using inheritance where structural typing fits | guide:protocol-interface-contract-useful guide:protocol-contract-commonality-implementers | none | strong | - | - |
| F115 | P1 | Returning mutable internal state | guide:mutable-default-arguments-accidental guide:surprising-mutation guide:py-return-copies | none | strong | - | - |
| F116 | P1 | Hiding expensive I/O behind innocent properties | guide:network-call-shouldn-also | scan:io-in-property | strong | - | - |
| F117 | P1 | Mixing synchronous and asynchronous contracts unpredictably | guide:sync-async-semantics guide:follow-existing-convention-async | scan:async-no-await scan:missing-await | strong | PERF-13 | - |
| F118 | P1 | Failing to document ordering and stability | guide:write-what-caller-guess guide:api-names-true | none | strong | - | - |
| F119 | P1 | Returning opaque errors without structured meaning | guide:errors-should-actionable-without guide:distinguish-expected-domain-errors | scan:generic-exception scan:opaque-error | strong | - | - |
| F120 | P1 | Omitting units and coordinate systems from contracts | guide:put-units-name guide:comments guide:api-names-true | none | strong | - | - |

## PYSEM: Python semantics and idioms

| ID | Tier | What goes wrong | Prevent | Find and fix | Fit | Same as | What's missing |
|---|---|---|---|---|---|---|---|
| F121 | P1 | Using mutable default arguments | note:scan-on-edit hook:scan-at-stop guide:mutable-default-arguments | scan:mutable-default | strong | LOGIC-34 | - |
| F122 | P1 | Capturing loop variables late in closures | guide:closures-capturing-loop-variable | scan:loop-variable-closure | strong | - | - |
| F123 | P1 | Confusing shallow and deep copies | guide:know-whether-need-shallow | none | strong | - | - |
| F124 | P1 | Using truthiness when zero or empty is valid | guide:rather-than-0-valid guide:py-falsy | none | strong | - | - |
| F125 | P1 | Comparing values with identity | guide:py-identity | tool:tools | strong | - | - |
| F126 | P1 | Using mutable or unstable dictionary keys | guide:py-stable-keys | none | strong | - | - |
| F127 | P1 | Consuming an iterator more than once | guide:iterators-generators-exhausted-first | none | strong | - | - |
| F128 | P1 | Returning lazy work after closing its resource | guide:lazy-evaluation-running-later | scan:lazy-after-close | strong | - | - |
| F129 | P1 | Catching Exception around unrelated operations | note:scan-on-edit guide:catch-exception-make-failure | scan:broad-wrap scan:swallowed-exception scan:bare-except | strong | ERR-02 | - |
| F130 | P0 | Using assert for security or input validation | guide:assert-used-required-validation guide:assert-authorization-check | scan:assert-validation | strong | LOGIC-34 | - |
| F131 | P1 | Suppressing exception context indiscriminately | guide:preserve-causes-raise-from | none | strong | - | - |
| F132 | P1 | Failing to close files clients or cursors | guide:context-managers-files-sockets | scan:resource-no-context | strong | ERR-14 | - |
| F133 | P1 | Doing network or filesystem work at import time | guide:one-way-deps guide:import-time-code-runs | scan:import-time-io | strong | PERF-27 | - |
| F134 | P1 | Configuring global logging inside a library | guide:libraries-only-call-logging | none | strong | - | - |
| F135 | P1 | Mutating collections during iteration | guide:py-mutate-iterate | scan:mutated-while-iterating | strong | - | - |
| F136 | P1 | Assuming bool is excluded from integer validation | guide:py-bool-int | none | strong | - | - |
| F137 | P1 | Depending on garbage collection for correctness | guide:context-managers-files-sockets guide:py-del | none | strong | - | - |
| F138 | P1 | Overusing decorators that obscure signatures or state | guide:signature-changing-decorators-hide-2 guide:avoid-unnecessary-metaclasses-decorators-2 guide:py-wraps | scan:unwrapped-decorator | strong | - | - |
| F139 | P1 | Using class attributes for per-instance mutable data | guide:accidental-aliasing guide:dataclass-plain-records guide:py-class-shared | scan:shared-class-mutable | strong | - | - |
| F140 | P2 | Ignoring Python protocols and built-in iteration idioms | guide:capabilities-compared guide:follow-pep-8-pep | scan:handrolled-helper scan:range-len-loop | strong | API-20 | - |

## PYENV: Python environments, packaging and tooling

| ID | Tier | What goes wrong | Prevent | Find and fix | Fit | Same as | What's missing |
|---|---|---|---|---|---|---|---|
| F141 | P1 | Using a different interpreter from the project's environment | guide:then-reuse-existing-environment guide:passing-suites query:commands guide:py-interpreter | none | strong | - | - |
| F142 | P1 | Installing project dependencies globally | guide:then-reuse-existing-environment guide:py-install-env | none | strong | - | - |
| F143 | P1 | Bypassing the existing package manager | note:wrong-manager gate:second-lockfile guide:install-stack-established query:commands guide:py-install-env | none | strong | BUILD-09 | - |
| F144 | P1 | Updating declarations without updating resolution artifacts | gate:lockfile-not-updated | gate:lockfile-not-updated | strong | BUILD-10 | - |
| F145 | P1 | Testing only against an editable checkout | guide:only-editable-imports-from guide:imports-public-exports-from guide:real-entry-point | none | strong | - | - |
| F146 | P1 | Relying on the working directory for imports | guide:fix-packaging-rather-than guide:python-m-pytest-adds | guide:sys-path-insert-hard | strong | - | - |
| F147 | P1 | Naming modules after standard-library packages | note:python-facts guide:shadows-standard-library-breaks | scan:stdlib-shadowed | strong | - | - |
| F148 | P1 | Omitting package data from the build | guide:since-those-hide-missing guide:src-layout-makes-tests | none | strong | - | - |
| F149 | P1 | Misdeclaring supported Python versions | guide:check-supported-python-requires guide:raise-python-version-express guide:py-versions-wheels | scan:deprecated-api | strong | - | - |
| F150 | P1 | Making optional dependencies mandatory at import time | guide:py-optional-extra | none | strong | - | - |
| F151 | P1 | Putting development tools in runtime requirements | guide:py-dev-deps | none | strong | - | - |
| F152 | P1 | Ignoring binary wheel and platform availability | guide:vet-dependency guide:py-versions-wheels | none | strong | - | - |
| F153 | P1 | Treating formatting as semantic validation | hook:check-after-edit hook:pass-claim | none | strong | - | - |
| F154 | P1 | Disabling lint rules globally to pass one change | hook:weakened-check hook:side-effects-named guide:honest-checks guide:lowering-global-setting-land guide:configuration-counts-too | scan:checks-hidden-by-config gate:checks-relaxed | strong | GAME-29 | - |
| F155 | P1 | Adding conflicting formatter configurations | guide:migrate-tooling | scan:competing-dependencies scan:formatter-conflict | strong | ARCH-14 | - |
| F156 | P1 | Claiming type safety after checking only one file | guide:thorough-claim-needs-make guide:mypy-skips-bodies-unannotated guide:py-type-scope | tool:tools | strong | - | - |
| F157 | P1 | Ignoring py.typed or distributed type information | guide:typed-library-ships-py guide:pyi-stub-claim-about guide:py-type-scope | none | strong | - | - |
| F158 | P1 | Hardcoding developer-specific paths | scan:absolute-path | scan:absolute-path | strong | ARCH-22 | - |
| F159 | P1 | Executing arbitrary build hooks during casual dependency inspection | guide:read-before-run guide:importing-collecting-aren-read tool:deps guide:py-build-runs-code | none | strong | - | - |
| F160 | P1 | Ignoring subprocess failure and text encoding | note:python-facts guide:subprocess-run-raise-non guide:text-true-decodes-with | scan:ignored-error | strong | - | - |

## DOMAIN: Domain correctness and algorithms

| ID | Tier | What goes wrong | Prevent | Find and fix | Fit | Same as | What's missing |
|---|---|---|---|---|---|---|---|
| F161 | P1 | Choosing an algorithm without stating its invariants | guide:pattern-preconditions guide:algorithms guide:explicit-invariants-failure-analysis guide:algo-invariants | none | strong | - | - |
| F162 | P1 | Using inclusive bounds where exclusive bounds are required | guide:edge-inputs guide:state-assumptions guide:test-bounds | none | strong | LOGIC-04 LOGIC-20 | - |
| F163 | P1 | Mishandling duplicate values | guide:edge-inputs guide:nulls-duplicates-ties note:python-facts guide:algo-duplicates | none | strong | - | - |
| F164 | P1 | Assuming inputs are sorted | guide:pattern-preconditions guide:algo-invariants | none | strong | - | - |
| F165 | P1 | Depending on an unspecified iteration order | guide:dict-set-ordering-assumptions guide:set-order-varies-between guide:directory-listings-globs | none | strong | - | - |
| F166 | P1 | Using floating point for exact decimal rules | scan:float-money guide:decimal-money-rounding-mode | scan:float-money | strong | LOGIC-35 | - |
| F167 | P1 | Ignoring NaN infinity and signed zero | guide:float-comparison-nan-ordering note:python-facts guide:py-nan | scan:nan-comparison | strong | - | - |
| F168 | P1 | Using overflow-prone fixed-width arithmetic | guide:edge-inputs guide:integer-overflow-size-calculations guide:json-parsing-loses-large guide:py-fixed-width | none | strong | LOGIC-23 | - |
| F169 | P1 | Mixing integer and real division semantics | guide:integer-versus-real-division guide:py-division | none | strong | DATA-11 | - |
| F170 | P1 | Ignoring timezone and daylight-saving transitions | note:python-facts guide:lang-time guide:dst-boundaries guide:pytz-timezones-passed-tzinfo | scan:naive-datetime | strong | LOGIC-36 | - |
| F171 | P1 | Using wall-clock time for elapsed durations | guide:py-monotonic | scan:wall-clock-wait | strong | - | - |
| F172 | P1 | Assuming byte count equals character count | guide:bytes-versus-text-encodings guide:include-unicode guide:py-text-length | none | strong | - | - |
| F173 | P1 | Normalizing identifiers without domain rules | guide:unicode-normalization-casefolding guide:py-normalize-ids | none | strong | - | - |
| F174 | P1 | Silently truncating mismatched sequences | guide:py-zip-strict | none | strong | - | - |
| F175 | P1 | Applying non-associative operations as if reorderable | guide:output-equivalent guide:rewrites-keep guide:dist-reorder | tool:golden | strong | - | - |
| F176 | P1 | Using unstable tie-breaking | guide:sort-stability-ties guide:nulls-duplicates-ties | none | strong | - | - |
| F177 | P1 | Treating partial results as complete results | guide:failure-visible guide:rel-partial-result | none | strong | - | - |
| F178 | P1 | Applying a transformation twice on retries | guide:retries note:security-facts | scan:handrolled-retry | strong | ERR-13 | - |
| F179 | P1 | Using random behavior without controllable reproducibility | guide:freeze-time-seed-randomness guide:unseeded-randomness guide:py-seeded | scan:test-nondeterministic | strong | TEST-13 | - |
| F180 | P1 | Validating fields individually but missing cross-field rules | guide:make-invalid-states-hard guide:cross-field | none | strong | - | - |

## ORACLE: Test objectives, oracles and coverage

| ID | Tier | What goes wrong | Prevent | Find and fix | Fit | Same as | What's missing |
|---|---|---|---|---|---|---|---|
| F181 | P0 | Skipping meaningful tests for changed risky behavior | gate:no-test-changed guide:one-small-test-new guide:negative-integration-tests | gate:no-test-changed query:tests scan:module-untested | strong | - | - |
| F182 | P1 | Writing tests that mirror the implementation | guide:expected-from-requirement guide:test-restates-implementation-proves | none | strong | TEST-01 | - |
| F183 | P1 | Writing assertions that cannot fail meaningfully | note:scan-on-edit hook:scan-at-stop note:python-facts guide:assertions-fail | scan:test-tautology scan:test-weak-assert tool:mutate | strong | TEST-09 TEST-10 TEST-12 | - |
| F184 | P1 | Checking only that a function returns | note:scan-on-edit hook:scan-at-stop guide:assert-result-none-pass | scan:test-no-assert scan:test-weak-assert tool:mutate | strong | TEST-06 TEST-07 TEST-19 | - |
| F185 | P1 | Hardcoding outputs from the current buggy implementation | guide:expected-from-requirement gate:expected-value-rewritten | gate:expected-value-rewritten | strong | TEST-01 GAME-03 | - |
| F186 | P1 | Testing only happy paths | guide:edge-inputs gate:judgment guide:negative-integration-tests | tool:mutate | strong | LOGIC-09 TEST-37 | - |
| F187 | P1 | Omitting boundary and empty cases | guide:edge-inputs gate:judgment guide:test-bounds | none | strong | LOGIC-07 | - |
| F188 | P1 | Missing a regression test for the original symptom | guide:critical-test-fails guide:reproduce-first note:edit-before-reproducing gate:no-test-changed | none | strong | - | - |
| F189 | P1 | Confusing coverage percentage with assertion quality | guide:score-not-proof guide:shows-what-never-ran | tool:mutate | strong | TEST-02 TEST-11 | - |
| F190 | P1 | Ignoring state transitions | guide:contracts-between guide:test-transitions | none | strong | - | - |
| F191 | P1 | Not testing invariants across many inputs | guide:rule-across-many-inputs guide:hypothesis-given-real-property | none | strong | - | - |
| F192 | P1 | Skipping parser and deserializer adversarial inputs | guide:parsers-untrusted-input guide:edge-inputs | none | strong | - | - |
| F193 | P1 | Omitting compatibility tests for public changes | guide:compat-deliberate gate:caller-not-updated gate:removed-still-named guide:test-compat | query:api | strong | - | - |
| F194 | P1 | Testing side effects only through mocked call counts | guide:mocks-limit guide:test-only-asserts-mock | scan:test-overmocked tool:mutate | strong | TEST-03 | - |
| F195 | P1 | Ignoring nonfunctional requirements in tests | guide:know-done guide:run-at-size guide:load-tests-against-stated | tool:bench | strong | - | - |
| F196 | P1 | Using snapshots without reviewing semantic changes | note:snapshots gate:snapshots-rewritten guide:honest-checks | gate:snapshots-rewritten | strong | TEST-35 | - |
| F197 | P1 | Failing to map requirements to checks | guide:know-done tool:goal gate:judgment | tool:goal | strong | - | - |
| F198 | P1 | Claiming complete verification from a narrow test subset | gate:wide-reach guide:project-suite gate:judgment guide:thorough-claim-needs-make | query:impact query:tests | strong | TEST-20 TEST-23 | - |
| F199 | P2 | Adding exhaustive tests for trivial mechanical edits | guide:no-test-count gate:size guide:redundant-tests-trivial-code | gate:size | strong | TEST-16 TEST-17 | - |
| F200 | P1 | Treating generated tests as independent evidence automatically | guide:project-suite guide:code-test-written-one | none | strong | - | - |

## REAL: Test realism, isolation and reliability

| ID | Tier | What goes wrong | Prevent | Find and fix | Fit | Same as | What's missing |
|---|---|---|---|---|---|---|---|
| F201 | P1 | Mocking the entire system under test | guide:mocks-limit | scan:test-mocks-subject scan:test-overmocked scan:mock-of-subject | strong | TEST-04 | - |
| F202 | P1 | Using mocks with impossible behavior | guide:mocks-limit | none | strong | - | - |
| F203 | P1 | Testing a different database engine from production | guide:mocks-limit guide:sqlite-prove-postgres guide:test-same-engine | none | strong | - | - |
| F204 | P1 | Using only tiny uniform fixtures | guide:edge-inputs guide:sample-data-usually-hides guide:run-at-size guide:fixtures-are-as-large | tool:mutate | strong | TEST-37 | - |
| F205 | P1 | Letting tests depend on execution order | guide:both-create-order-dependence guide:def-varying-result guide:test-isolation | tool:mutate | strong | - | - |
| F206 | P1 | Sharing mutable fixtures across unrelated tests | guide:fixtures-share-mutable-state guide:test-isolation | none | strong | - | - |
| F207 | P1 | Using real time sleeps for synchronization | guide:honest-checks guide:poll-deadline-rather-than | scan:test-sleep | strong | PERF-24 | - |
| F208 | P1 | Using randomness without preserving failing inputs | guide:seed-randomness guide:property-based-tests guide:py-seeded | scan:test-nondeterministic scan:unseeded-random-test | strong | - | - |
| F209 | P1 | Mocking authorization to always allow access | guide:edge-inputs guide:mocks-limit guide:sec-second-tenant | tool:mutate | strong | - | - |
| F210 | P0 | Running tests against production services or data | guide:synthetic-data-tests-unless guide:before-destructive note:tests-on-production note:load-test-live | none | strong | - | - |
| F211 | P1 | Leaking background tasks between tests | guide:keep-references-tasks-create note:python-facts note:leaked-work guide:a-test-cancels-and-awaits | scan:dropped-task tool:mutate | strong | - | - |
| F212 | P1 | Failing to await asynchronous assertions or work | note:scan-on-edit guide:coroutine-was-never-awaited | scan:missing-await scan:async-foreach | strong | PERF-12 | - |
| F213 | P1 | Reusing fixed ports or filenames in parallel tests | guide:each-worker-gets-own guide:worktrees-isolate-files-databases | scan:fixed-test-resource | strong | - | - |
| F214 | P1 | Leaving network calls uncontrolled in unit tests | guide:mock-at-outer-boundary | scan:network-in-unit-test | strong | - | - |
| F215 | P1 | Using permissive mocks that accept invalid signatures | note:python-facts guide:accepts-any-method-arguments | scan:mock-assert-typo | strong | - | - |
| F216 | P1 | Hiding failing tests behind skips or expected failures | hook:weakened-check guide:honest-checks guide:pre-existing-named | scan:test-skipped scan:test-focused query:markers gate:test-weakened | strong | GAME-05 GAME-07 | - |
| F217 | P1 | Rerunning flaky tests until they pass | guide:def-varying-result guide:rerunning-until-green | none | strong | - | - |
| F218 | P1 | Making fixtures more complex than the feature | guide:quarter-size guide:fixtures-are-as-large | gate:size | strong | TEST-16 | - |
| F219 | P1 | Not verifying teardown on failure paths | guide:reliability guide:failure-injection guide:test-cleanup-after-failure | scan:resource-no-context | strong | - | - |
| F220 | P1 | Failing to distinguish test-environment failure from product failure | guide:passing-suites guide:pre-existing-named guide:evidence-status guide:def-never-started | gate:judgment | strong | - | - |

## VERIFY: Debugging, review and truthful verification

| ID | Tier | What goes wrong | Prevent | Find and fix | Fit | Same as | What's missing |
|---|---|---|---|---|---|---|---|
| F221 | P0 | Claiming tests passed without executing them | hook:pass-claim hook:check-after-edit hook:test-count | tool:goal | strong | REPORT-01 | - |
| F222 | P0 | Ignoring a failing exit code or partial tool output | hook:failure-unmentioned note:failed-streak note:repeated-failure guide:passing-suites guide:pipe-hides-exit-status | tool:goal | strong | LOOP-07 REPORT-03 TEST-18 | - |
| F223 | P1 | Reusing test evidence from before the final edit | hook:check-after-edit guide:evidence-stale | tool:goal | strong | TEST-33 REPORT-20 | - |
| F224 | P1 | Testing the wrong branch checkout or artifact | guide:passing-suites guide:def-checks-elsewhere guide:which-copy-of-the-code-ran | query:commands gate:stale-base | strong | TEST-34 | - |
| F225 | P1 | Interpreting zero collected tests as success | hook:pass-claim hook:failure-unmentioned guide:passing-suites guide:def-ran-tests | tool:goal tool:mutate | strong | - | - |
| F226 | P1 | Skipping self-review after implementation | hook:review-required gate:judgment guide:maintainer-read | tool:gate | strong | SCOPE-18 | - |
| F227 | P1 | Reviewing only edited lines | gate:wide-reach gate:caller-not-updated gate:usual-partner guide:every-caller-data-path guide:read-callers-what-changed | query:impact tool:gate | strong | - | - |
| F228 | P1 | Debugging by making many simultaneous changes | guide:back-out note:failed-streak guide:change-one-thing-per guide:one-change-per-attempt | none | strong | - | - |
| F229 | P1 | Failing to reproduce the bug before repair | guide:reproduce-first note:edit-before-reproducing guide:cause-established | guide:critical-test-fails | strong | TEST-26 SCOPE-23 | - |
| F230 | P1 | Ignoring stack traces and detailed errors | guide:earliest-error note:failed-streak note:repeated-failure | guide:earliest-error | strong | LOOP-07 | - |
| F231 | P1 | Assuming a reviewer agent is an oracle | guide:clean-review-weak guide:reviewer-brief guide:delegate-claims | tool:mutate | strong | REPORT-25 | - |
| F232 | P1 | Accepting review findings without verification | guide:suggestions-tested guide:review-findings guide:verify-before-calling | tool:golden | strong | LOOP-26 | - |
| F233 | P1 | Using the implementer's summary as the review input | guide:reviewer-brief hook:review-required guide:treat-author-claims | none | strong | LOOP-28 | - |
| F234 | P1 | Claiming a performance gain from intuition | hook:speedup-claim guide:numbers-from-run | tool:bench | strong | PERF-10 | - |
| F235 | P1 | Claiming security from a functional green suite | note:security-facts hook:review-required guide:appear-only-their-scope note:security-claim-unchecked | tool:scan tool:tools | strong | SEC-01 | - |
| F236 | P1 | Failing to inspect accidental changes | hook:side-effects-named gate:format-churn gate:scope guide:surgical | tool:gate scan:debug-leftover scan:scratch-file | strong | SCOPE-07 BUILD-11 BUILD-22 | - |
| F237 | P1 | Ignoring warnings that change correctness | guide:passing-suites guide:formatter-ran guide:turns-collection-warnings-into guide:warnings-matter | tool:tools | strong | TEST-32 | - |
| F238 | P1 | Reporting partial implementation as complete | hook:stop-short guide:no-silent-narrowing note:scan-on-edit hook:scan-at-stop note:done-with-goal-unverified | tool:goal scan:stub-body scan:placeholder-comment gate:judgment | strong | LOGIC-14 SCOPE-29 REPORT-02 | - |
| F239 | P1 | Failing to critique simplification opportunities | guide:maintainer-read guide:quarter-size guide:simpler-design gate:judgment | gate:complexity-rose scan:single-impl-abstraction scan:pass-through scan:pattern-one-product | strong | TEAM-26 | - |
| F240 | P1 | Not checking the actual user-visible workflow | guide:real-entry-point guide:passing-not-requirement gate:judgment | query:entry | strong | BUILD-04 TEAM-38 | - |

## APPSEC: Application security and trust boundaries

| ID | Tier | What goes wrong | Prevent | Find and fix | Fit | Same as | What's missing |
|---|---|---|---|---|---|---|---|
| F241 | P0 | Omitting authorization on protected operations | note:security-facts hook:review-required guide:same-access-path | scan:missing-auth query:boundaries scan:mass-assignment | strong | SEC-19 SEC-23 | - |
| F242 | P0 | Trusting client-supplied object ownership | note:security-facts hook:review-required guide:same-access-path scan:mass-assignment guide:sec-second-tenant | query:boundaries scan:mass-assignment scan:owner-from-request scan:object-not-scoped scan:unscoped-lookup | strong | SEC-21 SEC-26 | - |
| F243 | P0 | Applying tenant filters inconsistently | guide:same-access-path hook:review-required note:security-facts guide:sec-second-tenant | query:boundaries scan:object-not-scoped scan:cache-reads-user scan:unscoped-lookup | strong | SEC-20 SEC-22 SEC-24 | - |
| F244 | P0 | Interpolating untrusted values into SQL | note:scan-on-edit hook:scan-at-stop guide:dynamic-identifiers-need-allow | scan:sql-injection | strong | DATA-01 DATA-02 | - |
| F245 | P0 | Passing untrusted strings into a shell | note:scan-on-edit hook:scan-at-stop guide:conditional-security | scan:shell-injection scan:ci-script-injection | strong | SEC-04 SEC-08 | - |
| F246 | P0 | Deserializing untrusted executable formats | note:scan-on-edit hook:scan-at-stop guide:conditional-security | scan:unsafe-deserialize query:boundaries | strong | - | - |
| F247 | P0 | Fetching arbitrary user-provided URLs | guide:conditional-security | scan:ssrf | strong | SEC-12 | - |
| F248 | P0 | Joining untrusted paths without containment checks | guide:conditional-security guide:resolve-relative | scan:path-traversal scan:weak-path-check scan:unsafe-extract | strong | SEC-05 SEC-06 | - |
| F249 | P0 | Rendering untrusted content as executable markup | guide:conditional-security guide:escape-context | scan:xss-sink | strong | SEC-02 | - |
| F250 | P0 | Omitting CSRF protection where browser credentials are automatic | guide:conditional-security guide:sec-csrf | scan:disabled-control tool:tools scan:state-change-on-get | strong | SEC-34 | - |
| F251 | P0 | Using permissive credentialed CORS settings | scan:permissive-cors guide:sec-cors-credentials | scan:permissive-cors | strong | SEC-39 | - |
| F252 | P0 | Storing passwords or signing secrets insecurely | hook:secret-edit guide:established-libraries guide:argon2-scrypt-bcrypt | scan:weak-password-hash scan:hardcoded-secret scan:secret-in-client-bundle query:leaks scan:key-in-source | strong | SEC-14 SEC-46 SEC-50 | - |
| F253 | P0 | Disabling TLS certificate verification | note:scan-on-edit hook:scan-at-stop | scan:tls-disabled | strong | SEC-17 | - |
| F254 | P0 | Accepting unsigned or replayable webhooks | hook:review-required note:security-facts guide:retries guide:sec-webhooks | scan:secret-compare query:boundaries scan:webhook-unverified | strong | - | - |
| F255 | P0 | Treating file extensions as sufficient upload validation | guide:conditional-security guide:sec-uploads | scan:unbounded-upload scan:upload-no-limit scan:upload-in-webroot scan:upload-extension-only | strong | - | - |
| F256 | P1 | Omitting abuse limits on expensive or sensitive endpoints | guide:resource-use scan:login-no-rate-limit guide:sec-paid-routes | scan:login-no-rate-limit query:boundaries | strong | SEC-32 SEC-33 | - |
| F257 | P0 | Returning debug details and secrets in errors | guide:logs-errors guide:errors-should-actionable-without | scan:debug-exposed scan:error-details-exposed | strong | - | - |
| F258 | P0 | Failing open when authorization infrastructure errors | note:scan-on-edit hook:scan-at-stop guide:fail-closed | scan:fail-open | strong | - | - |
| F259 | P0 | Using predictable tokens for security decisions | guide:established-libraries | scan:insecure-random | strong | SEC-16 | - |
| F260 | P0 | Leaving session revocation and privilege changes ineffective | hook:review-required guide:sec-revocation | query:boundaries scan:disabled-control | strong | SEC-37 | - |

## AGENT: Agent tools, supply chain and privacy

| ID | Tier | What goes wrong | Prevent | Find and fix | Fit | Same as | What's missing |
|---|---|---|---|---|---|---|---|
| F261 | P0 | Executing instructions embedded in retrieved files or logs | note:addressed-to-agent guide:data-not-instruction guide:untrusted-content guide:relayed-task | scan:instruction-injection scan:hidden-unicode | strong | SAFE-37 SAFE-39 SAFE-45 SAFE-46 | - |
| F262 | P0 | Giving an agent broader credentials than its task requires | guide:credential-mismatch scan:agent-permission-widened guide:sec-least-access | scan:agent-permission-widened scan:ci-write-all scan:iac-wildcard-permission | strong | SCOPE-15 PIPE-28 | - |
| F263 | P0 | Reading secrets unnecessarily into model context | note:secret-read guide:secrets-kept-out hook:credential-read hook:secret-printed | none | strong | SEC-57 | - |
| F264 | P0 | Including secrets in commands logs or generated examples | hook:secret-edit hook:secret-web hook:secret-net guide:secrets-kept-out | scan:hardcoded-secret scan:sensitive-log query:leaks scan:container-secret-arg | strong | SEC-48 SEC-55 SEC-59 | - |
| F265 | P0 | Running destructive commands with unchecked paths | hook:hard-to-undo guide:before-destructive hook:variable-delete hook:unchecked-path-delete hook:make-delete-unset hook:bucket-reach | scan:shell-rm-unguarded scan:shell-unquoted-rm scan:shell-masked-failure | strong | SAFE-09 SAFE-10 SAFE-11 SAFE-12 | - |
| F266 | P0 | Executing downloaded installers without provenance checks | hook:hard-to-undo guide:read-before-run hook:download-then-run hook:download-run-later hook:download-in-build hook:wrapper-moved note:pipe-added note:install-source | scan:curl-pipe-shell scan:unverified-download-exec | strong | PIPE-31 | - |
| F267 | P0 | Trusting mutable dependency or action references indefinitely | scan:ci-unpinned-action scan:dep-unpinned scan:container-unpinned-image guide:vet-dependency | scan:ci-unpinned-action scan:container-unpinned-image scan:dep-unpinned scan:nb-unpinned-install | strong | PIPE-16 PIPE-25 BUILD-18 | - |
| F268 | P0 | Treating third-party skills and hooks as harmless text | guide:read-before-run guide:vet-dependency gate:agent-config-changed guide:sec-skills-are-code | scan:instruction-injection scan:hidden-unicode scan:agent-permission-widened gate:agent-config-changed scan:sends-credentials scan:unverified-download-exec | strong | BUILD-25 SAFE-47 | - |
| F269 | P0 | Letting untrusted pull requests run with privileged secrets | scan:ci-untrusted-checkout scan:ci-script-injection | scan:ci-untrusted-checkout scan:ci-script-injection | strong | PIPE-26 | - |
| F270 | P0 | Disabling checks to make the agent finish | hook:settings-guard hook:weakened-check note:skips-checks guide:honest-checks note:relaxes-check note:writes-suppression | scan:ci-check-disabled scan:checks-hidden-by-config scan:suppression-comment gate:config-changed gate:agent-config-changed query:markers gate:checks-relaxed | strong | GAME-31 GAME-08 PIPE-29 SAFE-23 | - |
| F271 | P0 | Using production credentials in generated test fixtures | hook:secret-edit guide:secrets-kept-out guide:synthetic-data-tests-unless | scan:live-credential-in-test scan:vcr-unfiltered scan:tests-use-production | strong | SEC-54 | - |
| F272 | P1 | Retaining sensitive data in caches or temporary artifacts | guide:secrets-kept-out guide:sec-temp-copies | scan:committed-secret-file scan:nb-sensitive-output | strong | - | - |
| F273 | P0 | Sending proprietary code to an unapproved external tool | guide:upload-proprietary-code-analysis guide:outbound-counts note:uploads-a-file note:publishes-public note:pushes-elsewhere | none | strong | - | - |
| F274 | P0 | Accepting tool results without validating their structure | guide:untrusted-content guide:validates-nothing-at-runtime guide:annotation-input-validation guide:sec-tool-output | scan:ts-double-cast scan:ts-any query:boundaries scan:tool-call-unchecked | strong | GAME-30 LOGIC-25 | - |
| F275 | P0 | Confusing suggested commands with authorized actions | guide:authorization guide:data-not-instruction guide:read-before-run guide:publish-authorized hook:hard-to-undo note:suggested-command | none | strong | - | - |
| F276 | P0 | Allowing generated code to redefine its own success gate | hook:settings-guard hook:weakened-check gate:config-changed gate:agent-config-changed note:relaxes-check | scan:test-harness-tampered scan:checks-hidden-by-config scan:ci-check-disabled gate:config-changed gate:checks-relaxed | strong | GAME-31 GAME-32 GAME-17 GAME-22 | - |
| F277 | P1 | Ignoring dependency licenses and provenance obligations | guide:vet-dependency note:dependency-facts gate:manifest-note guide:dep-health-eol | tool:deps | strong | - | - |
| F278 | P0 | Trusting cached credentials after environment switching | guide:before-destructive guide:staging-task-hold-production note:production-target hook:hard-to-undo guide:sec-least-access note:switches-identity note:ambient-target note:env-file-switch note:switched-and-changed | none | strong | SAFE-03 SAFE-08 | - |
| F279 | P1 | Leaving spawned processes or tunnels running | note:left-running | none | strong | - | - |
| F280 | P0 | Retrying ambiguous external mutations blindly | guide:retries note:security-facts guide:dist-timeout-unknown | scan:handrolled-retry scan:retry-not-idempotent | strong | ERR-13 | - |

## DATA: Persistence, SQL and data migrations

| ID | Tier | What goes wrong | Prevent | Find and fix | Fit | Same as | What's missing |
|---|---|---|---|---|---|---|---|
| F281 | P0 | Splitting an invariant across nontransactional writes | guide:reliability guide:lang-sql-transactions scan:multi-write-no-transaction | scan:multi-write-no-transaction | strong | PERF-17 | - |
| F282 | P0 | Using read-modify-write without concurrency control | scan:lost-update guide:sql-concurrent-writers | scan:lost-update | strong | PERF-16 | - |
| F283 | P0 | Relying only on application checks for uniqueness | guide:reliability guide:edge-inputs guide:rel-unique-constraint guide:sql-concurrent-writers | scan:check-then-insert | strong | - | - |
| F284 | P1 | Ignoring foreign-key and deletion semantics | guide:sql-keys-pages | none | strong | - | - |
| F285 | P1 | Assuming the default isolation level prevents all anomalies | guide:lang-sql-transactions guide:sql-concurrent-writers | scan:lost-update | strong | - | - |
| F286 | P1 | Holding transactions open during remote calls | guide:sql-concurrent-writers | none | strong | - | - |
| F287 | P1 | Using unbounded result queries | guide:bound-it | scan:unpaginated-query scan:materialize-all | strong | PERF-26 | - |
| F288 | P1 | Introducing N plus one database access | guide:find-what-grows | scan:query-in-loop | strong | PERF-01 | - |
| F289 | P1 | Adding indexes without considering access patterns | guide:read-query-plan-anything guide:sql-keys-pages | none | strong | - | - |
| F290 | P1 | Paginating mutable data with unstable ordering | guide:sql-keys-pages | none | strong | - | - |
| F291 | P0 | Running destructive schema changes without a recovery plan | scan:migration-destroys-data scan:migration-no-rollback guide:coexist guide:before-destructive hook:hard-to-undo hook:review-required | scan:migration-destroys-data scan:migration-no-rollback | strong | DATA-25 DATA-26 DATA-27 | - |
| F292 | P1 | Assuming migrations are instant on large tables | scan:migration-locks-table guide:lang-sql-transactions | scan:migration-locks-table | strong | DATA-23 DATA-24 DATA-28 | - |
| F293 | P1 | Changing schema and application versions incompatibly | guide:coexist guide:compat-deliberate guide:contracts-between guide:ship-schema-code-changes guide:sql-renames-time | scan:migration-destroys-data gate:model-no-migration | strong | DATA-25 | - |
| F294 | P0 | Writing files nonatomically when partial files are invalid | guide:write-temporary-file-rename guide:reliability | scan:nonatomic-state-write | strong | - | - |
| F295 | P0 | Acknowledging durable writes before durability is established | guide:reliability guide:failure-visible guide:rel-ack-durable | scan:unacknowledged-write scan:ack-before-durable scan:durability-disabled | strong | - | - |
| F296 | P1 | Ignoring connection-pool limits and lifecycle | guide:lang-resources guide:connection-pools | scan:resource-no-context scan:go-defer-in-loop scan:client-per-call | strong | ERR-14 | - |
| F297 | P1 | Using floating or inconsistent timestamp precision in storage | guide:edge-inputs guide:sql-renames-time | none | strong | - | - |
| F298 | P1 | Failing to handle serialization or deadlock retries | guide:sql-concurrent-writers | none | strong | - | - |
| F299 | P0 | Restoring backups without testing restoration | guide:before-destructive note:production-target guide:rel-backup-restore hook:restore-over-production note:backups-unrestored | none | strong | - | - |
| F300 | P1 | Ignoring schema evolution in serialized persistent objects | guide:compat-deliberate guide:contracts-between guide:stored-data | query:find | strong | DATA-30 | - |

## ASYNC: Asynchronous execution and concurrency

| ID | Tier | What goes wrong | Prevent | Find and fix | Fit | Same as | What's missing |
|---|---|---|---|---|---|---|---|
| F301 | P1 | Blocking the event loop with synchronous I/O | note:scan-on-edit hook:scan-at-stop guide:anything-blocking-cpu-heavy guide:do-blocking-i-o | scan:blocking-in-async | strong | PERF-11 | - |
| F302 | P1 | Launching unbounded concurrent tasks | guide:bound-it guide:semaphore-bounds-work-flight guide:mapping-large-list-promises guide:unbounded-goroutine-creation-leak | scan:unbounded-concurrency | strong | PERF-15 | - |
| F303 | P1 | Swallowing cancellation | note:python-facts guide:must-propagate-catching-log guide:also-intercepts-cancellation-interpreter guide:restore-interrupt-status guide:rethrow guide:dropping-future-cancellation guide:test-cancellation-directly | scan:swallowed-cancellation scan:bare-except scan:swallowed-exception | strong | - | - |
| F304 | P1 | Spawning tasks without lifecycle ownership | note:python-facts guide:keep-references-tasks-create-2 guide:every-goroutine-needs-way guide:structured-concurrency-avoid | scan:dropped-task scan:structured-concurrency-escape scan:effect-no-cleanup | strong | PERF-14 PERF-21 | - |
| F305 | P0 | Updating shared state without synchronization | note:language-skill gate:judgment guide:lang-race guide:mutable-state-shared-across guide:tsan-concurrent-code guide:py-compound-race note:race-detector-not-run | scan:lost-update scan:process-local-state scan:unsynchronized-state scan:rebuilt-while-shared | strong | PERF-16 PERF-18 PERF-19 | - |
| F306 | P1 | Acquiring locks in inconsistent order | guide:tsan-concurrent-code | scan:lock-order | strong | PERF-20 | - |
| F307 | P1 | Awaiting unknown work while holding a lock | guide:guard-held-across guide:dont-await-while-holding | tool:tools scan:await-under-thread-lock | strong | PERF-20 | - |
| F308 | P1 | Assuming the GIL makes compound operations safe | guide:state-universal-gil-rules guide:mutable-state-shared-across guide:py-compound-race | none | strong | PERF-18 | - |
| F309 | P1 | Choosing threads for CPU parallelism without measuring | guide:choose-async-threads-processes guide:find-what-binds | tool:bench | strong | - | - |
| F310 | P1 | Passing unpicklable state into process workers | guide:arguments-need-picklable guide:py-process-pools | scan:process-pool-unpicklable | strong | - | - |
| F311 | P1 | Ignoring process startup and import requirements | guide:default-start-method guide:one-way-deps guide:py-process-pools | scan:import-time-io | strong | PERF-27 | - |
| F312 | P1 | Nesting event-loop runners in active loops | guide:py-nested-loop | scan:nested-event-loop | strong | - | - |
| F313 | P1 | Timing out a wait while underlying work continues | note:python-facts guide:cancels-wait-thread guide:rejects-early-without-cancelling guide:rel-timeout-continues | none | strong | - | - |
| F314 | P1 | Losing exceptions from background futures | note:python-facts guide:keeps-exception-future guide:unawaited-promise-loses-errors | scan:dropped-task scan:async-foreach | strong | PERF-14 PERF-22 | - |
| F315 | P1 | Sharing non-thread-safe clients or sessions | guide:mutable-state-shared-across guide:py-client-threads | none | strong | PERF-18 | - |
| F316 | P1 | Failing to propagate request context into workers | guide:interacts-pools-virtual-threads guide:respect-cancellation guide:py-contextvars | none | strong | - | - |
| F317 | P1 | Shutting down executors before dependent work completes | guide:reliability guide:py-shutdown | none | strong | - | - |
| F318 | P1 | Submitting work that waits on the same exhausted pool | guide:layers guide:py-pool-self-wait guide:jvm-pool-self-wait | none | strong | PERF-20 | - |
| F319 | P1 | Acknowledging queued work before it succeeds | guide:workers-die-mid-task note:security-facts guide:rel-ack-durable | none | strong | - | - |
| F320 | P1 | Retrying after cancellation or deadline expiry | guide:retries guide:must-propagate-catching-log guide:rel-backoff | scan:handrolled-retry scan:swallowed-cancellation | strong | ERR-13 | - |

## DIST: Distributed systems and resilience

| ID | Tier | What goes wrong | Prevent | Find and fix | Fit | Same as | What's missing |
|---|---|---|---|---|---|---|---|
| F321 | P1 | Omitting network timeouts | note:python-facts guide:give-external-calls-deadlines guide:default-client-timeout | scan:missing-timeout | strong | ERR-12 | - |
| F322 | P1 | Giving each nested call a fresh full timeout | guide:respect-cancellation guide:bound-it guide:rel-one-deadline | none | strong | - | - |
| F323 | P1 | Retrying without backoff or jitter | guide:examine-skew-stragglers-retry guide:rel-backoff | scan:handrolled-retry | strong | ERR-13 | - |
| F324 | P0 | Retrying non-idempotent operations without protection | guide:retries note:security-facts | scan:handrolled-retry scan:retry-not-idempotent | strong | ERR-13 | - |
| F325 | P1 | Stacking retries across every service layer | guide:examine-skew-stragglers-retry guide:rel-one-layer | scan:handrolled-retry | strong | - | - |
| F326 | P1 | Ignoring overload and admission control | guide:bound-it guide:resource-use guide:load-tests-against-stated | none | strong | - | - |
| F327 | P1 | Assuming messages arrive exactly once | guide:assume-messages-arrive-more guide:duplicate-out-order-delivery note:security-facts | none | strong | - | - |
| F328 | P1 | Assuming messages arrive in order | guide:assume-messages-arrive-more guide:duplicate-out-order-delivery note:security-facts | none | strong | - | - |
| F329 | P0 | Using distributed locks without fencing | guide:worker-loss guide:dist-fencing | scan:lock-without-fencing | strong | - | - |
| F330 | P1 | Treating network partitions as ordinary exceptions | guide:reliability guide:idempotency-partial-failure guide:dist-timeout-unknown | none | strong | - | - |
| F331 | P1 | Using wall clocks to establish distributed causality | guide:dist-clocks | none | strong | - | - |
| F332 | P1 | Using process-randomized hashes for partition routing | guide:dist-stable-hash guide:py-salted-hash | scan:salted-hash-partition | strong | - | - |
| F333 | P1 | Ignoring skewed partition keys | guide:examine-skew-stragglers-retry guide:find-what-binds guide:dist-skew | none | strong | - | - |
| F334 | P1 | Creating tasks smaller than scheduling overhead | guide:coordination-overhead guide:dist-task-size | tool:bench | strong | - | - |
| F335 | P1 | Centralizing all data or metadata at the coordinator | guide:coordination-overhead guide:dist-task-size | none | strong | - | - |
| F336 | P0 | Checkpointing progress separately from committed side effects | guide:consider-crash-after-effect guide:retries note:security-facts guide:reliability | scan:multi-write-no-transaction scan:checkpoint-before-effect scan:ack-before-effect scan:auto-commit-before-write | strong | PERF-17 | - |
| F337 | P1 | Assuming every node has identical capabilities | guide:examine-skew-stragglers-retry guide:dist-nodes-differ | none | strong | - | - |
| F338 | P1 | Confusing liveness with readiness | guide:dist-liveness | none | strong | - | - |
| F339 | P1 | Failing to drain work during deployment | guide:reliability guide:rel-sigterm | none | strong | - | - |
| F340 | P1 | Testing only all-nodes-healthy execution | guide:failure-injection-timeouts-partial-2 guide:edge-inputs | none | strong | LOGIC-09 | - |

## PERF: Performance, algorithms and measurement

| ID | Tier | What goes wrong | Prevent | Find and fix | Fit | Same as | What's missing |
|---|---|---|---|---|---|---|---|
| F341 | P1 | Optimizing without identifying the bottleneck | guide:find-what-binds note:performance-facts | tool:bench | strong | LOGIC-46 | - |
| F342 | P1 | Using asymptotic complexity alone to predict speed | guide:algorithms guide:algorithmic-gain-establish-end guide:static-complexity-reasoning | tool:bench | strong | - | - |
| F343 | P1 | Introducing quadratic scans in growing workloads | guide:algorithms guide:find-what-grows | scan:nested-same-collection scan:list-membership-in-loop scan:sort-in-loop tool:bench | strong | PERF-03 | - |
| F344 | P1 | Sorting when only membership or grouping is needed | guide:find-what-grows | tool:bench | strong | - | - |
| F345 | P1 | Using linear membership checks repeatedly | guide:algorithms | scan:list-membership-in-loop | strong | PERF-03 | - |
| F346 | P1 | Repeating expensive parsing or compilation in hot loops | guide:find-what-grows | scan:regex-compile-loop tool:bench | strong | - | - |
| F347 | P1 | Performing remote I/O one item at a time | guide:find-what-grows | scan:query-in-loop scan:remote-get-in-loop scan:io-in-loop | strong | PERF-01 PERF-02 | - |
| F348 | P1 | Converting representations repeatedly | guide:find-what-grows guide:vectorize-where-conversion-cost guide:algorithmic-gain-establish-end | scan:transfer-in-loop tool:bench | strong | - | - |
| F349 | P1 | Vectorizing without preserving semantics | guide:output-equivalent guide:rewrites-keep guide:preserve-behavior-old-shape | tool:golden | strong | DATA-34 | - |
| F350 | P1 | Adding caching without an invalidation contract | guide:cache-not-free | none | strong | PERF-09 | - |
| F351 | P1 | Caching across user or tenant boundaries | guide:same-access-path guide:key-a-cache-by-everything | query:grep scan:cache-reads-user | strong | SEC-24 | - |
| F352 | P1 | Benchmarking only warm steady-state execution | guide:cold-warm-state | tool:bench | strong | - | - |
| F353 | P1 | Reporting averages while tails dominate user experience | guide:percentiles-averages-alone | none | strong | - | - |
| F354 | P1 | Changing benchmark inputs between baseline and candidate | guide:run-untouched-code-first-2 guide:change-one-thing-per hook:speedup-claim note:performance-facts | tool:bench | strong | - | - |
| F355 | P1 | Reporting offered load as completed throughput | guide:measure-completed | none | strong | - | - |
| F356 | P1 | Discarding failed or slow benchmark runs without explanation | guide:judge-against-run-run hook:failure-unmentioned guide:evidence-status guide:measure-keep-runs | tool:bench | strong | - | - |
| F357 | P1 | Ignoring total cost while improving one latency metric | guide:fix-time-alone-leave guide:memory-storage-limits-hardware note:performance-facts | tool:bench | strong | - | - |
| F358 | P1 | Parallelizing a serially constrained workload | guide:find-what-binds guide:dist-serial | tool:bench | strong | - | - |
| F359 | P2 | Adding noisy microbenchmark gates to every change | guide:run-only-depth-performance guide:judge-against-run-run guide:it-needs-to-exist | none | strong | - | - |
| F360 | P1 | Optimizing away correctness work without an equivalent guarantee | guide:safety-beats guide:output-equivalent guide:some-things-get-simplified | tool:golden | strong | PERF-29 | - |

## MEM: Memory, streaming and large datasets

| ID | Tier | What goes wrong | Prevent | Find and fix | Fit | Same as | What's missing |
|---|---|---|---|---|---|---|---|
| F361 | P1 | Materializing an entire input unnecessarily | guide:bound-it guide:materializing-input | scan:materialize-all scan:unpaginated-query tool:bench | strong | PERF-07 PERF-26 | - |
| F362 | P1 | Sizing batches only by row count | guide:bound-it guide:py-batch-bytes | tool:bench | strong | - | - |
| F363 | P1 | Keeping all outputs until the end | guide:generator-sufficient-later-stage guide:bound-it | tool:bench | strong | PERF-07 | - |
| F364 | P1 | Assuming a generator makes the whole pipeline streaming | guide:generator-sufficient-later-stage guide:find-what-grows note:performance-facts | tool:bench | strong | - | - |
| F365 | P1 | Creating unnecessary full-data copies | guide:find-what-grows guide:inspect-python-object-overhead | scan:dataframe-grow-loop tool:bench | strong | - | - |
| F366 | P1 | Assuming zero-copy conversions without checking | guide:inspect-python-object-overhead guide:py-copies | tool:bench | strong | - | - |
| F367 | P1 | Holding views that retain large backing buffers | guide:py-views-retain | tool:bench | strong | - | - |
| F368 | P1 | Using object-heavy representations for dense data | guide:inspect-python-object-overhead guide:py-dense | tool:bench | strong | - | - |
| F369 | P1 | Building an unbounded hash join or aggregation | guide:bound-it note:python-facts guide:duplicate-keys-multiplies-rows guide:py-hash-join | tool:bench | strong | PERF-07 | - |
| F370 | P1 | Repeatedly concatenating growing tables or arrays | note:scan-on-edit hook:scan-at-stop | scan:dataframe-grow-loop scan:string-concat-loop | strong | PERF-04 | - |
| F371 | P1 | Spilling without disk capacity and cleanup limits | guide:bound-it guide:find-what-grows guide:perf-spill-budget | none | strong | - | - |
| F372 | P1 | Collecting distributed results on the driver | guide:bound-it | scan:materialize-all | strong | PERF-07 | - |
| F373 | P1 | Ignoring serialization buffers in memory estimates | guide:find-what-grows guide:measure-peak-rss-just guide:perf-serialization-peak | tool:bench | strong | - | - |
| F374 | P1 | Multiplying large data copies across process workers | guide:module-level-state-exists guide:py-process-pools | none | strong | - | - |
| F375 | P1 | Using caches without size bounds | guide:cache-not-free guide:bound-it note:python-facts | scan:unbounded-cache scan:process-local-state | strong | PERF-08 | - |
| F376 | P1 | Retaining objects through callbacks traces or closures | guide:which-keeps-instances-alive note:python-facts guide:py-retained | scan:unbounded-cache scan:effect-no-cleanup | strong | - | - |
| F377 | P1 | Measuring only Python allocator memory | guide:measure-peak-rss-just | tool:bench | strong | - | - |
| F378 | P1 | Allowing producers to outrun consumers | guide:bound-it guide:bound-executor-queues-well guide:bound-thread-pools-queues | scan:unbounded-queue | strong | PERF-08 | - |
| F379 | P1 | Handling OOM by blindly retrying the same batch | guide:instead-layering-retries guide:retries guide:perf-oom-retry | scan:handrolled-retry | strong | LOGIC-46 | - |
| F380 | P1 | Testing memory only on average-shaped records | guide:run-at-size guide:edge-inputs gate:judgment guide:measure-widest | tool:bench | strong | PERF-31 | - |

## HW: Hardware, native code and accelerators

| ID | Tier | What goes wrong | Prevent | Find and fix | Fit | Same as | What's missing |
|---|---|---|---|---|---|---|---|
| F381 | P1 | Ignoring memory bandwidth and cache locality | guide:layers guide:hw-data-movement | scan:python-loop-over-array tool:bench | strong | - | - |
| F382 | P1 | Oversubscribing nested native thread pools | guide:find-what-grows guide:hw-cpu-count | scan:oversubscription | strong | - | - |
| F383 | P1 | Using host CPU count inside constrained containers | guide:hw-cpu-count guide:py-cpu-count | none | strong | - | - |
| F384 | P1 | Ignoring NUMA placement for large shared state | guide:layers guide:hw-data-movement | none | strong | - | - |
| F385 | P1 | Introducing false sharing between hot counters | guide:layers guide:hw-data-movement | none | strong | - | - |
| F386 | P0 | Mismatching native types lengths or ABI assumptions | note:language-skill guide:change-public-header-struct guide:integer-overflow-size-calculations | scan:ctypes-untyped scan:native-type-mismatch scan:ffi-layout scan:ctypes-buffer-unchecked | strong | XF-23 | - |
| F387 | P0 | Releasing native buffers while consumers still use them | note:language-skill guide:state-ownership-lifetimes-every guide:run-tests-under-asan guide:state-invariant-each | tool:tools gate:memory-safety-added scan:buffer-lifetime scan:ctypes-callback-collected | strong | PERF-28 PERF-30 | - |
| F388 | P0 | Removing bounds checks without proving safety | guide:safety-beats guide:state-invariant-each guide:run-tests-under-asan | tool:tools gate:memory-safety-added scan:unchecked-bound | strong | PERF-29 LOGIC-21 | - |
| F389 | P1 | Assuming SIMD instructions exist on all targets | guide:layers guide:hw-isa-baseline | none | strong | - | - |
| F390 | P1 | Sending tiny workloads to a GPU | guide:layers guide:find-what-binds guide:hw-gpu-fixed-cost | tool:bench | strong | - | - |
| F391 | P1 | Repeatedly copying data between host and device | guide:layers guide:hw-gpu-fixed-cost | scan:transfer-in-loop | strong | - | - |
| F392 | P1 | Timing GPU launches without synchronization | guide:hw-gpu-sync | scan:gpu-timing-unsynced | strong | - | - |
| F393 | P1 | Ignoring GPU memory limits and temporary allocations | guide:bound-it guide:layers guide:hw-device-memory guide:py-device-memory | none | strong | - | - |
| F394 | P1 | Using inefficient device memory access patterns | guide:layers | none | strong | - | - |
| F395 | P1 | Launching many tiny kernels unnecessarily | guide:layers guide:hw-gpu-fixed-cost | scan:python-loop-over-array | strong | - | - |
| F396 | P1 | Changing numerical precision without error analysis | guide:output-equivalent guide:rewrites-keep guide:hw-precision | tool:golden gate:precision-lowered | strong | DATA-34 | - |
| F397 | P1 | Recompiling identical kernels or execution plans repeatedly | guide:find-what-grows guide:hw-compile-once | scan:regex-compile-loop scan:compile-in-loop | strong | - | - |
| F398 | P1 | Benchmarking under uncontrolled thermal or power conditions | guide:judge-against-run-run guide:representative-baseline-changed-version guide:measure-alternate | tool:bench | strong | - | - |
| F399 | P1 | Choosing I/O strategies without storage characteristics | guide:layers guide:memory-storage-limits-hardware guide:hw-storage | scan:io-in-loop | strong | - | - |
| F400 | P1 | Assuming optional acceleration is always available | guide:layers guide:hw-fallback | none | strong | ARCH-26 | - |

## UX: Usability, accessibility and developer experience

| ID | Tier | What goes wrong | Prevent | Find and fix | Fit | Same as | What's missing |
|---|---|---|---|---|---|---|---|
| F401 | P1 | Building controls that do not complete the user journey | guide:real-entry-point guide:passing-not-requirement gate:new-unused | scan:unreferenced-def query:entry scan:dead-control | strong | XF-16 LOGIC-40 | - |
| F402 | P1 | Showing generic failure messages without a recovery action | guide:errors-should-actionable-without | scan:opaque-error | strong | - | - |
| F403 | P1 | Discarding user input after validation failure | guide:passing-not-requirement guide:ui-states | none | strong | - | - |
| F404 | P1 | Leaving loading and empty states undefined | guide:passing-not-requirement guide:edge-inputs | none | strong | UI-09 | - |
| F405 | P1 | Allowing duplicate submissions during slow operations | guide:retries guide:reliability guide:edge-inputs guide:ui-states | none | strong | - | - |
| F406 | P1 | Making primary functionality inaccessible by keyboard | guide:layers guide:ui-states | scan:a11y-missing tool:tools | strong | UI-01 | - |
| F407 | P1 | Using unlabeled or nonsemantic controls | guide:layers | scan:a11y-missing scan:generic-link-text tool:tools | strong | UI-01 UI-02 UI-03 | - |
| F408 | P1 | Relying only on color to communicate state | guide:layers guide:ui-states | none | strong | UI-01 | - |
| F409 | P1 | Ignoring focus management after dynamic updates | guide:layers guide:ui-states | none | strong | UI-01 | - |
| F410 | P1 | Testing only one viewport and input method | guide:passing-not-requirement guide:edge-inputs guide:ui-states | none | strong | - | - |
| F411 | P1 | Making destructive actions easy to trigger accidentally | guide:make-common-operations-discoverable guide:product-ui | none | strong | - | - |
| F412 | P1 | Mixing machine output and progress messages in CLIs | guide:passing-not-requirement guide:cli-streams | none | strong | - | - |
| F413 | P1 | Returning success exit codes after CLI failure | guide:failure-visible note:scan-on-edit guide:cli-streams | scan:failure-reported-as-success scan:swallowed-exception scan:broad-wrap scan:ignored-error | strong | ERR-05 | - |
| F414 | P1 | Using surprising or unsafe defaults | guide:make-common-operations-discoverable guide:check-what-security-setting note:scan-on-edit | scan:tls-disabled scan:debug-exposed scan:permissive-cors scan:env-flag-truthy scan:insecure-cookie | strong | SEC-40 | - |
| F415 | P1 | Requiring knowledge of internal implementation terms | guide:vocabulary guide:product-ui | none | strong | - | - |
| F416 | P1 | Hiding expensive operations behind ordinary interactions | guide:network-call-shouldn-also guide:conversions-state-their-cost guide:mind-orm-lazy-loading guide:perf-hidden-cost | scan:query-in-loop | strong | - | - |
| F417 | P1 | Ignoring localization and regional formatting | guide:edge-inputs guide:locale-dependent-sorting guide:product-ui | none | strong | - | - |
| F418 | P1 | Providing examples that omit essential setup | guide:run-each-command-snippet guide:examples-public-documentation-should | tool:docs | strong | - | - |
| F419 | P1 | Making recovery require restarting the whole workflow | guide:reliability guide:atomic-replacement guide:rel-resume | none | strong | - | - |
| F420 | P2 | Adding excessive options to the main workflow | guide:it-needs-to-exist guide:new-structure guide:avoid-parameter-soup | scan:unused-option scan:many-params scan:flag-params | strong | - | - |

## LANG: Cross-language correctness and conventions

| ID | Tier | What goes wrong | Prevent | Find and fix | Fit | Same as | What's missing |
|---|---|---|---|---|---|---|---|
| F421 | P1 | Treating TypeScript types as external-data validation | note:language-skill guide:types-erased | scan:ts-double-cast scan:ts-any | strong | GAME-30 | - |
| F422 | P1 | Using async callbacks in APIs that do not await them | note:scan-on-edit hook:scan-at-stop guide:foreach-await guide:ts-async-predicates | scan:async-foreach scan:async-predicate | strong | PERF-12 | - |
| F423 | P1 | Ignoring React effect cleanup and dependencies | note:language-skill guide:useeffect-missing-dependencies-cleanup | scan:effect-no-cleanup tool:tools | strong | UI-06 | - |
| F424 | P1 | Allowing stale frontend requests to overwrite newer state | guide:abortcontroller-cancellation guide:ts-stale-response | none | strong | - | - |
| F425 | P1 | Using JavaScript numbers for integers beyond safe precision | note:language-skill guide:json-parsing-loses-large | none | strong | - | - |
| F426 | P0 | Merging untrusted objects into prototypes or configuration | guide:validate-at-trust-boundaries guide:ts-prototype | scan:mass-assignment scan:prototype-pollution | strong | - | - |
| F427 | P1 | Using Rust unwrap or expect on recoverable external failures | note:language-skill guide:unwrap-expect-library-request | scan:panic-in-library | strong | - | - |
| F428 | P1 | Cloning large Rust structures to avoid ownership design | note:language-skill guide:clone-appease-borrow-checker | none | strong | - | - |
| F429 | P0 | Introducing Rust unsafe without documented invariants | note:language-skill guide:state-invariant-each-unsafe guide:native-unsafe-code | scan:unsafe-undocumented gate:memory-safety-added | strong | - | - |
| F430 | P1 | Blocking a Rust async executor with CPU or sync I/O work | note:language-skill guide:hold-blocking-lock-do | none | strong | PERF-11 | - |
| F431 | P1 | Leaking Go goroutines through abandoned channels | note:language-skill guide:every-goroutine-needs-way guide:closing-channels-sender-job | none | strong | PERF-21 | - |
| F432 | P1 | Ignoring Go error returns | note:language-skill guide:handle-every-returned-error | scan:ignored-error tool:tools | strong | ERR-01 | - |
| F433 | P1 | Using JVM resources without deterministic closure | guide:lang-resources note:language-skill | none | strong | ERR-14 | - |
| F434 | P1 | Violating equality and hash contracts in JVM domain objects | guide:jvm-equals-hash | scan:equals-without-hashcode | strong | - | - |
| F435 | P0 | Managing C++ resources with ambiguous ownership | note:language-skill guide:state-ownership-lifetimes-every | scan:raw-ownership | strong | - | - |
| F436 | P0 | Relying on undefined C or C++ behavior for speed | note:language-skill guide:safety-beats guide:uninitialized-reads-make-test | gate:memory-safety-added scan:undefined-behavior | strong | PERF-29 | - |
| F437 | P0 | Building shell commands through unsafe string concatenation | note:scan-on-edit hook:scan-at-stop guide:conditional-security guide:lang-shell | scan:shell-injection scan:dynamic-eval | strong | SEC-04 | - |
| F438 | P1 | Ignoring shell pipeline failure semantics | guide:lang-shell guide:piping-also-hides-real | scan:shell-no-strict scan:shell-masked-failure scan:ignored-error | strong | SAFE-12 | - |
| F439 | P1 | Copying syntax and conventions across incompatible languages | note:language-skill guide:translate-patterns-from-another | scan:convention-mismatch tool:tools | strong | LOGIC-37 BUILD-30 | - |
| F440 | P1 | Assuming identical encoding newline and integer behavior across languages | guide:contracts-between guide:edge-inputs guide:integer-precision-across-languages guide:json-parsing-loses-large guide:cross-language-boundary | none | strong | LOGIC-37 | - |

## TEAM: Multi-agent coordination and shared work

| ID | Tier | What goes wrong | Prevent | Find and fix | Fit | Same as | What's missing |
|---|---|---|---|---|---|---|---|
| F441 | P1 | Using more agents without independent work to give them | guide:delegation-choice guide:dont-split guide:spawning-better-answer-help | tool:partition tool:map | strong | - | - |
| F442 | P1 | Underdelegating large independent investigations | guide:delegation-choice guide:one-reader-per-5 | tool:partition tool:map | strong | - | - |
| F443 | P1 | Assigning overlapping ownership of the same files | tool:coord guide:shared-tree guide:writers-limit | tool:partition tool:coord | strong | TEAM-01 TEAM-08 | - |
| F444 | P1 | Delegating without a shared interface contract | guide:contracts-first guide:delegation-brief tool:design note:design-decision | tool:design | strong | TEAM-04 TEAM-07 | - |
| F445 | P1 | Giving subagents vague goals | guide:delegation-brief guide:occam-delegation-guidance-at | none | strong | TEAM-14 | - |
| F446 | P1 | Sending every agent the entire project history | guide:delegation-brief guide:pass-conclusions | none | strong | - | - |
| F447 | P0 | Letting one agent revert another's uncommitted work | hook:git-guard guide:shared-tree guide:check-tree-first note:discards-uncommitted note:uncommitted-overwrite | tool:coord | strong | SAFE-17 SAFE-18 SAFE-19 TEAM-02 | - |
| F448 | P1 | Assuming separate worktrees isolate external resources | guide:worktrees-isolate-files-databases-2 guide:team-shared-machine | none | strong | - | - |
| F449 | P1 | Failing to track base revisions | gate:stale-base guide:handoff guide:check-what-new-worktree | gate:stale-base tool:coord | strong | TEAM-20 LOC-13 | - |
| F450 | P1 | Treating a clean textual merge as semantic correctness | guide:delegate-claims guide:combined-behavior guide:contracts-first guide:team-integrate-early | tool:design query:impact | strong | TEAM-04 | - |
| F451 | P1 | Trusting subagent completion messages without inspection | guide:delegate-claims guide:evidence-status guide:worker-findings-claims | tool:gate | strong | TEAM-05 REPORT-08 | - |
| F452 | P1 | Delegating the critical path and then waiting idly | guide:delegation-choice guide:team-critical-path | none | strong | - | - |
| F453 | P1 | Letting subagents spawn recursively without budget | guide:delegation-brief guide:bound-long-runs | none | strong | - | - |
| F454 | P1 | Using many reviewers with the same assumptions | guide:clean-review-weak guide:reviewer-brief guide:team-reviewers-differ | none | strong | - | - |
| F455 | P1 | Failing to broadcast changed requirements | guide:notify-affected-collaborators-interface guide:decisions-in-a-file tool:design guide:team-broadcast | none | strong | - | - |
| F456 | P1 | Editing shared dependency manifests concurrently | guide:avoid-simultaneous-writes-one tool:coord | tool:coord | strong | TEAM-09 | - |
| F457 | P1 | Leaving completed or obsolete agents running | guide:delegate-claims guide:team-broadcast | none | strong | - | - |
| F458 | P1 | Integrating every branch only at the end | guide:delegate-claims guide:complete-slices guide:finish-check-one-slice guide:team-integrate-early | none | strong | - | - |
| F459 | P1 | Ignoring total resource contention across agents | guide:delegation-choice guide:delegation-brief guide:worktrees-isolate-files-databases-2 guide:team-shared-machine | tool:partition | strong | - | - |
| F460 | P1 | Losing decisions in agent-to-agent messages | guide:decisions-in-a-file tool:design guide:handoff | tool:design | strong | TEAM-15 | - |

## SHIP: CI, delivery, deployment and operations

| ID | Tier | What goes wrong | Prevent | Find and fix | Fit | Same as | What's missing |
|---|---|---|---|---|---|---|---|
| F461 | P1 | Running checks locally that differ from CI | guide:contracts-known guide:passing-suites guide:rel-run-what-ci-runs | query:commands | strong | - | - |
| F462 | P1 | Misconfiguring path filters or job dependencies | guide:compat-deliberate guide:rel-run-what-ci-runs | tool:tools scan:ci-check-disabled | strong | PIPE-23 | - |
| F463 | P0 | Ignoring failed required checks during release | hook:failure-unmentioned note:skips-checks note:push-default guide:publish-authorized guide:rel-required-checks | none | strong | TEAM-21 SAFE-21 | - |
| F464 | P1 | Publishing an artifact different from the tested artifact | guide:passing-not-requirement guide:test-built-artifact-clean guide:packaging-affected-exercise-built guide:rel-ship-tested | none | strong | - | - |
| F465 | P1 | Relying on undeclared build inputs | gate:crosses-boundary gate:env-var-undeclared | scan:undeclared-dependency tool:deps scan:absolute-path | strong | ARCH-08 | - |
| F466 | P1 | Omitting a production-mode smoke test | guide:passing-not-requirement guide:real-entry-point gate:env-var-undeclared guide:rel-prod-smoke | none | strong | ARCH-26 PIPE-30 | - |
| F467 | P1 | Failing to validate configuration at startup | guide:read-environment-once-at guide:fail-closed-2 gate:env-var-undeclared guide:config-startup | scan:env-flag-truthy scan:unreferenced-setting | strong | - | - |
| F468 | P1 | Ignoring environment drift between staging and production | guide:layers guide:before-destructive guide:name-what-differs-in-production | none | strong | - | - |
| F469 | P1 | Deploying a risky change to all users immediately | guide:coexist guide:layers guide:publish-authorized guide:rel-staged | none | strong | - | - |
| F470 | P1 | Assuming rollback works with irreversible side effects | guide:coexist guide:before-destructive guide:rel-rollback | scan:migration-no-rollback scan:migration-destroys-data | strong | DATA-27 | - |
| F471 | P1 | Missing metrics for the changed behavior | guide:add-observability-at-operational guide:rel-signal | none | strong | - | - |
| F472 | P1 | Creating unbounded metric label cardinality | guide:bound-it guide:find-what-grows guide:rel-signal | none | strong | - | - |
| F473 | P1 | Logging every event at high volume synchronously | guide:noisy-logging-every-function guide:perf-log-volume | none | strong | - | - |
| F474 | P1 | Failing to connect errors across service boundaries | guide:preserve-causes-raise-from guide:handle-every-returned-error guide:rel-trace-id | none | strong | - | - |
| F475 | P1 | Ignoring process signals and termination deadlines | guide:layers guide:swallow-interruptedexception guide:rel-sigterm | none | strong | - | - |
| F476 | P1 | Sizing resources from idle behavior | guide:run-at-size guide:report-how-much-headroom | tool:bench | strong | - | - |
| F477 | P1 | Omitting artifact and dependency inventory | guide:rel-ship-tested | tool:deps | strong | - | - |
| F478 | P1 | Leaving feature flags without owners or removal conditions | guide:mark-limit-request-allows guide:flag-owner | scan:unreferenced-setting | strong | - | - |
| F479 | P1 | Alerting only on internal exceptions | guide:rel-signal | none | strong | - | - |
| F480 | P1 | Finishing at deployment without checking the outcome | guide:evidence-status guide:real-entry-point guide:rel-check-outcome | none | strong | REPORT-01 | - |

## DOCS: Documentation, maintenance and agent quality controls

| ID | Tier | What goes wrong | Prevent | Find and fix | Fit | Same as | What's missing |
|---|---|---|---|---|---|---|---|
| F481 | P1 | Commenting what the syntax already says | guide:comments gate:denser | scan:narration-comment scan:comment-flood scan:ai-residue | strong | SHAPE-15 | - |
| F482 | P1 | Omitting comments for surprising invariants or workarounds | guide:comments guide:under-document-what-matters | scan:missing-docstring gate:comments-lost | strong | - | - |
| F483 | P1 | Leaving comments inconsistent with the code | guide:comments guide:keep-docs-true | none | strong | - | - |
| F484 | P1 | Failing to document public error and resource semantics | guide:public-docstrings-cover-behavior guide:write-what-caller-guess | scan:missing-docstring | strong | - | - |
| F485 | P1 | Maintaining examples that are never executed | guide:examples-public-documentation-should guide:run-each-command-snippet guide:run-examples | tool:docs gate:docs-facts | strong | - | - |
| F486 | P1 | Leaving TODOs without a concrete condition or owner | guide:todo-names-owner-issue guide:mark-limit-request-allows | scan:placeholder-comment | strong | - | - |
| F487 | P1 | Omitting rationale for consequential architecture decisions | tool:design guide:substantial-choices-record-options-2 guide:record-alternative-rejected-why | tool:design | strong | - | - |
| F488 | P1 | Failing to document migration steps for breaking changes | guide:compat-deliberate guide:changelog-deprecation-notes-same guide:docs-breaking | query:api | strong | - | - |
| F489 | P1 | Writing operational runbooks with guessed commands | guide:capture-real-output-from guide:anything-needs-credentials-has guide:docs-runbook | tool:docs | strong | - | - |
| F490 | P1 | Ending with a verbose narrative instead of useful evidence | guide:report-format guide:evidence-status | none | strong | REPORT-11 | - |
| F491 | P1 | Loading all quality rules into every prompt | guide:design-doc-small scan:instructions-bloated | scan:instructions-bloated | strong | CTX-07 | - |
| F492 | P1 | Stacking skills with conflicting mandatory workflows | guide:style-guide-repository-enforces guide:conflicting-skills | none | strong | CTX-27 | - |
| F493 | P1 | Treating prompt instructions as enforcement | guide:not-a-boundary guide:boundaries guide:hooks-ci-say-nothing | none | strong | - | - |
| F494 | P1 | Applying heavyweight review rituals to every edit | guide:depth-by-effect guide:design-doc-small guide:delegation-choice | none | strong | - | - |
| F495 | P1 | Never evaluating whether a skill improves outcomes | note:steering-file guide:notes-evidence guide:judging-a-skill | none | strong | - | - |
| F496 | P1 | Evaluating only the tasks used to write the skill | guide:notes-evidence guide:judging-a-skill | none | strong | - | - |
| F497 | P1 | Ignoring accumulated quality across repeated changes | gate:complexity-rose gate:denser tool:baseline | tool:baseline query:history | strong | SHAPE-06 SHAPE-20 TEAM-32 | - |
| F498 | P1 | Using model agreement as the only acceptance signal | guide:clean-review-weak hook:check-after-edit | tool:goal | strong | REPORT-25 | - |
| F499 | P1 | Adding permanent rules after every isolated mistake | note:steering-file guide:notes-evidence guide:rules-after-recurrence | guide:notes-evidence | strong | CTX-23 | - |
| F500 | P1 | Measuring agent success without human rework and operating cost | guide:at-lowest-total-cost guide:depth-by-effect guide:judging-a-skill | query:history | strong | TEAM-31 | - |

## Counted done by the owner's decision

No static check can reach these nine, since each needs the data model, the host, the target machine or production itself: F016, F021, F039, F204, F242, F243, F262, F394 and F468. occam has guidance for each, and the owner decided on 2026-11-07 that it counts as done (DESIGN.md `catalog-500-owner-calls`). That decision is the reason they read strong, not a check. F226 reads strong for a related reason: its check that the diff was inspected rides on send-backs that already happen, the form the owner chose for Stop checks.

## Still open

P0 rows that need something occam doesn't have go here. None does now: the last ones were settled by the owner's decisions recorded in DESIGN.md as `catalog-500-owner-calls`.

| ID | What it would take | Why it isn't here |
|---|---|---|

## Mechanisms named here

The tokens in the large-codebase catalog's Mechanisms table mean the same here. These are the ones this catalog adds, and `tests/test_quality_catalog.py` fails if the phrase in the last column leaves its file.

| Token | File | Must contain |
|---|---|---|
| note:left-running | plugin/hooks/stop_checks.py | `def left_running` |
| hook:credential-read | plugin/hooks/occam_hook.py | `def before_read` |
| hook:download-then-run | plugin/hooks/occam_evidence.py | `def _runs_what_it_downloaded` |
| hook:variable-delete | plugin/hooks/destructive.py | `def unset_variable` |
| hook:secret-printed | plugin/hooks/printed_secrets.py | `def secret_printed` |
| hook:unchecked-path-delete | plugin/hooks/destructive.py | `def empty_path_variable` |
| hook:make-delete-unset | plugin/hooks/destructive.py | `def make_deletes_through_unset` |
| hook:bucket-reach | plugin/hooks/destructive.py | `def bucket_reach` |
| hook:download-run-later | plugin/hooks/shell_writes.py | `def runs_an_earlier_download` |
| hook:download-in-build | plugin/hooks/shell_writes.py | `def build_runs_a_new_download` |
| hook:wrapper-moved | plugin/hooks/shell_writes.py | `def wrapper_moved` |
| hook:restore-over-production | plugin/hooks/destructive.py | `def restore_reason` |
| note:done-with-goal-unverified | plugin/hooks/stop_checks.py | `def done_with_goal_unverified` |
| note:leaked-work | plugin/hooks/repo_notes.py | `def leaked_work` |
| note:listed-item-left-out | plugin/hooks/stop_checks.py | `def listed_item_left_out` |
| note:race-detector-not-run | plugin/hooks/stop_checks.py | `def race_detector_not_run` |
| note:security-claim-unchecked | plugin/hooks/stop_checks.py | `def security_claim_unchecked` |
| note:switches-identity | plugin/hooks/repo_notes.py | `_SWITCH_NOTE` |
| note:tests-on-production | plugin/hooks/command_reach.py | `_TESTS_ON_PRODUCTION` |
| note:undeclared-install | plugin/hooks/command_reach.py | `def _undeclared` |
| note:uploads-a-file | plugin/hooks/command_reach.py | `def _uploaded` |
| note:ambient-target | plugin/hooks/command_reach.py | `def _changes_through` |
| note:env-file-switch | plugin/hooks/command_reach.py | `env-file-switch` |
| note:load-test-live | plugin/hooks/command_reach.py | `load-test-live` |
| note:install-source | plugin/hooks/command_reach.py | `def _install_source` |
| note:pipe-added | plugin/hooks/repo_notes.py | `pipe-added:` |
| note:relaxes-check | plugin/hooks/occam_evidence.py | `def how_a_change_relaxes` |
| note:writes-suppression | plugin/hooks/repo_notes.py | `writes-suppression` |
| note:publishes-public | plugin/hooks/command_reach.py | `publishes-public` |
| note:pushes-elsewhere | plugin/hooks/command_reach.py | `pushes-elsewhere` |
| note:suggested-command | plugin/hooks/repo_notes.py | `def _suggested` |
| note:backups-unrestored | plugin/hooks/repo_notes.py | `_BACKUP_NOTE` |
| note:discards-uncommitted | plugin/hooks/repo_notes.py | `def _discards_the_tree` |
| note:uncommitted-overwrite | plugin/hooks/repo_notes.py | `def overwrites_uncommitted` |
| note:switched-and-changed | plugin/hooks/command_reach.py | `switched-and-changed` |
| gate:added-dependencies | plugin/skills/occam/scripts/occam_tools/verify.py | `def _added_dependencies` |
| gate:goal-limits | plugin/skills/occam/scripts/occam_tools/workflow.py | `def _broken_limit` |
| gate:instructions-covering | plugin/skills/occam/scripts/occam_tools/verify.py | `def _instructions_question` |
| gate:types-silenced | plugin/skills/occam/scripts/occam_tools/change_checks.py | `def _types_silenced` |
| guide:a-slice-is-one-behavior | plugin/skills/occam/references/collaboration.md | `A slice is one behavior through every file` |
| guide:a-test-cancels-and-awaits | plugin/skills/occam-python/references/testing.md | `A test cancels and awaits every task it starts` |
| guide:directory-listings-globs | plugin/skills/occam-python/references/runtime.md | `have no defined order` |
| guide:dont-await-while-holding | plugin/skills/occam-python/references/runtime.md | `Don't await while holding a threading lock` |
| guide:examples-illustrate-a-rule | plugin/skills/occam/references/collaboration.md | `Examples illustrate a rule` |
| guide:find-the-problem-behind-it | plugin/skills/occam/references/collaboration.md | `Find the problem behind it` |
| guide:follow-a-redirect | plugin/skills/occam/references/collaboration.md | `When the user changes the goal mid-task` |
| guide:key-a-cache-by-everything | plugin/skills/occam/references/performance.md | `Key it by everything the result depends on` |
| guide:name-conflicts | plugin/skills/occam/references/collaboration.md | `When two stated requirements or constraints conflict` |
| guide:name-where-it-runs | plugin/skills/occam/references/collaboration.md | `the platforms, runtimes and versions supported and not` |
| guide:sort-what-you-were-told | plugin/skills/occam/references/collaboration.md | `Separate requirements from preferences` |
| guide:start-each-request-fresh | plugin/skills/occam/references/collaboration.md | `Recheck the branch, paths, conventions and constraints` |
| guide:text-true-decodes-with | plugin/skills/occam-python/references/runtime.md | ``text=True` decodes with the locale's encoding` |
| guide:which-copy-of-the-code-ran | plugin/skills/occam/references/verification.md | `confirm the revision and which copy of the code ran` |
| gate:checks-relaxed | plugin/skills/occam/scripts/occam_tools/change_checks.py | `def _checks_relaxed` |
| gate:memory-safety-added | plugin/skills/occam/scripts/occam_tools/change_checks.py | `def _memory_safety_added` |
| gate:precision-lowered | plugin/skills/occam/scripts/occam_tools/change_checks.py | `def _precision_lowered` |
| guide:abortcontroller-cancellation | plugin/skills/occam-typescript/SKILL.md | `` use `AbortController` for cancellation `` |
| guide:abstract-production-concerns-make | plugin/skills/occam/SKILL.md | `abstract production concerns don't make a script a platform` |
| guide:accept-small-interfaces-return | plugin/skills/occam-go/SKILL.md | `accept small interfaces and return concrete types` |
| guide:accepts-any-method-arguments | plugin/skills/occam-python/references/testing.md | `accepts any method and arguments` |
| guide:accidental-aliasing | plugin/skills/occam-python/SKILL.md | `accidental aliasing` |
| guide:add-observability-at-operational | plugin/skills/occam/references/design.md | `Add observability at operational boundaries` |
| guide:algo-duplicates | plugin/skills/occam/references/design.md | `Decide what duplicates mean` |
| guide:algo-invariants | plugin/skills/occam/references/design.md | `Write down the invariant the algorithm keeps` |
| guide:algorithmic-gain-establish-end | plugin/skills/occam/references/design.md | `an algorithmic gain doesn't establish end-to-end performance` |
| guide:also-intercepts-cancellation-interpreter | plugin/skills/occam-python/SKILL.md | `also intercepts cancellation and interpreter shutdown` |
| guide:annotation-input-validation | plugin/skills/occam-python/SKILL.md | `An annotation isn't input validation` |
| guide:annotation-input-validation-security | plugin/skills/occam-python/SKILL.md | `An annotation isn't input validation or a security check` |
| guide:any-at-boundary-spreads | plugin/skills/occam-python/references/structure.md | `` `Any` at a boundary spreads to everything downstream `` |
| guide:anything-blocking-cpu-heavy | plugin/skills/occam-python/SKILL.md | `Anything blocking or CPU-heavy on the event loop stalls every other coroutine` |
| guide:anything-needs-credentials-has | plugin/skills/occam-docs/SKILL.md | `Anything that needs credentials or has outside effects is reported as not run` |
| guide:api-names-true | plugin/skills/occam/references/design.md | `When behavior changes, rename what no longer describes it` |
| guide:api-signatures | plugin/skills/occam/references/design.md | `Keep parameter order the same across related functions` |
| guide:appear-only-their-scope | plugin/skills/occam/references/done.md | `appear only with their scope and evidence` |
| guide:argon2-scrypt-bcrypt | plugin/skills/occam-python/references/apis-and-security.md | `argon2, scrypt or bcrypt` |
| guide:arguments-need-picklable | plugin/skills/occam-python/references/structure.md | `so arguments need to be picklable` |
| guide:ask-before-changing-what | plugin/skills/occam/SKILL.md | `Ask before changing what acceptance means` |
| guide:ask-decisions-about-ambiguity | plugin/skills/occam/references/collaboration.md | `Ask for decisions about ambiguity that changes acceptance` |
| guide:assert-authorization-check | plugin/skills/occam-python/references/apis-and-security.md | `` `assert` for an authorization check `` |
| guide:assert-result-none-pass | plugin/skills/occam-python/references/testing.md | `` `assert result` and `is not None` pass for wrong values `` |
| guide:assert-used-required-validation | plugin/skills/occam-python/SKILL.md | `` `assert` used for required validation, since `-O` removes it `` |
| guide:assertions-fail | plugin/skills/occam-python/references/testing.md | `Assertions that can't fail` |
| guide:assume-messages-arrive-more | plugin/skills/occam/references/security.md | `Assume messages can arrive more than once and out of order` |
| guide:at-lowest-total-cost | plugin/skills/occam/SKILL.md | `at the lowest total cost to build, review and run` |
| guide:atomic-replacement | plugin/skills/occam/references/security.md | `Atomic replacement.` |
| guide:avoid-both-untyped-public | plugin/skills/occam-python/SKILL.md | `Avoid both untyped public contracts` |
| guide:avoid-inheritance-just-reach | plugin/skills/occam/references/design.md | `Avoid inheritance just to reach helpers` |
| guide:avoid-needless-cleverness | plugin/skills/occam/references/design.md | `Avoid needless cleverness` |
| guide:avoid-parameter-soup | plugin/skills/occam/references/design.md | `Avoid parameter soup` |
| guide:avoid-simultaneous-writes-one | plugin/skills/occam/references/collaboration.md | `avoid simultaneous writes to one interface or lockfile` |
| guide:avoid-unnecessary-metaclasses-decorators | plugin/skills/occam-python/SKILL.md | `Avoid unnecessary metaclasses, decorators, dynamic attributes, import tricks` |
| guide:avoid-unnecessary-metaclasses-decorators-2 | plugin/skills/occam-python/SKILL.md | `Avoid unnecessary metaclasses, decorators` |
| guide:become-dumping-ground | plugin/skills/occam-python/references/structure.md | `doesn't become a dumping ground` |
| guide:booleans-read-predicates | plugin/skills/occam-python/references/naming-and-docs.md | `Booleans read as predicates` |
| guide:both-create-order-dependence | plugin/skills/occam-python/references/testing.md | `Both create order dependence` |
| guide:bound-executor-queues-well | plugin/skills/occam-python/SKILL.md | `Bound executor queues as well as workers` |
| guide:bound-thread-pools-queues | plugin/skills/occam-jvm/SKILL.md | `bound thread pools and queues` |
| guide:bytes-versus-text-encodings | plugin/skills/occam-python/SKILL.md | `bytes versus text, encodings` |
| guide:cancels-wait-thread | plugin/skills/occam-python/references/runtime.md | `cancels the wait, not the thread` |
| guide:capture-real-output-from | plugin/skills/occam-docs/SKILL.md | `` Capture real output from `--help` and from running it `` |
| guide:catch-exception-make-failure | plugin/skills/occam-python/SKILL.md | `` don't catch `Exception` to make a failure disappear `` |
| guide:change-one-thing-per | plugin/skills/occam/references/performance.md | `Change one thing per measurement` |
| guide:change-public-header-struct | plugin/skills/occam-cpp/SKILL.md | `a change to a public header or struct layout can break callers that still compile` |
| guide:change-what-generated-from | plugin/skills/occam/references/design.md | `Change what it's generated from and rerun the tool that writes it` |
| guide:changelog-deprecation-notes-same | plugin/skills/occam-python/references/naming-and-docs.md | `changelog and deprecation notes in the same change` |
| guide:check-apis-against-what | plugin/hooks/rule_card.py | `Check APIs against what's installed, not memory` |
| guide:check-how-change-behaves | plugin/skills/occam/references/verification.md | `Check how a change behaves under real configuration and defaults` |
| guide:check-supported-python-requires | plugin/skills/occam-python/references/apis-and-security.md | `` Check the supported Python in `requires-python` and CI `` |
| guide:check-what-new-worktree | plugin/skills/occam/references/collaboration.md | `Check what a new worktree is based on` |
| guide:check-what-package-already | plugin/skills/occam-python/references/naming-and-docs.md | `Check what the package already calls this` |
| guide:check-what-security-setting | plugin/skills/occam/references/security.md | `Check what a security setting defaults to` |
| guide:choose-async-threads-processes | plugin/skills/occam-python/SKILL.md | `Choose async, threads, processes or native and vectorized execution from the measured workload` |
| guide:cli-streams | plugin/skills/occam/references/design.md | `Results go to stdout, and progress, warnings and errors to stderr` |
| guide:clone-appease-borrow-checker | plugin/skills/occam-rust/SKILL.md | `clone to appease the borrow checker only with a reason` |
| guide:closing-channels-sender-job | plugin/skills/occam-go/SKILL.md | `closing channels is the sender's job` |
| guide:closures-capturing-loop-variable | plugin/skills/occam-python/SKILL.md | `closures capturing a loop variable` |
| guide:code-test-written-one | plugin/skills/occam/references/verification.md | `Code and test written by one author share one understanding of the problem` |
| guide:cold-warm-state | plugin/skills/occam/references/performance.md | `cold or warm state` |
| guide:compare-candidates-fitness-total | plugin/skills/occam/references/design.md | `Compare candidates on fitness and total cost` |
| guide:config-startup | plugin/skills/occam/references/design.md | `Read and validate it at startup` |
| guide:configuration-counts-too | plugin/skills/occam-python/references/naming-and-docs.md | `Configuration counts too` |
| guide:conflicting-skills | plugin/skills/occam/references/collaboration.md | `When two loaded skills or instruction files require steps that conflict` |
| guide:connection-pools | plugin/skills/occam/references/design.md | `connection pools` |
| guide:consider-crash-after-effect | plugin/skills/occam/references/security.md | `Consider a crash after the effect but before recording it` |
| guide:context-managers-files-sockets | plugin/skills/occam-python/SKILL.md | `Use context managers for files, sockets, locks and sessions` |
| guide:conversions-state-their-cost | plugin/skills/occam-rust/SKILL.md | `Conversions state their cost` |
| guide:coordination-overhead | plugin/skills/occam/references/performance.md | `coordination overhead` |
| guide:coroutine-was-never-awaited | plugin/skills/occam-python/references/testing.md | `coroutine was never awaited` |
| guide:cross-field | plugin/skills/occam/references/design.md | `Check relations between fields as well as each field` |
| guide:cross-language-boundary | plugin/skills/occam/references/design.md | `state the encoding, line endings, integer width and time format` |
| guide:dataclass-plain-records | plugin/skills/occam-python/references/structure.md | `` Use `dataclass` for plain records `` |
| guide:decimal-money-rounding-mode | plugin/skills/occam-python/SKILL.md | `` `Decimal` for money, the rounding mode the domain requires `` |
| guide:def-checks-elsewhere | plugin/hooks/shell_writes.py | `def checks_elsewhere` |
| guide:def-never-started | plugin/hooks/occam_commands.py | `def never_started` |
| guide:def-ran-tests | plugin/skills/occam/scripts/occam_tools/zero_tests.py | `def ran_no_tests` |
| guide:def-varying-result | plugin/hooks/stop_checks.py | `def varying_result` |
| guide:default-client-timeout | plugin/skills/occam-go/SKILL.md | `the default client with no timeout` |
| guide:default-start-method | plugin/skills/occam-python/references/structure.md | `The default start method is` |
| guide:dep-health-eol | plugin/skills/occam/references/design.md | `end of life or deprecation, license and whether it allows` |
| guide:dep-lockfile-diff | plugin/skills/occam/references/design.md | `read what the lockfile added, removed or moved a major version` |
| guide:dict-set-ordering-assumptions | plugin/skills/occam-python/SKILL.md | `dict and set ordering assumptions` |
| guide:diff-moves-code-changes | plugin/skills/occam-audit/references/repair.md | `A diff that moves code and changes behavior can't be reviewed` |
| guide:differential-tests-against-old | plugin/skills/occam/references/verification.md | `Differential tests against the old code or a reference` |
| guide:dist-clocks | plugin/skills/occam/references/performance.md | `Order events by a sequence number or version from one authority` |
| guide:dist-fencing | plugin/skills/occam/references/performance.md | `a fencing token that only increases` |
| guide:dist-liveness | plugin/skills/occam/references/performance.md | `Liveness says restart me, readiness says stop sending me traffic` |
| guide:dist-nodes-differ | plugin/skills/occam/references/performance.md | `during a rolling deploy, code version vary` |
| guide:dist-reorder | plugin/skills/occam/references/performance.md | `A parallel or reordered float reduction differs in its last digits` |
| guide:dist-serial | plugin/skills/occam/references/performance.md | `Serial parts cap the gain.` |
| guide:dist-skew | plugin/skills/occam/references/performance.md | `Count rows per key on real data before choosing a key` |
| guide:dist-stable-hash | plugin/skills/occam/references/performance.md | `Partition by a stable hash.` |
| guide:dist-task-size | plugin/skills/occam/references/performance.md | `Each task, process or remote call has a fixed cost` |
| guide:dist-timeout-unknown | plugin/skills/occam/references/performance.md | `A timeout doesn't say what happened.` |
| guide:distinguish-expected-domain-errors | plugin/skills/occam-python/SKILL.md | `Distinguish expected domain errors from programmer errors` |
| guide:do-blocking-i-o | plugin/skills/occam-rust/SKILL.md | `do blocking I/O on the executor` |
| guide:docs-breaking | plugin/skills/occam-docs/SKILL.md | `A breaking change's entry says what breaks` |
| guide:docs-runbook | plugin/skills/occam-docs/SKILL.md | `A runbook's commands are ones you ran` |
| guide:drive-toward-checkable-end | plugin/skills/occam/references/collaboration.md | `drive toward a checkable end state rather than a list of steps` |
| guide:dropping-future-cancellation | plugin/skills/occam-rust/SKILL.md | `dropping a future is cancellation` |
| guide:dst-boundaries | plugin/skills/occam-python/SKILL.md | `DST boundaries` |
| guide:duplicate-keys-multiplies-rows | plugin/skills/occam-python/references/runtime.md | `on duplicate keys multiplies rows` |
| guide:duplicate-out-order-delivery | plugin/skills/occam/references/performance.md | `duplicate or out-of-order delivery` |
| guide:dynamic-identifiers-need-allow | plugin/skills/occam-sql/SKILL.md | `Dynamic identifiers need an allow-list` |
| guide:each-worker-gets-own | plugin/skills/occam-python/references/testing.md | `each worker gets its own temp directory, database and ports` |
| guide:errors-should-actionable-without | plugin/skills/occam/references/design.md | `Errors should be actionable without leaking secrets` |
| guide:escape-context | plugin/skills/occam-typescript/SKILL.md | `escape for the context` |
| guide:every-caller-data-path | plugin/hooks/stop_checks.py | `every caller and data path it reaches` |
| guide:every-goroutine-needs-way | plugin/skills/occam-go/SKILL.md | `every goroutine needs a way to stop` |
| guide:examine-skew-stragglers-retry | plugin/skills/occam/references/performance.md | `Examine skew, stragglers, retry storms` |
| guide:example-shows-the-call | plugin/skills/occam/references/design.md | `A library's example shows the call, not where its client lives` |
| guide:examples-public-documentation-should | plugin/skills/occam/references/design.md | `Examples in public documentation should actually run` |
| guide:explicit-invariants-failure-analysis | plugin/skills/occam/SKILL.md | `explicit invariants and failure analysis` |
| guide:extend-existing-base-class | plugin/skills/occam-python/references/structure.md | `Extend an existing base class when its contract fits` |
| guide:fail-closed | plugin/skills/occam/references/security.md | `Fail closed` |
| guide:fail-closed-2 | plugin/skills/occam/references/security.md | `Fail closed.` |
| guide:failure-injection | plugin/skills/occam/references/verification.md | `Failure injection` |
| guide:failure-injection-timeouts-partial | plugin/skills/occam/references/verification.md | `Failure injection: timeouts, partial failure, permission denied, cancellation, recovery` |
| guide:failure-injection-timeouts-partial-2 | plugin/skills/occam/references/verification.md | `Failure injection: timeouts, partial failure` |
| guide:fewest-lines-most-abstractions | plugin/skills/occam/SKILL.md | `Not fewest lines, most abstractions, most tests or most agents` |
| guide:finish-check-one-slice | plugin/skills/occam/references/collaboration.md | `Finish and check one slice before starting the next` |
| guide:fix-packaging-rather-than | plugin/skills/occam-python/references/structure.md | `` fix packaging rather than editing `sys.path` `` |
| guide:fix-time-alone-leave | plugin/skills/occam/references/performance.md | `a fix to time alone can leave memory over the limit` |
| guide:fixtures-are-as-large | plugin/skills/occam/references/verification.md | `Fixtures are as large and varied as what the change meets` |
| guide:fixtures-share-mutable-state | plugin/skills/occam-python/references/testing.md | `fixtures share mutable state` |
| guide:flag-owner | plugin/skills/occam/references/design.md | `A new flag names its owner and when it comes out` |
| guide:flag-selects-between-them | plugin/skills/occam-audit/references/repair.md | `a flag that selects between them is worse than the copies` |
| guide:flags-select-between-unrelated | plugin/skills/occam/references/design.md | `flags select between unrelated behaviors` |
| guide:float-comparison-nan-ordering | plugin/skills/occam-python/SKILL.md | `float comparison, NaN ordering` |
| guide:follow-accepted-decisions-supersede | plugin/skills/occam/SKILL.md | `Follow accepted decisions or supersede them` |
| guide:follow-existing-convention-async | plugin/skills/occam-python/references/naming-and-docs.md | `Follow the existing convention for async pairs` |
| guide:follow-pep-8-pep | plugin/skills/occam-python/SKILL.md | `Follow PEP 8, PEP 257 and the repository's public API conventions` |
| guide:foreach-await | plugin/skills/occam-typescript/SKILL.md | `` `forEach` doesn't await `` |
| guide:freeze-time-seed-randomness | plugin/skills/occam-python/references/testing.md | `Freeze time, seed randomness` |
| guide:generate-planning-files-trivial | plugin/skills/occam/references/collaboration.md | `Don't generate planning files for trivial edits` |
| guide:generator-sufficient-later-stage | plugin/skills/occam-python/SKILL.md | `A generator isn't sufficient if a later stage collects everything` |
| guide:get-means-cheap-lookup | plugin/skills/occam-python/references/naming-and-docs.md | `` If `get_` means a cheap lookup here, a network call shouldn't also be `get_` `` |
| guide:give-external-calls-deadlines | plugin/skills/occam/references/security.md | `Give external calls deadlines` |
| guide:goal-recorded | plugin/skills/occam/scripts/occam_tools/verify.py | `No goal recorded` |
| guide:goes-new-file-named | plugin/skills/occam/references/design.md | `goes in a new file named for that responsibility` |
| guide:guard-held-across | plugin/skills/occam-rust/SKILL.md | `guard held across` |
| guide:handle-every-returned-error | plugin/skills/occam-go/SKILL.md | `` handle every returned error and wrap with `%w` `` |
| guide:hold-blocking-lock-do | plugin/skills/occam-rust/SKILL.md | `Don't hold a blocking lock or do blocking I/O on the executor` |
| guide:honor-explicit-restrictions-even | plugin/skills/occam/SKILL.md | `Honor explicit restrictions even when a broader fix looks better` |
| guide:hooks-ci-say-nothing | plugin/skills/occam/SKILL.md | `No hooks or CI: say nothing enforces these checks` |
| guide:hw-compile-once | plugin/skills/occam/references/performance.md | `Cache on shapes, dtypes and settings` |
| guide:hw-cpu-count | plugin/skills/occam/references/performance.md | `knows a container's CPU quota` |
| guide:hw-data-movement | plugin/skills/occam/references/performance.md | `Profile cache misses, memory bandwidth and NUMA placement` |
| guide:hw-device-memory | plugin/skills/occam/references/performance.md | `Budget intermediates and concurrent batches` |
| guide:hw-fallback | plugin/skills/occam/references/performance.md | `Acceleration is optional unless required.` |
| guide:hw-gpu-fixed-cost | plugin/skills/occam/references/performance.md | `Launches and host-device copies cost more than small work saves` |
| guide:hw-gpu-sync | plugin/skills/occam/references/performance.md | `Time GPU work after synchronizing.` |
| guide:hw-isa-baseline | plugin/skills/occam/references/performance.md | `Build for a stated baseline, or dispatch at runtime` |
| guide:hw-precision | plugin/skills/occam/references/performance.md | `Lower precision needs an error budget.` |
| guide:hw-storage | plugin/skills/occam/references/performance.md | `Small writes and frequent syncs are slow on network and cloud storage` |
| guide:hypothesis-given-real-property | plugin/skills/occam-python/references/testing.md | `` Use Hypothesis's `@given` when a real property exists `` |
| guide:idempotency-partial-failure | plugin/skills/occam/references/performance.md | `idempotency, partial failure` |
| guide:import-time-code-runs | plugin/skills/occam-python/references/structure.md | `Import-time code runs for every importer` |
| guide:importing-collecting-aren-read | plugin/skills/occam-python/references/auditing.md | `Importing and collecting aren't read-only` |
| guide:imports-public-exports-from | plugin/skills/occam/references/verification.md | `imports and public exports from a built artifact when packaging is affected` |
| guide:include-unicode | plugin/skills/occam/references/verification.md | `Include Unicode` |
| guide:including-strings-config-templates | plugin/skills/occam/references/design.md | `including strings, config, templates, reflection and test doubles` |
| guide:incompatible-api-schema-changes | plugin/skills/occam/SKILL.md | `incompatible API or schema changes` |
| guide:inconsistent-return-types | plugin/skills/occam/references/design.md | `inconsistent return types` |
| guide:inspect-python-object-overhead | plugin/skills/occam-python/SKILL.md | `Inspect Python object overhead, dtypes` |
| guide:install-stack-established | plugin/skills/occam-python/SKILL.md | `install a stack that isn't established` |
| guide:instead-layering-retries | plugin/skills/occam/references/bugs.md | `instead of layering retries` |
| guide:integer-overflow-size-calculations | plugin/skills/occam-cpp/SKILL.md | `integer overflow in size calculations` |
| guide:integer-precision-across-languages | plugin/skills/occam-python/SKILL.md | `integer precision across languages` |
| guide:integer-versus-real-division | plugin/skills/occam-sql/SKILL.md | `integer versus real division` |
| guide:integrate-dependency-order | plugin/skills/occam/references/collaboration.md | `integrate in dependency order` |
| guide:interacts-pools-virtual-threads | plugin/skills/occam-jvm/SKILL.md | `interacts with pools and virtual threads` |
| guide:iterators-generators-exhausted-first | plugin/skills/occam-python/SKILL.md | `Iterators and generators exhausted by a first pass` |
| guide:json-parsing-loses-large | plugin/skills/occam-typescript/SKILL.md | `JSON parsing loses large integer precision` |
| guide:judge-against-run-run | plugin/skills/occam/references/performance.md | `judge it against the run-to-run noise from repeats` |
| guide:judging-a-skill | plugin/skills/occam/references/collaboration.md | `Compare runs with and without it on the same tasks` |
| guide:jvm-equals-hash | plugin/skills/occam-jvm/SKILL.md | `` Override `equals` and `hashCode` together `` |
| guide:jvm-pool-self-wait | plugin/skills/occam-jvm/SKILL.md | `a task that submits to its own bounded executor` |
| guide:keep-docs-true | plugin/skills/occam-python/references/naming-and-docs.md | `Keep docs true.` |
| guide:keep-references-tasks-create | plugin/skills/occam-python/SKILL.md | `Keep references to tasks you create` |
| guide:keep-references-tasks-create-2 | plugin/skills/occam-python/SKILL.md | `Keep references to tasks you create, and don't leave any running when the caller is cancelled` |
| guide:keep-singular-plural-verbs | plugin/skills/occam/references/design.md | `Keep singular and plural, verbs, units, sync and async semantics, error types and return conventions consistent` |
| guide:keep-together | plugin/skills/occam/references/design.md | `A small feature that changes as one stays in one file` |
| guide:keeps-exception-future | plugin/skills/occam-python/references/runtime.md | `keeps an exception in the future` |
| guide:know-whether-need-shallow | plugin/skills/occam-python/SKILL.md | `Know whether you need a shallow or a deep copy` |
| guide:lazy-evaluation-running-later | plugin/skills/occam-python/SKILL.md | `lazy evaluation running later than you assume` |
| guide:leave-out-features-nobody | plugin/hooks/rule_card.py | `leave out features nobody asked for` |
| guide:libraries-only-call-logging | plugin/skills/occam-python/references/structure.md | `` Libraries only call `logging.getLogger(__name__)` `` |
| guide:library-declares-ranges-application | plugin/skills/occam-python/references/structure.md | `a library declares ranges, and an application pins with a lockfile` |
| guide:load-tests-against-stated | plugin/skills/occam/references/verification.md | `Load tests against a stated workload` |
| guide:locale-dependent-sorting | plugin/skills/occam-python/SKILL.md | `locale-dependent sorting` |
| guide:lock-behavior-before-change | plugin/skills/occam-audit/references/repair.md | `Lock behavior before you change it` |
| guide:looks-like-report-work | plugin/hooks/occam_hook.py | `looks like a report on this work` |
| guide:lowering-global-setting-land | plugin/skills/occam-python/references/structure.md | `Lowering a global setting to land one change costs everyone` |
| guide:make-common-operations-discoverable | plugin/skills/occam/references/design.md | `Make common operations discoverable with safe defaults` |
| guide:make-flag-parameters-keyword | plugin/skills/occam-python/references/naming-and-docs.md | `Make flag parameters keyword-only` |
| guide:make-invalid-states-hard | plugin/skills/occam/references/design.md | `Make invalid states hard to express where practical` |
| guide:make-one-small-real | plugin/skills/occam/references/design.md | `make one small real call before building on it` |
| guide:mapping-large-list-promises | plugin/skills/occam-typescript/SKILL.md | `mapping a large list to promises starts everything at once` |
| guide:mark-limit-request-allows | plugin/skills/occam/references/new-code.md | `Mark a limit the request allows` |
| guide:materializing-input | plugin/skills/occam-python/SKILL.md | `Materializing an input with` |
| guide:measure-alternate | plugin/skills/occam/references/performance.md | `Alternate baseline and candidate runs on the same machine` |
| guide:measure-completed | plugin/skills/occam/references/performance.md | `Report completed, successful operations per second` |
| guide:measure-keep-runs | plugin/skills/occam/references/performance.md | `Keep every run.` |
| guide:measure-peak-rss-just | plugin/skills/occam-python/SKILL.md | `measure peak RSS, not just elapsed time` |
| guide:measure-widest | plugin/skills/occam/references/performance.md | `Measure memory on the largest and widest records` |
| guide:memory-storage-limits-hardware | plugin/skills/occam/references/performance.md | `memory and storage limits, hardware, failure expectations and cost` |
| guide:migrate-tooling | plugin/skills/occam-python/SKILL.md | `Don't migrate tooling` |
| guide:mind-orm-lazy-loading | plugin/skills/occam-jvm/SKILL.md | `mind ORM lazy loading and N+1 queries` |
| guide:mock-at-outer-boundary | plugin/skills/occam-python/references/testing.md | `Mock at the outer boundary` |
| guide:module-boundary-costs-nothing | plugin/skills/occam/references/design.md | `A module boundary costs nothing at runtime` |
| guide:module-level-state-exists | plugin/skills/occam-python/references/structure.md | `Module-level state exists once per process` |
| guide:must-propagate-catching-log | plugin/skills/occam-python/SKILL.md | `must propagate: re-raise it after logging` |
| guide:mutable-default-arguments | plugin/skills/occam-python/SKILL.md | `Mutable default arguments` |
| guide:mutable-default-arguments-accidental | plugin/skills/occam-python/SKILL.md | `Mutable default arguments and accidental aliasing` |
| guide:mutable-state-shared-across | plugin/skills/occam-python/SKILL.md | `Mutable state shared across threads, tasks or requests` |
| guide:mypy-skips-bodies-unannotated | plugin/skills/occam-python/references/auditing.md | `` mypy skips the bodies of unannotated functions unless `check_untyped_defs` is on `` |
| guide:name-what-differs-in-production | plugin/skills/occam/references/design.md | `name the configuration, versions and limits that differ in production` |
| guide:name-who-reads-an-output | plugin/skills/occam/references/design.md | `Name who reads an output, a person, a program or another service` |
| guide:native-unsafe-code | plugin/skills/occam/SKILL.md | `native or unsafe code` |
| guide:need-genuinely-trivial | plugin/skills/occam/references/design.md | `the need is genuinely trivial` |
| guide:negative-integration-tests | plugin/skills/occam/SKILL.md | `negative and integration tests` |
| guide:network-call-shouldn-also | plugin/skills/occam-python/references/naming-and-docs.md | `` a network call shouldn't also be `get_` `` |
| guide:never-put-mock-todo | plugin/hooks/rule_card.py | `Never put a mock, TODO, hard-coded example or cut-down version` |
| guide:new-evidence-changes-plan | plugin/skills/occam/SKILL.md | `new evidence changes the plan, not the goal` |
| guide:no-metaprogramming | plugin/skills/occam/references/design.md | `metaclasses and generated code hide control flow` |
| guide:noisy-logging-every-function | plugin/skills/occam/references/design.md | `not noisy logging in every function` |
| guide:non-goal-could-reasonably | plugin/skills/occam/references/collaboration.md | `A non-goal could reasonably have been a goal` |
| guide:notify-affected-collaborators-interface | plugin/skills/occam/references/collaboration.md | `notify affected collaborators of interface changes and blockers` |
| guide:null-undefined-missing-key | plugin/skills/occam-typescript/SKILL.md | `` `null`, `undefined` and a missing key differ `` |
| guide:nulls-duplicates-ties | plugin/skills/occam-sql/SKILL.md | `NULLs, duplicates, ties` |
| guide:occam-delegation-guidance-at | plugin/hooks/occam_hook.py | `occam's delegation guidance is at` |
| guide:one-change-per-attempt | plugin/skills/occam/references/verification.md | `Change one thing per attempt` |
| guide:one-per-step-longer | plugin/skills/occam/SKILL.md | `one per step of a longer plan` |
| guide:one-reader-per-5 | plugin/skills/occam-audit/references/scale.md | `One reader per 5,000 lines of risk-ranked code` |
| guide:one-small-test-new | plugin/skills/occam/SKILL.md | `one small test for new branching or parsing logic` |
| guide:only-editable-imports-from | plugin/skills/occam-python/SKILL.md | `not only editable imports from the repository root` |
| guide:order-steps | plugin/skills/occam/references/design.md | `Order your own steps` |
| guide:own-responsibility-belongs-own | plugin/hooks/scale_notes.py | `with its own responsibility belongs in its own module` |
| guide:package-exposes-small-surface | plugin/skills/occam-python/references/structure.md | `` A package exposes a small surface through `__init__.py` and `__all__` `` |
| guide:packaging-affected-exercise-built | plugin/skills/occam-typescript/SKILL.md | `When packaging is affected, exercise the built output` |
| guide:parameter-heavy-universal-function | plugin/skills/occam/references/design.md | `a parameter-heavy universal function whose flags select between unrelated behaviors` |
| guide:parsers-untrusted-input | plugin/skills/occam/references/verification.md | `Parsers and untrusted input` |
| guide:pass-conclusions | plugin/skills/occam-audit/references/scale.md | `Don't pass on your conclusions` |
| guide:percentiles-averages-alone | plugin/skills/occam/references/performance.md | `Use percentiles, not averages alone` |
| guide:perf-hidden-cost | plugin/skills/occam/references/performance.md | `that users trigger casually shouldn't hide a slow or paid operation` |
| guide:perf-log-volume | plugin/skills/occam/references/performance.md | `Logging every event on a hot path costs I/O and money` |
| guide:perf-oom-retry | plugin/skills/occam/references/performance.md | `An out-of-memory failure repeats on the same input` |
| guide:perf-serialization-peak | plugin/skills/occam/references/performance.md | `Peak memory counts serialization too` |
| guide:perf-spill-budget | plugin/skills/occam/references/performance.md | `Spilling to disk needs its own budget` |
| guide:pipe-hides-exit-status | plugin/hooks/occam_commands.py | `A pipe hides the exit status` |
| guide:piping-also-hides-real | plugin/skills/occam-python/references/testing.md | `Piping also hides real failures.` |
| guide:poll-deadline-rather-than | plugin/skills/occam-python/references/testing.md | `poll with a deadline rather than` |
| guide:prefer-composition-small-interfaces | plugin/skills/occam/references/design.md | `Prefer composition and small interfaces` |
| guide:prefer-domain-word | plugin/skills/occam-python/references/naming-and-docs.md | `Prefer the domain's word` |
| guide:prefer-thin-adapter-at | plugin/skills/occam/references/design.md | `Prefer a thin adapter at a real domain boundary to wrapping every function of a dependency` |
| guide:preserve-behavior-old-shape | plugin/skills/occam/references/performance.md | `Preserve behavior the old shape gave for free` |
| guide:preserve-causes-raise-from | plugin/skills/occam-python/SKILL.md | `` Preserve causes with `raise ... from` `` |
| guide:product-ui | plugin/skills/occam/references/design.md | `A destructive action says what it will remove` |
| guide:property-based-tests | plugin/skills/occam/references/verification.md | `Property-based tests` |
| guide:protocol-contract-commonality-implementers | plugin/skills/occam-python/references/structure.md | `` Use `Protocol` when the contract is the commonality and implementers are unrelated `` |
| guide:protocol-interface-contract-useful | plugin/skills/occam/references/design.md | `a protocol or interface when the contract is the useful commonality` |
| guide:public-docstrings-cover-behavior | plugin/skills/occam/references/design.md | `Public docstrings cover behavior, inputs, outputs, errors and side effects` |
| guide:put-units-name | plugin/skills/occam-python/references/naming-and-docs.md | `Put units in the name` |
| guide:py-batch-bytes | plugin/skills/occam-python/references/runtime.md | `Size batches by bytes,` |
| guide:py-bool-int | plugin/skills/occam-python/references/runtime.md | `` `bool` is an `int`, `` |
| guide:py-build-runs-code | plugin/skills/occam-python/references/structure.md | `Inspecting a package can run it.` |
| guide:py-class-shared | plugin/skills/occam-python/references/runtime.md | `A list or dict in a class body is shared by every instance.` |
| guide:py-client-threads | plugin/skills/occam-python/references/runtime.md | `Check a client's thread-safety before sharing it.` |
| guide:py-compound-race | plugin/skills/occam-python/references/runtime.md | `Compound updates race with or without the GIL.` |
| guide:py-contextvars | plugin/skills/occam-python/references/runtime.md | `` don't carry `contextvars` `` |
| guide:py-copies | plugin/skills/occam-python/references/runtime.md | `Whether a conversion copies` |
| guide:py-cpu-count | plugin/skills/occam-python/references/runtime.md | `` `os.cpu_count()` counts the host, `` |
| guide:py-del | plugin/skills/occam-python/references/runtime.md | `` Cleanup in `__del__` runs when the collector decides, `` |
| guide:py-dense | plugin/skills/occam-python/references/runtime.md | `Dense numbers belong in arrays or columnar frames,` |
| guide:py-dev-deps | plugin/skills/occam-python/references/structure.md | `Test, lint and documentation tools go in a dev group or extra` |
| guide:py-device-memory | plugin/skills/occam-python/references/runtime.md | `Size batches against the device` |
| guide:py-division | plugin/skills/occam-python/references/runtime.md | `` `/` between ints returns a float, `` |
| guide:py-falsy | plugin/skills/occam-python/references/runtime.md | `keep missing, null, empty and zero apart` |
| guide:py-fixed-width | plugin/skills/occam-python/references/runtime.md | `NumPy and pandas integers are fixed width` |
| guide:py-hash-join | plugin/skills/occam-python/references/runtime.md | `holds a hash table of its keys` |
| guide:py-identity | plugin/skills/occam-python/references/runtime.md | `` `is` compares identity. `` |
| guide:py-install-env | plugin/skills/occam-python/references/structure.md | `Install only into that environment, with its manager.` |
| guide:py-interpreter | plugin/skills/occam-python/references/structure.md | `Use the project's interpreter.` |
| guide:py-monotonic | plugin/skills/occam-python/references/runtime.md | `` Measure elapsed time and deadlines with `time.monotonic()` `` |
| guide:py-mutate-iterate | plugin/skills/occam-python/references/runtime.md | `Removing from a collection while looping over it` |
| guide:py-nan | plugin/skills/occam-python/references/runtime.md | `NaN equals nothing, itself included,` |
| guide:py-nested-loop | plugin/skills/occam-python/references/runtime.md | `` `asyncio.run` inside a running loop raises. `` |
| guide:py-normalize-ids | plugin/skills/occam-python/references/runtime.md | `Normalizing an identifier with NFKC` |
| guide:py-optional-extra | plugin/skills/occam-python/references/structure.md | `A package from an optional extra is imported inside the function that needs it` |
| guide:py-pool-self-wait | plugin/skills/occam-python/references/runtime.md | `A pool waiting on itself deadlocks.` |
| guide:py-process-pools | plugin/skills/occam-python/references/runtime.md | `Process pools pickle what they run,` |
| guide:py-retained | plugin/skills/occam-python/references/runtime.md | `stored exceptions with tracebacks, and caches keep objects alive` |
| guide:py-return-copies | plugin/skills/occam-python/references/runtime.md | `Returning internal state lets callers change it.` |
| guide:py-salted-hash | plugin/skills/occam-python/references/runtime.md | `` `hash()` of `str` and `bytes` changes per process. `` |
| guide:py-seeded | plugin/skills/occam-python/references/runtime.md | `` Code that samples or shuffles takes a `random.Random` or a seed, `` |
| guide:py-shutdown | plugin/skills/occam-python/references/runtime.md | `Shutdown can drop work.` |
| guide:py-stable-keys | plugin/skills/occam-python/references/runtime.md | `A dict key or set member must not change while stored.` |
| guide:py-text-length | plugin/skills/occam-python/references/runtime.md | `` `len(s)` counts code points. `` |
| guide:py-type-scope | plugin/skills/occam-python/references/structure.md | `Type safety is claimed for what the checker covered.` |
| guide:py-versions-wheels | plugin/skills/occam-python/references/structure.md | `` newer than `requires-python` break users on the floor `` |
| guide:py-views-retain | plugin/skills/occam-python/references/runtime.md | `keeps its whole parent buffer alive` |
| guide:py-wraps | plugin/skills/occam-python/references/runtime.md | `` A decorator without `functools.wraps` `` |
| guide:py-zip-strict | plugin/skills/occam-python/references/runtime.md | `` `zip()` stops at the shortest input. `` |
| guide:pyi-stub-claim-about | plugin/skills/occam-python/references/runtime.md | `` A `.pyi` stub is a claim about the runtime that nothing enforces by default `` |
| guide:python-m-pytest-adds | plugin/skills/occam-python/references/testing.md | `` `python -m pytest` adds the current directory to `sys.path` `` |
| guide:pytz-timezones-passed-tzinfo | plugin/skills/occam-python/references/apis-and-security.md | `` `pytz` timezones passed as `tzinfo=` `` |
| guide:raise-python-version-express | plugin/skills/occam-python/SKILL.md | `raise the Python version to express a preference` |
| guide:rather-than-0-valid | plugin/skills/occam-typescript/SKILL.md | `` Use `??` rather than `||` when `0` or `""` are valid `` |
| guide:rather-than-inventing-receipt | plugin/skills/occam/references/verification.md | `rather than inventing a receipt system` |
| guide:read-callers-what-changed | plugin/agents/code-reviewer.md | `read the callers of what changed` |
| guide:read-environment-once-at | plugin/skills/occam-python/references/structure.md | `read the environment once, at the edge` |
| guide:read-query-plan-anything | plugin/skills/occam-sql/SKILL.md | `Read the query plan for anything large` |
| guide:read-request-literally-before | plugin/skills/occam/references/design.md | `Read the request literally before matching it to a problem you recognize` |
| guide:record-alternative-rejected-why | plugin/skills/occam/references/collaboration.md | `Record the alternative you rejected and why` |
| guide:red-baseline-itself-finding | plugin/skills/occam-audit/SKILL.md | `A red baseline is itself a finding` |
| guide:redundant-tests-trivial-code | plugin/skills/occam/references/verification.md | `redundant tests for trivial code` |
| guide:refactors-preserve-intended-semantics | plugin/skills/occam/references/design.md | `Refactors preserve intended semantics unless a behavior change is the goal` |
| guide:registries-reflection-plugins-framework | plugin/skills/occam/references/design.md | `Registries, reflection, plugins and framework autodiscovery mean a text search can't prove that nothing uses something` |
| guide:reject-generic-utility-bucket | plugin/skills/occam/references/design.md | `Reject a generic utility bucket` |
| guide:rejects-early-without-cancelling | plugin/skills/occam-typescript/SKILL.md | `rejects early without cancelling the others` |
| guide:rel-ack-durable | plugin/skills/occam/references/security.md | `only after the effect is durable` |
| guide:rel-backoff | plugin/skills/occam/references/security.md | `back off with jitter, and stop once the caller has cancelled` |
| guide:rel-backup-restore | plugin/skills/occam/references/security.md | `A backup counts once a restore of it has worked` |
| guide:rel-check-outcome | plugin/skills/occam/references/verification.md | `A deploy is done when you've checked the outcome` |
| guide:rel-one-deadline | plugin/skills/occam/references/security.md | `Pass one deadline down` |
| guide:rel-one-layer | plugin/skills/occam/references/security.md | `Retry at one layer` |
| guide:rel-partial-result | plugin/skills/occam/references/security.md | `A paginated, truncated or partly failed result says so` |
| guide:rel-prod-smoke | plugin/skills/occam/references/verification.md | `Start it as production does,` |
| guide:rel-required-checks | plugin/skills/occam/references/verification.md | `A failed required check stops the release.` |
| guide:rel-resume | plugin/skills/occam/references/security.md | `keeps enough state to retry the failed step` |
| guide:rel-rollback | plugin/skills/occam/references/security.md | `list what it does that rollback won't undo` |
| guide:rel-run-what-ci-runs | plugin/skills/occam/references/verification.md | `Run what CI runs,` |
| guide:rel-ship-tested | plugin/skills/occam/references/verification.md | `Ship what you tested.` |
| guide:rel-signal | plugin/skills/occam/references/verification.md | `names the metric or log line that shows it working` |
| guide:rel-sigterm | plugin/skills/occam/references/security.md | `On SIGTERM, stop taking work` |
| guide:rel-staged | plugin/skills/occam/references/verification.md | `Roll out a risky change in stages,` |
| guide:rel-timeout-continues | plugin/skills/occam/references/security.md | `A timeout on the wait doesn't stop the work` |
| guide:rel-trace-id | plugin/skills/occam/references/security.md | `Pass a correlation or trace id through every call` |
| guide:rel-unique-constraint | plugin/skills/occam/references/security.md | `Enforce it with a unique constraint in storage` |
| guide:remove-abandoned-code-imports | plugin/skills/occam/references/design.md | `Remove abandoned code, imports, debug artifacts, obsolete flags and scaffolding that your change orphaned` |
| guide:remove-old-one-after | plugin/skills/occam/references/collaboration.md | `remove the old one after that` |
| guide:report-how-much-headroom | plugin/skills/occam/references/performance.md | `Report how much headroom you measured relative to the limit` |
| guide:representative-baseline-changed-version | plugin/skills/occam/references/performance.md | `Use a representative baseline and the changed version in comparable environments` |
| guide:rerunning-until-green | plugin/skills/occam/references/verification.md | `Rerunning until green` |
| guide:resolve-relative | plugin/skills/occam-python/references/apis-and-security.md | `resolve().is_relative_to` |
| guide:respect-cancellation | plugin/skills/occam-go/SKILL.md | `respect its cancellation` |
| guide:respect-existing-well-designed | plugin/skills/occam/references/design.md | `Respect existing well-designed base classes` |
| guide:restore-interrupt-status | plugin/skills/occam-jvm/SKILL.md | `restore the interrupt status` |
| guide:rethrow | plugin/skills/occam-jvm/SKILL.md | `so rethrow it` |
| guide:revisit-custom-code | plugin/skills/occam/references/design.md | `When the oldest runtime a project supports moves up, look again at what it wrote for older ones` |
| guide:rule-across-many-inputs | plugin/skills/occam/references/verification.md | `A rule across many inputs` |
| guide:rules-after-recurrence | plugin/skills/occam/references/collaboration.md | `Add a rule after a mistake only once it recurs` |
| guide:run-each-command-snippet | plugin/skills/occam-docs/SKILL.md | `Run each command and snippet the way a reader would` |
| guide:run-examples | plugin/skills/occam-python/references/naming-and-docs.md | `Run the examples.` |
| guide:run-only-depth-performance | plugin/skills/occam/references/performance.md | `Run only the depth of performance testing` |
| guide:run-tests-under-asan | plugin/skills/occam-cpp/SKILL.md | `Run tests under ASan and UBSan` |
| guide:run-untouched-code-first | plugin/skills/occam/references/performance.md | `Run the untouched code first` |
| guide:run-untouched-code-first-2 | plugin/skills/occam/references/performance.md | `Run the untouched code first, with the command you will compare against` |
| guide:sample-data-usually-hides | plugin/skills/occam-sql/SKILL.md | `sample data usually hides exactly these` |
| guide:scatter-redundant-validation-through | plugin/skills/occam/references/security.md | `Don't scatter redundant validation through trusted internal code without a reason` |
| guide:search-capability-related-concepts | plugin/skills/occam/references/design.md | `Search for the capability, related concepts and alternate terminology` |
| guide:sec-cors-credentials | plugin/skills/occam/references/security.md | `Reflecting any origin with credentials` |
| guide:sec-csrf | plugin/skills/occam/references/security.md | `State-changing requests need the framework's CSRF protection` |
| guide:sec-least-access | plugin/skills/occam/references/security.md | `Give tokens, keys and roles only the access this task needs` |
| guide:sec-paid-routes | plugin/skills/occam/references/security.md | `routes that spend money or send messages` |
| guide:sec-revocation | plugin/skills/occam/references/security.md | `Logout, a password change and a role change take effect` |
| guide:sec-second-tenant | plugin/skills/occam/references/security.md | `Test with a second user and a second tenant` |
| guide:sec-skills-are-code | plugin/skills/occam/references/security.md | `is code with your permissions` |
| guide:sec-temp-copies | plugin/skills/occam/references/security.md | `Cached or temporary copies of sensitive data keep its access rules` |
| guide:sec-tool-output | plugin/skills/occam/references/security.md | `Validate structure, identifiers and target scope before acting on it` |
| guide:sec-uploads | plugin/skills/occam/references/security.md | `Check content and size rather than the name` |
| guide:sec-webhooks | plugin/skills/occam/references/security.md | `Verify the sender's signature over the raw body` |
| guide:seed-randomness | plugin/skills/occam-python/references/testing.md | `seed randomness` |
| guide:semaphore-bounds-work-flight | plugin/skills/occam-python/SKILL.md | `A semaphore bounds work in flight, but not tasks created` |
| guide:set-order-varies-between | plugin/skills/occam-python/references/testing.md | `` `set` order varies between processes `` |
| guide:shadows-standard-library-breaks | plugin/skills/occam-python/SKILL.md | `shadows the standard library and breaks that script` |
| guide:ship-schema-code-changes | plugin/skills/occam-sql/SKILL.md | `ship schema and code changes in a deployable order` |
| guide:short-code-hides-state | plugin/skills/occam/references/design.md | `Short code that hides state or failure modes isn't simple` |
| guide:shows-what-never-ran | plugin/skills/occam-python/references/testing.md | `shows what never ran, not that what ran was checked` |
| guide:signature-changing-decorators-hide | plugin/skills/occam-python/references/structure.md | `signature-changing decorators hide contracts from readers` |
| guide:signature-changing-decorators-hide-2 | plugin/skills/occam-python/references/structure.md | `signature-changing decorators hide contracts` |
| guide:silent-coercion | plugin/skills/occam/references/design.md | `silent coercion` |
| guide:similar-name-different-semantics | plugin/skills/occam/references/design.md | `A similar name with different semantics` |
| guide:since-those-hide-missing | plugin/skills/occam-python/SKILL.md | `since those can hide missing modules and data files` |
| guide:some-things-get-simplified | plugin/skills/occam-audit/references/repair.md | `Some things don't get simplified away` |
| guide:sort-stability-ties | plugin/skills/occam-python/SKILL.md | `sort stability and ties` |
| guide:spawning-better-answer-help | plugin/skills/occam-audit/references/scale.md | `Spawning for a "better answer" doesn't help` |
| guide:speculative-extensibility-pass-through | plugin/skills/occam/references/design.md | `Speculative extensibility and pass-through layers can't` |
| guide:split-where-calls-across | plugin/skills/occam-python/references/structure.md | `split where calls across the boundary are few` |
| guide:sql-concurrent-writers | plugin/skills/occam-sql/SKILL.md | `Repeatable Read still allows write skew` |
| guide:sql-keys-pages | plugin/skills/occam-sql/SKILL.md | `` give each foreign key a deliberate `ON DELETE` `` |
| guide:sql-renames-time | plugin/skills/occam-sql/SKILL.md | `a rename breaks the code still running from the last deploy` |
| guide:sqlite-prove-postgres | plugin/skills/occam-python/references/testing.md | `SQLite doesn't prove Postgres` |
| guide:src-layout-makes-tests | plugin/skills/occam-python/references/structure.md | `` a `src/` layout makes tests import the installed package `` |
| guide:staging-task-hold-production | plugin/skills/occam/references/security.md | `A staging task can hold a production token` |
| guide:state-invariant-each | plugin/skills/occam-rust/SKILL.md | `state the invariant each` |
| guide:state-invariant-each-unsafe | plugin/skills/occam-rust/SKILL.md | `` state the invariant each `unsafe` block relies on `` |
| guide:state-ownership-lifetimes-every | plugin/skills/occam-cpp/SKILL.md | `state ownership and lifetimes for every pointer you introduce` |
| guide:state-universal-gil-rules | plugin/skills/occam-python/SKILL.md | `Don't state universal GIL rules` |
| guide:static-complexity-reasoning | plugin/skills/occam/references/performance.md | `Static complexity reasoning` |
| guide:stored-data | plugin/skills/occam/references/design.md | `Stored data outlives the code.` |
| guide:structured-concurrency-avoid | plugin/skills/occam-jvm/SKILL.md | `use structured concurrency and avoid` |
| guide:style-guide-repository-enforces | plugin/skills/occam-docs/SKILL.md | `A style guide this repository enforces beats it` |
| guide:subprocess-run-raise-non | plugin/skills/occam-python/references/runtime.md | `` `subprocess.run` doesn't raise on a non-zero exit without `check=True` `` |
| guide:substantial-choices-record-options | plugin/skills/occam/references/design.md | `For substantial choices, record the options and the reason in a line or two` |
| guide:substantial-choices-record-options-2 | plugin/skills/occam/references/design.md | `For substantial choices, record the options and the reason` |
| guide:supersede-reason-stays-record | plugin/skills/occam/references/collaboration.md | `Supersede it, so the reason stays on record for whoever comes next` |
| guide:surprising-mutation | plugin/skills/occam/references/design.md | `surprising mutation` |
| guide:swallow-interruptedexception | plugin/skills/occam-jvm/SKILL.md | `` Don't swallow `InterruptedException` `` |
| guide:sync-async-semantics | plugin/skills/occam/references/design.md | `sync and async semantics` |
| guide:synthetic-data-tests-unless | plugin/skills/occam/references/security.md | `Use synthetic data for tests unless access and handling are authorized` |
| guide:sys-path-insert-hard | plugin/skills/occam-python/references/auditing.md | `` `sys.path.insert`, hard-coded `/Users/...` paths `` |
| guide:team-broadcast | plugin/skills/occam/references/collaboration.md | `tell every worker it affects` |
| guide:team-critical-path | plugin/skills/occam/references/collaboration.md | `Keep the critical path.` |
| guide:team-integrate-early | plugin/skills/occam/references/collaboration.md | `Integrate as results land,` |
| guide:team-reviewers-differ | plugin/skills/occam/references/collaboration.md | `Reviewers with the same brief share blind spots.` |
| guide:team-shared-machine | plugin/skills/occam/references/collaboration.md | `One machine is shared.` |
| guide:test-bounds | plugin/skills/occam/references/verification.md | `test both sides of it, the empty range and two ranges that meet` |
| guide:test-built-artifact-clean | plugin/skills/occam-python/SKILL.md | `test the built artifact or a clean install` |
| guide:test-cancellation-directly | plugin/skills/occam-python/references/testing.md | `Test cancellation directly` |
| guide:test-cleanup-after-failure | plugin/skills/occam/references/verification.md | `and that cleanup still ran afterwards` |
| guide:test-compat | plugin/skills/occam/references/verification.md | `old calls, old stored data and old clients still work` |
| guide:test-isolation | plugin/skills/occam/references/verification.md | `A new test should pass alone and in shuffled order` |
| guide:test-only-asserts-mock | plugin/skills/occam-python/references/testing.md | `A test that only asserts on mock calls verifies wiring, not behavior` |
| guide:test-restates-implementation-proves | plugin/skills/occam/references/verification.md | `a test that restates the implementation proves only that the code agrees with itself` |
| guide:test-same-engine | plugin/skills/occam/references/verification.md | `Run integration tests on the database engine and major version production uses` |
| guide:test-transitions | plugin/skills/occam/references/verification.md | `Each allowed and forbidden transition` |
| guide:then-reuse-existing-environment | plugin/skills/occam-python/SKILL.md | `then reuse the existing environment` |
| guide:thorough-claim-needs-make | plugin/skills/occam/SKILL.md | `Be as thorough as your claim needs, or make a smaller claim` |
| guide:todo-names-owner-issue | plugin/skills/occam-python/references/naming-and-docs.md | `` A `TODO` names an owner or issue `` |
| guide:trace-one-real-request | plugin/skills/occam-audit/SKILL.md | `Trace one real request or job end to end` |
| guide:translate-patterns-from-another | plugin/skills/occam-typescript/SKILL.md | `Don't translate patterns from another language mechanically` |
| guide:treat-author-claims | plugin/agents/code-reviewer.md | `Treat the author's claims` |
| guide:ts-async-predicates | plugin/skills/occam-typescript/SKILL.md | `treat an async callback's promise as true` |
| guide:ts-prototype | plugin/skills/occam-typescript/SKILL.md | `` a deep merge can reach `Object.prototype` `` |
| guide:ts-stale-response | plugin/skills/occam-typescript/SKILL.md | `A response that arrives after a newer request was sent` |
| guide:tsan-concurrent-code | plugin/skills/occam-cpp/SKILL.md | `TSan for concurrent code` |
| guide:turn-request-into-checks | plugin/skills/occam/SKILL.md | `Turn the request into checks that can fail` |
| guide:turns-collection-warnings-into | plugin/skills/occam-python/references/testing.md | `turns collection warnings into errors` |
| guide:two-similar-bodies-justify | plugin/skills/occam-audit/references/repair.md | `Two similar bodies don't justify a new abstraction` |
| guide:typed-library-ships-py | plugin/skills/occam-python/references/structure.md | `` A typed library ships `py.typed` `` |
| guide:types-erased | plugin/skills/occam-typescript/SKILL.md | `Types are erased` |
| guide:typescript-type-assertion-validates | plugin/skills/occam-typescript/SKILL.md | `` a TypeScript type or `as` assertion validates nothing at runtime `` |
| guide:ui-states | plugin/skills/occam/references/verification.md | `After a rejected submission the form keeps what was typed` |
| guide:unawaited-promise-loses-errors | plugin/skills/occam-typescript/SKILL.md | `an unawaited promise loses its errors` |
| guide:unbounded-goroutine-creation-leak | plugin/skills/occam-go/SKILL.md | `Unbounded goroutine creation is a leak waiting for load` |
| guide:under-document-what-matters | plugin/skills/occam-python/references/naming-and-docs.md | `under-document what matters` |
| guide:unfamiliar-changes-working-tree | plugin/hooks/rule_card.py | `Unfamiliar changes in the working tree are someone's work` |
| guide:unicode-normalization-casefolding | plugin/skills/occam-python/SKILL.md | `Unicode normalization, casefolding` |
| guide:uninitialized-reads-make-test | plugin/skills/occam-cpp/SKILL.md | `uninitialized reads can make a test pass and production fail` |
| guide:unseeded-randomness | plugin/skills/occam-python/references/notebooks.md | `unseeded randomness` |
| guide:unwrap-expect-library-request | plugin/skills/occam-rust/SKILL.md | `` `unwrap` and `expect` in library or request paths turn bad input into a panic `` |
| guide:upload-proprietary-code-analysis | plugin/skills/occam/references/design.md | `don't upload proprietary code to analysis services by default` |
| guide:useeffect-missing-dependencies-cleanup | plugin/skills/occam-typescript/SKILL.md | `` `useEffect` with missing dependencies or no cleanup `` |
| guide:user-suggests-shortcut-would | plugin/skills/occam/references/collaboration.md | `If the user suggests a shortcut that would fail, explain the failure and offer a sound alternative` |
| guide:validate-at-trust-boundaries | plugin/skills/occam/references/security.md | `Validate at trust boundaries and preserve safe defaults` |
| guide:validates-nothing-at-runtime | plugin/skills/occam-typescript/SKILL.md | `validates nothing at runtime` |
| guide:vectorize-where-conversion-cost | plugin/skills/occam-python/SKILL.md | `Vectorize where the conversion cost doesn't dominate` |
| guide:vendored-copy-gets-changed | plugin/skills/occam/references/design.md | `A vendored copy gets changed upstream` |
| guide:warnings-matter | plugin/skills/occam/references/verification.md | `A warning about an unawaited coroutine` |
| guide:what-exists-before-adding | plugin/hooks/rule_card.py | `Use what exists before adding` |
| guide:where-code-disagree-about | plugin/skills/occam/SKILL.md | `Where it and the code disagree about what exists, the code is right` |
| guide:where-it-runs | plugin/skills/occam/references/design.md | `Know how many processes and machines run this` |
| guide:which-keeps-instances-alive | plugin/skills/occam-python/SKILL.md | `which keeps instances alive until evicted` |
| guide:which-setting-wins | plugin/skills/occam/references/design.md | `Trace defaults, config files, environment and flags` |
| guide:why-it-is | plugin/skills/occam/references/design.md | `Recent history, decision records and design notes` |
| guide:worker-findings-claims | plugin/skills/occam-audit/references/scale.md | `A worker's findings are claims` |
| guide:worker-loss | plugin/skills/occam/references/performance.md | `worker loss` |
| guide:workers-die-mid-task | plugin/skills/occam/references/security.md | `workers can die mid-task` |
| guide:worktrees-isolate-files-databases | plugin/skills/occam/references/collaboration.md | `Worktrees isolate files, not databases, ports` |
| guide:worktrees-isolate-files-databases-2 | plugin/skills/occam/references/collaboration.md | `Worktrees isolate files, not databases, ports, caches, credentials, test resources or external services` |
| guide:write-temporary-file-rename | plugin/skills/occam/references/security.md | `Write to a temporary file and rename` |
| guide:write-what-caller-guess | plugin/skills/occam-python/references/naming-and-docs.md | `Write what a caller can't guess` |
