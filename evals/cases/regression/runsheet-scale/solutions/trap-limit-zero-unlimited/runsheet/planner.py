"""Work out the sequence steps run in."""

from collections import defaultdict
from heapq import heapify, heappop, heappush

from .model import CycleError, UnknownStepError


def _check_needs(steps):
    known = {step.name for step in steps}
    for step in steps:
        for name in step.needs:
            if name not in known:
                raise UnknownStepError(name, needed_by=step.name)
    return known


def _waits(step, known):
    return step.needs + tuple(name for name in step.after if name in known)


def _scan_order(steps):
    return sorted(steps, key=lambda step: -step.priority)


def _stuck(blocked, done, known):
    first = {}
    for step in blocked:
        first.setdefault(step.name, step)
    path = {}
    name = blocked[0].name
    while name is not None and name not in path:
        path[name] = len(path)
        name = next((w for w in _waits(first[name], known) if w not in done), None)
    if name is None:
        cycle = []
    else:
        names = list(path)
        cycle = names[path[name]:] + [name]
    return CycleError([step.name for step in blocked], cycle)


class _Board:
    """Tracks which ranked steps are still waiting, by position in scan order."""

    def __init__(self, steps):
        steps = list(steps)
        self.known = _check_needs(steps)
        self.ranked = _scan_order(steps)
        self.done = set()
        self.ran = [False] * len(self.ranked)
        self.left = len(self.ranked)
        self.outstanding = [0] * len(self.ranked)
        self.waiters = defaultdict(list)
        self.ready = []
        for index, step in enumerate(self.ranked):
            waits = set(_waits(step, self.known))
            self.outstanding[index] = len(waits)
            for name in waits:
                self.waiters[name].append(index)
            if not waits:
                self.ready.append(index)

    def run(self, index):
        self.ran[index] = True
        self.left -= 1

    def finish(self, name):
        """Mark a name done and return the positions this released."""
        if name in self.done:
            return []
        self.done.add(name)
        released = []
        for index in self.waiters.pop(name, ()):
            self.outstanding[index] -= 1
            if self.outstanding[index] == 0:
                released.append(index)
        return released

    def stuck(self):
        blocked = [step for index, step in enumerate(self.ranked) if not self.ran[index]]
        return _stuck(blocked, self.done, self.known)


def order(steps):
    board = _Board(steps)
    this_scan = board.ready
    next_scan = []
    result = []
    while this_scan:
        index = heappop(this_scan)
        board.run(index)
        name = board.ranked[index].name
        result.append(name)
        for released in board.finish(name):
            if released > index:
                heappush(this_scan, released)
            else:
                next_scan.append(released)
        if not this_scan:
            this_scan, next_scan = next_scan, []
            heapify(this_scan)
    if board.left:
        raise board.stuck()
    return result


def waves(steps, limit=None):
    board = _Board(steps)
    ready = board.ready
    result = []
    while board.left:
        wave = []
        while ready and (not limit or len(wave) < limit):
            wave.append(heappop(ready))
        if not wave:
            raise board.stuck()
        names = [board.ranked[index].name for index in wave]
        result.append(names)
        for index in wave:
            board.run(index)
        for name in names:
            for released in board.finish(name):
                heappush(ready, released)
    return result


def subset(steps, targets):
    steps = list(steps)
    by_name = defaultdict(list)
    for step in steps:
        by_name[step.name].append(step)
    wanted = set()
    stack = list(targets)
    while stack:
        name = stack.pop()
        if name in wanted:
            continue
        if name not in by_name:
            raise UnknownStepError(name)
        wanted.add(name)
        for step in by_name[name]:
            stack.extend(step.needs)
    return order(step for step in steps if step.name in wanted)
