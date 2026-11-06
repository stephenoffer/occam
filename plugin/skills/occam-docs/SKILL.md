---
name: occam-docs
description: Writing or updating documentation for code, such as a README, API reference, guide, docstrings or changelog, especially for code just written. Takes claims from the code, checks them with the occam tools, runs the examples, then hands the prose to human-voice if installed. Use alongside occam.
---

# Documenting code

Documentation written straight after the code tends to describe what the author meant to build, in a voice nobody uses. Facts come first, because a well-written wrong claim costs a reader more than a clumsy right one, and a rewrite for voice is when facts slip. That is why the steps run in this order.

Write what the request or the repository calls for. A small fix updates the sentence it made wrong and doesn't earn a new guide. `occam` below means `python3 ../occam/scripts/occam.py`, relative to this skill.

## Order

1. **Reader and scope.** Who reads this, and what are they trying to do? Extend the documents already here and follow their layout before adding one.
2. **Facts from the code.** Read the code as it is now, not the plan, the commit message or your memory of writing it: entry points, public names and signatures, flags and defaults, configuration keys, environment variables, errors and side effects. Keep a list with file and line. Capture real output from `--help` and from running it. Where code and intent disagree, that is a defect to report, not a sentence to write.
3. **Claims the evidence supports.** "Fast", "secure", "production ready" and "supports X" each need a test or measurement you have, with its scope. Say what is untested. Don't document a path nothing reaches, and don't invent output, benchmarks or versions.
4. **Draft.** Use `human-voice` in `generate` mode if it is available, with the fact list as the brief. Otherwise write plainly.
5. **Check the facts.** `occam docs FILE` compares names, paths, flags, links and example syntax with the repository. Each lead gets fixed in the document or the code, or you can say why it is fine, such as a third-party name or an illustrative example.
6. **Run the examples.** Run each command and snippet the way a reader would, in a temporary copy if it writes files. The tool only reads them. Anything that needs credentials or has outside effects is reported as not run.
7. **Voice pass.** Copy the file, load `human-voice`, and run `fix` at the depth it sets for what the document costs if it reads badly. Then run `occam docs FILE --before COPY`. Restore any number, code span, link or code block the rewrite lost or added, unless you can say why it had to change. Repeat after each pass, and rerun any example the pass touched.
8. **Report.** Facts checked, examples run and not run, the voice pass and its result, and what the tools can't see.

Facts win over rhythm. If the only way to improve a sentence is to round a number or drop a caveat, leave the sentence.

## Working with human-voice

It is a separate, optional install.

- **Not installed:** skip step 7 and report "voice pass not run: human-voice isn't installed". Don't imitate it by swapping words, since word choice is the weakest signal it describes.
- **Register:** a README or API reference is `technical`, a how-to is `tutorial`, a changelog is `release_notes`. `occam docs --register NAME` passes the same choice to its linter. Older versions don't have the last two and report a failure, which means updating it, not dropping the flag and calling it checked.
- **Structure that carries information stays.** An API reference keeps a heading per entry, a runbook keeps numbered steps and a comparison keeps its table.
- **The score is a floor.** A low one doesn't show the prose reads well, a high one in a reference table may mean nothing, and scales differ between versions. Don't write to the number, and never use evasion tricks such as odd characters or injected typos.
- **It stays on.** Once loaded it shapes everything you write for the rest of the session, including replies and commit messages. It doesn't change what a report has to say: keep verified, failed, blocked and not run in those words, and don't soften a failure for rhythm. A style guide this repository enforces beats it.
- **Keep the copy out of the way.** It makes a `.bak` beside a file that version control doesn't track. Remove that once the pass is accepted, unless the user wants it.

## Docstrings and comments

These live in code files, so changing them is a code edit. Only the words change, and the tests run afterward. `occam docs` doesn't read them, so check each parameter, error and unit against the code by reading it. A doctest counts as an example. Use the lightest depth of a voice pass, and only on what you were asked to document.

## What the tools can't see

A name that exists may still be described wrongly. `occam docs` knows a name appears somewhere in the code, and not what it does, its signature, its default, or whether the flag belongs to that command. Those need reading. It parses Markdown only, doesn't check heading anchors, and treats every word in the code as known, so a name surviving only in a comment still passes. `--before` sees tokens, so "rose 12%" and "fell 12%" look alike. Read the rewrite against the original as well.

After changing code, run `occam docs` on the existing documents to find names that no longer exist. `occam gate` also warns about changed documents.
