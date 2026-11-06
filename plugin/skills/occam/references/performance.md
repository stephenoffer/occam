# Performance, scale and resource safety

## Start from a workload model

Translate "fast" and "scalable" into input sizes and distributions, concurrency, latency or throughput goals, memory and storage limits, hardware, failure expectations and cost. If missing information changes the architecture, ask. For a safe reversible choice, state an assumption and don't claim unsupported scale.

## Find what binds

Find the stage that limits the goal before tuning anything, and read stages and workers one at a time. An outer bound makes everything under it look idle, and an average across workers hides the one the others wait for. Try the least invasive change that moves the binding stage. If your speedup comes from replacing the component you were asked to tune, say so, since that is a different change from tuning it.

## Find what grows

Identify resource growth: CPU, peak memory, queue depth, open files, connections, retries, disk, network requests, fan-out, retained state.

Look for accidental quadratic work, repeated parsing, N+1 queries, unbounded buffering, full materialization, unnecessary sorting, repeated serialization and copies, lock contention, and parallelism multiplied across libraries or processes.

Fix the whole path. After removing the obvious hot spot, re-measure: the next stage may materialize everything anyway, and a fix to time alone can leave memory over the limit. Preserve behavior the old shape gave for free, such as ordering and what a failure leaves behind.

## Bound what can be exhausted

Bound concurrency, memory, retries and queues when exhaustion is plausible. Use deadlines, backpressure, pagination or chunking, batching, spilling to disk, admission control or caching as required.

A cache isn't a free fix. Define invalidation, size bounds and consistency, and confirm that the time really goes where the cache would help before adding one.

## Distributed systems

Examine skew, stragglers, retry storms, duplicate or out-of-order delivery, worker loss, cancellation, idempotency, partial failure, coordination overhead and consistency.

## Measuring

Measure material performance claims. `occam bench --cmd "... {n}" --sizes ...` runs fresh processes across sizes and reports time, peak memory and growth, and a local measurement is all it claims:

- Run the untouched code first, with the command you will compare against, before changing anything. If you have already edited, measure it from a separate worktree or copy, not a stash.
- Change one thing per measurement, and judge it against the run-to-run noise from repeats. A move inside the noise isn't a win.
- Report the number from the final code. A figure from an earlier version is stale, however recent.
- Use a representative baseline and the changed version in comparable environments.
- Validate that the output is equivalent, because a faster wrong answer isn't an improvement.
- Record dataset shape, runtime and hardware, cold or warm state, relevant contention, repetitions and variability.
- Measure peak memory as well as elapsed time when memory matters, in a fresh process, so earlier work doesn't distort the peak.
- Use percentiles, not averages alone, when tail latency is the requirement.

Run at the required size, or say you didn't. A tiny happy-path benchmark doesn't establish large-scale readiness.

Report how much headroom you measured relative to the limit, and label each claim as one of:

| Evidence | Supports |
|---|---|
| Static complexity reasoning | How it should grow |
| Local measurement | This machine, this data |
| Production-scale evidence | Real capacity |

Explain any extrapolation and its limits. If profiling or the target hardware is unavailable, report what remains unverified. Run only the depth of performance testing the change and its acceptance criteria justify.
