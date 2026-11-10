"""Shared state and durability in JavaScript and TypeScript: updates lost between a read and a write, a row checked for and then inserted,
mutations retried with no idempotency key, files rewritten in place, and work acknowledged before it's stored."""

from __future__ import annotations

import bisect
import itertools
import re
from collections.abc import Iterator

from . import js_syntax as js
from .source import Source

MAX_FUNCTION = 20_000  # a longer body isn't read, so nested bodies can't make these quadratic
_LOCKS = re.compile(r"transaction|\block\b|\.lock\s*\(|Lock\b|FOR UPDATE|forUpdate|\$inc\b|\bincrement\s*\(|\bdecrement\s*\(|__v\b|version|optimistic|mutex|"
                    r"withLock|redlock|semaphore|\bwatch\s*\(|\bmulti\s*\(|\beval\s*\(|\bincr(?:by)?\s*\(|\bhincrby\s*\(|runExclusive|acquire", re.I)


def _bodies(bodies: list[js.Function], code: str) -> Iterator[js.Function]:
    return js.within_budget(bodies, len(code), MAX_FUNCTION)


# ---------------------------------------------------------------- lost updates

_LOADED = re.compile(r"\b(?:const|let|var)\s+([\w$]+)\s*(?::[^=;\n]{1,100})?=\s*await\s+[\w$.]+\s*\.\s*(?:findById|findOne|findUnique|findFirst|findByPk|findOneBy|"
                     r"findOneByOrFail|findOneOrFail|findUniqueOrThrow|findFirstOrThrow)\s*\(")
_KV_READ = re.compile(r"\bawait\s+((?:this\s*\.\s*)?[\w$]+)\s*\.\s*(?:get|hget|hgetall)\s*\(\s*([^()\n]{1,80}?)\s*\)")
_ARITHMETIC = re.compile(r"(?:\+=|-=|\+\+|--)|=\s*[^;\n=]{0,80}[-+]\s*\d")
_CHECK = re.compile(r"\bif\s*\(\s*!?\s*([\w$]+)\s*\.\s*([\w$]+)\s*(?:<=?|>=?|[!=]==?)")


def lost_updates(source: Source, bodies: list[js.Function]) -> Iterator[tuple]:
    """A value read, changed in JavaScript and written back, with no lock, version or atomic increment: a record loaded and saved, a JSON
    document got from a key-value store and set again, or an in-memory field checked before an await and changed after it. Two requests at
    once both read the old value, and one update is lost."""
    code = source.code
    locks = [match.start() for match in _LOCKS.finditer(code)]
    for function in _bodies(bodies, code):
        if js.holds_any(locks, function.start, function.end):
            continue
        body = code[function.start:function.end]
        found = _saved_record(body) or _kv_round_trip(body) or (_checked_across_await(body) if "await" in body else None)
        if found:
            offset, message = found
            yield "lost-update", source.line_of(function.start + offset), message, {}


def _saved_record(body: str) -> tuple[int, str] | None:
    for loaded in itertools.islice(_LOADED.finditer(body), 50):
        name = re.escape(loaded.group(1))
        change = re.search(rf"(?<![\w$.]){name}\s*\.\s*([\w$]+)\s*(?:\+=|-=|\+\+|--)|(?<![\w$.]){name}\s*\.\s*([\w$]+)\s*=\s*[^;\n=]{{0,60}}\b{name}\s*\.\s*\2\s*[-+]",
                           body[loaded.end():])
        if change and re.search(rf"(?<![\w$.]){name}\s*\.\s*save\s*\(|\.\s*save\s*\(\s*{name}\b", body[loaded.end() + change.end():]):
            field = change.group(1) or change.group(2)
            return loaded.end() + change.start(), (f"{loaded.group(1)}.{field} is read, changed here and saved back with no lock or version check, so "
                                                    "two requests at once both read the old value and one update is lost. Update it atomically, such as "
                                                    "$inc or { increment: 1 }, or lock the row in a transaction.")
    return None


def _kv_round_trip(body: str) -> tuple[int, str] | None:
    for read in itertools.islice(_KV_READ.finditer(body), 50):
        store, key = re.escape(read.group(1)), re.escape(read.group(2).strip())
        written = re.search(rf"{store}\s*\.\s*(?:set|hset|setex)\s*\(\s*{key}\s*,", body[read.end():])
        if written and _ARITHMETIC.search(body, read.end(), read.end() + written.start()):
            return read.start(), ("This reads a value from the store, changes it here and writes it back, so concurrent calls overwrite each other's "
                                  "changes. Use an atomic command such as INCRBY or HINCRBY, or WATCH/MULTI or a Lua script.")
    return None


def _checked_across_await(body: str) -> tuple[int, str] | None:
    for check in itertools.islice(_CHECK.finditer(body), 50):
        name, field = re.escape(check.group(1)), re.escape(check.group(2))
        change = re.search(rf"(?<![\w$.]){name}\s*\.\s*{field}\s*(?:\+=|-=|\+\+|--)|(?<![\w$.]){name}\s*\.\s*{field}\s*=\s*[^;\n=]{{0,60}}\b{name}\s*\.\s*{field}\s*[-+]",
                           body[check.end():])
        if change and re.search(r"\bawait\b", body[check.end():check.end() + change.start()]):
            return check.end() + change.start(), (f"{check.group(1)}.{check.group(2)} is checked, then an await lets other requests run, then it's "
                                                  "changed, so two requests can both pass the check. Change it before the await, or hold a lock across both.")
    return None


# ---------------------------------------------------------------- check, then insert

_LOOKED_UP = re.compile(r"\b(?:const|let|var)\s+([\w$]+)\s*(?::[^=;\n]{1,100})?=\s*await\s+([\w$.]+?)\s*\.\s*(?:findFirst|findOne|findUnique|exists|count|findOneBy|countDocuments)\s*\(")
_UNIQUE_HANDLED = re.compile(r"P2002|23505|ER_DUP_ENTRY|E11000|\b11000\b|UniqueConstraint|unique_violation|duplicate|upsert|onConflict|ignoreDuplicates|skipDuplicates|"
                             r"@@unique|@unique|unique\s*:\s*true|\.unique\s*\(|\$setOnInsert|findOrCreate|findOneAndUpdate", re.I)


def check_then_insert(source: Source, bodies: list[js.Function]) -> Iterator[tuple]:
    """Looking a row up, returning if it's there, then creating it: two requests at once both find nothing and both create it. Only a unique
    constraint, with its conflict handled, stops that."""
    if _UNIQUE_HANDLED.search(source.text):
        return
    code = source.code
    for function in _bodies(bodies, code):
        body = code[function.start:function.end]
        for looked in itertools.islice(_LOOKED_UP.finditer(body), 50):
            name, model = re.escape(looked.group(1)), re.escape(looked.group(2))
            test = re.search(rf"\bif\s*\(\s*!?\s*{name}\b", body[looked.end():])
            created = re.search(rf"(?<![\w$.]){model}\s*\.\s*(?:create|insert|insertOne)\s*\(", body[looked.end():]) if test else None
            if created and created.start() > test.start():
                yield ("check-then-insert", source.line_of(function.start + looked.end() + created.start()), "This checks that the row is missing and "
                       "then creates it, so two requests at once can both create it. Back it with a unique constraint and handle the conflict, or use an "
                       "upsert.", {})
                break


# ---------------------------------------------------------------- retried mutations

_IDEMPOTENT = re.compile(r"idempot|Idempotency-Key|dedup|existing|already|reconcil|requestId|request_id", re.I)
_MUTATION = re.compile(r"""method\s*:\s*['"](?:POST|PATCH)['"]|\.\s*(?:post|patch)\s*(?:<[^()<>]{0,100}>\s*)?\(|\.\s*create\s*\(|"""
                       r"""\b(?:charge|transfer|payout|refund|sendMail|sendEmail|sendSms|publish)\w*\s*\(""", re.I)
_RETRY_LOOP = re.compile(r"\b(?:for|while)\s*\(([^()]{0,200})\)\s*\{")
_RETRY_WORDS = re.compile(r"attempt|retr|tries|\btry\b", re.I)
_RETRY_CALL = re.compile(r"(?<![\w$.])(?:pRetry|retry|asyncRetry|backOff|withRetry|retryAsync|promiseRetry)\s*\(")
_AXIOS_RETRY = re.compile(r"\baxiosRetry\s*\(\s*([\w$.]+)\s*,\s*\{")
_SAFE_CONDITION = re.compile(r"isIdempotentRequestError|isNetworkOrIdempotentRequestError|isSafeRequestError|\bmethod\b")


def retried_mutations(source: Source, brackets: dict[int, int]) -> Iterator[tuple]:
    """A POST or a payment retried after an error that may have come after it took effect, with no idempotency key and no check of what
    happened, so it can happen twice: a hand-written retry loop, a retry helper, or axios-retry told to retry any method."""
    code, text = source.code, source.text
    if _IDEMPOTENT.search(text):
        return
    posts: dict[str, bool] = {}
    for match in _AXIOS_RETRY.finditer(code):
        close = brackets.get(match.end() - 1, -1)
        options = code[match.end():min(close, match.end() + 2000)] if close > 0 else ""
        client = match.group(1)
        if client not in posts:  # once per client, however many times it's configured
            posts[client] = bool(re.search(rf"\b{re.escape(client)}\s*\.\s*(?:post|patch)\s*(?:<[^()<>]{{0,100}}>\s*)?\(", code))
        if "retryCondition" in options and not _SAFE_CONDITION.search(options) and posts[client]:
            yield ("retry-not-idempotent", source.line_of(match.start()), "This retry condition retries any method, so a POST whose response was lost "
                   "is sent again and its effect happens twice. Keep axios-retry's default, which retries only idempotent methods, or send an "
                   "Idempotency-Key.", {})
    loops = [match for match in _RETRY_LOOP.finditer(code) if _RETRY_WORDS.search(match.group(1))]
    helpers = list(_RETRY_CALL.finditer(code))
    if not loops and not helpers:
        return
    # Each kind of offset is found once, so nested loops are judged by lookups, not by reading each loop again.
    catches = [match.start() for match in re.finditer(r"\bcatch\b", code)]
    mutations = [match.start() for match in _MUTATION.finditer(text)]
    for match in loops:
        close = brackets.get(match.end() - 1, -1)
        if close > 0 and js.holds_any(catches, match.end(), close) and js.holds_any(mutations, match.end(), close):
            yield ("retry-not-idempotent", source.line_of(match.start()), "This loop retries a request that changes something, with no idempotency key "
                   "and no check of whether the last try took effect, so a timeout after it succeeded repeats it. Send an idempotency key, or look the "
                   "result up before trying again.", {})
    for match in helpers:
        close = brackets.get(match.end() - 1, -1)
        if close > 0 and js.holds_any(mutations, match.end(), close):
            yield ("retry-not-idempotent", source.line_of(match.start()), "This retries a request that changes something, with no idempotency key, so "
                   "an attempt that succeeded but timed out is repeated. Send an idempotency key the far side deduplicates on.", {})


# ---------------------------------------------------------------- files rewritten in place

_WRITES_FILE = re.compile(r"(?<![\w$])(?:fs\s*\.\s*|fsp\s*\.\s*|promises\s*\.\s*|fs\s*\.\s*promises\s*\.\s*)?(?:writeFile|writeFileSync)\s*\(")
_READS_FILE = re.compile(r"(?<![\w$])(?:fs\s*\.\s*|fsp\s*\.\s*|promises\s*\.\s*|fs\s*\.\s*promises\s*\.\s*)?(?:readFile|readFileSync|createReadStream)\s*\(")
_REPLACES = re.compile(r"\brename(?:Sync)?\s*\(|write-file-atomic|writeFileAtomic|atomically|steno")


def nonatomic_writes(source: Source, brackets: dict[int, int]) -> Iterator[tuple]:
    """A file this module rewrites in place with writeFile and also reads back: a crash or a reader in the middle sees it half written."""
    code, text = source.code, source.text
    if _REPLACES.search(text):
        return
    module_level = {match.group(1) for match in re.finditer(r"^(?:export\s+)?(?:const|let|var)\s+([\w$]+)", code, re.M)}

    def key(match: re.Match) -> str | None:
        spans = js.argument_spans(code, match.end() - 1, brackets, 1)
        argument = re.sub(r"\s+", "", text[spans[0][0]:spans[0][1]]) if spans else ""
        stable = re.fullmatch(r"[A-Z][A-Z0-9_]+|this\.[\w$.]+", argument) or argument in module_level or (argument and not re.fullmatch(r"[\w$]+", argument))
        return argument if stable and not argument.startswith(("'/dev/", '"/dev/', "'/proc/", '"/proc/')) else None

    reads = {key(match) for match in _READS_FILE.finditer(code)} - {None}
    for match in _WRITES_FILE.finditer(code):
        if key(match) in reads:
            yield ("nonatomic-state-write", source.line_of(match.start()), "This file is rewritten in place and this module reads it back, so a crash "
                   "or a reader in the middle sees it half written. Write a temporary file beside it and rename it over the original.", {"confidence": "medium"})
            return


# ---------------------------------------------------------------- acknowledged too early

_UNACKNOWLEDGED = re.compile(r"\bwriteConcern\s*:\s*\{[^{}]{0,100}\bw\s*:\s*0\b|\backs\s*:\s*0\b")
_WRITE_CALL = re.compile(r"\.\s*write\s*\(")
_SUCCESS = re.compile(r"\b(?:res|reply|response)\s*\.\s*(?:status|code)\s*\(\s*20\d\s*\)|\b(?:res|reply)\s*\.\s*sendStatus\s*\(\s*20\d|\b(?:res|reply)\s*\.\s*(?:json|send)\s*\(")
_RESPONSE_OBJECT = re.compile(r"^(?:res|reply|response|ctx|socket|ws|process\.std\w+|console)\b")
_DURABLE = re.compile(r"fsync|fdatasync|\bfinish\b|\bdrain\b|\bclose\b|callback|\bcb\b|\bonce\s*\(")


def early_success(source: Source, brackets: dict[int, int], handlers: list[tuple[int, int]]) -> Iterator[tuple]:
    """A handler that writes to a file stream and replies success at once, before the write's callback or an fsync, or a client set not to wait
    for the server's acknowledgement, so a crash loses what the caller was told is stored."""
    code = source.code
    for match in _UNACKNOWLEDGED.finditer(code):
        yield ("ack-before-durable", source.line_of(match.start()), "This turns off the server's acknowledgement of writes, so a write that never "
               "landed still counts as done. Keep acknowledgement on, and reply only after it.", {})
    if "createWriteStream" not in code:
        return
    successes = [match.start() for match in _SUCCESS.finditer(code)]
    durables = [match.start() for match in _DURABLE.finditer(code)]
    writes = [match for match in _WRITE_CALL.finditer(code)]
    write_starts = [match.start() for match in writes]
    for start, end in handlers:
        for write in writes[bisect.bisect_left(write_starts, start):bisect.bisect_left(write_starts, end)]:
            receiver = _receiver(code, write.start())
            if not receiver or _RESPONSE_OBJECT.match(receiver) or re.search(r"\bawait\s*$", code[max(0, write.start() - len(receiver) - 20):write.start() - len(receiver)]):
                continue
            index = bisect.bisect_left(successes, write.end())
            success = successes[index] if index < len(successes) and successes[index] < end else -1
            if success > 0 and len(js.argument_spans(code, write.end() - 1, brackets, 2)) == 1 and not js.holds_any(durables, write.end(), success):
                yield ("ack-before-durable", source.line_of(write.start()), "This replies success right after handing the record to a write stream, "
                       "before the write completes or is synced, so a crash loses records the caller was told are stored. Reply in the write's "
                       "callback, after an fsync if the contract says durable.", {})
                break


def _receiver(code: str, dot: int) -> str:
    """What `.write(` is called on, walked back from its dot: `stream`, `this.out` or `streamForToday()`, at most 200 characters."""
    index, low = dot - 1, max(0, dot - 200)
    while index >= low and code[index] in " \t":
        index -= 1
    if index >= low and code[index] == ")" and code[index - 1:index + 1] == "()":
        index -= 2
    while index >= low and (code[index].isalnum() or code[index] in "_$."):
        index -= 1
    return code[index + 1:dot].strip()


_ACKS = re.compile(r"DeleteMessage(?:Batch)?Command|\bdeleteMessage\w*\s*\(|\.\s*ack\s*\(|\bcommitOffsets\s*\(")
_ACK_NAME = re.compile(r"(?:\.\s*)?\b(?:ack|acknowledge|delete\w*Message\w*|remove\w*Message|commitOffsets)\s*\(")
_MESSAGE_LOOP = re.compile(r"\bfor\s*\(\s*(?:const|let|var)\s+[\w$]+\s+of\s+[^()]{1,100}\)\s*\{")
_AWAITED_CALL = re.compile(r"\bawait\s+([\w$.]+)\s*\(|\bawait\s+[\w$.]+\s*\.\s*send\s*\(\s*new\s+(\w+)")
_CONSUMER_RUN = re.compile(r"\.\s*run\s*\(\s*\{")
_EACH_MESSAGE = re.compile(r"\beachMessage\s*:\s*")


def early_acks(source: Source, brackets: dict[int, int], bodies: list[js.Function]) -> Iterator[tuple]:
    """A message acknowledged, deleted or its offset committed before the work it carries is stored, so a crash or an error in between loses it:
    an ack first in the loop over received messages, a kafkajs eachMessage that only buffers while offsets auto-commit, or amqplib's noAck."""
    code = source.code
    acks = [match.start() for match in _ACKS.finditer(code)]
    ack_helpers = {function.name for function in bodies if function.name and js.holds_any(acks, function.start, function.end)}
    awaited = list(_AWAITED_CALL.finditer(code))
    awaited_starts = [call.start() for call in awaited]
    for match in _MESSAGE_LOOP.finditer(code):
        close = brackets.get(match.end() - 1, -1)
        index = bisect.bisect_left(awaited_starts, match.end())
        calls = [call for call in awaited[index:index + 2] if close > 0 and call.start() < close]
        if len(calls) < 2:
            continue
        first = calls[0]
        name = (first.group(1) or "").rsplit(".", 1)[-1]
        if name in ack_helpers or _ACK_NAME.match(name + "(") or (first.group(2) or "").startswith("DeleteMessage"):
            yield ("ack-before-effect", source.line_of(first.start()), "The message is acknowledged before it's handled, so a crash or an error in "
                   "the handler loses it for good. Acknowledge after the work is stored, and make the handler safe to run twice.", {})
    starts = [function.start for function in bodies]
    for match in _CONSUMER_RUN.finditer(code):
        close = brackets.get(match.end() - 1, -1)
        options = code[match.end():close] if close > 0 else ""
        each = _EACH_MESSAGE.search(options)
        if not each or re.search(r"\bautoCommit\s*:\s*false\b", options):
            continue
        offset = match.end() + each.end()
        index = bisect.bisect_left(starts, offset)
        handler = bodies[index] if index < len(bodies) and bodies[index].start < close else None
        if handler and "await" not in code[handler.start:handler.end] and re.search(r"\.\s*push\s*\(", code[handler.start:handler.end]):
            yield ("ack-before-effect", source.line_of(offset), "eachMessage only buffers the message, and kafkajs commits its offset as soon as "
                   "eachMessage returns, so a crash before the buffer is written skips those messages. Commit after the flush, with autoCommit off.", {})
    for match in re.finditer(r"\bnoAck\s*:\s*true\b", code):
        yield ("ack-before-effect", source.line_of(match.start()), "With noAck the broker drops each message as soon as it's delivered, so a crash "
               "while handling it loses it. Acknowledge after the work is done.", {})


def findings(source: Source, brackets: dict[int, int], bodies: list[js.Function], handlers: list[tuple[int, int]]) -> list[tuple]:
    return [*lost_updates(source, bodies), *check_then_insert(source, bodies), *retried_mutations(source, brackets), *nonatomic_writes(source, brackets),
            *early_success(source, brackets, handlers), *early_acks(source, brackets, bodies)]
