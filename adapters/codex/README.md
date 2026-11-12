# Codex adapter

**Status: hooks run once, skills untested.** On 2026-11-11 the hooks ran in five short live Codex CLI 0.164.0-alpha sessions, through a logging wrapper, and [What was tested](../../docs/evidence.md) says what was seen. Everything else here comes from the docs.

Everything here is optional. The skill works with no adapter: copy one folder and you are done. Nothing in this directory activates by itself.

Checked against the official docs on 2026-11-05 and Codex CLI 0.164.0-alpha. What was actually run is listed in [What was tested](../../docs/evidence.md).

## Install the skill

| Scope | Command |
|---|---|
| You, all projects | `mkdir -p ~/.agents/skills && cp -R plugin/skills/* ~/.agents/skills/` |
| One repository | `mkdir -p <repo>/.agents/skills && cp -R plugin/skills/* <repo>/.agents/skills/` |

Check first that nothing there has the same name. Note the path: Codex discovers skills under `.agents/skills`, not `.claude/skills` or `~/.codex/skills`. They load implicitly from their descriptions, or invoke one with `$occam` or `$occam-python`, or through `/skills`. The eight language skills carry `disable-model-invocation: true`, a Claude Code key that keeps them off its always-on listing. The Agent Skills reference validator rejects that key, and whether Codex loads, ignores or rejects these skills hasn't been checked.

The Claude Code plugin's enforcement hooks are not part of this. On Codex, occam is guidance, so nothing makes it fire or holds an edit. Whether a Codex equivalent is worth building is an open question.

No `agents/openai.yaml` is shipped, because the defaults (implicit invocation on) are what this skill wants.

## Optional: install as a plugin, with hooks

`plugin/.codex-plugin/plugin.json` makes `plugin/` a Codex plugin, and `.agents/plugins/marketplace.json` at the repository root lists it, per the plugin docs. It adds hooks in `plugin/hooks/codex-hooks.json`: edits are held on a request that reads as audit-only, review-only or plan-only, or that only says no to a final message asking whether to go ahead with work, and from the shell any write except one plain command naming a path that isn't there yet; after an edit, the scanner mentions serious findings the edit introduced; and before stopping, the agent is sent back once if any remain, except on a turn where edits are held. None of this has run on Codex yet. What's new is judged against a record made just before the edit.

Codex skips plugin hooks until you review and trust them in `/hooks`, and a changed script needs trusting again. Plugins with hooks can't go in the public plugin directory, which is one more reason the skills work alone. The protocol was written from the docs and tested locally with the documented events, then run once under Codex, where the hold, the note after an edit and the send-back at Stop all fired. To try the hooks without installing anything, put `plugin/hooks/codex-hooks.json`'s entries, with the script's full path, in a repository's `.codex/hooks.json` and run `codex exec --dangerously-bypass-hook-trust` there. An edit made with a shell command isn't scanned afterwards, since PostToolUse here covers patches and file writes.

## The audit tools

`plugin/skills/occam/scripts/occam.py` runs the same on any host. `occam-audit` uses it from `../occam/scripts/occam.py`, so copy the skills as a set. State goes in `~/.cache/occam`, or a temporary folder if that isn't writable. If nothing is, `scan` still works without its cache, while `goal` and `coord` can't run.

## Optional: independent reviewer

Copy `reviewer.toml` to `.codex/agents/` or `~/.codex/agents/`, and `auditor.toml` too if you split audits across agents.

- **A custom agent can't be made read-only.** Per the docs, instructions can ask an agent not to edit, but they "don't create a separate read-only sandbox", and sandbox settings in the file don't override the parent. For a guaranteed read-only review, run it in a read-only session: `codex exec -s read-only "..."`.
- Subagents spawn after a direct request or an applicable project or skill instruction.
- Same-model reviewers are not statistically independent, and a reviewer's approval is a claim to inspect, not proof.
