---
name: occam-rust
description: Rust engineering guidance on ownership, error handling and panics, unsafe invariants, async cancellation and blocking, crate structure, naming, test results. Use alongside occam when writing, debugging or reviewing Rust where these matter.
---

# Rust

Read the actual manifest and conventions before choosing commands, and use the ecosystem's established tools. Don't translate patterns from another language mechanically.

- **Tooling:** check the workspace layout, `rust-version`, features, and that `cargo clippy` and `cargo test` run with the features CI uses.
- **Ownership:** clone to appease the borrow checker only with a reason, and prefer borrowing or restructuring. Long-lived references usually signal a design question.
- **Errors:** return `Result`. `unwrap` and `expect` in library or request paths turn bad input into a panic, and slicing and indexing can panic too. Follow the crate's error conventions.
- **Unsafe:** state the invariant each `unsafe` block relies on and keep it small. Test it with Miri or sanitizers where available.
- **Async:** dropping a future is cancellation, so check that state stays consistent at each `.await`. Don't hold a blocking lock or do blocking I/O on the executor. A `Mutex` guard held across `.await` is a common deadlock.
- **Tests and features:** feature combinations can compile separately and fail together, so test the combinations CI builds.
- **Structure:** a file is part of the crate only if a `mod` names it. An undeclared file isn't compiled at all, so its code and tests silently don't exist. Keep visibility narrow with `pub(crate)`, and split crates for a real boundary, not tidiness.
- **Naming:** `snake_case` for functions and modules, `CamelCase` for types, `SCREAMING_SNAKE_CASE` for constants. Conversions state their cost: `as_` is a cheap borrow, `to_` usually costs something, `into_` consumes. Getters drop `get_`.
- **Test results:** `cargo test` exits 0 when a filter matches nothing, showing only `filtered out`, and when tests are `#[ignore]`d, so read the summary lines. Each file in `tests/` is its own crate and sees only the public API.
- **What generated code gets wrong here:** `unwrap` and `expect` on ordinary failures, `clone` to appease the borrow checker, `unsafe` with no stated invariant, blocking calls inside async, trait hierarchies with one implementor, invented crate APIs and features, and crates added for what `std` has. `cargo clippy` and `cargo audit` come first, and `occam-audit`'s scanner has only text-level rules here.
