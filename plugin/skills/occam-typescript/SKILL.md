---
name: occam-typescript
description: TypeScript and JavaScript guidance on null versus undefined, runtime validation, promises and cancellation, number precision, output escaping, builds, modules, naming, test results. Use alongside occam to write, debug or review TypeScript or JavaScript where these matter.
disable-model-invocation: true
---

# TypeScript and JavaScript

Read the actual manifest and conventions before choosing commands, and use the ecosystem's established tools. Don't translate patterns from another language mechanically.

- **Tooling:** check `package.json` scripts, the lockfile and its package manager, the Node version, `tsconfig` strictness, and whether the project is ESM or CommonJS.
- **Nullability:** `null`, `undefined` and a missing key differ. Use `??` rather than `||` when `0` or `""` are valid. A truthiness check on an optional security value is a common way to skip it.
- **Types are erased:** a TypeScript type or `as` assertion validates nothing at runtime. Validate at trust boundaries. `any` silently disables checks downstream.
- **Async:** an unawaited promise loses its errors. `Promise.all` rejects early without cancelling the others, so use `AbortController` for cancellation. `forEach` doesn't await, and `filter`, `some` and `find` treat an async callback's promise as true. Bound concurrency, since mapping a large list to promises starts everything at once. A response that arrives after a newer request was sent mustn't overwrite the newer state, so abort the old request or check which request it answers.
- **Merging objects:** copying keys from parsed JSON or a request into an object lets a `__proto__` key replace its prototype, and a deep merge can reach `Object.prototype`, which every object shares. Allow-list the keys, skip `__proto__`, `constructor` and `prototype`, or build into `Object.create(null)` or a `Map`.
- **Numbers:** floats only, so use `BigInt` or integer minor units for money and large IDs. JSON parsing loses large integer precision.
- **Output:** escape for the context, and keep user data out of `innerHTML` and `eval`. Compare secrets in constant time with `crypto.timingSafeEqual`.
- **Modules and builds:** a passing type check says nothing about the emitted bundle. When packaging is affected, exercise the built output, and check `exports` in `package.json` from a clean install.
- **Structure:** `tsc` doesn't report import cycles, which then fail at runtime, as `undefined` values in CommonJS and `ReferenceError` in ES modules, so keep dependencies pointing one way. Use `import type` for types. Barrel `index.ts` files make cycles easy, so follow what the repository does.
- **Naming:** `camelCase` for values, `PascalCase` for types and components, and the repository's file naming. A case-insensitive filesystem can hide a wrong-case import until CI runs on Linux.
- **Test results:** `it.only` skips the rest of the file and, outside CI, still exits 0, so check for stray `.only` and `.skip`. `--passWithNoTests` turns an empty run into success.
- **What generated code gets wrong here:** `any` and `as` casts to silence the checker, `useEffect` with missing dependencies or no cleanup, fetching in a loop or per component rather than batching, a client-side check as the only authorization, untyped API responses trusted as typed, a new dependency for what the platform has (`fetch`, `structuredClone`, `crypto.randomUUID`, `Intl`), and hooks or framework APIs from an older major version. Check the installed version's docs. `knip` finds unused exports and dependencies, `tsc --noEmit` and the project's linter come first, and `occam-audit`'s scanner has only text-level rules here.
