"""C, C++ and Rust checks that read a function or a class at a time: a length or index from input reaching memory unchecked, raw
pointers with two owners or none, behaviour the standard leaves undefined, buffers that die before their consumer, and layouts that
differ across a foreign-function boundary.

Each reports what one file shows. Whether a length was checked by the caller, or a pointer is opaque to the other side, can't be seen
here, so these are leads at medium confidence: none sends an agent back at Stop. Brackets are paired once per file (`brackets.pairs`),
and each check reads a bounded window, so no input makes a check quadratic.
"""

from __future__ import annotations

import bisect
import re
from collections.abc import Iterable, Iterator
from typing import NamedTuple

from . import brackets
from .source import Source

MAX_BODY = 60_000    # how much of a body one lookup reads
MAX_SITES = 300      # sinks, acquisitions or defaults read per function or file. Real code has far fewer; hostile input can't multiply them
MAX_WINDOW = 20_000  # how far back a check or a declaration is looked for


class Function(NamedTuple):
    name: str
    start: int        # offset of the head
    body_start: int   # offset just past the opening brace
    end: int          # offset of the closing brace
    params: str


class _File(NamedTuple):
    source: Source
    code: str
    pairs: dict


def _inner(ctx: _File, opening: int, limit: int = 2000) -> str:
    return brackets.inside(ctx.code, ctx.pairs, opening, limit)


def _arguments(inner: str) -> list[str]:
    """Split a call's arguments at top-level commas."""
    parts, depth, piece = [], 0, 0
    for index, character in enumerate(inner):
        if character in "([{<" and not (character == "<" and inner[index + 1:index + 2] in "<="):
            depth += 1
        elif character in ")]}>" and not (character == ">" and inner[index - 1:index] in "->"):
            depth = max(0, depth - 1)
        elif character == "," and depth == 0:
            parts.append(inner[piece:index].strip())
            piece = index + 1
    parts.append(inner[piece:].strip())
    return parts


_KEYWORDS = {"if", "for", "while", "switch", "return", "else", "do", "case", "catch", "sizeof", "new", "delete", "throw", "using", "namespace", "typedef"}
# A definition: words for the return type and qualifiers, a name, parameters, then an optional initializer list, and a brace.
_HEAD = re.compile(r"^[ \t]*(?:[\w:<>,~]+[ \t\n*&]+){0,6}?(?P<name>~?[A-Za-z_][\w:~]*)[ \t]*\((?P<params>[^()]{0,600}(?:\([^()]{0,120}\)[^()]{0,300}){0,4})\)"
                   r"[ \t\n\w&]{0,80}(?::[^{;]{0,800})?\{", re.M)


def functions(code: str, paired: dict[int, int]) -> list[Function]:
    """Each function, outermost only: C and C++ don't nest definitions, so a head inside a body is a macro or a misreading, and reading
    every one would read the rest of the file once per head."""
    found: list[Function] = []
    for match in _HEAD.finditer(code):
        name = match.group("name")
        if name.split("::")[-1] in _KEYWORDS or (found and match.start() < found[-1].end):
            continue
        opening = match.end() - 1
        closing = paired.get(opening, -1)
        if closing > 0:
            found.append(Function(name, match.start(), opening + 1, closing, match.group("params")))
    return found


def _mentions(name: str, text: str) -> bool:
    return bool(re.search(rf"(?<![\w.>]){re.escape(name)}(?!\w)", text))


_IF_WHILE = re.compile(r"\b(?:if|while)\s*\(")
_TERNARY = re.compile(r"[^;{}?]{1,200}\?(?![?:])")
_ASSERT = re.compile(r"\b(?:assert|ASSERT|DCHECK|DCHECK_\w+|assert_param)\s*\(")
_CLAMP = re.compile(r"\b(?:MIN|min|std::min|std::clamp|clamp|MIN_)\s*\(")
_SIZED_BY = re.compile(r"(?:\b(?:malloc|calloc|realloc|alloca|resize|reserve|assign)\s*\(|\bnew\s+[\w:]+\s*\[|\bstd::(?:vector|string)\s*<[^;>]{0,200}>\s*\w+\s*[({])[^;]{0,300}")
_MASKED = re.compile(r"(?<![\w.>])(\w+)\s*(?:&=|%=)")


class _Checks(NamedTuple):
    bounds: list   # (offset, text): conditions, ternary tests, min/clamp calls, allocations and masks, in order
    asserts: list  # (offset, text)


def _checks(ctx: _File, function: Function) -> _Checks:
    """Every place in the function that could bound a value, found once."""
    code, start, end = ctx.code, function.body_start, function.end
    bounds = [(match.start(), _inner(ctx, match.end() - 1)) for match in _IF_WHILE.finditer(code, start, end)]
    bounds += [(match.start(), match.group(0)) for match in _TERNARY.finditer(code, start, end)]
    bounds += [(match.start(), _inner(ctx, match.end() - 1)) for match in _CLAMP.finditer(code, start, end)]
    bounds += [(match.start(), match.group(0)) for match in _SIZED_BY.finditer(code, start, end)]
    bounds += [(match.start(), match.group(1)) for match in _MASKED.finditer(code, start, end)]
    asserts = [(match.start(), _inner(ctx, match.end() - 1)) for match in _ASSERT.finditer(code, start, end)]
    return _Checks(sorted(bounds), asserts)


def _first_mention(places: list, name: str, low: int, high: int, cache: dict) -> bool:
    """Whether any of these places in [low, high) mentions `name`. The offsets that do are found once per name."""
    if name not in cache:
        cache[name] = [offset for offset, text in places if _mentions(name, text)]
    offsets = cache[name]
    index = bisect.bisect_left(offsets, low)
    return index < len(offsets) and offsets[index] < high


# ---------------------------------------------------------------- lengths and indexes from input

# Where a value comes off the wire: bytes shifted together, a byte-order conversion, a read_be16-style helper, or a header's length field.
_FROM_WIRE = re.compile(r"\w+\s*\[[^\]\n]{1,40}\]\s*<<\s*\d+|\b(?:ntoh[sl]|be(?:16|32|64)toh|le(?:16|32|64)toh|bswap_?(?:16|32|64)|__builtin_bswap(?:16|32|64)|_byteswap_\w+|OSSwap\w+)\s*\("
                        r"|\b(?:read|load|get|rd|parse|decode|fetch|peek)_?(?:u|be|le|uint|int)?_?(?:8|16|32|64)(?:_?(?:be|le))?\s*\(|\b(?:be|le)(?:16|32|64)(?:dec|_to_cpu)\s*\("
                        r"|\b(?:hdr|header|pkt|packet|msg|message|frame|req|request|rec|record|tlv|chunk)\s*(?:->|\.)\s*\w*(?:len|length|size|count|sz)\b", re.I)
_ASSIGN = re.compile(r"(?<![\w.>])([A-Za-z_]\w*)\s*=(?!=)\s*([^;]{1,300});")
_COPY = re.compile(r"(?<![\w.>])(?:std::)?(memcpy|memmove|memcpy_s|strncpy|strncat|bcopy|fread|recv|read)\s*\(")
_LENGTH_ARGUMENT = {"memcpy": 2, "memmove": 2, "memcpy_s": 3, "strncpy": 2, "strncat": 2, "bcopy": 2, "fread": 2, "recv": 2, "read": 2}


def _length_findings(ctx: _File, function: Function, checks: _Checks) -> Iterator[tuple]:
    code, source = ctx.code, ctx.source
    tainted: dict[str, list[int]] = {}
    for match in _ASSIGN.finditer(code, function.body_start, function.end):
        if _FROM_WIRE.search(match.group(2)):
            tainted.setdefault(match.group(1), []).append(match.end())
    bounded: dict[str, list] = {}
    asserted_at: dict[str, list] = {}
    for count, match in enumerate(_COPY.finditer(code, function.body_start, function.end)):
        if count >= MAX_SITES:
            return
        arguments = _arguments(_inner(ctx, match.end() - 1))
        position = _LENGTH_ARGUMENT[match.group(1)]
        if len(arguments) <= position:
            continue
        length = re.sub(r"\bsizeof\s*(?:\([^()]*\)|\w+)", "0", arguments[position])  # a size, whatever the operand holds
        # Each name counts from its last assignment from the wire before this copy.
        since = {name: ends[bisect.bisect_left(ends, match.start()) - 1] for name, ends in tainted.items()
                 if ends[0] <= match.start() and _mentions(name, length)}
        if not since and not _FROM_WIRE.search(length):
            continue
        watched = since or {length: function.body_start}
        low = {name: max(start, match.start() - MAX_WINDOW) for name, start in watched.items()}
        if any(_first_mention(checks.bounds, name, low[name], match.start(), bounded) for name in watched):
            continue
        shown = next(iter(since), length[:40])
        line = source.line_of(match.start())
        if any(_first_mention(checks.asserts, name, low[name], match.start(), asserted_at) for name in watched):
            yield ("assert-validation", line, f"The only bound on {shown} before {match.group(1)} is an assert, which release builds compile out with "
                   "NDEBUG, so a hostile length overflows the buffer there. Check it with an if and return an error.", {"severity": "high", "confidence": "medium"})
        else:
            yield ("unchecked-bound", line, f"{shown} comes from the input and reaches {match.group(1)} with nothing checking it against the destination "
                   "or the bytes left, so a hostile length overflows or over-reads. Check it first and return an error.", {})


_MESSAGE_PARAM = re.compile(r"(?:\b[\w:]{0,80}(?:Message|Msg|Request|Packet|Frame|Command|Event|Header)\w{0,40}\s*[&*]?\s*|[&*]\s*)(msg|message|req|request|packet|pkt|frame|cmd|command|ev|event|hdr|header|input|payload)\b"
                            r"|\b[\w:]{0,80}(?:Message|Msg|Request|Packet|Frame|Command)\w{0,40}\s*[&*]\s*(\w+)")
_SUBSCRIPT = re.compile(r"(?<!\w)(\w{1,80})\s*\[([^\[\]\n]{1,200})\]")
# Containers whose operator[] takes a key, not a position, so a key from a message can't land outside them.
_ASSOCIATIVE = re.compile(r"\b(?:std::)?(?:unordered_map|unordered_multimap|map|multimap|flat_map|flat_hash_map|node_hash_map|btree_map|dense_hash_map|hash_map|robin_map|"
                          r"QMap|QHash|QMultiMap|QMultiHash)\s*<[^;]{0,300}?>\s+(\w+)\s*[;={(]")
_TEXT_KEY = re.compile(r"(?:path|name|key|url|uri|host|email|token|method|label|title|text|str|string)$", re.I)


def _index_findings(ctx: _File, function: Function, checks: _Checks, keyed: set) -> Iterator[tuple]:
    names = {name for found in _MESSAGE_PARAM.finditer(function.params) for name in found.groups() if name}
    if not names:
        return
    code, source = ctx.code, ctx.source
    alternatives = "|".join(map(re.escape, names))
    validated = re.search(rf"\b(?:validate|check|verify|sanitize)\w*\s*\(\s*(?:{alternatives})\b", code[function.body_start:function.end])
    validated_at = function.body_start + validated.start() if validated else function.end
    places = [(offset, re.sub(r"\s+", "", text)) for offset, text in checks.bounds + checks.asserts]
    first: dict[str, int] = {}
    seen: set[int] = set()
    for count, match in enumerate(_SUBSCRIPT.finditer(code, function.body_start, function.end)):
        if count >= MAX_SITES * 10:
            return
        if match.group(1) in keyed or match.start() > validated_at:
            continue
        fields = [field for field in re.findall(rf"\b(?:{alternatives})\s*(?:\.|->)\s*\w+", match.group(2)) if not _TEXT_KEY.search(field)]
        unchecked = []
        for field in fields:
            compact = re.sub(r"\s+", "", field)
            if compact not in first:
                first[compact] = min((offset for offset, text in places if compact in text), default=function.end)
            if first[compact] > match.start():
                unchecked.append(compact)
        line = source.line_of(match.start())
        if unchecked and line not in seen:
            seen.add(line)
            yield ("unchecked-bound", line, f"{unchecked[0]} comes from the message and indexes memory with operator[], which doesn't check it, so a "
                   "hostile index reads or writes outside the container. Check it against size() first, or use .at().", {})


_PROXY = re.compile(r"(?<![\w:<>])(?:auto|[\w:<>]{1,120})\s*&?\s*(\w+)\s*=\s*\w+\s*\.\s*(?:mutable_)?unchecked\s*<[^<>;]{0,40}>\s*\(\s*\)")


def _proxy_findings(ctx: _File, function: Function) -> Iterator[tuple]:
    proxies = set(_PROXY.findall(ctx.code, function.body_start, function.end))
    if len(proxies) < 2:
        return
    alternatives = "|".join(map(re.escape, proxies))
    for count, match in enumerate(re.finditer(rf"(?<![\w.])({alternatives})\s*\(", ctx.code[function.body_start:function.end])):
        if count >= MAX_SITES * 10:
            return
        inner = _inner(ctx, function.body_start + match.end() - 1, 400)
        inner_proxy = re.search(rf"(?<![\w.])({alternatives})\s*\(", inner)
        if inner_proxy:
            yield ("unchecked-bound", ctx.source.line_of(function.body_start + match.start()), f"{match.group(1)}(...) is an unchecked view indexed "
                   f"by a value read straight from {inner_proxy.group(1)}, the caller's data, so an out-of-range index reads arbitrary memory. Check "
                   "each index against shape() first, or use at().", {})
            return


# ---------------------------------------------------------------- ownership

_CLASS = re.compile(r"\b(?:class|struct)\s+(?:[A-Z_]+\s+)?(\w+)\s*(?:final\s*)?(?::(?P<bases>[^{;]{0,400}))?\{")
_OUT_OF_LINE_DESTRUCTOR = re.compile(r"\b(\w+)\s*::\s*~(\w+)\s*\(\s*(?:void\s*)?\)\s*(?:noexcept\s*)?\{")
_RELEASE = re.compile(r"\bdelete\s*(?:\[\s*\])?\s*(?:this\s*->\s*)?(\w+)|\b(?:free|fclose|pclose|closedir|munmap|dlclose|CloseHandle|\w+_(?:free|destroy|release|finalize|close|unref|dispose|cleanup)\w*)\s*\(\s*(?:this\s*->\s*)?(\w+)")
_NONCOPYABLE = re.compile(r"\b(?:noncopyable|NonCopyable|Noncopyable|Uncopyable|NoCopy\w*|DISALLOW_COPY\w*|Q_DISABLE_COPY\w*|NON_COPYABLE\w*|NONCOPYABLE\w*)\b")
_SMART_NEW = r"(?:std::)?(?:shared_ptr|unique_ptr)\s*<[^;{{}}()]{{1,200}}?>\s*(?:\w+\s*)?[({{]\s*{0}\s*[)}}]"
_SMART_FROM = r"(?:std::)?(?:shared_ptr|unique_ptr)\s*<[^;{{}}()]{{1,200}}?>\s*(?:\w+\s*)?[({{]\s*{0}\s*[)}}]|\.reset\s*\(\s*{0}\s*\)"
_CLEARED = r"\b{0}\s*\.\s*{1}\s*=\s*(?:nullptr|NULL|0|-1|\{{\s*\}})|\bstd::exchange\s*\(\s*{0}\s*\.\s*{1}\b|\bswap\s*\(|\b{0}\s*\.\s*(?:release|reset)\s*\("


def _class_findings(ctx: _File) -> Iterator[tuple]:
    code, source = ctx.code, ctx.source
    outside: dict[str, int] = {}  # each out-of-line destructor's opening brace, found in one pass
    for found in _OUT_OF_LINE_DESTRUCTOR.finditer(code):
        if found.group(1) == found.group(2):
            outside.setdefault(found.group(1), found.end() - 1)
    budget = 4 * len(code)
    for match in _CLASS.finditer(code):
        name = match.group(1)
        closing = ctx.pairs.get(match.end() - 1, -1)
        if closing < 0 or budget <= 0:
            continue
        body = code[match.end():closing]
        budget -= len(body)
        if "~" not in body and name not in outside:
            continue  # nothing releases anything
        destructor = re.search(rf"~{name}\s*\(\s*(?:void\s*)?\)\s*(?:noexcept\s*(?:\([^)]*\))?\s*)?(?:override\s*)?\{{", body)
        if destructor:
            destructor_body = _inner(ctx, match.end() + destructor.end() - 1, MAX_BODY)
        else:
            destructor_body = _inner(ctx, outside[name], MAX_BODY) if name in outside else ""
        pointers = set(re.findall(r"[\w:>]\s*\*\s*(\w+)\s*(?:=[^;]*)?;", body))
        released = [member for found in _RELEASE.finditer(destructor_body) for member in found.groups() if member and member in pointers]
        if not released:
            continue
        line = source.line_of(match.end() + destructor.start()) if destructor else source.line_of(match.start())
        copy_constructor = re.search(rf"\b{name}\s*\(\s*(?:const\s+)?{name}\s*&(?!&)", body)
        copy_assignment = re.search(rf"\boperator\s*=\s*\(\s*(?:const\s+)?{name}\s*&(?!&)", body)
        moves = re.search(rf"\b{name}\s*\(\s*{name}\s*&&|\boperator\s*=\s*\(\s*{name}\s*&&", body)
        if not (copy_constructor and copy_assignment) and not moves and not _NONCOPYABLE.search((match.group("bases") or "") + body):
            yield ("raw-ownership", line, f"{name} releases {released[0]} in its destructor but keeps the compiler's copy "
                   f"{'assignment' if copy_constructor else 'constructor'}, so a copy releases the same {released[0]} twice. Delete or define "
                   "copying, or hold it in a std::vector or std::unique_ptr.", {})
            continue
        for found in re.finditer(rf"\b{name}\s*\(\s*{name}\s*&&\s*(\w+)\s*\)[^{{;]{{0,800}}\{{|\boperator\s*=\s*\(\s*{name}\s*&&\s*(\w+)\s*\)[^{{;]{{0,80}}\{{", body):
            other = found.group(1) or found.group(2)
            whole = found.group(0) + _inner(ctx, match.end() + found.end() - 1, MAX_BODY)
            for member in dict.fromkeys(released):
                takes = re.search(rf"\b{member}\s*(?:[({{]\s*{other}\s*\.\s*{member}\b|=\s*{other}\s*\.\s*{member}\b)", whole)
                if takes and not re.search(_CLEARED.format(re.escape(other), re.escape(member)), whole):
                    yield ("raw-ownership", source.line_of(match.end() + found.start()), f"This move takes {other}.{member} without clearing it, so the "
                           f"moved-from {name} releases {member} too when it's destroyed. Take it with std::exchange({other}.{member}, nullptr).", {})
                    break


_THIS_ADOPTED = re.compile(r"(?:std::)?(?:shared_ptr|unique_ptr)\s*<[^;{}()]{1,200}?>\s*(?:\w+\s*)?[({]\s*this\s*[)}]|\.reset\s*\(\s*this\s*\)")
_RAW_PARAM = re.compile(r"(?:^|,)\s*(?:const\s+)?([A-Za-z_][\w:]*(?:<[^<>]{0,80}>)?)\s*\*\s*(?:const\s+)?(\w+)\s*(?=,|$)")
_ACQUIRE = re.compile(r"(?:(?<![\w:])[\w:]{1,120}(?:<[^<>;]{0,80}>)?\s*\*\s*|\bauto\s*\*?\s*)(\w+)\s*=\s*(?:\([^()]{0,40}\)\s*)?(?:std::)?(fopen|popen|opendir|malloc|calloc|strdup|new)\b")


def _ownership_findings(ctx: _File, function: Function, is_cpp: bool) -> Iterator[tuple]:
    source = ctx.source
    body = ctx.code[function.body_start:function.end]
    at = function.body_start
    for match in _THIS_ADOPTED.finditer(body):
        yield ("raw-ownership", source.line_of(at + match.start()), "Wrapping this in a new smart pointer starts a second, independent owner "
               "beside whoever already owns the object, so each deletes it. Derive from std::enable_shared_from_this and call shared_from_this().", {})
    # OpenSSL-style `set0`, `take` and `own` names document the hand-off in a C API, which can't take a smart pointer.
    says_so = re.search(r"set0|take|_own|own_", function.name, re.I)
    for found in [] if says_so else _RAW_PARAM.finditer(function.params):
        kind, name = found.groups()
        if kind in ("char", "void", "wchar_t") or kind.endswith("char"):
            continue
        adopted = re.search(_SMART_NEW.format(re.escape(name)), body)
        if adopted:
            yield ("raw-ownership", source.line_of(at + adopted.start()), f"{function.name.split('::')[-1]} takes ownership of the raw {kind}* {name}, "
                   "and nothing in its signature says so, so a caller can delete it or wrap it again. Take std::unique_ptr by value, or a "
                   "shared_ptr.", {})
    for count, acquired in enumerate(_ACQUIRE.finditer(body)):
        if count >= MAX_SITES:
            return
        name, how = acquired.groups()
        after = body[acquired.end():acquired.end() + MAX_WINDOW]
        wrapped = re.search(_SMART_FROM.format(re.escape(name)), after)
        handed = re.search(rf"[\w>]\s*\(\s*(?:[^;()]*,\s*)?{re.escape(name)}\s*[,)]", after[:wrapped.start()]) if wrapped and how == "new" else None
        if handed and not re.search(rf"\bdelete\s+{re.escape(name)}\b", after[:wrapped.start()]):
            yield ("raw-ownership", source.line_of(at + acquired.end() + wrapped.start()), f"{name} was already passed on as a raw pointer before "
                   "this wraps it in a new owner, so if the callee kept it too, two owners delete it. Make it one smart pointer from the start, "
                   "with std::make_shared or std::make_unique, and pass that.", {})
            continue
        if not is_cpp or wrapped:
            continue
        released = re.search(rf"\bdelete\s*(?:\[\s*\])?\s*{re.escape(name)}\b|\b(?:fclose|pclose|closedir|free)\s*\(\s*{re.escape(name)}\s*\)|\btry\s*\{{", after)
        limit = released.start() if released else len(after)
        for throw in re.finditer(r"\bthrow\b", after[:limit]):
            near = after[max(0, throw.start() - 160):throw.start()]
            if re.search(rf"!\s*{re.escape(name)}\b|\b{re.escape(name)}\s*==\s*(?:nullptr|NULL|0)\b|(?:nullptr|NULL)\s*==\s*{re.escape(name)}\b", near.rsplit(";", 1)[-1]):
                continue  # the check that it was acquired
            yield ("raw-ownership", source.line_of(at + acquired.start()), f"{name} holds a resource in a raw pointer, and the throw on line "
                   f"{source.line_of(at + acquired.end() + throw.start())} leaves it leaked. Hold it in a std::unique_ptr (with fclose as the deleter "
                   "for a FILE*) or a std::vector.", {})
            break


_DELETES_EACH = re.compile(r"\bfor\s*\(\s*(?:const\s+)?(?:auto|([\w:]{1,120}))\s*\*?\s*&?\s*(\w+)\s*:\s*(\w+)\s*\)\s*\{?\s*delete\s+\2\b")


def _deleted_twice(ctx: _File, found: list[Function]) -> Iterator[tuple]:
    code = ctx.code
    owned: dict[str, str | None] = {}
    for function in found:
        if "~" in function.name:
            for loop in _DELETES_EACH.finditer(code, function.body_start, function.end):
                owned[loop.group(3)] = loop.group(1)
    for container, element in list(owned.items())[:20]:
        removes = re.compile(rf"\b{re.escape(container)}\s*\.\s*(?:erase|remove|clear|pop_\w+|extract)\b|\bstd::remove\w*\s*\(\s*{re.escape(container)}\b")
        for function in found:
            if "~" in function.name:
                continue
            body = code[function.body_start:function.end]
            if "delete" not in body or removes.search(body):
                continue
            for count, deleted in enumerate(re.finditer(r"\bdelete\s+(\w+)\s*;", body)):
                if count >= 50:
                    break
                name = deleted.group(1)
                declared = re.search(rf"\b([\w:]{{1,120}})\s*\*\s*{re.escape(name)}\b", function.params + " " + body[:MAX_WINDOW])
                if element and (not declared or declared.group(1) != element):
                    continue
                yield ("raw-ownership", ctx.source.line_of(function.body_start + deleted.start()), f"The destructor deletes every element of "
                       f"{container}, and {function.name.split('::')[-1]} deletes {name} without taking it out of {container}, so it's freed twice. "
                       "Hold the elements in std::unique_ptr, or remove one before deleting it.", {})
                return


# ---------------------------------------------------------------- undefined behaviour

_WIDE = r"(?:std::)?(?:u?int(?:16|32|64)_t|uint(?:16|32|64)|u(?:16|32|64)|(?:unsigned\s+)?(?:short|int|long(?:\s+long)?)|float|double)"
_CAST_READ = re.compile(rf"\*\s*\(\s*(?:const\s+)?(?:volatile\s+)?(?P<type>{_WIDE})\s*(?:const\s*)?\*\s*\)\s*\(?\s*(?P<amp>&\s*)?(?P<name>[A-Za-z_]\w*)"
                        rf"|\*\s*reinterpret_cast\s*<\s*(?:const\s+)?(?:volatile\s+)?(?P<type2>{_WIDE})\s*(?:const\s*)?\*\s*>\s*\(\s*(?P<amp2>&\s*)?(?P<name2>[A-Za-z_]\w*)"
                        rf"|\breinterpret_cast\s*<\s*(?:const\s+)?(?P<type3>{_WIDE})\s*(?:const\s*)?\*\s*>\s*\(\s*(?P<name3>[A-Za-z_]\w*)[^()]{{0,40}}\)\s*\[")
_BYTES = r"(?:const\s+)?(?:std::)?(?:u?int8_t|uint8|u8|(?:unsigned\s+|signed\s+)?char|std::byte|byte|BYTE|u_char)\s*(?:const\s*)?\*\s*(?:const\s+)?(?:__restrict\w*\s+)?{0}\b"
_FLOATING = re.compile(r"float|double")


def _enclosing(found: list[Function], starts: list[int], offset: int) -> Function | None:
    index = bisect.bisect_right(starts, offset) - 1
    inside = [function for function in found[max(0, index - 8):index + 1] if function.body_start <= offset < function.end]
    return min(inside, key=lambda function: function.end - function.body_start) if inside else None


def _cast_findings(ctx: _File, found: list[Function], starts: list[int]) -> Iterator[tuple]:
    code, source = ctx.code, ctx.source
    for count, match in enumerate(_CAST_READ.finditer(code)):
        if count >= MAX_SITES:
            return
        kind = match.group("type") or match.group("type2") or match.group("type3")
        name = match.group("name") or match.group("name2") or match.group("name3")
        address = match.group("amp") or match.group("amp2")
        function = _enclosing(found, starts, match.start())
        if function is None:
            continue
        before = function.params + ";" + code[max(function.body_start, match.start() - MAX_WINDOW):match.start()]  # its own declaration, not a namesake
        if address:
            declared = re.search(rf"\b(float|double|(?:std::)?u?int\d+_t|int|long|unsigned)\s+{re.escape(name)}\s*[=;,)]", before)
            if declared and bool(_FLOATING.match(declared.group(1))) != bool(_FLOATING.search(kind)):
                yield ("undefined-behavior", source.line_of(match.start()), f"This reads {name}, a {declared.group(1)}, through a {kind} pointer, which "
                       "breaks strict aliasing, so the optimizer may reorder or drop it. Use std::bit_cast or memcpy.", {})
        elif re.search(_BYTES.format(re.escape(name)), before):
            yield ("undefined-behavior", source.line_of(match.start()), f"This reads a {kind} through a cast of the byte pointer {name}, which is a "
                   "misaligned access at most offsets and breaks strict aliasing, both undefined. memcpy into a local, which compiles to the same load.", {})


_UNION = re.compile(r"\bunion\s+(\w+)?\s*\{([^{}]{0,800})\}\s*(\w+)?\s*;")
_MEMBER = re.compile(r"([\w:]+)\s+(\w+)\s*(?:\[[^\]]*\])?\s*;")


def _union_findings(ctx: _File, found: list[Function]) -> Iterator[tuple]:
    code = ctx.code
    for count, match in enumerate(_UNION.finditer(code)):
        if count >= 20:
            return
        members = {name: kind for kind, name in _MEMBER.findall(match.group(2))}
        if not (any(_FLOATING.search(kind) for kind in members.values()) and any(not _FLOATING.search(kind) for kind in members.values())):
            continue
        variables = set(re.findall(rf"\b{re.escape(match.group(1))}\s+(\w+)\s*[;={{]", code)[:20]) if match.group(1) else set()
        if match.group(3):
            variables.add(match.group(3))
        for function in found:
            body = code[function.body_start:function.end]
            for variable in variables:
                if variable not in body:
                    continue
                written = None
                for access in re.finditer(rf"\b{re.escape(variable)}\s*\.\s*(\w+)(\s*=(?!=))?", body):
                    member = access.group(1)
                    if member not in members:
                        continue
                    if access.group(2):
                        written = member
                    elif written and member != written:
                        yield ("undefined-behavior", ctx.source.line_of(function.body_start + access.start()), f"{variable}.{member} reads a different "
                               f"member of the union than the one last written ({variable}.{written}), which is undefined in C++. Use std::bit_cast "
                               "or memcpy.", {})
                        break


_UNREACHABLE_DEFAULT = re.compile(r"\bdefault\s*:\s*\{?\s*(?:__builtin_unreachable\s*\(\s*\)|std::unreachable\s*\(\s*\)|__assume\s*\(\s*(?:0|false)\s*\))")
_INTEGER = re.compile(r"^(?:const\s+)?(?:std::)?(?:u?int\d*_t|uint\d+|u\d+|i\d+|s\d+|int|unsigned(?:\s+\w+)?|signed(?:\s+\w+)?|char|short|long(?:\s+long)?|size_t|byte|BYTE|WORD|DWORD)$")


def _unreachable_findings(ctx: _File) -> Iterator[tuple]:
    code = ctx.code
    switches = [found.end() - 1 for found in re.finditer(r"\bswitch\s*\(", code)]
    for count, match in enumerate(_UNREACHABLE_DEFAULT.finditer(code)):
        if count >= MAX_SITES:
            return
        nearest = bisect.bisect_left(switches, match.start()) - 1
        if nearest < 0 or match.start() - switches[nearest] > MAX_WINDOW:
            continue
        opening = switches[nearest]
        subject = _inner(ctx, opening, 300).strip()
        from_data = "[" in subject or subject.startswith("*")
        if re.fullmatch(r"\w+", subject):
            before = code[max(0, opening - 5000):opening]
            declared = list(re.finditer(rf"([\w:]{{1,60}}(?:\s+[\w:]{{1,60}})?)\s+{re.escape(subject)}\s*(=|;|\{{|\))([^;]{{0,200}})", before))
            if declared:
                kind, _, value = declared[-1].groups()
                from_data = bool(_INTEGER.match(kind.strip())) or (kind.strip().endswith("auto") and "[" in value)
        if from_data:
            yield ("undefined-behavior", ctx.source.line_of(match.start()), f"default: tells the compiler no other value of {subject} occurs, but it's "
                   "an integer read from data, so a value no case lists is undefined behaviour rather than an error. Report the bad value in default.", {})


# ---------------------------------------------------------------- buffers that outlive their owner

_ASYNC_IO = re.compile(r"\basync_(?:write|send|write_some|send_to|write_at|read|read_some|receive|receive_from|read_at)\s*\(")
_LOCAL_STORAGE = r"(?:(?:std::)?(?:string|vector\s*<[^;>]{{0,200}}>|array\s*<[^;>]{{0,200}}>|basic_string\s*<[^;>]{{0,200}}>)\s+{0}\b|\b(?:char|uint8_t|unsigned\s+char|std::byte|u_char)\s+{0}\s*\[|\bauto\s+{0}\s*=\s*(?!std::make_shared|std::make_unique|std::shared_ptr|std::unique_ptr|new\b|&))"


def _lifetime_findings(ctx: _File, function: Function) -> Iterator[tuple]:
    code, source = ctx.code, ctx.source
    for count, match in enumerate(_ASYNC_IO.finditer(code, function.body_start, function.end)):
        if count >= MAX_SITES:
            break
        call = _inner(ctx, match.end() - 1, 3000)
        if re.search(r"\byield\b|use_awaitable|use_future|\bdeferred\b", call) or re.search(r"co_await\s*[\w:]*$", code[max(0, match.start() - 60):match.start()]):
            continue  # the coroutine waits for it, so the local lives until it's done
        named = re.search(r"\bbuffer\s*\(\s*(\w+)\s*[,)]", call)
        if not named:
            continue
        window = code[max(function.body_start, match.start() - MAX_WINDOW):match.start()]
        declared = re.search(_LOCAL_STORAGE.format(re.escape(named.group(1))), window)
        if declared and "static" not in window[max(0, declared.start() - 20):declared.start()]:
            yield ("buffer-lifetime", source.line_of(match.start()), f"buffer({named.group(1)}) points into a local that's destroyed when "
                   f"{function.name.split('::')[-1]} returns, while the operation still uses it. Keep the data in a member, or in a shared_ptr the "
                   "completion handler captures.", {})
    for count, match in enumerate(re.finditer(r"\bpy::array(?:_t\s*<[^;]{0,120}?>)?\s*[({]", code[function.body_start:function.end])):
        if count >= MAX_SITES:
            break
        arguments = _arguments(_inner(ctx, function.body_start + match.end() - 1, 2000))
        if len(arguments) >= 3 and re.fullmatch(r"py::none\s*\(\s*\)", arguments[-1]):
            yield ("buffer-lifetime", source.line_of(function.body_start + match.start()), "py::none() as the base makes NumPy borrow this pointer "
                   "with nothing keeping its memory alive, so the array reads freed memory once this function's data is gone. Pass a py::capsule "
                   "that owns it, or let pybind11 copy it.", {})


# ---------------------------------------------------------------- layout across a foreign-function boundary

_ARRAY_PARAM = re.compile(r"\bpy::array_t\s*<([^<>]{0,200})>\s*(?:const\s*)?&?\s*(\w+)|\bpy::array\s*(?:const\s*)?&?\s*(\w+)")
_INDEX_PART = r"(?:[^\[\]\n]|\[[^\[\]\n]{0,60}\])"
_FLAT_INDEX = re.compile(rf"\w\s*\[{_INDEX_PART}{{0,160}}\*{_INDEX_PART}{{0,160}}\]")  # one level of nesting, as p[i * shape[1] + j]


def _strides_findings(ctx: _File, function: Function) -> Iterator[tuple]:
    if "py::array" not in function.params:
        return
    body = ctx.code[function.body_start:function.end]
    if re.search(r"strides?\b|c_contiguous|f_contiguous|c_style|f_style|unchecked\s*<|mutable_unchecked", body) or not _FLAT_INDEX.search(body):
        return
    for match in _ARRAY_PARAM.finditer(function.params):
        flags, name = (match.group(1), match.group(2)) if match.group(2) else ("", match.group(3))
        if re.search(r"c_style|f_style", flags):
            continue
        if re.search(rf"\b{re.escape(name)}\s*\.\s*(?:request|data|mutable_data)\s*\(", body):
            yield ("ffi-layout", ctx.source.line_of(function.start), f"{function.name} reads {name}'s buffer as one contiguous C-order block, but "
                   "the parameter accepts any NumPy array, and a transposed, sliced or reversed one has other strides, so this reads the wrong elements "
                   "or past the buffer. Declare py::array_t<T, py::array::c_style | py::array::forcecast>, or index through unchecked<2>().", {})
            return


_RUST_STRUCT = re.compile(r"\b(?:struct|enum)\s+(\w+)")
_REPR_C = re.compile(r"#\[repr\([^)\n]{0,80}\b(?:C|transparent|u8|u16|u32|u64|i8|i16|i32|i64)\b")
# The code view blanks a string's contents, so `extern "C"` reads as `extern " "` there.
_EXTERN_BLOCK = re.compile(r"\bextern\s+\"[^\"\n]{0,12}\"\s*\{")
_EXPORTED = re.compile(r"\bextern\s+\"[^\"\n]{0,12}\"\s+fn\s+\w+\s*\(([^)]{0,800})\)")
_BEHIND_POINTER = re.compile(r"\*\s*(?:const|mut)\s+(?:[\w:]+::)?(\w+)")
_CALLBACK_TYPE = re.compile(r"\bfn\s*\(([^()]{0,400})\)")


class _Spans(NamedTuple):
    starts: list
    reach: list  # the furthest end of any span starting at or before each start, so containment is one bisection

    def contain(self, offset: int) -> bool:
        index = bisect.bisect_right(self.starts, offset) - 1
        return index >= 0 and self.reach[index] > offset


def _macro_spans(ctx: _File) -> _Spans:
    spans = sorted((macro.end(), ctx.pairs[macro.end() - 1]) for macro in re.finditer(r"\b\w+!\s*(?:\w+\s*)?\{", ctx.code) if macro.end() - 1 in ctx.pairs)
    reach, furthest = [], -1
    for _, end in spans:
        furthest = max(furthest, end)
        reach.append(furthest)
    return _Spans([start for start, _ in spans], reach)


def _rust_layout_findings(ctx: _File) -> Iterator[tuple]:
    """A struct C reads needs C's layout: one an imported function takes by value, or behind a pointer that C doesn't hand back. One that
    comes back to Rust, through a callback's parameters or an exported function's, is user data C never reads, so it doesn't count.
    wasm-bindgen's `extern "C"` blocks are JavaScript imports it converts itself, and a struct inside a macro such as libc's `s! {}` gets its
    repr from the macro."""
    code = ctx.code
    if not _EXTERN_BLOCK.search(code) and not _EXPORTED.search(code):
        return
    macros = _macro_spans(ctx)
    imports = []
    for block in _EXTERN_BLOCK.finditer(code):
        closing = ctx.pairs.get(block.end() - 1, -1)
        attributes = code[max(0, block.start() - 400):block.start()]
        if closing < 0 or macros.contain(block.start()) or re.search(r"#\[\s*(?:[\w:]{0,60}::)?wasm_bindgen\b[^\]]{0,300}\]\s*(?:#\[[^\]]*\]\s*)*(?:pub\s+)?$", attributes):
            continue
        imports.append(code[block.end():closing])
    exports = [found.group(1) for found in _EXPORTED.finditer(code)]
    imported = " ".join(imports)
    handed_back = {name for text in exports + [callback for callback in _CALLBACK_TYPE.findall(imported)] for name in _BEHIND_POINTER.findall(text)}
    behind_pointer = set(_BEHIND_POINTER.findall(imported)) - handed_back
    by_value = set(re.findall(r"\b([A-Z]\w*)\b", _BEHIND_POINTER.sub(" ", " ".join([imported, *exports]))))
    used = by_value | behind_pointer
    if not used:
        return
    for count, match in enumerate(_RUST_STRUCT.finditer(code)):
        if count >= MAX_SITES * 10:
            return
        name = match.group(1)
        if name not in used:
            continue
        window = code[max(0, match.start() - 600):match.start()]
        attributes = window[max(window.rfind(";"), window.rfind("}")) + 1:]  # what's between the previous item and this one
        if _REPR_C.search(attributes) or macros.contain(match.start()):
            continue
        if re.match(r"\s*(?:<[^>{;]*>)?\s*(?:;|\{\s*\}|\(\s*\)|\{\s*_\w*\s*:\s*\[\s*u8\s*;\s*0\s*\]\s*,?\s*\})", code[match.end():match.end() + 200]):
            continue  # an opaque type, only ever behind a pointer
        yield ("ffi-layout", ctx.source.line_of(match.start(1)), f"{name} crosses into C through an extern \"C\" signature but has no #[repr(C)], "
               "so Rust is free to reorder and pad its fields unlike the C struct. Add #[repr(C)] and match each field's C type.", {})


# ---------------------------------------------------------------- Rust files written in place

_RUST_WRITE = re.compile(r"\b(?:fs::write|File::create)\s*\(\s*&?\s*([\w.]+)")
# tempfile's NamedTempFile::persist renames too, but `persist` alone is a common method name.
_RUST_REPLACED = re.compile(r"\brename\s*\(|\bNamedTempFile\b|\btempfile\b|\batomicwrites?\b|\batomic_write\b")
_RUST_FN = re.compile(r"\bfn\s+\w+")


def _rust_nonatomic(source: Source, code: str) -> Iterator[tuple]:
    if _RUST_REPLACED.search(code):
        return
    starts = [found.start() for found in _RUST_FN.finditer(code)]
    reads: dict[tuple, bool] = {}
    for count, match in enumerate(_RUST_WRITE.finditer(code)):
        if count >= MAX_SITES:
            return
        target = match.group(1)
        region = (0, len(code))
        if "." not in target:  # a local: another function's `path` is another file
            index = bisect.bisect_right(starts, match.start())
            region = (starts[index - 1] if index else 0, starts[index] if index < len(starts) else len(code))
        key = (target, region)
        if key not in reads:
            pattern = re.compile(rf"\b(?:fs::read(?:_to_string)?|File::open)\s*\(\s*&?\s*{re.escape(target)}\s*\)")
            reads[key] = bool(pattern.search(code, region[0], region[1]))
        if reads[key]:
            yield ("nonatomic-state-write", source.line_of(match.start()), "This file is written in place and read back here, so a crash mid-write "
                   "leaves it truncated and the next load fails. Write a temporary file in the same folder, sync it, and fs::rename it over the "
                   "original.", {"confidence": "medium"})


def findings(source: Source, is_test: bool, is_script: bool) -> Iterable[tuple]:
    """Yield (rule, line, message, overrides) for one C, C++ or Rust file."""
    if is_test:
        return
    code = source.code
    if source.language == "rust":
        tests = re.search(r"#\[cfg\(test\)\]\s*(?:pub(?:\([^)\n]*\))?\s+)?mod\s+\w+\s*\{", code)
        code = code[:tests.start()] if tests else code
        if _EXTERN_BLOCK.search(code) or _EXPORTED.search(code):
            yield from _rust_layout_findings(_File(source, code, brackets.pairs(code)))
        yield from _rust_nonatomic(source, code)
        return
    ctx = _File(source, code, brackets.pairs(code))
    is_cpp = source.language == "cpp" or bool(re.search(r"\b(?:class|namespace|template|std::)\b", code))
    found = functions(code, ctx.pairs)
    keyed = set(_ASSOCIATIVE.findall(code))
    for function in found:
        checks = _checks(ctx, function)
        yield from _length_findings(ctx, function, checks)
        yield from _index_findings(ctx, function, checks, keyed)
        yield from _ownership_findings(ctx, function, is_cpp)
        if is_cpp:
            yield from _proxy_findings(ctx, function)
            yield from _lifetime_findings(ctx, function)
            yield from _strides_findings(ctx, function)
    yield from _cast_findings(ctx, found, [function.body_start for function in found])
    yield from _unreachable_findings(ctx)
    if is_cpp:
        yield from _class_findings(ctx)
        yield from _deleted_twice(ctx, found)
        yield from _union_findings(ctx, found)
