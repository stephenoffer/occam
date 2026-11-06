"""Run a batch of API scenarios against a runsheet implementation and report plain JSON.

Imported by conftest.py to get the expected answers from the frozen original, and run as a
script in a subprocess, with the workspace on PYTHONPATH, to get the workspace's answers.
"""

import json
import sys

ERROR_ATTRIBUTES = {
    "ParseError": ("line",),
    "UnknownStepError": ("missing", "needed_by"),
    "CycleError": ("blocked", "cycle"),
}


def record(step):
    return [step.name, list(step.needs), list(step.after), step.priority]


def build_steps(api, case):
    if "text" in case:
        return api.parse(case["text"])
    return [api.Step(s["name"], needs=tuple(s.get("needs", ())), after=tuple(s.get("after", ())),
                     priority=s.get("priority", 0)) for s in case["steps"]]


def perform(api, case):
    steps = build_steps(api, case)
    op = case["op"]
    if op == "parse":
        return [record(step) for step in steps]
    if op == "order":
        return api.order(steps)
    if op == "order_iter":
        return api.order(iter(steps))
    if op == "waves":
        return api.waves(steps, limit=case.get("limit"))
    if op == "waves_iter":
        return api.waves(iter(steps), limit=case.get("limit"))
    if op == "waves_positional":
        return api.waves(steps, case.get("limit"))
    if op == "subset":
        return api.subset(steps, case["targets"])
    if op == "subset_iter":
        return api.subset(iter(steps), iter(case["targets"]))
    if op == "repeat_calls":
        results = [api.order(steps), api.waves(steps), api.order(steps), api.waves(steps, limit=1),
                   api.subset(steps, [steps[0].name]), api.order(steps)]
        return [results, [record(step) for step in steps]]
    raise ValueError(op)


def evaluate(api, case):
    try:
        # A round trip through JSON, so a tuple and a list count as the same sequence.
        return {"value": json.loads(json.dumps(perform(api, case)))}
    except api.PlanError as exc:
        name = type(exc).__name__
        report = {"error": name, "message": str(exc)}
        for attribute in ERROR_ATTRIBUTES.get(name, ()):
            value = getattr(exc, attribute, "<absent>")
            report[attribute] = list(value) if isinstance(value, (list, tuple)) else value
        return report
    except Exception as exc:
        return {"crash": type(exc).__name__, "detail": str(exc)[:300]}


def main():
    import runsheet
    cases = json.load(sys.stdin)
    print(json.dumps([evaluate(runsheet, case) for case in cases]))


if __name__ == "__main__":
    main()
