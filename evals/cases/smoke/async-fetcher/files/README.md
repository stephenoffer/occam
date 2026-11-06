# bulkfetch

Fetches many URLs concurrently over a transport supplied by the caller.

A transport has one coroutine, `await transport.get(url) -> bytes`. The caller owns the transport's lifetime.

Run the tests with `pytest`.
