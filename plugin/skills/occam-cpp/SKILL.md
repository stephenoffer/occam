---
name: occam-cpp
description: C and C++ guidance on ownership, lifetimes, undefined behavior, sanitizers, error paths, hostile input, ABI. Use alongside occam to write, debug or review C or C++ where these matter.
disable-model-invocation: true
---

# C and C++

Read the actual manifest and conventions before choosing commands, and use the ecosystem's established tools. Don't translate patterns from another language mechanically.

- **Tooling:** check the build system, language standard, compiler flags and warning level. Run tests under ASan and UBSan, and TSan for concurrent code, where available.
- **Memory:** state ownership and lifetimes for every pointer you introduce. In C++, prefer RAII and smart pointers. Watch for use-after-free, iterator invalidation, buffer overflows, integer overflow in size calculations, and returning views into temporaries.
- **Undefined behavior:** signed overflow, out-of-bounds access, data races and uninitialized reads can make a test pass and production fail. Passing tests isn't evidence of absence here.
- **Errors and cleanup:** check every return value in C and use a consistent cleanup path. Follow the project's exception policy in C++, and keep destructors non-throwing.
- **Input:** treat lengths and format strings from outside as hostile, and prefer bounded functions.
- **Headers and ABI:** a change to a public header or struct layout can break callers that still compile. Treat it as a public contract.
- **What generated code gets wrong here:** unchecked `malloc` and return values, `strcpy` and `sprintf`, raw `new` with no owner, `using namespace` in headers, invalidated iterators, invented standard library functions or ones newer than the project's standard, and tests that pass under undefined behavior. Sanitizers and `clang-tidy` come first, and `occam-audit`'s scanner has only text-level rules here.
