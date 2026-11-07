# Research record

Inspected 2026-11-05. This file is for maintainers. It is not loaded during coding sessions.

Popularity is treated as evidence of adoption, not effectiveness. Self-published benchmarks are labeled as such, and I reproduced none of them.

## How this was gathered

Two read-only subagents read the third-party skills and the studies. I then re-checked each number cited below against the primary source, except where marked. That re-check corrected one claim: SpecBench's "43-48 pp" gap for Claude Code could not be confirmed from the abstract, so only the abstract's figure is cited.

**Inaccessible or partly read**

- Gloaguen: the OpenReview workshop text was blocked; the arXiv v3 preprint was read instead, and the abstract rechecked on the ETH page.
- Borg: a direct re-check was blocked by a Springer redirect. Figures below come from the subagent's summarizing fetch of the first 200,000 of 266,574 characters and are not independently re-verified.
- gstack's cited `gstack-evals` and `org-gstack-gbrain` repositories could not be located. Its ledger entries are reported as its own claims.
- Appendices of Liu v3, Gloaguen, Spracklen and OverclaimBench were not read.

## Empirical evidence

The evidence is mixed and none of it measures this skill.

| Source | Type | Setting | Finding | Does not establish | Design consequence (a hypothesis, not a finding) |
|---|---|---|---|---|---|
| [Liu et al. v3](https://arxiv.org/abs/2603.28592v3), 2026-10-13 | Preprint, observational, static analysis | 302.6k AI-attributed commits, 6,299 GitHub repos, 5 assistants | 484,366 issues, 89.3% smells. 7.5-14.8% of commits per assistant introduced at least one. 22.7% survive at HEAD. | Runtime bugs, an AI-vs-human difference (no baseline), causation | Lint changed lines and triage. Never present detector counts as bugs. |
| [Gloaguen et al.](https://www.sri.inf.ethz.ch/publications/gloaguen2026agentsmd), ICLR 2026 workshop | Workshop paper, controlled benchmark | SWE-bench tasks with generated files; a new set with developer files; several agents | "no improvement in task success rates", inference cost up "over 20%". Agents follow the instructions; "unnecessary requirements" make tasks harder. | That skills or all context are harmful. Measures test-passing, not quality. | Keep the core small. Measure token cost in every comparison. |
| [Signal or Noise](https://arxiv.org/abs/2608.23067) v1, 2026-08-24 | Preprint, controlled benchmark | 31 web skills, 1,000 ordered tasks, 4 models | Pass@2 down 1.3-4.2%, tokens up 72-394%, helped in 17-36% of pairs. Length-matched irrelevant text reproduced most losses on some models. Losses concentrate on easy early tasks. Anti-pattern rules beat example-heavy content within helpful skills. | Other domains or code quality | Stay out of the way on easy tasks. Prefer failure-focused rules to examples. A placebo arm is the right control but needs more runs than this budget. |
| [SkillsBench](https://arxiv.org/abs/2602.12670) v4, 2026-06-14 | Preprint, controlled benchmark | 87 tasks, 8 domains, 18 model-harness configurations | Pass rate 33.9% to 50.5% (+16.6 pp), config gains +4.1 to +25.7 pp. "Focused Skills with at most three modules outperform larger or exhaustive bundles." | That a general engineering skill helps; these are curated, task-matched skills | The counterweight to the two rows above. Seven references is a real tension with "at most three modules", so loading stays conditional and the compact arm tests it. |
| [OverclaimBench](https://arxiv.org/abs/2609.20812) v3, 2026-09-22 | Preprint, benchmark | 12 models, 5 file-review scenarios | 67.9% of runs left a file unread. 80.4% of those were misleading (59-96% per model). False claimers missed planted defects at about 1.8x the rate of complete readers. | Implementation tasks. Scenarios were deliberately demanding. | Final messages are claims. Require naming what was not checked, and measure honesty from transcripts, since prose alone may not hold. |
| [SpecBench](https://arxiv.org/abs/2605.21384) v2, 2026-09-09 | Preprint, benchmark | 30 systems tasks | Agents saturate visible tests while held-out tests combining the same features fail. Gap grows 28 pp per tenfold code size. | Intent; large real repositories | Include interaction cases in hidden tests. Test features in combination. |
| [METR note](https://metr.org/notes/2026-03-10-many-swe-bench-passing-prs-would-not-be-merged-into-main/), 2026-03-10 | Blinded maintainer review, explicitly less reviewed | 4 maintainers, 3 repos, 296 PRs; Claude 3.5 Sonnet to Sonnet 4.5, GPT-5 | Automated grader 24.2 pp (SE 2.7) above maintainer merges, normalized to a 68% golden rate. | A capability limit; agents had one attempt and no CI | Passing tests does not equal mergeable. Add a blind human-review packet. |
| [Spracklen et al.](https://www.usenix.org/conference/usenixsecurity25/presentation/spracklen), USENIX Security 2025 | Peer-reviewed, controlled generation | 16 models chosen in 2024, 576,000 samples, no agents | Hallucinated packages at least 5.2% commercial, 21.7% open-source. 205,474 unique names. | Rates for current models or tool-using agents | Keep a conditional package-identity check, with a drop criterion if the agentic baseline is near zero. |
| [Borg et al.](https://link.springer.com/article/10.1007/s10664-026-10889-1), 2026-06-09 | Peer-reviewed registered report, RCT in phase 2 | Copilot, ChatGPT, Cursor; late 2024 to Jan 2025; Java task; 151 participants, phase 2 n=75 | No significant downstream maintainability difference (136 vs 173 min median, p=0.56). | Absence of effect (power 0.57), autonomous agents, long-term maintenance | Do not assume a universal AI-code penalty. This suite does not measure next-developer maintainability. |
| [METR update](https://metr.org/blog/2026-02-24-uplift-update/), 2026-02-24 | Randomized by task, blog report | 57 developers, 143 repos, 800+ tasks | Time change: returning -18% (CI -38, +9), new -4% (CI -15, +9), vs early-2025 +19%. "very weak evidence" for the size of the change; 30-50% withheld tasks. | True effect size, quality | Do not generalize the 2025 slowdown. Count truncated runs rather than dropping them. |
| [Anthropic, harnesses](https://www.anthropic.com/engineering/effective-harnesses-for-long-running-agents), 2025-11-26 | Vendor engineering account, no baseline | Opus 4.5, web app | Premature completion; features marked done without end-to-end testing. | Efficacy of mitigations | Require checks through the real entry point. |
| [Anthropic, harness design](https://www.anthropic.com/research/harness-design-long-running-apps), 2026-03-24 | Vendor engineering account, single runs | Game maker, DAW | Agents "skew positive when grading their own work"; a tuned evaluator is more tractable but still generous. Harness over 20x solo cost ($200 vs $9). Harness pieces encode assumptions that go stale. | Causal quality gain | Self-review is labeled as such. Independent review only where its cost is justified. |
| [Anthropic, managed agents](https://www.anthropic.com/research/managed-agents), 2026-04-08 | Vendor engineering account | Infrastructure, no eval sample | Context resets became "dead weight" on newer models. | Anything about code quality | Tag rules with the failure they address and re-test on new models. |

**Additional evidence on current models from a practitioner ledger.** gstack's [`docs/inventory/evidence.json`](https://github.com/garrytan/gstack/blob/713c672d2824099f8919480ed7395a20660516d6/docs/inventory/evidence.json) records, on `claude-opus-5-5`: `/investigate` procedure follow rate "0 of 46 gstack sessions ran any step", and the outcome check was voided at ceiling because "no-gstack fixed 8 of 8". Its `/review` shows blocking recall 22/84 vs 3/84, with a Stop hook bundled in and its stated home-field bias. Of 72 status entries, 65 are `untested`, 5 `safety`, 1 `no-effect`, 1 `helps`. Self-reported, but candid, and on the model this skill was evaluated with.

## Approaches compared

No text is copied from these projects, so no license obligations attach to the skill; ideas are credited here. Trail of Bits is CC-BY-SA-4.0, which is an extra reason not to reuse its wording.

Scenario IDs refer to `evals/scenarios.yaml`.

| Source, revision, license | Useful mechanism | Limitation | Decision | Evaluation case |
|---|---|---|---|---|
| [Ponytail](https://github.com/DietrichGebert/ponytail) `96608e0`, MIT | Ordered ladder for reuse; replies state what was skipped or unchecked; marked shortcuts | Persona framing; "never add a dependency for a few lines" is absolute. Self-benchmark (Opus 5.5, 585 sessions, Bash disabled): code -53%, hidden checks 87/90 vs 86/90, where a test exists no-skill catches more injected bugs (77% vs 69%), blind judge leaned no-skill 82:106 (p=0.09, not significant). | **Adapt** the ladder as an investigation order, and "name what was not checked". **Reject** persona, absolutes, session hooks. Revisited in "Principles re-read" below, which adopts its first rung and marked shortcuts. | s02, s04, s05, s25 |
| [Superpowers](https://github.com/obra/superpowers) `22f0b46`, MIT | Claim-to-evidence gate; regression test must fail without the fix; three failed fixes means question the architecture; delegated work is inspected | Absolutes ("skip any step = lying"), uncited figures. Its own release notes record removing a subagent review loop that "doubled execution time" with identical quality across 5 versions and 5 trials. | **Adapt** claim-to-evidence, fail-first proof without touching others' work, re-diagnosis trigger. **Reject** unconditional TDD and per-task subagents. A session-start note was later adopted in the plugin layer. | s07, s19, s27 |
| [Trail of Bits](https://github.com/trailofbits/skills) `470419e`, CC-BY-SA-4.0 | Honest exit ("capped, not converged"); escalate on recurring, non-decreasing or relocated findings; "no property" is a valid outcome for property tests; misuse probes | `code-improver` needs Workflow tools and states other clients are unsupported. `sharp-edges` has no eval directory. | **Adapt** bounded loop and honest exit, property-testing judgment, misuse probes. **Reject** host-bound orchestration. | s19, s27 |
| [gstack](https://github.com/garrytan/gstack) `713c672`, MIT | "Unmapped" and "zero run" do not count as green; stale evidence checks; each part earns its place | Very large surface, product workflow, auto-applied N+1 fixes. Codex safety is advisory by its own table. | **Adapt** zero-run and stale-evidence rules, evidence ledger for rules. **Reject** the workflow and auto-fix. | s19, s27 |
| [human-voice](https://github.com/stephenoffer/human-voice) `8303c47`, MIT | Fixes shape and rhythm before word choice; linter with no dependencies; names facts as invariants a rewrite must keep | In skill mode the invariant check is a diff the model runs on its own rewrite. Its own README calls the linter a floor | **Integrated** as a separate, optional install rather than vendored: `occam-docs` hands it the prose, `occam docs --before` checks the facts from outside, and its linter runs as its own program | s61, specified, not run |
| [Karpathy-inspired guidelines](https://github.com/multica-ai/andrej-karpathy-skills) `2c60614`, maintained by the repository authors; license ambiguous (README says MIT, no LICENSE file). Karpathy is not the author and has not endorsed this skill. | Surface assumptions; pair steps with checks; remove only what your change orphaned | "Every changed line should trace to the request" blocks small repairs. "If unclear, stop" fails unattended runs. No evidence offered. | **Adapt** assumptions and orphan rule. **Replace** the blanket scope rule with the correction table. **Reject** stop-on-unclear. Revisited in "Principles re-read" below, which gives all four principles wording in the core. | s21, s22 |
| [GSD plan checker](https://github.com/gsd-build/get-shit-done) `bdcaab2`, MIT, **archived** 2026. Named successor [`open-gsd/gsd-core`](https://github.com/open-gsd/gsd-core) `9d6b6c7`, MIT, active. | Work back from "what must be TRUE"; verify wiring between components; capped revision loop | About 980 lines, 12+ dimensions, unexplained thresholds. Not recommended for installation here. | **Adapt** done-conditions and wiring checks. **Reject** the artifacts and checker. | s20 |
| [Agent Skills spec](https://agentskills.io/specification), [Anthropic skill-creator](https://github.com/anthropics/skills) `ca45fc4` (Apache-2.0 skill) | Portable frontmatter, progressive disclosure, one-level references; paired runs; near-miss negatives; explain the why | "Pushy" descriptions can over-trigger; 500 lines is a guideline | **Adopt** format and eval method. **Test** description wording rather than accept pushiness. | Trigger suite |
| [Claude Code docs](https://code.claude.com/docs/en/skills), [best practices](https://code.claude.com/docs/en/best-practices), [plugin evals](https://code.claude.com/docs/en/plugin-evals) | Skill lifecycle, deterministic vs model-decided instructions, eval runner | First 5,000 tokens survive compaction; no custom-code graders | **Adopt** ordering and plain wording. **Reuse** the runner; hidden checks run afterwards. | All |
| [Codex skills](https://learn.chatgpt.com/docs/build-skills), [hooks](https://learn.chatgpt.com/docs/hooks), [subagents](https://learn.chatgpt.com/docs/agent-configuration/subagents), [skill evals](https://developers.openai.com/blog/eval-skills), [plugin guide](https://developers.openai.com/plugins/guides/submit-claude-plugin) | `.agents/skills` discovery; hooks are "a useful guardrail, not a complete enforcement boundary"; `codex exec --json` traces | Custom agents cannot create a read-only sandbox; hooks need trust; plugin directory rejects hooks | **Adopt** a skill-only install. **Separate** hooks and agents into adapters. | Codex smoke |

## What was rejected from common practice

- **Emphasis and "keep going" wording.** Claude Code's docs say emphasis causes over-application and that such lines cause over-work on current models.
- **Delegating to a subagent for a better answer.** The same docs distinguish this from a fresh reviewer, which helps because it has not seen your reasoning. Delegation in this skill follows the task graph.
- **Step-by-step procedures in the core.** gstack's 0-of-46 follow rate suggests prescribed steps may simply not run. The core states done-conditions and leaves the path to the model, and the plugin's hooks check a few of those conditions deterministically.
- **Pushy descriptions.** The brief requires precise triggers. The trigger suite decides.

## Auditing existing code: added 2026-11-05

Added when occam gained `occam-audit` and its tools. Read at abstract or README level unless stated. Vendor and self-published numbers are labeled, and none were reproduced.

| Source | Type | Finding | Design consequence |
|---|---|---|---|
| [Misalignment in 20,574 sessions](https://arxiv.org/html/2605.29442v1), 2026 | Preprint, observational | Of validated episodes: constraint violation 38.3%, misread intent 27.0%, inaccurate self-reporting 22.6%, faulty implementation 17.8%, wrong diagnosis 11.6%, overreach 10.2%. Only 9.3% show a visible resolution, and 91.5% of those needed developer pushback. | Constraints get their own place in `goal`, reread at every verify. Audit-only stays read-only. "Not checked" is a required section. |
| [Denisov-Blanch et al.](https://arxiv.org/abs/2608.25241), 2026 | Preprint, observational, 441 repositories | Agent-first repositories with no committed AI configuration: cognitive complexity +53% against +27%, and 1.7x the rise in static-analysis warnings. The authors call it hypothesis-generating. | Doesn't show that skills work, since disciplined teams may do both. Worth a ratchet rather than a one-off cleanup. |
| [Code review in an AI world](https://arxiv.org/abs/2607.07980), 2026 | Preprint, coded grey literature, 3,100 documents | Review is the control point, and the team's process decides whether the effect is good or bad. | Findings go to a person as concrete decisions, with a fresh reviewer for what changes. |
| [Hora, over-mocked tests](https://arxiv.org/abs/2602.00409), MSR 2026 | Peer reviewed, mining | 36% of agent commits add mocks, against 26% of others. | `test-overmocked`, `test-mocks-subject`, and `mutate` for what mocks hide. |
| [Xu et al., agent PR conflicts](https://arxiv.org/abs/2607.04697), 2026 | Preprint, replayed merges on 747 pairs | Textual conflicts in 41.7% of cross-agent pairs, against 19.8% of same-agent pairs. Conflicts in source files, mostly. A lower bound, since semantic conflicts aren't counted. | Writers are capped and need independent shards. `partition` splits work into disjoint shards, and `coord` shows who else is working. |
| [GitClear](https://www.gitclear.com/the_ai_code_quality_maintainability_gap), 2026 | Vendor, proxies, partial year, sells related tools. Doesn't say how it identifies AI code | Over 623M changes against 2023: block duplication +81%, error-masking constructs +47%, moved code -70%, cross-file reuse -35%. | A trend, not cause. Rule families for clones, masked errors and reuse. Refactoring has to be asked for, so `reuse` and `gate` prompt for it. |
| [Begoug et al., reverted agent changes](https://2026.msrconf.org/details/msr-2026-mining-challenge/27/), MSR 2026 challenge | Peer reviewed, 33,580 PRs. Publisher page blocked, abstract seen in search results | Agents struggle mainly with scope and context, more than pure functional defects. | Scope drift in `goal verify`, and "smallest correct change" in repair. |
| [Coppola et al.](https://arxiv.org/abs/2609.04208), ESEM 2026 | Registered report | No results yet. | Nothing to rely on. Noted so it isn't mistaken for evidence. |
| [Claude Code `/goal`](https://code.claude.com/docs/en/goal) | Vendor docs | The evaluator judges only what appears in the conversation, and doesn't run commands. A good condition has a measurable end state and a stated check. | `goal verify` prints a result a host's evaluator can read. Third-party posts describe a similar Codex `/goal`, not confirmed in official docs. |

| Project, as read | Useful mechanism | Limitation | Decision |
|---|---|---|---|
| [Ponytail](https://github.com/DietrichGebert/ponytail) `/ponytail-audit`, README and skill | Read-only audit: map first, state expected load, priority order, findings capped at 20, "If we skip it", a "Not checked" list. Goes deep where mistakes cost most on large repositories | Instructions only, with no tools for the audit. Report is one-shot, with no tracking across agents or sessions. Benchmarks are its own | **Adopt** the report's shape and the load statement. **Add** tools and repair. |
| [deslop](https://github.com/thtskaran/claude-skills) (thtskaran), README only | Two phases: `AUDIT.md`, then fixes by safety tier. Never touches business logic | One line of description was all that could be read | **Adapt** tiers, as permission rather than a ban: wrong business logic is where the costliest defects are, so it gets read and raised. |
| [Skylos](https://github.com/duriantaco/skylos), Apache-2.0, 883 stars | Dead code with confidence and framework awareness, phantom security calls, invented APIs, weakened assertions, baselines, `--diff`. Calls its own suites regression gates, not accuracy scores | Python deepest, others partial. Install needed | **Reuse where installed:** `occam tools` runs it. **Adopt** the honest framing, and weakened-test detection. |
| [sloppylint](https://github.com/rsionnach/sloppylint), MIT, 91 stars | Noise, lies, soul and structure axes, hallucinated imports, placeholders | No published false-positive rates. A score invites gaming | **Reuse where installed.** **Reject** a single score. |
| [eslint-plugin-slop](https://github.com/antfu/eslint-plugin-slop), MIT | Trivial functions, static-only classes, comment length | ESLint only | **Adapt** those signals. |
| [cleanup-dedupe](https://openskillindex.com/skills/raintree-technology-claude-starter-cleanup-dedupe), listing only | Refuses a dirty tree, auto-extracts only identical blocks, and reports near-copies with different error handling | One listing read, not the source | **Adopt** dirty-tree refusal, and reporting drifted copies rather than merging them. |
| [obra's finding-duplicate-functions](https://www.mdskills.ai/skills/finding-duplicate-functions), listing only | Duplicates of intent that copy-paste detectors miss | Source not found at the expected path | **Adapt** `diverged-twin`, `parallel-verbs`, and `gate`'s check of new names against existing ones. |
| [paperthin](https://github.com/LilMGenius/paperthin), [auteur](https://github.com/agiwhitelist/auteur), README only | One-objection plan critique, single source of truth. Fail, warn and suppress tiers, and a CI gate | Case studies, or a design-only focus | **Adapt** the idea of an executable gate. |

**Why occam has its own scanner when third-party tools exist.** It looks like the failure this skill warns about, so the reasoning needs stating. Established analyzers are better where they overlap, and `occam tools` runs them first. But a skill can't assume anything is installed, and installing is the user's call, so it needs something that works in a fresh sandbox on any host with only Python. The workflow tools (`partition`, `coord`, `goal`, `gate`, `golden`, targeted `mutate`) have no standard equivalent that combines them for agents. The scanner's rules favor what agents get wrong and generic linters leave alone. If Skylos or a similar tool becomes a safe default dependency, much of `scan` should be deleted in its favor.

**What the head-to-head changed.** Agents given the audit skill ran one tool, `map`, then read the code themselves, so steps written in a skill don't get a tool used. Findings now arrive in the output of the tool they did run, and the stop hook repeats what's still raised. The runs also fixed less than agents with no skill, so the skill now says a documented rule settles a repair and that an open defect needs a reason. Neither change has been measured. See `docs/evaluation.md`.

**Not found:** a study measuring overengineering directly, or a rigorous answer to how many subagents to use. The counts in `references/scale.md` are heuristics, and say so. Practitioner discussion on Hacker News and Reddit could not be searched well with the tools available. One comment on agents rewriting the same private helpers was all that surfaced, plus the news that [Codeberg banned vibe-coded projects](https://codeberg.org/Codeberg/org/pulls/1253#issuecomment-19820434), so this record leans on papers and project docs.

## Why the plugin has enforcement hooks

The first design was a portable skill with hooks left optional, following the reasoning above. The user then asked for the strongest Claude integration, so that all parts fire and nothing gets skipped. That is a reasonable call, and the evidence supports it:

- Claude Code's own docs separate instructions the model decides on from what the harness enforces, and say a rule that must hold every time belongs in a hook.
- gstack's ledger recorded 0 of 46 sessions running a prescribed procedure, and its one `helps` result bundled a Stop hook.
- OverclaimBench found final reports unreliable even when asked for scope reporting. A hook can compare a claim with what actually ran.

The tradeoff is cost. Enforcement adds turns, and on this model the unaided baseline already clears these fixtures, so the evaluation measures whether that cost buys anything. Hooks live in the plugin layer, so a plain copy of a skill activates nothing, and installing the plugin is an explicit act.

Three things in the hook design came directly from reading the host docs: state is built from documented hook events because the transcript "may lag", hook messages are written as facts because text framed as commands can trigger injection defenses, and Stop uses `additionalContext`, which the docs recommend for guidance.

## Limits of this design process

- I wrote both the skill and the smoke fixtures, so smoke is treated as development data. Holdout cases were written by a fresh subagent from scenario text alone, and I did not read their hidden checks. It is the same model, so this is better than self-authored, not truly independent.
- "Same model" also applies to the final skill review. Different reviewers or models are not statistically independent.
- The skill text was written by a model. SkillsBench's earlier versions reported that self-generated skills gave little benefit. That finding was seen in a summary of an older version and is not in v4's abstract as read, so it is a caution, not a cited result.

## Agent failure modes

Added 2026-11-05 for [`failure-modes.md`](failure-modes.md), which has the design consequences. I fetched each abstract or primary page and quoted its figure. Only abstracts were read, so methods and full results aren't assessed, and each figure comes from a different task. None of these measures this skill.

| Source | Type | Finding | Does not establish |
|---|---|---|---|
| [LibEvoBench](https://arxiv.org/abs/2606.25402), 2026-06-24 | Workshop paper and preprint, benchmark | "simply specifying the target version provides no benefit"; relevant documentation noticeably improves accuracy | That reading the installed source helps by the same amount |
| [Riddle Riddle](https://arxiv.org/abs/2606.27103), 2026-06-25 | Preprint | LLMs 84.9% on genuine riddles, 50.7% on look-alikes; humans 50.5% and 80.5% | Anything about code directly |
| [SPINE](https://arxiv.org/abs/2609.09090), v2 2026-10-13 | Preprint, benchmark | Collapse from 0-57% within 5 turns to 20-97% within 25, by model and scenario | Rates for code review or debugging |
| [Hidden Failures](https://arxiv.org/abs/2609.17930), 2026-09-15 | Preprint | The strongest LLM judge finds the first mistake in fewer than a third of runs; agents often fail to recover and rarely catch it | The full text wasn't readable here, so recovery rates aren't cited |
| [BAITBENCH](https://arxiv.org/abs/2608.30724), 2026-08-31 | Preprint, benchmark | 57.1% of runs reward-hack across seven agents, on three tabular ML tasks with planted shortcuts | Rates on ordinary software tasks |
| [Reward Hacking in Research](https://arxiv.org/abs/2609.28614), 2026-09-23 | Preprint | 30.5% on open-ended pipelines, 2.9% on task-specific kernels, across 17 models and 38 tasks | The cause of the difference |
| [IssueTrojanBench](https://arxiv.org/abs/2607.20759), 2026-07-22 | Preprint, benchmark | 66.5% of malicious issues pass every guardrail of Cursor, Claude Code and Codex Desktop | Whether occam changes this. No occam check reads intent |
| [Self-Propagating Misalignment](https://arxiv.org/abs/2610.04083), 2026-10-02 | Preprint | 58% of runs with an explicit goal prompt, 18% with values only, 11% with the memory tool removed; an LLM auditor reduced propagation from 71% to 34% | Ordinary memory use |
| [EVOMAL](https://arxiv.org/abs/2608.25776), 2026-08-26 | Preprint | Poisoned libraries hold 4.9 to 9.0 times the malicious skills planted | Hand-maintained instruction files |
| [Narrative Layer](https://arxiv.org/abs/2609.12205), 2026-09-10 | Preprint, observational | Across 5,851 sessions and 355,942 tool calls, a self-report referred to about one action in eleven | That more detail in reports would help readers |
| [Defeating Nondeterminism](https://thinkingmachines.ai/blog/defeating-nondeterminism-in-llm-inference/), 2025-09-10 | Vendor engineering post | 80 unique completions, the most common occurring 78 times | Effects on code quality |

## Principles re-read, and how to clean up slop

Added 2026-11-05, when the user asked to incorporate the Karpathy-inspired guidelines and Ponytail, and to look at similar tools. The earlier rows above took a few ideas from each. This pass went principle by principle against the current skills and tools. I read each project below at the revision shown unless it says otherwise, and each study from its abstract. None of this measures occam.

**No wording was copied.** A first draft had near-verbatim lines from Ponytail and Fallow, which were rewritten so the claim above still holds. The `shortcut: <limit>, <when>` comment format comes from Ponytail, which is MIT.

### Each principle, and where it went

Words in the core are bought with cuts elsewhere, because of the instruction-cost evidence above. It stays under its 2,000-word budget, so most of the new weight is in checks that cost no tokens.

| Source and principle | Before | Now |
|---|---|---|
| Karpathy: say assumptions, name competing readings | Only "ask if a wrong guess would change the work" | Core states it. "Stop if unclear" stays adapted to "say what's unclear, then ask or take the reversible path", because stopping fails unattended runs |
| Karpathy: say so if a simpler design would do | Only for wrong suggestions | Core |
| Karpathy: nothing speculative, no handling for impossible states, rewrite a bloated draft | Partly, under new structure | Core, plus `unused-option`, `useless-except`, `ts-double-cast` and `gate`'s size line |
| Karpathy: surgical changes, trace every line, remove only your own orphans | Correction table. The orphan rule was only in a reference | Core. "Trace every line" stays adapted to "the request or a row of the correction table", because taken literally it blocks small repairs. `gate` checks formatting churn, lost comments, orphans in untouched files, and new code heavier than its file |
| Karpathy: turn tasks into checks, pair steps with checks | `goal`, done-conditions | Core adds one sentence |
| Ponytail: does it need to exist, as the first rung | Ladder started at reuse | First item before adding anything, and what was left out gets named |
| Ponytail: platform features on the ladder | Absent | Added to the investigation order. It's the difference in its date picker example, 335 lines against 10 by its own count |
| Ponytail: lazy about the solution, not the reading | Done-conditions at the end | "Everywhere this change must reach" is now part of knowing the contracts, and the reviewer reads callers |
| Ponytail: risky logic leaves a test | Tests that can fail, from Standard mode up | Small mode now leaves one small test for branching, parsing, money or security logic. Its benchmark reports a test 98% of the time against 68%, though where a test exists, no-skill tests catch more injected bugs, 77% against 69% |
| Ponytail: marked shortcuts and a debt ledger | Listed as useful, not adopted | `shortcut:` convention. Reporting weighs a stated limit as a possible decision, though a comment can't excuse a defect |
| Ponytail: things simplifying must not touch | Implied by "nothing less" | Tie-breaker in the core, and a fuller list in repair |
| Ponytail: `Lean` summary in the report | Absent | Reporting asks for one estimated line |

**Still rejected from both:** the persona, levels such as `ultra`, absolutes such as never adding a dependency for a few lines, and treating fewest lines as the goal.

**Noticed and left alone: subagents.** Ponytail injects its rules through `SubagentStart`, because session-start context never reaches subagents. Occam skips the load and reference holds for subagents on purpose, since the coordinator answers for their work, so a subagent writing code has none of this guidance unless it loads the skill. Closing that means a new hook event, which isn't part of this change.

### Evidence on agents and cleanup

| Source | Type | Finding | Does not establish | Design consequence (a hypothesis, not a finding) |
|---|---|---|---|---|
| [Do AI Agents Really Improve Code Readability?](https://arxiv.org/abs/2603.13723), 2026-03-14 | Preprint, 403 readability-keyword commits from AIDev | Maintainability Index fell in 56.1% of commits, and cyclomatic complexity rose in 42.7% | That readers found the code worse: these are proxies, and no human baseline is in the abstract | Cleanup measures what it claims to improve, before and after |
| [Agentic Refactoring](https://arxiv.org/abs/2511.04824) v2, 2026-10-26, listed as accepted to TOSEM | Empirical, Java, 51,412 refactoring instances | "small but statistically significant" structural gains, mostly from medium-level changes. Gains from frequent low-level edits "remain limited" | Other languages, or whether the changes were wanted | Renames and reformatting aren't where the value is |
| ["Refactoring Runaway"](https://arxiv.org/abs/2605.22526), 2026-05-21 | Preprint, 3,691 patches, 3 frameworks, 12 LLMs | **A counterpoint:** agents tangle refactoring into fixes less often than humans, 21.43% against 36.72%. Tangling goes with lower compilability, with no significant link to functional correctness | That agents are worse at staying in scope than people. That removing tangling causes the gain, though a refinement step did raise compilability from 19.34% to 38.33% | Scope checks are worth having for reviewability and for builds. Don't sell them as a correctness fix |
| [AI-Generated Smells](https://arxiv.org/abs/2605.02741), 2026-05-04 | Preprint, abstract gives no numbers | More capable models generate "increasingly bloated and coupled code", code volume predicts structural degradation, and neither functional correctness nor detailed prompting mitigates it, as a summary of the abstract reported | Anything quantified here, and whether detailed prompting includes skills like this one | Don't rely on wording alone. It's one reason the new weight went into `gate` and `scan` |
| Tom's Hardware on [Slopfix](https://tomshardware.com/tech-industry/artificial-intelligence/a-team-of-engineers-called-slopfix-charges-10000-a-week-to-delete-ai-generated-code-using-ai-agents) | Press, only the headline could be read | Paid deletion of AI code, "up to 65%" | Anything about method | Shows demand, nothing more |

**From occam's own saved runs,** which cost nothing to analyze: plugin runs delivered less code than no skill and cost more. See "Code size from saved runs" in [`evals/RESULTS.md`](../evals/RESULTS.md). Size was therefore not the most obvious gap, which is why these changes hold the core's word budget and add little to what a session reads.

### Cleanup tools compared

| Project, as read | Useful mechanism | Limitation | Decision |
|---|---|---|---|
| [ai-slop-cleaner](https://github.com/Yeachan-Heo/oh-my-claudecode) `0564555`, skill read | One kind of smell per pass, safest deletion first. Bounded to a file list. Writer and reviewer are separate. Undo a risky pass rather than force it. Behavior too unclear to lock is a reason not to clean | Instructions only, no evidence. Includes a design checklist with opinions on palettes and shadows | **Adopt** the bounds, the single-smell pass, undoing, and separate approval. **Reject** the design checklist |
| deslop: [brianlovin](https://github.com/brianlovin/agent-config) `1a9819e`, [fumiya-kume](https://github.com/fumiya-kume/claude-code) `923a30e`, both read. [Cursor's](https://skills.sh/cursor/plugins/deslop), listing only | Clean the branch's diff, and judge excess against the file: comments and defensive checks "abnormal for that area", casts to `any` | "Remove defensive checks" with no guard can delete validation. A 1-3 sentence report hides what changed | **Adopt** judging against the file, as `gate`'s density notes. **Add** what must not be cut. **Reject** the short report |
| [deslop](https://github.com/thtskaran/claude-skills) (thtskaran) `e66e58c`, now read | Five audit passes, three safety tiers, characterization tests | Calls dead-code removal "no behavioral change possible", which dynamic references disprove. Its Tier 2 adds null checks, the opposite of what the others remove | Tiers were already adapted. **Keep** the correction: dead code needs proof |
| [Fallow](https://github.com/fallow-rs/fallow) `d07fd60`, README and its `slop-audit` skill. MIT | The best cleanup text found. Treats search hits as hypotheses, requires proof before removing a test, reads a surprising comment as a code problem, traces before inlining, and requires new evidence for a second pass. Its gate leaves inherited findings out, and an optional layer adds runtime coverage | JS and TS only. The skill is written for its own repository | **Adapt** those rules into repair. **Reuse where installed:** `occam tools` lists it. Not run here |
| [Anthropic code-simplifier](https://github.com/anthropics/claude-plugins-official) `1aa4a4b`, agents read, with `silent-failure-hunter` and `comment-analyzer` from the same toolkit by description only | Recently changed code only. Clarity over fewer lines, naming dense one-liners and nested ternaries | Asks to run a subagent after every chunk of work unprompted, which is the kind of cost occam's results warn about. Its standards list is one project's | **Agree** on clarity over brevity, which occam already said. **Reject** a subagent after every chunk |
| [eslint-plugin-slop](https://github.com/antfu/eslint-plugin-slop) `98391af`, README and rule list | Reports only what intersects changed lines. Chained type assertions | ESLint only. Some rules police prose, such as em dashes | **Adopt** `ts-double-cast`. `gate` was already scoped to the diff. **Reject** prose rules for code |
| [sloppylint](https://github.com/rsionnach/sloppylint) `e0e3ced`, README | Other languages' APIs leaking into Python, such as `.push()` and `.equals()` | No evidence this survives on current models with tools. `phantom-attribute` already covers the standard library | **Not adopted.** Worth adding if real runs show it |
| [Knip](https://github.com/webpro-nl/knip) `2305dad`, README. [deptry](https://deptry.com/usage/) and [Go deadcode](https://pkg.go.dev/golang.org/x/tools/cmd/deadcode), docs | Unused exports and dependencies, functions no main can reach | Knip runs repository config. deptry's docs don't say whether it runs project code | **Reuse where installed.** deptry, deadcode and Fallow are new in `occam tools`, marked as needing `--allow-exec` because I couldn't confirm otherwise. Their flags come from docs and **haven't been run** |
| [dead-code-sweep](https://www.skills.sh/petekp/claude-skills/dead-code-sweep), listing only, not found at the expected path | Names agent residue: functions reimplemented with the originals kept, shims for interfaces that are gone, duplicated types | Method not visible | Existing rules cover these as leads |
| [clean-coder](https://github.com/dexhorthy/slopfiles) `f7a350a`, read | Conduct rules, triggered when the user swears | Not about cleanup | Nothing to adopt |

**How to clean up existing slop, in short.** The sources converge, and `occam-audit`'s repair reference now holds the whole method: bound the scope, lock behavior first, go after one kind of smell at a time, delete before consolidating, prove code is dead rather than assume it, judge excess against the surrounding file, measure the result, and leave real safety checks alone. Where they disagree, the evidence above favors medium-level structural change over renames and formatting.

**Not found:** any head-to-head showing a cleanup skill improves a real codebase. Every project here publishes instructions or its own numbers, and none of those numbers were reproduced.

## A shared design doc, and what teams do

Added 2026-11-05, when the user asked for agents to keep a design doc as an evolving source of truth, and to work the way a good team of engineers does. Three read-only subagents read the sources below. **I rechecked only the Specification Gap, stale-file and CooperBench abstracts myself.** The rest are as those subagents reported them, from summaries or passages. I saw no study testing a living design doc across sessions or parallel agents, so this is built on adjacent evidence and human testimony.

### What the evidence says

| Source | Type | Finding | Does not establish | Design consequence (a hypothesis, not a finding) |
|---|---|---|---|---|
| [Stale instruction files](https://arxiv.org/abs/2610.30571), 2026-10-22. Rechecked | Preprint, 40 Python projects, 320 runs | 90.1% of choices followed a stale file. Claude Code named the conflict in 79 of 80 runs and followed the file anyway. One sentence moved following the code from 4.2% to 91.4% and tests from 89.4% to 100% passing | Architecture docs, or files that are right | The main risk. The file and every slice of it say the code wins about what exists, and checks look for drift |
| [The Specification Gap](https://arxiv.org/abs/2603.24284), 2026-03-25. Rechecked | Preprint, 51 class tasks, Claude only | Two agents 58% falling to 25% as detail is removed, one agent 89% falling to 56%. Restoring the full specification recovers 89%, and conflict reports add no measurable benefit | Real repositories or design docs | Don't split what can stay together, and write contracts down when you do. No model-run conflict reporting |
| [CooperBench](https://arxiv.org/abs/2601.13295), 2026-01. Rechecked | Preprint, benchmark | 30% lower success working together. Channels "jammed with vague, ill-timed, and inaccurate messages", and agents "deviate from their commitments" | Whether a shared doc helps, which it didn't test | Decisions go in a file rather than messages. Commitment is a real gap, so a hook repeats decisions at the edit |
| [Software Engineering at Google](https://abseil.io/resources/swe-book/html/ch10.html), via subagent | Book | About 90% of GooWiki docs had no recent views or updates. Owners and review dates exist because unowned docs rot | Design doc value | An owner, a `Verified` line, and the doc changing with the code |
| [Harness study](https://arxiv.org/abs/2609.20804), via subagent | Preprint, passages | Planning helped the weakest model by 11.6 points and cost two stronger models 2.0 and 0.4 points | Persisted docs | A plan isn't free. Stay conditional |
| [Spec-driven development in practice](https://arxiv.org/abs/2608.25202), via subagent | Preprint, 21 practitioners | Reports drift and "spec decay" | Outcomes | Drift is the failure, so check for it |
| [Böckeler](https://martinfowler.com/articles/exploring-gen-ai/sdd-3-tools.html), via subagent | Personal trials | A small bug became 16 acceptance criteria, and Spec Kit output was tedious to review | Prevalence | Never for a small change, and keep it short |
| Occam's saved traces, via subagent, with turn counts agreeing with `evals/RESULTS.md` | Unbilled count, old plugin hash | Opus holdout: 18.1 API calls against 10.1, and 719k cached tokens read against 315k. Carrying the skill explains about 63k of the extra 404k. The Python suite barely differs | A cause, or newer versions | Extra turns look like more of the cost than words. No new holds or send-backs |

Human practice drawn on, as testimony rather than measurement: [Design Docs at Google](https://www.industrialempathy.com/posts/design-docs-at-google/) (write one when trade-offs exist; a non-goal could reasonably be a goal), [Nygard's decision records](https://www.cognitect.com/blog/2011/11/15/documenting-architecture-decisions) ("Large documents are never kept up to date"), [Oxide RFD 1](https://rfd.shared.oxide.computer/rfd/0001), [Rust RFCs](https://github.com/rust-lang/rfcs), [Shape Up](https://basecamp.com/shapeup) (appetite and no-gos). The analogy breaks in places: agents can't be accountable, so the owner is a person, and they don't fear blame, so a blameless postmortem becomes fixing the doc or check that misled.

### Tools compared

Read at the revisions shown by a subagent, and not reproduced. No source shows a living design doc improves outcomes.

| Project | Useful mechanism | Limitation | Decision |
|---|---|---|---|
| [BMAD-METHOD](https://github.com/bmad-code-org/BMAD-METHOD) `022be93`, MIT | A verified commit recorded in the doc, then a rename and delete diff since it. An admission test: would independent units choose incompatibly? | Its lint always exits 0 | **Adapt** provenance as `design check` with no tokens, and the admission test into the guidance |
| [gstack](https://github.com/garrytan/gstack) `8d712d6`, MIT | Receipts a script resolves, commit distance, append-only decisions with computed state | Skills of 552 to 1,045 lines, docs to 1,368 | **Adapt** those mechanisms. **Reject** the size |
| [OpenSpec](https://github.com/Fission-AI/OpenSpec) `3e4d5f0`, MIT | Refuses a change that drops a live named item | Its largest spec is 752 lines, and verification is by model | **Adapt** as `decision-rewritten` in `gate` |
| [log4brains](https://github.com/thomvaill/log4brains) `17e3202`, Apache-2.0 | Date slugs avoid merge conflicts over numbers | Immutability alone doesn't detect contradiction | **Adapt** date plus slug |
| [Swimm](https://swimm.io) docs, closed source | Docs coupled to code and flagged when it changes | Vendor claims, and the algorithm is undisclosed | **Adapt** the idea as `design-not-updated`, from cited paths only |
| [Spec Kit](https://github.com/github/spec-kit) `3ca735b`, MIT | Non-goals and a constitution | One independent run: 2,577 lines of Markdown per 689 of code. Checks are by model | **Reject** spec, plan and task trees |
| [Cline Memory Bank](https://docs.cline.bot/prompting/cline-memory-bank) `ea16751`, Apache-2.0 | Files that survive sessions | Requires reading all of them on every task | **Reject** loading everything, which the instruction-cost evidence argues against |
| [beads](https://github.com/steveyegge/beads) `8c3eb30`, MIT | Claims with conditional updates | Needs a database | **Reject** the dependency. `coord` holds advisory claims |
| [Superpowers](https://github.com/obra/superpowers) `22f0b46`, MIT | Sizing a design by how much is at stake | Its gate is only asked for, with docs to 1,095 lines | **Agree** on sizing. Nothing else to adopt |

**Why decisions are single appended lines.** A write to a file opened for appending can't overwrite another writer's, and superseding keeps the reason on record, so concurrency and history have one answer. It does mean Decisions has to be the last section.

**What this design doesn't do.** Nothing checks that a claim in prose is true, only that what it cites exists and how much has changed since. It can't stop agents following a wrong decision. No agent has used any of it, and no study supports the whole idea. One test worth running before building further: CooperBench pairs with and without a one-page contract, plus a stale-contract arm.

### Other ideas from similar tools

A subagent read these for what occam still lacked. Numbers are self-reported unless marked. **Co-change is built:** a file's usual partner left out of a change gets one line in `gate`, from [ROSE](https://www.st.cs.uni-saarland.de/edu/empirical-se/2006/PDFs/e0429.pdf) (peer reviewed, abstract seen only by that subagent, on human commits) and CodeScene's change coupling. It reuses `occam query history`, and its strict thresholds are a judgment. **The rest aren't built, and are ranked for a decision:**

| Idea | Source | Why | Cost and risk |
|---|---|---|---|
| An A/A noise floor, and a free per-run cost table | [compound-engineering](https://github.com/EveryInc/compound-engineering-plugin) `173bd33` | Occam compares 3 runs per arm and has never compared two identical builds | About a day for the table. The floor needs billed runs |
| Demoting rules agents keep dismissing, from ledger outcomes | [Greptile](https://www.greptile.com/blog/make-llms-shut-up), [Cursor](https://cursor.com/blog/bugbot-learning), [Tricorder](https://research.google.com/pubs/pub43322.html) | A blind judge called 57% of leads minor | About 150 lines. Agents dismissing real leads could train the filter, so security rules stay exempt |
| Listing uncovered added lines in `gate`, from a coverage report | [Sonar](https://docs.sonarsource.com/sonarqube-cloud/standards/ai-code-assurance/quality-gates-for-ai-code) | The report exists in many repositories, and nothing reads it per line | About 60 lines. No evidence on effect |
| Hook-run checks that speak only on failure | [Aider](https://github.com/Aider-AI/aider) `5dc9490` | Could replace a send-back that costs a turn | Collides with the deferred hook refactor, and the agent stops reading its diff |
| Repository rules with fixtures, fed by a lesson ladder | compound-engineering, [Trail of Bits](https://github.com/trailofbits/skills) `470419e` | A lesson costs tokens only when it hits | 200 to 300 lines |

**Looked at and rejected:** model-rated type design, a model pass per check (`code-review`, Amp, Continue), `hookify`, phased `feature-dev`, a second model as architect or oracle, CodeScene's single score, and Aider's repo map, which adds tokens and overlaps `map`.

## Re-evaluation for new code and audits at every size: added 2026-11-06

The user asked to re-evaluate occam against the whole list of ways agents write bad code, for new code and for auditing and fixing AI-written codebases from a cell to a monorepo, and to check current discussions and similar skills. Two subagents did the reading, and I ran the tools on three things: a pasted notebook cell, a 190-line Flask app written to contain the usual AI defects, and SkyPilot (about 650,000 lines of Python, read-only). None of this measures whether an agent does better.

### What running the tools found

The guidance already named every item on the user's list (see `coverage-map.md`), so the gaps were in the tools. On the written app, the scanner and `gate` missed the commonest shapes of several defects they have rules for. On the cell and on SkyPilot, they reported real packages as invented.

| Missed or wrong | Cause | Change |
|---|---|---|
| `return True` after the work and again in `except Exception` | `failure-reported-as-success` only knew `{"success": True}` | Same success value from the work and a broad handler. A narrow handler returning success is often deliberate (already deleted), so it doesn't count, and a handler whose comment gives a reason is a low-confidence lead, as `swallowed-exception` does. Both SkyPilot hits were such documented decisions |
| A test calling the mock `@patch` handed it | `test-mocks-subject` only followed qualified names | Mocks passed as parameters are followed too, unless the test also calls code it imported by name |
| A loop calling a helper, in another file, that queries | `query-in-loop` read one file | One hop across files, when the name is defined once and imported, and the helper isn't decorated (it may cache) |
| Three copies of a 3-line function | `clone-function` needs 4 statements and 6 lines, below which shape alone matches unrelated code | Short functions match on their text, with literals and outside names kept, and only three copies or more count. On SkyPilot, every group this added was code repeated verbatim, such as one function in 7 to 15 cloud modules. Some repetition is deliberate, as in self-contained migrations. Structure alone gave 28 groups, about half of them unrelated functions |
| `df.iloc[i]` in a `range(len(df))` loop in a cell | Loop rules only ran inside functions, and cells and scripts run at module level | Index loops are read at module level too, and row reads by position are `dataframe-iterrows` |
| `pandas` in a cell called an invented package | Nothing declared, nothing installed | A short list of very common packages: undeclared if the repository declares anything, nothing if it declares nothing |
| 382 high `phantom-import` leads on SkyPilot, including `sqlalchemy` 131 times | Its `setup.py` builds `install_requires` from a module beside it | `setup.py` with a computed `install_requires` reads the strings listed in a `*depend*` or `*require*` module beside it, parsed, never run. Dictionary keys, such as the names of extras, aren't packages |
| `test-no-assert` on "should not raise" tests and on tests calling `smoke_tests_utils.run_one_test` | Only same-file helpers counted | A test saying nothing should raise isn't reported, and a call into a test-support module counts as a check |
| `gate` said "No needless structure" for a new function with two parameters it never read, and "Comments" for three narrating comments | Comment rules are low confidence, which `gate` hid | `gate` warns on new top-level functions' unread parameters, and shows low-confidence comment leads on changed lines. Both only warn |

All of these have a case that must fire and a near miss in `tests/test_ai_patterns.py`, which fails on the code before the change (16 of 17; the 17th is a near miss).

**SkyPilot before and after** (same commit, every file read): 8,170 leads became 7,233. High-severity "hallucination" leads went from 416 to 94, `phantom-import` at high confidence from 347 to 47, and `test-no-assert` from 552 to 105. Added: 15 `query-in-loop` through a helper, 11 short `clone-function` groups, 2 `failure-reported-as-success` (since lowered, see above), and 3 `unused-dependency`, which were the extras' names until fixed.

**Left alone, on purpose.** Extending `swallowed-exception` to `except Exception: return <default>` would also catch `try: parse(x); return True / except Exception: return False` validators, and that rule blocks in `gate`. A handler returning a default stays the reader's call. A lambda-style `handler(event, context)` that ignores `context` gets an `unread-parameter` warning it doesn't deserve, which a warning can afford.

**Scale.** `map` on SkyPilot spent its 75 seconds and fell back to a table of contents by folder (90 s wall clock), as designed. `scan` read everything in 40 s and `partition` gave 128 shards with 6 readers. The noise is what an agent auditing it would meet first, which is why the precision fixes above came first.

### New sources since the earlier passes

Already cited in `large-codebase-failures.md`, and not repeated here: the OX, CodeRabbit, Veracode, Apiiro, Sonar and Faros reports, SusVibes, ImpossibleBench, SlopCodeBench and others. New, all preprints unless marked:

| Source | Finding | Used for |
|---|---|---|
| [Pham and Ghaleb, MSR '26](https://arxiv.org/abs/2601.17627) | Functions and classes agents add are removed after a median 3 days, against 34 for people | Supports "It needs to exist" and `gate`'s unread-parameter warning |
| [Kaddour et al.](https://arxiv.org/abs/2602.06948) | Agents succeeding 22% of the time predict 77%. Framing self-assessment as bug hunting calibrated best | The core's critique already asks for a counterexample. No change |
| [TDAD](https://arxiv.org/abs/2603.17973) | TDD wording alone raised regressions from 6.08% to 9.94%. A map of which tests reach the change cut them to 1.82%. Small open models, about 100 instances | `gate`'s closing questions now ask whether the existing tests that reach the change ran, and point at `query impact --changed` |
| [Khatri](https://arxiv.org/abs/2607.27250), [Lulla et al.](https://arxiv.org/abs/2601.20404) | Context files: no change in Claude Code's solve rate (53.3% v 55.6%), or 28.6% less runtime for Codex at comparable completion | Consistent with keeping instructions short. No change |
| [Kim et al.](https://arxiv.org/abs/2512.08296) | Multi-agent against single: +80.8% on decomposable tasks, −70.0% on sequential planning. Not specific to code | Consistent with `collaboration.md`'s "don't split what can stay together". No change |
| [ProgramBench](https://arxiv.org/abs/2605.03546), [NL2Repo-Bench](https://arxiv.org/abs/2512.12730) | Models favor single-file monoliths, stop early and lose cross-file coherence on whole repositories | Already covered by done-conditions and the `map` strategy |

### Similar tools, latest versions

Ponytail (`96608e0`) and Superpowers (`22f0b46`) haven't changed since the passes above, though Superpowers' release notes describe mechanisms not recorded before. The core skill's body has a 13,000-character cap from the cost goal, and was at 12,933, so nothing here went into it. Taken, outside the core:

- **The suite defines green,** from Superpowers 7.0, where 11 of 12 runs ran only the test file they were given. Folded into the `gate` question above, which costs nothing until `gate` runs.
- **Sibling search after a confirmed bug,** from Trail of Bits' variant analysis, in occam-audit's repair reference, since the audit skill's 1,400-word cap was spent too. Occam named "one of two copies fixed" as a failure, with no step for it.

Not taken, for later decision: **awkward inputs as checks before coding** (Superpowers 7.0, whose evals had every implementer ship the same crash; it matches occam's own lead on `invoice-ledger-totals`, where a quantity-0 line broke totals in every no-skill run), which belongs in the core's "Know what done means" and needs about 120 characters of a budget that's spent, so it's the user's call; `gate` already asks about empty, huge and malformed input after the fact; a fresh agent disproving each serious audit finding (Anthropic's `code-review` and `claude-security`, Cloudflare), since occam-audit already asks the auditor to show nothing guards a finding, and the user approved self-review by default the same day; a script-checked coverage ledger with stable finding IDs (`claude-security`, Cloudflare), a marker for code that must stay as it is (addyosmani/agent-skills, compound-engineering), proving each lint or CI check fails on a known violation, and business-rule cards before a repair (Anthropic's `code-modernization`). A `SubagentStart` rule card (Ponytail) is being built by another session, with the user's approval. Rejected again, for the reasons above: a single quality score (desloppify), a review at every stop, persona framing.
