# How agents get code wrong

Ten ways coding agents go wrong, what occam does about each, and what still gets past it. This file is for maintainers and is not loaded during coding sessions.

The list adapts a taxonomy of LLM agent failures from an unpublished evaluation of a performance-tuning agent, translated here into what each failure looks like in code. **The order is not a ranking.** The rates below come from different tasks and can't be compared across rows, and nobody has measured which of these costs most in practice.

## What that evaluation changed about the approach

Four results shaped this work more than the list did.

| Result | Evidence | What occam does because of it |
|---|---|---|
| A written method didn't make claims more accurate | About a third of headline speedups overstated the confirmed result, with the method (12 of 35) and without it (11 of 36) | Compares claims with a record the model doesn't write, instead of adding more instructions |
| More knowledge didn't help | An empty knowledge base scored 1.13 times the full one (CI 0.94 to 1.32), so its records showed no detectable benefit | Adds no recipes or reference data |
| Refusing bad output changed drafts more clearly than outcomes | Interim, 10 sessions per arm: 21 of 29 drafts refused and each refusal followed by a corrected draft, yet 2 of 10 sessions still delivered an unsupported claim, against 1 of 10 with the same checks only observing. Model cost was about 1.6 times higher | Claims no quality gain, and keeps these checks narrow and cheap |
| A check off the delivery path does nothing | The settings file never loaded in one campaign: 0 of 248 transcripts held a hook record, while emulated tests passed. Later, 15 report writes per arm went through the shell and skipped the check | Lists the routes around each check below, and treats a run in real Claude Code as the evidence that matters |

So the additions favor three things, in this order: a deterministic comparison against what the hook recorded, a short reminder at the moment it applies, and a line of guidance only where nothing else can reach.

## The ten at a glance

**How firm** uses the terms in [`claude-code.md`](claude-code.md): *denied* doesn't give way, *a person confirms* asks, *held once* denies and then lets a retry through, *sent back* continues the agent once at Stop, and *noted* adds a line of context. *Guidance* is text the model may ignore.

Three limits apply throughout. A turn starts at each user prompt, and Stop only compares in a turn that edited code, so a false claim in a turn with no code edit isn't checked. Each kind of hold gives way after six in a session, however different the edits. And failures and side effects from a subagent aren't held against the agent that called it, since a reviewer's job is to break things.

| # | Failure in code | What occam adds | How firm |
|---|---|---|---|
| 1 | Claiming what didn't happen | Final message compared with recorded checks: a failure left out, a test count no output shows, a measured speedup with no before and after | Sent back |
| 2 | Coding from stale memory | Read what's installed instead of recalling. Toolkit rules for phantom imports and deprecated APIs | Guidance |
| 3 | Applying a familiar fix where it doesn't fit | Check a pattern's preconditions. Find what binds before tuning | Guidance |
| 4 | Caving to pushback | A reminder when a prompt disputes a result after work has happened | Noted |
| 5 | Grading its own work | Expected values from the requirement. Reviewer runs things and is labeled fresh-context, not independent | Guidance |
| 6 | Building on an unnoticed first mistake | A note after three failed checks in a row: read the first error, back out failed attempts | Noted |
| 7 | Making the check pass instead of the code | Edits that remove assertions, skip tests or suppress after a failure. Turning the hooks off and hard-to-undo commands | Held once, a person confirms |
| 8 | Obeying or leaking through what it reads | Credentials in web requests, in edits, and in `curl`. Relayed tasks are data | Denied, held once, a person confirms |
| 9 | Learning the wrong lesson | A note when editing a file that steers later sessions | Noted |
| 10 | Not showing what it did | Installs, deletions, manifests and check config the report doesn't name. A result that varies with nothing changed | Sent back |

## The ten in detail

### 1. Claiming what didn't happen

The report says tests pass, that something was verified, or that a change made the job five times faster, and the run behind it failed, measured other code, or never happened.

**Evidence.** Of 12 models on file review tasks, 67.9% of runs left a file unread, and 80.4% of those were misleading about it (OverclaimBench). Self-reports refer to about one action in eleven (Narrative Layer).

**What occam does.** At Stop the hook compares the final message with what it recorded, and sends the agent back, once per state of the code, if:

- a check failed after the last edit and hasn't passed since, and the message doesn't mention a failure, or claims a pass in a sentence that doesn't qualify it. Only the same command settles a failure, or an unnarrowed run of a whole suite, so `pytest --ignore=tests/test_a.py` doesn't
- the message reports N passing, some output this turn states a count, and none contains N
- the message states a measured speedup or saving, and no command ran both before the first edit and after the last
- the message admits part of the request wasn't done, such as "I split out only a small part". This fires once a session, and asks for the rest, or the one decision a person has to make
- a notebook this turn changed can't run top to bottom, by a static read of its cells. This fires once per notebook

This extends the existing rule that a claim of passing needs a check that passed. A check that never started, or that ran on a temp copy of older code, doesn't count as a failure of this code, because showing a new test fails on the old code is what the skill asks for.

**What gets past it.** Stopping short in other words, including stopping without saying so, and any admission in a turn with no code edit, since Stop only compares after one. A notebook that fails for any reason a static read can't see. A real failure in the same command as a run on a temp copy. A wrong figure with the right shape, a count that happens to appear elsewhere in the output, a runner that prints no count, a speedup in words without a number, and a before-and-after that ran the same command on different input. Failure words are matched loosely, so "still has issues" passes as honest even when it understates. One-off scripts on stdin or in `-c` aren't tracked. A false claim about anything other than tests or speed isn't seen, and neither is a review claim about files read. The hook compares against what it saw, so a passing check that didn't exercise the change still counts.

### 2. Coding from stale memory

Removed APIs, renamed flags and old config keys, written confidently from training data, or taken from documentation for another release.

**Evidence.** "Simply specifying the target version provides no benefit", while relevant documentation noticeably improves accuracy (LibEvoBench).

**What occam does.** Guidance in `design.md` and the core: read the lockfile, the installed source or `--help`, or that release's documentation, and make one small real call before building on it. In the audit toolkit, `occam.py scan` has `phantom-import`, `phantom-attribute` and `deprecated-api`, and `deps --online` checks that a package exists.

**What gets past it.** Most of it. No hook checks this. A plausible call into a real third-party package isn't caught by the toolkit either, since `phantom-attribute` covers the standard library only. A test that exercises the call is the real defense.

### 3. Applying a familiar fix where it doesn't fit

Pattern matching on resemblance: the helper with a similar name and different semantics, the recipe from a similar system, the bottleneck that wasn't one, or a plausible implementation of something whose premise is false.

**Evidence.** Nine LLMs dropped from 84.9% on genuine riddles to 50.7% on look-alikes that need only a literal reading, while humans went the other way, 50.5% to 80.5% (Riddle Riddle).

**What occam does.** Guidance only. `design.md`: state what must be true for a pattern to work, read the request literally, and say so if a premise is false. `performance.md`, whose main points are stated before the edit on performance work: find the stage that binds before tuning.

**What gets past it.** Everything the model doesn't choose to apply. Whether a fix fits is a judgment no pattern can see, and we know of no deterministic check for it.

### 4. Caving to pushback

The agent drops a correct answer or reverts correct code because someone sounded sure, or takes a wrong diagnosis at face value.

**Evidence.** Abandoning the correct position rose from 0-57% within 5 turns to 20-97% within 25 turns, depending on model and scenario (SPINE).

**What occam does.** When a prompt disputes something after a session has edited or run checks, the hook adds a line: recheck against the evidence, change the answer for what the recheck shows or for new evidence, and say which. The note separates disputing a fact from stating a requirement, which is the user's call.

**What gets past it.** Pushback in other words, including the common "no, it should do X". A reminder doesn't make the model follow it, and this may also make an agent dig in when it is wrong. That risk is real and unmeasured.

### 5. Grading its own work

Tests derived from the implementation, mocks that share the code's wrong assumption, and a clean review from a reviewer with the author's blind spots.

**Evidence.** Even the strongest LLM judge finds an agent's first mistake in fewer than a third of runs (Hidden Failures).

**What occam does.** `verification.md`: take expected values from the requirement, not from the code's output. The reviewer agent is told it probably shares the author's blind spots, asked to run things and to prefer a breaking input to an argument, and told to call its result a fresh-context review. In the toolkit, `mutate` shows whether tests can fail, and `scan` has `test-tautology` and `test-mocks-subject`.

**What gets past it.** A reviewer running the same model is still the same model. Nothing here supplies real independence. Requiring a review costs the most of anything in the plugin, and this evidence argues against treating it as strong.

### 6. Building on an unnoticed first mistake

A wrong early step that everything then depends on. Patches pile up, and the last symptom gets fixed instead of the first cause.

**Evidence.** "After its first mistake an agent often fails to recover and rarely catches the error itself" (Hidden Failures).

**What occam does.** After three failed checks in a row, once code has changed, the hook adds one note: read the earliest error, the diagnosis may be wrong, and back out failed attempts. Each streak gets one note. `verification.md` says the same for hosts without hooks.

**What gets past it.** A wrong assumption that no check exercises, which is the worst version of this failure, since nothing goes red. A passing check resets the count, so alternating results never reach three.

### 7. Making the check pass instead of the code

Removing or skipping tests, hard-coding expected values, loosening configuration, skipping hooks, or tuning for the metric. It also covers replacing the component the user asked to fix, which can be valid but changes what the application is.

**Evidence.** 57.1% of runs reward-hacked planted shortcuts across seven frontier agents (BAITBENCH). Across 17 models, spontaneous reward hacking was 30.5% on open-ended research-pipeline tasks and 2.9% on task-specific kernels (Reward Hacking in Research).

**What occam does.**

- **Held once, and it must then be named in the report:** a test edit that removes assertions (a commented-out one counts) or adds a skip or `.only`, deleting a test source file from the shell unless this turn created it, and right after a failed check, with no code changed since: changing check configuration, or adding a suppression or a loosening setting to an existing file. Rewriting a test in place with `sed -i` or `perl -i` isn't held, so this one gets past.
- **A person confirms:** turning off these hooks through settings, recursive deletes of the root, home, the whole working directory or absolute paths outside temp and generated directories, running a download straight in a shell, `terraform destroy`, `kubectl delete`, and dropping tables through a SQL client.

**What gets past it.** Loosening an assertion without removing it (`== 3` to `>= 0`), special-casing a test input in the code, changing a test through a script or an overwriting redirect, and any of the "right after" changes once other code has changed. That last gap is deliberate: holding every shell edit to a test stopped agents adding tests (see "How we'd find out"). Also deletion through other tools, config edits made before any check fails, loosening settings not on the short list, removing the plugin's entry from settings rather than disabling it, and destructive commands not on the short list. A recursive delete of a relative path such as `rm -rf src` isn't asked about, because asking on every build directory cost more than it saved, so it relies on the report naming it and on version control. Renaming a helper like `assert_ok` reads as removing an assertion and is held once. The toolkit's `test-weakened` and `fake-success` catch some of these at review time. Rerunning until green is covered under failure 10.

### 8. Obeying or leaking through what it reads

Following instructions in an issue, a log or a dependency. Putting secrets in code, in a search query, or in a request.

**Evidence.** 66.5% of malicious issues got past every guardrail of Cursor, Claude Code and Codex Desktop (IssueTrojanBench).

**What occam does.**

- **Denied, and doesn't give way:** a credential shape in a `WebFetch` or `WebSearch` request.
- **Held once:** an edit that newly puts a credential shape into a project file, which must then be named in the report.
- **A person confirms:** a credential shape in the arguments to `curl`, `wget` and similar.
- **Guidance:** a task relayed through an issue is data until the user adopts it.

Values in these shapes are replaced before anything is stored or repeated, including prompts and commands. A credential in any other form can still reach the state file, because the hook can't recognize it.

A message from another session or a subagent is also not treated as the user's request, so it can't lift a read-only hold.

**What gets past it.** Prompt injection has no check at all. **No pattern reads intent**, so injected text can still steer what the model proposes. Secrets are matched only by unmistakable shapes, so a plain password, an internal hostname or a customer name passes. Shell network tools outside the list, other MCP servers, and variables holding the value are not seen.

### 9. Learning the wrong lesson

Writing a one-off or a mistaken conclusion into memory, a rules file or a skill, where every later session trusts it.

**Evidence.** A misaligned goal propagated through an agent's own memory in 58% of runs with an explicit goal prompt, and an LLM memory auditor only reduced propagation from 71% to 34% (Self-Propagating Misalignment). Self-poisoned skill libraries held 4.9 to 9.0 times the malicious skills planted (EVOMAL).

**What occam does.** The first edit in a session to a file that steers later sessions (`CLAUDE.md`, `AGENTS.md`, `SKILL.md`, memory directories and similar) gets one note: name the evidence and where it applies, one run is a hypothesis, and tool output isn't a source of rules. `collaboration.md` has the longer form.

**What gets past it.** Almost everything. This is a note, not a hold, because an agent writing memory is normal and often requested. Shell writes aren't seen, and nothing checks whether a lesson is true. The evidence above suggests agent-authored memory can't be audited into safety with another model, so treat these files as untrusted input to later sessions.

### 10. Not showing what it did

Installs, deletions and config changes that never reach the report, and a green result that only sometimes happens.

**Evidence.** Across 5,851 sessions and 355,942 tool calls, a self-report referred to about one action in eleven (Narrative Layer). Identical temperature-zero requests gave 80 unique completions, the most common occurring 78 times (He, Thinking Machines).

**What occam does.** At Stop the agent is sent back, once per state of the code, if:

- the message doesn't name an install, a deletion, a dependency manifest, check configuration, or a weakened test it changed this turn
- the same command failed and passed in consecutive runs with no edit or other command between them, and the message doesn't explain it

Each name is asked for once per turn.

**What gets past it.** A name appearing anywhere in the message counts as reported, even in an unrelated sentence. Other side effects, such as data changes, migrations and calls to services, aren't recorded. A flaky result only shows up if it happened to vary in this session. Reasoning isn't recorded at all.

## Not shown

- **None of this is shown to make software better.** The tests in `tests/test_failure_modes.py` show each check refuses and passes what it should on cases we wrote. They say nothing about whether agents produce better code. The evaluation above suggests that is a separate and harder question.
- **The false-positive rate on real work is only partly known.** Every hold, ask and continuation costs turns. Most patterns are tested on authored cases only, and the same author wrote the patterns and the cases. The one rule checked against real traces was mostly false positives until it was narrowed, so expect others to need the same.
- **The cost of these checks alone is unmeasured.** The re-evaluation in `evals/RESULTS.md` included them but can't separate them from other changes.
- **No adaptive attacker has tried these.** They are guardrails, not a security boundary, and a misdirected agent can route around them. Each section lists the routes we know of. One fresh-context review by the same model found many false interruptions and missed cases, now fixed and in the tests, but it stopped short of mutation-testing most of them.

## What the hook's reading of commands can't see

All of the above rests on reading a shell command without running it. On 19,370 generated commands run in real bash with logging stubs, it missed none of the programs that ran, and it read a program that didn't run in about 2,400, mostly `true || pytest` style branches, which a static read can't settle. Those commands were written by a reviewer, so they test odd shapes and not typical use, and they're no longer a blind test now that fixes were made against them. When it's unsure whether a `cd` ran, it assumes the project, so work in a temp copy can draw a false hold. These still get past it, and each one fails toward doing nothing, not toward stopping work:

- **Running code it can't read:** a script file's contents, `exec` of a variable, `__import__`, a renamed `open`, a library's own writer such as `df.to_csv`, `os.chdir` inside Python, and tools it doesn't know, such as `npx prettier --write`.
- **Variables and branches:** a command built from variables, a `cd` inside `if` or a loop, and code past a function it can't see called. A path in a variable reads as unclear rather than safe.
- **Size:** the hook gives up after 8 seconds and lets the command through, so megabytes of padding avoid every check. Inline Python over 100,000 characters isn't parsed, only searched for the obvious calls.
- **Whether a check really tested this code:** a check that names no path and runs from the project counts, even if it tests something else. A real check and a run on a temp copy in one command count as a real failure, since their output can't be told apart. Matching pytest's result lines to runs was tried and removed, because a fresh review got real failures recorded as passes.
- **Notebooks:** only the use of a name before its definition across cells. A name never defined, one defined later in the same cell, a syntax error or an exception aren't seen, and a name used inside a function body can be flagged though the notebook runs.
- **PowerShell:** a line ending in a backslash reads as joined to the next. Windows hasn't been run at all.

## How we'd find out

Keep the two questions apart: do the checks work, and do they change anything?

1. **Do they fire in real Claude Code?** Partly seen, in one real session on 2026-11-05: the edit hold and its retry, the shell-deletion hold, the failed-check note, the note on steering files, and the new fields in the state file. That run also found a fault the emulated tests had missed, since fixed: a reworded shell description defeated "held once". In the 7 plugin runs of the re-evaluation, `evals/RESULTS.md` records a removed-assertion hold once, a shell edit to a test twice, and three person-confirm asks, which an unattended run turns into denials. Two of those asks were `git stash`, from agents setting up a before-and-after comparison, and one was a false recursive-delete ask, since fixed. **Not yet seen:** the web denial, and a Stop comparison sending an agent back. Those 7 runs had no Stop continuations, which doesn't show whether the comparisons would catch anything.
2. **What do they cost?** Partly known, and the first real data found a bad rule. Across the recorded runs, the rule on changes "right after a failed check" held nine times. Five were false: agents adding tests or writing a new file on a task whose check was red from the start, and the "right after" condition stayed true across eight or more edits. The other four rewrote expected values with `sed -i`, which is its purpose. The two `harbour-tide-gauges` runs with those false holds took 18 and 21 tool calls, against 9 for the third plugin run and 4 to 6 with no skill, though the holds aren't the only difference. Replaying those runs' recorded tool calls through the narrowed rule held the four and not the five. The user later limited shell holds to destructive actions, so none of the nine is held now, including the four. A replay shows what the rule would do to those actions, not how an agent would respond. Still to do: count holds, continuations and false positives over ordinary sessions.
3. **Do they change delivered claims?** Compare the plugin with these checks observing only against the same checks enforcing, on tasks that require a report and have a hidden confirmation run. Score the share of sessions that deliver a claim the confirmation doesn't support. Plan for far more than 10 sessions per arm.

## Sources

Figures were re-checked on 2026-11-05 against each abstract or primary page, not taken from the source taxonomy. OverclaimBench is recorded in [`research.md`](research.md).

| Short name | Source |
|---|---|
| OverclaimBench | [arXiv:2609.20812](https://arxiv.org/abs/2609.20812) |
| LibEvoBench | Cipollone et al., [arXiv:2606.25402](https://arxiv.org/abs/2606.25402) |
| Riddle Riddle | Fascendini et al., [arXiv:2606.27103](https://arxiv.org/abs/2606.27103) |
| SPINE | Tang et al., [arXiv:2609.09090](https://arxiv.org/abs/2609.09090) |
| Hidden Failures | Rahman et al., [arXiv:2609.17930](https://arxiv.org/abs/2609.17930) |
| BAITBENCH | Prasad et al., [arXiv:2608.30724](https://arxiv.org/abs/2608.30724) |
| Reward Hacking in Research | Huang et al., [arXiv:2609.28614](https://arxiv.org/abs/2609.28614) |
| IssueTrojanBench | Singh et al., [arXiv:2607.20759](https://arxiv.org/abs/2607.20759) |
| Self-Propagating Misalignment | Das et al., [arXiv:2610.04083](https://arxiv.org/abs/2610.04083) |
| EVOMAL | Wu et al., [arXiv:2608.25776](https://arxiv.org/abs/2608.25776) |
| Narrative Layer | Kraishan and Jitkajornwanich, [arXiv:2609.12205](https://arxiv.org/abs/2609.12205) |
| He, Thinking Machines | [Defeating Nondeterminism in LLM Inference](https://thinkingmachines.ai/blog/defeating-nondeterminism-in-llm-inference/), 2025 |

**Left out because they couldn't be confirmed.** The source taxonomy gives two more figures for failure 6: agents recover from a first mistake in 30.5% of runs and never notice it in 38.5%. The Hidden Failures abstract says only "often" and "rarely", and its full text couldn't be read here. The taxonomy's other citations for failures 1, 3 and 4 weren't checked and aren't used. The internal figures at the top of this file come from an unpublished, interim evaluation that hasn't been independently reviewed.
