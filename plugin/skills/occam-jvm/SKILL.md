---
name: occam-jvm
description: Java and Kotlin guidance on nullability, interruption, coroutine cancellation, bounded pools, transactions, exact decimals. Use alongside occam to write, debug or review Java or Kotlin where these matter.
---

# Java and Kotlin

Read the actual manifest and conventions before choosing commands, and use the ecosystem's established tools. Don't translate patterns from another language mechanically.

- **Tooling:** check Maven or Gradle configuration, the JDK target, and the established static analysis and test frameworks.
- **Nullability:** in Java, follow the project's annotations and `Optional` conventions, and in Kotlin, treat platform types from Java as unknown. `!!` should be rare and justified.
- **Resources and errors:** use try-with-resources or Kotlin `use`. Don't swallow `InterruptedException`: restore the interrupt status. Catching `Exception` in Kotlin coroutines also catches `CancellationException`, so rethrow it.
- **Concurrency:** bound thread pools and queues, since `newCachedThreadPool` and unbounded queues hide overload. Prefer `java.util.concurrent` to hand-rolled locking, and know that `ThreadLocal` interacts with pools and virtual threads. In Kotlin, use structured concurrency and avoid `GlobalScope`.
- **Data:** Use `BigDecimal` from strings for money, and mind ORM lazy loading and N+1 queries.
- **Transactions:** know where a transaction starts and ends. Framework proxies mean self-invocation can silently skip `@Transactional`.
- **What generated code gets wrong here:** swallowed `catch (Exception e)` and `printStackTrace`, `double` for money, `!!` to silence Kotlin's null checks, `GlobalScope`, N+1 through lazy ORM associations, factory and builder ceremony for one product, removed or old-major APIs (`javax` versus `jakarta`, old Spring), and untested `@Transactional` boundaries. The build's static analysis comes first, and `occam-audit`'s scanner has only text-level rules here.
