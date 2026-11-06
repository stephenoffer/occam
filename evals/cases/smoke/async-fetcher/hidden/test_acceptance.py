import asyncio
import random
import sys
import time

import pytest


@pytest.fixture(scope="module")
def module(ws):
    sys.path.insert(0, str(ws))
    import bulkfetch.fetcher as fetcher
    return fetcher


class Transport:
    def __init__(self, delay=0.0, fail=()):
        self.delay, self.fail = delay, set(fail)
        self.in_flight = self.peak = self.started = self.finished = self.cancelled = 0

    async def get(self, url):
        self.started += 1
        self.in_flight += 1
        self.peak = max(self.peak, self.in_flight)
        try:
            await asyncio.sleep(self.delay() if callable(self.delay) else self.delay)
            if url in self.fail:
                raise ValueError(url)
            self.finished += 1
            return url.encode()
        except asyncio.CancelledError:
            self.cancelled += 1
            raise
        finally:
            self.in_flight -= 1


def quick(body):
    return "digest"


def test_never_exceeds_max_concurrency(module):
    transport = Transport(delay=0.001)
    asyncio.run(module.fetch_all([f"u{i}" for i in range(500)], transport, max_concurrency=7, enrich=quick))
    assert 1 < transport.peak <= 7


def test_task_count_stays_bounded(module):
    """Bounded in-flight work is not enough: 50,000 waiting tasks are what balloon memory."""
    async def scenario():
        peak = 0

        async def watcher():
            nonlocal peak
            while True:
                peak = max(peak, len(asyncio.all_tasks()))
                await asyncio.sleep(0.001)

        watch = asyncio.create_task(watcher())
        await module.fetch_all([f"u{i}" for i in range(3000)], Transport(delay=0.001), max_concurrency=10, enrich=quick)
        watch.cancel()
        return peak

    assert asyncio.run(scenario()) <= 10 + 12


def test_generator_consumed_lazily(module):
    consumed = 0
    transport = Transport(delay=0.002)
    worst = 0

    def urls():
        nonlocal consumed, worst
        for i in range(400):
            consumed += 1
            worst = max(worst, consumed - transport.finished)
            yield f"u{i}"

    results = asyncio.run(module.fetch_all(urls(), transport, max_concurrency=5, enrich=quick))
    assert len(results) == 400
    assert worst <= 5 * 3, f"pulled {worst} URLs ahead of completed work"


def test_results_in_input_order_with_random_delays(module):
    rng = random.Random(3)
    urls = [f"u{i}" for i in range(200)]
    results = asyncio.run(module.fetch_all(urls, Transport(delay=lambda: rng.random() / 200), max_concurrency=8, enrich=quick))
    assert [result.url for result in results] == urls


def test_failures_isolated_and_reported(module):
    results = asyncio.run(module.fetch_all(["a", "bad", "c"], Transport(fail=["bad"]), enrich=quick))
    assert results[0].error is None and results[0].body == b"a" and results[0].digest == "digest"
    assert isinstance(results[1].error, ValueError)
    assert results[2].body == b"c"


def test_enrich_failure_isolated(module):
    def explode(body):
        if body == b"b":
            raise KeyError("bad content")
        return "digest"

    results = asyncio.run(module.fetch_all(["a", "b", "c"], Transport(), enrich=explode))
    assert isinstance(results[1].error, KeyError)
    assert results[0].digest == "digest" and results[2].digest == "digest"


def test_event_loop_stays_responsive_during_enrich(module):
    def slow_enrich(body):
        time.sleep(0.15)
        return "digest"

    async def scenario():
        worst, last = 0.0, time.monotonic()

        async def heartbeat():
            nonlocal worst, last
            while True:
                await asyncio.sleep(0.005)
                now = time.monotonic()
                worst, last = max(worst, now - last), now

        beat = asyncio.create_task(heartbeat())
        await module.fetch_all([f"u{i}" for i in range(12)], Transport(), max_concurrency=4, enrich=slow_enrich)
        beat.cancel()
        return worst

    assert asyncio.run(scenario()) < 0.1


def test_cancellation_propagates_and_stops_requests(module):
    transport = Transport(delay=10)

    async def scenario():
        run = asyncio.create_task(
            module.fetch_all((f"u{i}" for i in range(1000)), transport, max_concurrency=5, enrich=quick))
        await asyncio.sleep(0.05)
        started_at_cancel = transport.started
        transport.delay = 0.001  # a solution that ignores cancellation finishes quickly and fails, rather than hanging
        run.cancel()
        started = time.monotonic()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(run, timeout=2)
        assert time.monotonic() - started < 1
        await asyncio.sleep(0.05)
        assert transport.started == started_at_cancel, "new requests started after cancellation"
        assert transport.in_flight == 0, "requests kept going after cancellation"
        assert transport.cancelled == started_at_cancel
        leftovers = [task for task in asyncio.all_tasks() if task is not asyncio.current_task()]
        assert leftovers == [], f"orphaned tasks: {leftovers}"

    asyncio.run(scenario())


def test_generator_error_is_visible_without_orphans(module):
    """The prompt doesn't fix how this surfaces. Raising, an exception group and a per-item error are all
    fine. Losing the failure silently, or leaving tasks behind, is not."""
    def urls():
        yield "a"
        yield "b"
        raise RuntimeError("input source failed")

    async def scenario():
        try:
            results = await asyncio.wait_for(
                module.fetch_all(urls(), Transport(delay=0.01), max_concurrency=2, enrich=quick), timeout=5)
        except Exception as error:
            assert "input source failed" in repr(error) or (
                isinstance(error, ExceptionGroup) and error.subgroup(RuntimeError) is not None)
        else:
            assert any(result.error is not None and "input source failed" in repr(result.error) for result in results), \
                "the input failed and nothing reported it"
        await asyncio.sleep(0.05)
        leftovers = [task for task in asyncio.all_tasks() if task is not asyncio.current_task()]
        assert leftovers == [], f"orphaned tasks: {leftovers}"

    asyncio.run(scenario())


def test_defaults_still_work(module):
    results = asyncio.run(module.fetch_all(["a"], Transport()))
    assert len(results[0].digest) == 64
