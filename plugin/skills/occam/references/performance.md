# Performance, scale and resource safety

## Start from a workload model

Translate "fast" and "scalable" into input sizes and distributions, concurrency, latency or throughput goals, memory and storage limits, hardware, failure expectations and cost. If missing information changes the architecture, ask. For a safe reversible choice, state an assumption and don't claim unsupported scale.

## Find what binds

Find the stage that limits the goal before tuning anything, and read stages and workers one at a time. An outer bound makes everything under it look idle, and an average across workers hides the one the others wait for. Try the least invasive change that moves the binding stage. If your speedup comes from replacing the component you were asked to tune, say so, since that is a different change from tuning it.

## Find what grows

Identify resource growth: CPU, peak memory, queue depth, open files, connections, retries, disk, network requests, fan-out, retained state.

Look for accidental quadratic work, repeated parsing, N+1 queries, unbounded buffering, full materialization, unnecessary sorting, repeated serialization and copies, lock contention, and parallelism multiplied across libraries or processes.

Fix the whole path. After removing the obvious hot spot, re-measure: the next stage may materialize everything anyway, and a fix to time alone can leave memory over the limit. Preserve behavior the old shape gave for free, such as ordering and what a failure leaves behind.

Peak memory counts serialization too: `json.dumps`, pickling to a worker and building a response each hold another copy. Logging every event on a hot path costs I/O and money, so sample or aggregate it. A property, page load or button that users trigger casually shouldn't hide a slow or paid operation; make the cost visible and cancellable.

## Bound what can be exhausted

Bound concurrency, memory, retries and queues when exhaustion is plausible. Use deadlines, backpressure, pagination or chunking, batching, spilling to disk, admission control or caching as required.

A cache isn't a free fix. Key it by everything the result depends on, user, tenant and permissions included. Define invalidation, size bounds and consistency, and confirm that the time really goes where the cache would help before adding one.

Spilling to disk needs its own budget, a plan for a full disk, and cleanup of its files after failure as well as success. An out-of-memory failure repeats on the same input, so split the batch or cut its peak, and resume from the last good checkpoint rather than retrying the same work.

## Distributed systems

Examine skew, stragglers, retry storms, duplicate or out-of-order delivery, worker loss, cancellation, idempotency, partial failure, coordination overhead and consistency.

- **A timeout doesn't say what happened.** The other side may have acted, so check its state or use an idempotency key before repeating, and decide what a node does when it can't reach its peers.
- **A lock with a lease can expire while its holder still works.** If a stale holder can write, have storage reject it: a fencing token that only increases, checked on every write.
- **Clocks disagree and jump.** Order events by a sequence number or version from one authority, not by timestamps from different machines.
- **Partition by a stable hash.** Python's `hash()` of a string changes per process. Version the partitioning when it changes, since keys move.
- **Skew.** Count rows per key on real data before choosing a key, and split or salt the hot ones. One slow partition sets the finish time.
- **Task size.** Each task, process or remote call has a fixed cost, so batch work until computing dominates. Keep data with the workers and send back reductions rather than everything to the coordinator.
- **Nodes differ.** Hardware, memory and, during a rolling deploy, code version vary, so state each task's requirements and check them where it lands.
- **Liveness and readiness are different questions.** Liveness says restart me, readiness says stop sending me traffic. A dependency outage should fail readiness, not liveness, or every node restarts at once.
- **Serial parts cap the gain.** Find the shared lock, single database or ordered step before parallelizing, since the speedup can't pass what stays serial.
- **Reordering arithmetic changes results.** A parallel or reordered float reduction differs in its last digits, so compare within a stated margin of error.

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
- Report completed, successful operations per second with the error rate, and watch the backlog. A rate offered to a system that queues isn't throughput.
- Keep every run. If you exclude one, say which and why, by a rule set before you looked.
- Alternate baseline and candidate runs on the same machine, since temperature, power state and neighbors drift during a session.
- Measure memory on the largest and widest records, not only the typical ones.

Run at the required size, or say you didn't. A tiny happy-path benchmark doesn't establish large-scale readiness.

Report how much headroom you measured relative to the limit, and label each claim as one of:

| Evidence | Supports |
|---|---|
| Static complexity reasoning | How it should grow |
| Local measurement | This machine, this data |
| Production-scale evidence | Real capacity |

Explain any extrapolation and its limits. If profiling or the target hardware is unavailable, report what remains unverified. Run only the depth of performance testing the change and its acceptance criteria justify.

## Hardware and native code

Most of this can only be measured on the target machine, so say when you couldn't.

- **Count the CPUs you have.** `os.cpu_count()` reports the host, and neither it nor Go's `runtime.NumCPU()` knows a container's CPU quota. A process pool times BLAS or OpenMP threads per worker oversubscribes cores, so set the native thread count per worker.
- **Data movement usually dominates.** Profile cache misses, memory bandwidth and NUMA placement before tuning arithmetic. Counters that different threads write in a hot loop need their own cache line.
- **Instructions differ by machine.** `-march=native`, `target-cpu=native` or AVX intrinsics in a shipped build crash older CPUs. Build for a stated baseline, or dispatch at runtime with a tested fallback.
- **A GPU has fixed costs.** Launches and host-device copies cost more than small work saves, so measure where the GPU starts winning and keep a CPU path below it. Keep consecutive stages on the device, and batch or fuse small kernels.
- **Time GPU work after synchronizing.** CUDA and JAX run asynchronously, so a timer read without `torch.cuda.synchronize()`, `block_until_ready()` or device events times the launch.
- **Device memory is fixed.** Budget intermediates and concurrent batches, not just inputs, and check the peak the framework reports.
- **Lower precision needs an error budget.** Before switching to float16, bfloat16, TF32 or int8, compare with full precision on the inputs most sensitive to rounding, against an error bound you state in advance.
- **Compile once.** A fresh `numba.jit` or `tf.function` wrapper on each call or loop pass compiles again, and changing shapes or dtypes recompiles most JIT compilers. Cache on shapes, dtypes and settings, and check the framework's recompile count rather than assuming.
- **Acceleration is optional unless required.** Detect the GPU or instruction set, and either fall back correctly or fail with a clear message.
- **Storage has a shape.** Small writes and frequent syncs are slow on network and cloud storage. Measure request size and sync cost on the storage it will run on.
