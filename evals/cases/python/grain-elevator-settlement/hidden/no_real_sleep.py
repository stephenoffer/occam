"""Pytest plugin for nested test runs. A patch that misses leaves real retry backoff running, which should fail fast."""

import time

time.sleep = lambda seconds: None
