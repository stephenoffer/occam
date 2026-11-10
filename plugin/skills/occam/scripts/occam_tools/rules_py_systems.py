"""Python rules for what goes wrong below the code's own logic: storage settings that drop acknowledged writes, offsets committed before
the work they count, memory handed to C, and objects threads share. Each reads the whole tree on its own.

docs/quality-catalog.md says which failure each answers. None of these reaches high confidence, so they show as leads in `scan` and `gate`
and never send an agent back on their own.
"""

from __future__ import annotations

import ast
import re
from collections.abc import Iterator

from .py_helpers import _walk_own
from .rules_py_agent import FUNCTIONS, _text

# ---------------------------------------------------------------- durability

_UNSAFE_PRAGMA = re.compile(r"\bPRAGMA\s+(?:\w+\.)?(?:synchronous\s*=\s*(?:OFF|0)\b|journal_mode\s*=\s*(?:OFF|MEMORY)\b)", re.I)
_PRODUCER = re.compile(r"(?:^|\.)(?:\w*Producer)$")


def _no_ack(value: ast.AST) -> bool:
    return isinstance(value, ast.Constant) and value.value in (0, "0")


def _durability(tree: ast.Module) -> Iterator[tuple]:
    """Settings under which a write the caller is told succeeded can still vanish: Kafka's acks=0, SQLite with synchronous or the journal off,
    MongoDB's w=0."""
    for node in (node for node in ast.walk(tree) if isinstance(node, ast.Call)):
        name = _text(node.func)
        keywords = {keyword.arg: keyword.value for keyword in node.keywords}
        configs = [argument for argument in node.args if isinstance(argument, ast.Dict)]
        settings = {key.value: value for config in configs for key, value in zip(config.keys, config.values) if isinstance(key, ast.Constant)}
        if _PRODUCER.search(name) and (_no_ack(keywords.get("acks")) or _no_ack(settings.get("acks"))):
            yield ("durability-disabled", node.lineno, "acks=0 means the producer doesn't wait for any broker to store the message, so one lost on the way "
                   "is gone, though the caller was told it was recorded. Use acks='all' and wait on the send.", {})
        elif _no_ack(keywords.get("w")) and re.search(r"(?:^|\.)(?:MongoClient|AsyncIOMotorClient|WriteConcern|with_options)$", name):
            yield ("durability-disabled", node.lineno, "w=0 asks MongoDB for no acknowledgement, so a failed write looks like a successful one.", {})
        elif node.args and isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str) and _UNSAFE_PRAGMA.search(node.args[0].value):
            yield ("durability-disabled", node.lineno, f"`{_UNSAFE_PRAGMA.search(node.args[0].value).group(0)}` lets a crash or power loss drop or corrupt "
                   "writes SQLite already reported as committed. Keep synchronous at NORMAL with WAL, or FULL.", {})


_CONSUMER = re.compile(r"(?:^|\.)(?:\w*Consumer)$")


def _auto_commit_with_buffer(tree: ast.Module) -> Iterator[tuple]:
    """Auto-commit marks records consumed on a timer. When they wait in a buffer across polls, a crash after a commit loses the ones not yet written."""
    for function in (node for node in ast.walk(tree) if isinstance(node, FUNCTIONS)):
        consumer = None
        for node in (node for node in _walk_own(function) if isinstance(node, ast.Call) and _CONSUMER.search(_text(node.func))):
            keywords = {keyword.arg: keyword.value for keyword in node.keywords}
            settings = {key.value: value for argument in node.args if isinstance(argument, ast.Dict) for key, value in zip(argument.keys, argument.values) if isinstance(key, ast.Constant)}
            flag = keywords.get("enable_auto_commit", settings.get("enable.auto.commit"))
            if isinstance(flag, ast.Constant) and flag.value in (True, "true", "True"):
                consumer = node
        if consumer is None:
            continue
        grown = {_text(node.func.value) for loop in _walk_own(function) if isinstance(loop, (ast.For, ast.While, ast.AsyncFor))
                 for node in ast.walk(loop) if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr in ("append", "extend")}
        flushed_later = any(isinstance(node, ast.Compare) and isinstance(node.left, ast.Call) and _text(node.left.func) == "len" and node.left.args
                            and _text(node.left.args[0]) in grown for node in _walk_own(function))
        if flushed_later:
            yield ("auto-commit-before-write", consumer.lineno, "Offsets are auto-committed on a timer while records wait in a buffer until it fills, so a "
                   "crash after a commit skips the records that weren't written yet. Turn auto-commit off and commit after each flush.", {})


# ---------------------------------------------------------------- memory handed to C

_DTYPE_NAME = re.compile(r"(?:np|numpy)\.(float16|float32|float64|double|single|int8|int16|int32|int64|uint8|uint16|uint32|uint64|intc|bool_)\b|[\"'](float32|float64|f4|f8|int32|int64|i4|i8|uint8|u1)[\"']")
_DTYPE_ALIASES = {"double": "float64", "single": "float32", "f4": "float32", "f8": "float64", "i4": "int32", "i8": "int64", "u1": "uint8", "intc": "int32"}
# What a ctypes pointer type reads each element as.
_C_TYPES = {"c_float": "float32", "c_double": "float64", "c_int8": "int8", "c_byte": "int8", "c_int16": "int16", "c_short": "int16", "c_int32": "int32",
            "c_int": "int32", "c_int64": "int64", "c_longlong": "int64", "c_uint8": "uint8", "c_ubyte": "uint8", "c_uint16": "uint16", "c_uint32": "uint32",
            "c_uint": "uint32", "c_uint64": "uint64", "c_ulonglong": "uint64", "c_bool": "bool_"}
_FRESH_FLOAT64 = re.compile(r"^(?:np|numpy)\.(?:zeros|empty|ones)$")  # fresh and contiguous, float64 unless told otherwise
_FIXES_LAYOUT = re.compile(r"ascontiguousarray|\brequire\(|\.copy\(")


def _known_dtype(value: ast.AST | None, bound: dict, depth: int = 0) -> str | None:
    """The dtype an array is made with, when the code fixes it: `dtype=` or `.astype()` on anything that makes a fresh contiguous array, or
    np.zeros, np.empty and np.ones with none, which are float64. None when it depends on the input, as np.asarray(x) does."""
    if not isinstance(value, ast.Call) or depth > 3:
        return None
    name = _text(value.func)
    given = next((keyword.value for keyword in value.keywords if keyword.arg == "dtype"), None)
    if given is None and name.endswith(".astype") and value.args:
        given = value.args[0]
    if given is not None:
        found = _DTYPE_NAME.search(_text(given))
        return _DTYPE_ALIASES.get(found.group(1) or found.group(2), found.group(1) or found.group(2)) if found else "fixed"
    if _FRESH_FLOAT64.match(name):
        return "float64"
    if name.rsplit(".", 1)[-1] in ("empty_like", "zeros_like", "ones_like") and value.args and isinstance(value.args[0], ast.Name):
        return next((_known_dtype(item, bound, depth + 1) for item in bound.get(value.args[0].id, [])), None)
    return None


def _buffers_of_unknown_type(tree: ast.Module) -> Iterator[tuple]:
    """`arr.ctypes.data_as(POINTER(c_float))` hands C the raw bytes of whatever dtype and strides arr has. An array whose dtype this code
    fixes is fine when it matches the pointer, and wrong when it doesn't. One whose dtype comes from the input is unknown."""
    for function in (node for node in ast.walk(tree) if isinstance(node, FUNCTIONS)):
        bound: dict[str, list] = {}
        for node in _walk_own(function):
            if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
                bound.setdefault(node.targets[0].id, []).append(node.value)
        mentions_dtype = re.search(r"\.dtype\b|\.flags\b", _text(function))
        passed = sorted((node for node in _walk_own(function) if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "data_as"),
                        key=lambda node: (node.lineno, node.col_offset))
        for node in passed:
            owner = node.func.value.value if isinstance(node.func.value, ast.Attribute) and node.func.value.attr == "ctypes" else None
            if not isinstance(owner, ast.Name) or not node.args or "POINTER" not in _text(node.args[0]):
                continue
            pointed = _C_TYPES.get(_text(node.args[0]).rsplit(".", 1)[-1].rstrip(")").rsplit("(", 1)[-1].rsplit(".", 1)[-1])
            dtypes = {_known_dtype(value, bound) for value in bound.get(owner.id, [None])}
            if None not in dtypes and (pointed is None or dtypes <= {pointed, "fixed"}):
                continue
            if None in dtypes and (mentions_dtype or any(_FIXES_LAYOUT.search(_text(value)) for value in bound.get(owner.id, []))):
                continue
            wrong = sorted(dtypes - {None, "fixed", pointed})
            detail = f"is {wrong[0]}, but C reads it as {pointed}" if wrong and pointed else "has whatever dtype and layout its input had"
            yield ("ctypes-buffer-unchecked", node.lineno, f"{owner.id} goes to C as {_text(node.args[0])[:50]} and {detail}, so C reads the wrong width or "
                   "walks a strided view as packed. Convert with np.ascontiguousarray(..., dtype=...) first.", {})
            break


_CALLBACK_TYPE = re.compile(r"(?:^|\.)(?:CFUNCTYPE|WINFUNCTYPE|PYFUNCTYPE)$")
# Functions that keep a callback to call later. qsort() and friends call it before they return, so inline is fine there.
_KEEPS_IT = re.compile(r"start|register|set_?\w*(?:callback|handler|hook|listener)|subscribe|install|add_?\w*(?:callback|handler|listener|hook)|listen|watch|async|spawn|on_", re.I)


def _callbacks_left_to_collect(tree: ast.Module) -> Iterator[tuple]:
    """A ctypes callback object made inline as an argument has no other reference, so Python frees it once the call returns. C code that
    kept the pointer then calls freed memory."""
    types = {node.targets[0].id for node in ast.walk(tree) if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name)
             and isinstance(node.value, ast.Call) and _CALLBACK_TYPE.search(_text(node.value.func))}
    for node in (node for node in ast.walk(tree) if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)):
        if not _KEEPS_IT.search(node.func.attr):
            continue
        made = [argument for argument in [*node.args, *(keyword.value for keyword in node.keywords)] if isinstance(argument, ast.Call)
                and ((isinstance(argument.func, ast.Name) and argument.func.id in types) or (isinstance(argument.func, ast.Call) and _CALLBACK_TYPE.search(_text(argument.func.func))))]
        if made:
            yield ("ctypes-callback-collected", node.lineno, f"The callback passed to {node.func.attr}() is made inline, so nothing keeps it alive and Python "
                   "can free it while C still calls it. Store it, on the object that owns the job, until C is done with it.", {})


# ---------------------------------------------------------------- objects threads share

# Signs that this code runs on several threads at once. A web framework's import isn't one by itself, since many serve one request per process.
_THREADED = re.compile(r"\bimport\s+threading\b|\bfrom\s+threading\s+import\b|\bThread\(|\bThreadPoolExecutor\b|\bthreaded\s*=\s*True|\bconcurrent\.futures\b")
_LOCKS = re.compile(r"\b(?:R?Lock|Semaphore|BoundedSemaphore|Condition)\(|\bwith\s+self\.\w*lock\w*|\bacquire\(", re.I)


_SERVES = re.compile(r"\bfrom\s+(?:flask|django|fastapi|starlette)\b|\bimport\s+(?:flask|django|fastapi|starlette)\b")


def _self_attribute(node: ast.AST) -> str | None:
    return node.attr if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name) and node.value.id == "self" else None


def _check_then_act(tree: ast.Module, text: str) -> Iterator[tuple]:
    """`if self.tokens >= cost: self.tokens -= cost` in a class with no lock, in code that runs on threads: two threads both pass the check."""
    threaded = bool(_THREADED.search(text))
    for cls in (node for node in ast.walk(tree) if isinstance(node, ast.ClassDef)):
        # Or one instance kept for the whole process, at module level or in a module-level registry, in code that serves requests.
        shared = threaded or (bool(_SERVES.search(text)) and any(re.search(rf"\b{cls.name}\(", _text(node.value)) for node in tree.body
                                                                 if isinstance(node, (ast.Assign, ast.AnnAssign)) and node.value is not None))
        if not shared or _LOCKS.search(_text(cls)):
            continue
        for guard in (node for method in cls.body if isinstance(method, FUNCTIONS) for node in _walk_own(method) if isinstance(node, ast.If)):
            tested = {_self_attribute(node.left) for node in ast.walk(guard.test)  # a limit: `self.tokens >= cost`, not `self.size is not None`
                      if isinstance(node, ast.Compare) and any(isinstance(op, (ast.Gt, ast.GtE, ast.Lt, ast.LtE)) for op in node.ops)} - {None}
            changed = next((node for statement in guard.body for node in ast.walk(statement)
                            if isinstance(node, ast.AugAssign) and _self_attribute(node.target) in tested), None)
            if changed is not None:
                yield ("lost-update", changed.lineno, f"self.{_self_attribute(changed.target)} is checked and then changed with no lock, so two threads can "
                       "both pass the check before either changes it. Hold a threading.Lock across both.", {})
                break


def _rebuilt_in_place(tree: ast.Module) -> Iterator[tuple]:
    """A class that runs a thread and refreshes a collection with `self.items.clear()` then appends: readers on other threads see it empty or
    half built. Building a new one and assigning it swaps it whole."""
    for cls in (node for node in ast.walk(tree) if isinstance(node, ast.ClassDef)):
        source = _text(cls)
        if not re.search(r"\bThread\(|\bTimer\(", source) or _LOCKS.search(source):
            continue
        for method in (item for item in cls.body if isinstance(item, FUNCTIONS)):
            calls = [node for node in _walk_own(method) if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)]
            cleared = {_self_attribute(node.func.value): node for node in calls if node.func.attr == "clear"} if calls else {}
            refilled = {_self_attribute(node.func.value) for node in calls if node.func.attr in ("append", "extend", "add", "update", "insert")}
            emptied = next((name for name in cleared if name and name in refilled), None)
            if emptied:
                yield ("rebuilt-while-shared", cleared[emptied].lineno, f"self.{emptied} is cleared and refilled in place while this class's thread runs, so "
                       "a reader on another thread can see it empty or half built. Build the new one apart and assign it in one step.", {})
                break


def findings(tree: ast.Module, path: str, is_test: bool, is_script: bool, text: str = "") -> list[tuple]:
    """(rule, line, message, overrides) for one parsed module. A rule that breaks on unusual code loses only its own findings."""
    if is_test:
        return []
    # Each rule runs only where the module's text holds what it looks for.
    wanted = [(_auto_commit_with_buffer, r"Consumer"), (_buffers_of_unknown_type, r"data_as"), (_callbacks_left_to_collect, r"FUNCTYPE"),
              (_rebuilt_in_place, r"Thread\(|Timer\(")]
    if not is_script:  # a one-off load script may turn durability off on purpose
        wanted.append((_durability, r"acks|PRAGMA|\bw\s*=\s*0"))
    rules = [lambda rule=rule: rule(tree) for rule, needs in wanted if not text or re.search(needs, text)]
    if not text or "self." in text:
        rules.append(lambda: _check_then_act(tree, text))
    found: list[tuple] = []
    for rule in rules:
        try:
            found += list(rule())
        except (RecursionError, ValueError, AttributeError, TypeError):  # occam: ignore[swallowed-exception] one rule's miss, never the file's
            continue
    return found
