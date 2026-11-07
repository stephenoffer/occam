---
name: occam-go
description: Go guidance on error wrapping, goroutine lifetimes, context cancellation, nil pitfalls, cleanup, race testing, packages, naming, test results. Use alongside occam to write, debug or review Go where these matter.
---

# Go

Read the actual manifest and conventions before choosing commands, and use the ecosystem's established tools. Don't translate patterns from another language mechanically.

- **Tooling:** check `go.mod`, build tags, `go vet` and the project's linter. Run `go test -race` for concurrent code.
- **Errors:** handle every returned error and wrap with `%w`. Don't panic across package boundaries for expected failures.
- **Concurrency:** every goroutine needs a way to stop. Pass `context.Context` and respect its cancellation, and don't ignore deadlines on network calls. Unbounded goroutine creation is a leak waiting for load, and closing channels is the sender's job.
- **Nil and values:** a nil pointer in an interface isn't a nil interface. Writing to a nil map panics. Range variables and slice aliasing depend on the Go version and capacity.
- **Resources:** `defer` runs at function end, not loop end, so closing in a loop needs a helper. Always close response bodies.
- **Interfaces:** accept small interfaces and return concrete types. A new interface with one implementation needs a reason.
- **Structure:** a package is the unit of design, named for what it provides rather than `util` or `common`. `internal/` stops other modules importing it. Import cycles don't compile, so move the shared piece down.
- **Naming:** `MixedCaps`, short lowercase package names, and no stutter: `http.Server`, not `http.HTTPServer`. Getters drop `Get`, and acronyms keep their case, as in `ID` and `URL`. Capitalization is the public API, so renaming an exported name breaks callers.
- **Tests:** `go test` exits 0 on `[no tests to run]` when `-run` matches nothing, and on `[no test files]`, so read those lines. `(cached)` means nothing ran, and `-count=1` forces a run. Table tests with `t.Run` report each case by name.
- **What generated code gets wrong here:** `_` swallowing errors, `panic` for ordinary failures, goroutines with no way to stop, `http.Get` and the default client with no timeout, `interface{}` where a concrete type works, one-implementation interfaces copied from Java habits, deprecated `ioutil`, and invented module paths. `go vet`, `staticcheck` and `govulncheck` come first, and `occam-audit`'s scanner has only text-level rules here.
