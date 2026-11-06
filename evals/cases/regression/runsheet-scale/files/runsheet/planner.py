"""Work out the sequence steps run in."""

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
    path = []
    name = blocked[0].name
    while name is not None and name not in path:
        path.append(name)
        name = next((w for w in _waits(first[name], known) if w not in done), None)
    cycle = path[path.index(name):] + [name] if name is not None else []
    return CycleError([step.name for step in blocked], cycle)


def order(steps):
    steps = list(steps)
    known = _check_needs(steps)
    pending = _scan_order(steps)
    done = set()
    result = []
    while pending:
        remaining = []
        for step in pending:
            if all(name in done for name in _waits(step, known)):
                result.append(step.name)
                done.add(step.name)
            else:
                remaining.append(step)
        if len(remaining) == len(pending):
            raise _stuck(remaining, done, known)
        pending = remaining
    return result


def waves(steps, limit=None):
    steps = list(steps)
    known = _check_needs(steps)
    pending = _scan_order(steps)
    done = set()
    result = []
    while pending:
        wave, remaining = [], []
        for step in pending:
            has_room = limit is None or len(wave) < limit
            if has_room and all(name in done for name in _waits(step, known)):
                wave.append(step)
            else:
                remaining.append(step)
        if not wave:
            raise _stuck(remaining, done, known)
        result.append([step.name for step in wave])
        done.update(step.name for step in wave)
        pending = remaining
    return result


def subset(steps, targets):
    steps = list(steps)
    wanted = set()
    stack = list(targets)
    while stack:
        name = stack.pop()
        if name in wanted:
            continue
        matching = [step for step in steps if step.name == name]
        if not matching:
            raise UnknownStepError(name)
        wanted.add(name)
        for step in matching:
            stack.extend(step.needs)
    return order(step for step in steps if step.name in wanted)
