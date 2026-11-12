# occam plugin

This folder is what Claude Code installs. The project's README, examples and evidence are at [github.com/stephenoffer/occam](https://github.com/stephenoffer/occam).

```bash
claude plugin marketplace add stephenoffer/occam
claude plugin install occam@occam
```

## What's inside

| Part | What it is |
|---|---|
| 11 skills | `occam` for writing, fixing and reviewing code, `occam-audit` for auditing and repairing a codebase, `occam-docs` for documentation, and short guides for Python, TypeScript and JavaScript, Go, Rust, Java and Kotlin, C and C++, SQL, and shell |
| 3 commands | `/occam:razor` cuts what a change didn't need, `/occam:review` reviews a change without editing, and `/occam:audit` audits a codebase. They run only when you type them |
| 2 agents | `code-reviewer` gives security and money changes a fresh-context review and has no edit tools. `auditor` reads one shard of a large audit. Both have a shell, so staying read-only is an instruction they're given, not a limit |
| Hooks on 9 events | Each runs `python3 hooks/occam_hook.py` on your machine. They can hold an edit, ask you before a destructive command, or send the agent back when its final report contradicts what ran. [Every hook](https://github.com/stephenoffer/occam/blob/main/docs/claude-code.md) |
| A command line | `skills/occam/scripts/occam.py`, with `scan`, `query`, `gate`, `deps` and more. [All commands](https://github.com/stephenoffer/occam/blob/main/docs/tools.md) |

## What it runs and fetches

- Everything needs Python 3.9 or later and uses only the standard library.
- The hooks make no network calls. They run `git` and Python, and keep session state in `$CLAUDE_PLUGIN_DATA` or a temporary folder.
- The command line doesn't import or run the code it reads. `golden`, `mutate`, `bench` and `goal verify` run commands you give them. `tools --allow-exec` and `docs --allow-exec` run code from the repository.
- `deps --online` and `deps --name` ask pypi.org, registry.npmjs.org, crates.io or proxy.golang.org whether a package exists, sending only its name, and for a pinned Go module its version.
- `tools --run` starts analyzers you've installed, and some of those go online: semgrep fetches its rules, and `npm audit`, cargo-audit and osv-scanner send package names to their vulnerability databases.

## Switching it off

`OCCAM_HOOKS=guard` keeps only the safety guards, `OCCAM_HOOKS=off` turns the hooks off for a session, and `claude plugin uninstall occam@occam` removes it. It's a safety net, not a security boundary.

In claude.ai chat only the skills load. The hooks, commands and agents need Claude Code.
