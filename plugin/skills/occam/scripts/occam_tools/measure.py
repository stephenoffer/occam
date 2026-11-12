"""Evidence from running a command: whether its output changed since a recording, and how its time and memory grow with the input."""

from __future__ import annotations

import base64
import binascii
import difflib
import hashlib
import json
import math
import os
import platform
import re
import shlex
import signal
import statistics
import subprocess
import tempfile
import time
from itertools import zip_longest
from pathlib import Path

from . import files as filesystem
from .workflow import needs_a_shell
from .zero_tests import ran_no_tests

STREAMS = ("stdout", "stderr")


# ---------------------------------------------------------------- golden master


def _golden_path(root: Path, name: str) -> Path:
    """One file for each exact name. `a b`, `a_b` and `a/b` read alike once made safe for a file name, and the hash keeps them apart."""
    folder = filesystem.state_dir(root) / "golden"
    folder.mkdir(exist_ok=True)
    digest = hashlib.sha256(name.encode("utf-8", "surrogateescape")).hexdigest()[:16]
    return folder / f"{re.sub(r'[^A-Za-z0-9_.-]', '_', name)[:60]}-{digest}.json"


def _older_path(root: Path, name: str) -> Path | None:
    """Where an older occam kept a recording. Names like `a b` and `a_b` shared that spelling, so only a name it left unchanged can be trusted to own it."""
    stem = re.sub(r"[^\w.-]", "_", name)
    return filesystem.state_dir(root) / "golden" / f"{stem}.json" if stem == name else None


class CommandFailed(Exception):
    """The command couldn't run at all, which is different from running and failing."""


def _run_for_golden(root: Path, command: list[str], timeout: int) -> dict:
    try:
        done = filesystem.run_bounded(command, root, timeout)
    except subprocess.TimeoutExpired as error:
        raise CommandFailed(f"It didn't finish in {timeout}s.") from error
    except OSError as error:
        raise CommandFailed(f"It couldn't start: {error}.") from error
    if getattr(done, "cut", False):  # a recording is only worth its every byte
        raise CommandFailed("Its output passed 8 MB, so it can't be kept whole to compare. Record something smaller, such as its output piped through a hash.")
    # Exact bytes, so `\\r\\n` becoming `\\n`, or byte 0xFF becoming the text `\\xff`, still reads as a change.
    return {"exit": done.returncode, "stdout": done.stdout, "stderr": done.stderr}


def _normalize(output: dict, patterns: list[str]) -> dict:
    """Patterns are text. Decoding with surrogateescape gives back exactly the same bytes afterward, even where the output isn't UTF-8."""
    cleaned = dict(output)
    for key in STREAMS:
        text = output[key].decode("utf-8", "surrogateescape")
        for pattern in patterns:
            text = re.sub(pattern, "<normalized>", text)
        cleaned[key] = text.encode("utf-8", "surrogateescape")
    return cleaned


def _as_older_occam_stored(output: dict, patterns: list[str]) -> dict:
    """An older occam stored output decoded as text, so a recording it made is compared the same way."""
    cleaned = {"exit": output["exit"]}
    for key in STREAMS:
        cleaned[key] = output[key].decode("utf-8", "backslashreplace")
        for pattern in patterns:
            cleaned[key] = re.sub(pattern, "<normalized>", cleaned[key])
    return cleaned


def _write_atomically(path: Path, text: str) -> None:
    """A run stopped halfway leaves the last recording whole, not half of a new one."""
    handle, temporary = tempfile.mkstemp(dir=path.parent, prefix=path.name, suffix=".tmp")
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as file:
            file.write(text)
        os.replace(temporary, path)
    except BaseException:
        os.unlink(temporary)
        raise


def _load(path: Path, name: str) -> dict:
    """The recording, with `older` set for one an older occam made. A damaged one raises ValueError saying what's wrong."""
    recorded = json.loads(path.read_bytes())
    if not isinstance(recorded, dict):
        raise ValueError("it isn't a JSON object")
    command, patterns, result = recorded.get("command"), recorded.get("patterns", []), recorded.get("result")
    if not (isinstance(command, list) and command and all(isinstance(word, str) for word in command)):
        raise ValueError("its command isn't a list of words")
    if not (isinstance(patterns, list) and all(isinstance(pattern, str) for pattern in patterns)):
        raise ValueError("its --normalize patterns aren't a list of text")
    if not isinstance(result, dict) or type(result.get("exit")) is not int or not all(isinstance(result.get(key), str) for key in STREAMS):
        raise ValueError("its result needs a whole-number exit code and both streams")
    for pattern in patterns:
        try:
            re.compile(pattern)
        except re.error as error:
            raise ValueError(f"its pattern {pattern!r} isn't valid: {error}") from error
    older = recorded.get("format") != 2
    if not older and recorded.get("name") != name:
        raise ValueError(f"it holds the recording named {recorded.get('name')!r}")
    try:
        streams = {key: result[key] if older else base64.b64decode(result[key], validate=True) for key in STREAMS}
    except binascii.Error as error:
        raise ValueError(f"its output isn't base64: {error}") from error
    return {"command": command, "patterns": patterns, "older": older, "result": {"exit": result["exit"], **streams}}


def golden_record(root: Path, name: str, command: list[str], timeout: int, patterns: list[str]) -> tuple[str, int]:
    if not command:
        return "Give the command after --.", 2
    try:
        for pattern in patterns:
            re.compile(pattern)
    except re.error as error:
        return f"--normalize {pattern!r} isn't a valid expression: {error}.", 2
    try:
        first = _normalize(_run_for_golden(root, command, timeout), patterns)
        second = _normalize(_run_for_golden(root, command, timeout), patterns)
    except CommandFailed as error:
        return f"Not recorded. {error}", 2
    if first != second:
        return ("This command isn't deterministic: two runs differ. Fix the seed or clock, or blank the varying parts with --normalize. Not recorded.", 1)
    stored = {key: base64.b64encode(first[key]).decode("ascii") for key in STREAMS}
    try:
        _write_atomically(_golden_path(root, name), json.dumps({"format": 2, "name": name, "command": command, "patterns": patterns, "result": {"exit": first["exit"], **stored}}))
    except OSError as error:
        return f"Not recorded: it couldn't be saved ({error}). Any earlier recording named '{name}' is unchanged.", 2
    caution = ""
    if first["exit"]:
        caution = f" It exits {first['exit']}, so this records a failure, and a later match won't show it works."
    elif not first["stdout"] and not first["stderr"]:
        caution = " It prints nothing, so a later match will say very little."
    elif ran_no_tests((first["stdout"] + b"\n" + first["stderr"]).decode("utf-8", "replace")):
        caution = " It ran zero tests, so a later match won't show anything works."
    return f"Recorded '{name}': exit {first['exit']}, {len(first['stdout'])} bytes of output, identical across two runs.{caution}", 0


def _differences(recorded: dict, current: dict) -> list[str]:
    lines = []
    if current["exit"] != recorded["exit"]:
        lines.append(f"Exit {recorded['exit']} became {current['exit']}.")
    for stream in STREAMS:
        before, after = (value if isinstance(value, str) else value.decode("utf-8", "backslashreplace") for value in (recorded[stream], current[stream]))
        lines += list(difflib.unified_diff(before.splitlines(), after.splitlines(), "recorded", "current", lineterm="", n=1))[:40]
    if lines:
        return lines
    stream = next(stream for stream in STREAMS if recorded[stream] != current[stream])
    empty = recorded[stream][:0]
    old, new = next(pair for pair in zip_longest(recorded[stream].splitlines(True), current[stream].splitlines(True), fillvalue=empty) if pair[0] != pair[1])
    return [f"Only line endings or other invisible differences, such as an invalid byte that prints like the text of one. The first, in {stream}: {old!r} became {new!r}."]


def golden_check(root: Path, name: str, timeout: int) -> tuple[str, int]:
    path, older_path = _golden_path(root, name), _older_path(root, name)
    if not path.exists() and older_path is not None and older_path.exists():
        path = older_path
    if not path.exists():
        return f"No recording named '{name}'.", 2
    try:
        recorded = _load(path, name)
    except (OSError, ValueError, RecursionError) as error:
        return f"The recording '{name}' is damaged, so nothing was checked: {error}. Record it again. It's {path}.", 2
    try:
        output = _run_for_golden(root, recorded["command"], timeout)
    except CommandFailed as error:
        return f"'{name}' couldn't be checked. {error}", 2
    current = _as_older_occam_stored(output, recorded["patterns"]) if recorded["older"] else _normalize(output, recorded["patterns"])
    older = (" An older occam made this recording and stored its output as text, so an invalid byte and its escaped spelling read the same."
             + (" It also gave names like 'a b' and 'a_b' one file, so this may be another name's recording." if recorded["older"] and "_" in name else "")
             + " Recording it again makes the check exact.") if recorded["older"] else ""
    if current == recorded["result"]:
        failing = f" It was already exiting {current['exit']} when recorded, so this doesn't show it works." if current["exit"] else ""
        return f"'{name}' unchanged: same exit code and output.{failing}{older}", 0
    return "\n".join([f"'{name}' CHANGED.", *_differences(recorded["result"], current)]) + (f"\n{older.strip()}" if older else ""), 1


# ---------------------------------------------------------------- bench


def _stop(process: subprocess.Popen) -> None:
    """Its whole process group, since killing only the command would leave what it started running."""
    if hasattr(os, "killpg"):
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except OSError:
            pass
    process.kill()
    process.wait()


def _measure(command: list[str], timeout: int) -> tuple[float, float | None, int]:
    """Wall seconds, peak RSS in MB and exit code of one fresh process. Peak memory is None where os.wait4 doesn't exist, as on Windows."""
    started = time.perf_counter()
    process = subprocess.Popen(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=hasattr(os, "killpg"))
    filesystem._running.add(process)  # so stopping occam stops this too
    try:
        if not hasattr(os, "wait4"):
            process.wait(timeout)
            return time.perf_counter() - started, None, process.returncode
        while True:
            pid, status, usage = os.wait4(process.pid, os.WNOHANG)
            if pid:
                break
            if time.perf_counter() > started + timeout:
                raise subprocess.TimeoutExpired(command, timeout)
            time.sleep(0.005)
    except BaseException:
        _stop(process)
        raise
    finally:
        filesystem._running.discard(process)
        if hasattr(os, "killpg"):  # what it left running in the background would run on into the next measurement
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except OSError:
                pass
    elapsed = time.perf_counter() - started
    process.returncode = os.waitstatus_to_exitcode(status) if hasattr(os, "waitstatus_to_exitcode") else (status >> 8)
    divisor = 1024 * 1024 if platform.system() == "Darwin" else 1024
    return elapsed, usage.ru_maxrss / divisor, process.returncode


def _has_signal(xs: list[float], ys: list[float]) -> bool:
    """Whether at least two runs took measurably longer than startup."""
    return sum(1 for x, y in zip(xs, ys) if x > 0 and y - 0.95 * min(ys) > 0.02) >= 2


def _slope(xs: list[float], ys: list[float]) -> float | None:
    """Least-squares exponent of y = a + b * x^k, trying several startup costs `a` and keeping the straightest fit in log space.

    Assuming nearly all of the smallest run is startup would make plain linear work with none read as quadratic.
    None when startup hides the work, and when no fit through three or more points is straight enough to read an exponent from.
    """
    if not _has_signal(xs, ys):
        return None
    best: tuple[float, float] | None = None
    # Up close to all of the smallest run: one second of startup under a millisecond of linear work is still linear work.
    for share in (0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 0.95, 0.98, 0.99, 0.995, 0.999):
        floor = share * min(ys)
        least = max(1e-4, 0.005 * (max(ys) - floor))  # what's left above the floor has to be more than rounding
        pairs = [(math.log(x), math.log(y - floor)) for x, y in zip(xs, ys) if x > 0 and y - floor > least]
        if len(pairs) < 3:  # two points fit any curve
            continue
        mean_x = statistics.mean(p[0] for p in pairs)
        mean_y = statistics.mean(p[1] for p in pairs)
        across = sum((p[0] - mean_x) ** 2 for p in pairs)
        spread = sum((p[1] - mean_y) ** 2 for p in pairs)
        if not across:
            continue
        slope = sum((p[0] - mean_x) * (p[1] - mean_y) for p in pairs) / across
        straightness = round(slope ** 2 * across / spread, 3) if spread else 1.0
        if best is None or straightness > best[0]:  # a tie keeps the smaller startup cost, the plainer reading
            best = (straightness, slope)
    return best[1] if best and best[0] >= 0.9 else None


def _growth(xs: list[float], ys: list[float]) -> tuple[float | None, str]:
    """The exponent, or why none can be trusted: 'startup' when startup hides the work, or a reason the data can't settle it."""
    if not _has_signal(xs, ys):
        return None, "startup"
    if len(set(xs)) < 3:
        return None, f"{len(set(xs))} sizes can't show it, since two points fit any curve"
    rising = all(later > earlier for earlier, later in zip(ys, ys[1:]))  # noise goes up and down; 10 s of startup hiding real growth rises every time
    if max(ys) <= 1.1 * min(ys) and max(xs) >= 4 * min(xs) and not rising:
        return 0.0, ""  # flat across a wide range, where noise would make any fit crooked
    if any(later < 0.9 * earlier for earlier, later in zip(ys, ys[1:])):
        return None, "a larger size ran faster than a smaller one"
    exponent = _slope(xs, ys)
    return (exponent, "") if exponent is not None else (None, "no single power of n fits these numbers")


def _growth_line(done: list[tuple]) -> tuple[str, bool]:
    """Describe how time grew. True if it's worse than linear."""
    sizes = [float(r[0]) for r in done]
    time_growth, why = _growth(sizes, [r[1] for r in done])
    if why == "startup":
        return f"Not enough signal to fit growth: the largest run took {done[-1][1]:.3f}s, mostly startup. Use larger sizes.", False
    if time_growth is None:
        return f"Growth is inconclusive: {why}. Use at least three sizes spread wider, or more --repeat. This says nothing about its complexity.", False
    shape = "about linear or better" if time_growth < 1.25 else "superlinear" if time_growth < 1.8 else "about quadratic or worse"
    memory = ""
    if all(r[3] is not None for r in done):
        memory_growth, why = _growth(sizes, [r[3] for r in done])
        memory = (f" Peak memory grows like n^{memory_growth:.2f}." if memory_growth is not None else
                  " Peak memory stayed about flat." if why == "startup" else f" Peak memory growth is inconclusive: {why}.")
    return f"Time grows like n^{time_growth:.2f}: {shape}.{memory}", time_growth >= 1.25


def _limit_line(limit: float, value: float, size: int) -> tuple[str, bool]:
    if value > limit:
        return f"Time limit {limit}s EXCEEDED: {value:.2f}s at n={size}.", True
    headroom = limit / value if value else float("inf")
    return f"Time limit {limit}s: measured {value:.2f}s at n={size}, {headroom:.1f}x headroom.", False


def _bench_rows(template: str, sizes: list[int], repeat: int, timeout: int) -> list[tuple]:
    """(size, median seconds, spread, peak MB or None, status) for each size, stopping at the first that fails."""
    rows = []
    for size in sorted(sizes):
        text = template.replace("{n}", str(size))
        command = ["sh", "-c", text] if needs_a_shell(template) else shlex.split(text)
        times, memory = [], []
        status = "ok"
        for _ in range(repeat):
            try:
                elapsed, rss, code = _measure(command, timeout)
            except subprocess.TimeoutExpired:
                status = "timed out"
                break
            except OSError as error:
                status = f"couldn't start: {error.strerror}"
                break
            if code != 0:
                status = f"exit {code}"
                break
            times.append(elapsed)
            memory.append(rss)
        if status != "ok":
            rows.append((size, None, None, None, status))
            break
        rows.append((size, statistics.median(times), max(times) - min(times), None if None in memory else max(memory), status))
    return rows


def bench(template: str, sizes: list[int], repeat: int, limit_seconds: float | None, timeout: int) -> tuple[str, int]:
    if "{n}" not in template:
        return "The command needs {n} where the size goes.", 2
    try:
        shlex.split(template)
    except ValueError as error:
        return f"That command can't be read: {error}.", 2
    rows = _bench_rows(template, sizes, repeat, timeout)
    done = [r for r in rows if r[4] == "ok"]
    out = [f"{os.cpu_count()} CPUs, {platform.system()} {platform.machine()}, Python {platform.python_version()}. Each row: {repeat} fresh processes, median time and largest peak RSS."]
    if needs_a_shell(template):
        out.append("It uses shell syntax, so each run went through sh -c, whose own start is in the times.")
    if not hasattr(os, "wait4"):
        out.append("Peak memory isn't measured here, since this platform has no os.wait4. Times are wall-clock.")
    out.append(f"{'size':>12}{'seconds':>10}{'spread':>9}{'peak MB':>10}  status")
    for size, seconds, spread, rss, status in rows:
        measured = f"{seconds:>10.3f}{spread:>9.3f}" + (f"{rss:>10.1f}" if rss is not None else f"{'-':>10}") if status == "ok" else f"{'-':>10}{'-':>9}{'-':>10}"
        out.append(f"{size:>12}{measured}  {status}")
    failed = len(done) != len(rows)
    if len(done) >= 2:
        line, worse = _growth_line(done)
        out.append(line)
        failed = failed or worse
    if done and limit_seconds is not None:
        line, exceeded = _limit_line(limit_seconds, done[-1][1], done[-1][0])
        out.append(line)
        failed = failed or exceeded
    out.append("Evidence label: local measurement, this machine and this data. It says how it grew here, not what production capacity is. Check the output is still correct too.")
    return "\n".join(out), 2 if any(row[4].startswith("couldn't start") for row in rows) else 1 if failed else 0
