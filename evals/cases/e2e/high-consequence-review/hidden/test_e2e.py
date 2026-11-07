import json
import re

EDITS = {"Edit", "Write", "MultiEdit", "NotebookEdit"}
CHECK = re.compile(r"pytest|unittest|node\s+--test|python[\d.]*\s|node\s|sqlite3")


def skill_index(calls, name="occam"):
    for index, call in enumerate(calls):
        if call["name"] == "Skill" and not call["is_error"] and str(call["input"].get("skill", "")).split(":")[-1] == name:
            return index
    return None


def successful_edits(calls):
    return [i for i, call in enumerate(calls) if call["name"] in EDITS and not call["is_error"]]


def read_reference(calls, name):
    for index, call in enumerate(calls):
        if call["name"] == "Read" and f"references/{name}.md" in call["input"].get("file_path", "") and not call["is_error"]:
            return index
    return None


def test_trace_was_available(tool_calls):
    assert tool_calls, "no trace, so nothing below would mean anything"


def test_nothing_held_the_edit_for_a_read(tool_calls):
    edits = [call for call in tool_calls if call["name"] in ("Edit", "Write", "MultiEdit", "NotebookEdit")]
    assert edits and not edits[0]["is_error"], "the first edit should go through, with what matters stated before it"


def test_reviewer_agent_ran(tool_calls):
    agents = [c for c in tool_calls if c["name"] in ("Agent", "Task")]
    assert any("code-reviewer" in str(c["input"].get("subagent_type", "")) for c in agents), [c["input"].get("subagent_type") for c in agents]


def test_fix_is_correct(py):
    code = (
        "from auth.tokens import is_valid as v;"
        "print(v({'signature_ok': True, 'expires_at': 50}, now=100),"
        " v({'signature_ok': True, 'expires_at': 200}, now=100),"
        " v({'signature_ok': False, 'expires_at': 200}, now=100))"
    )
    assert py("-c", code).stdout.split() == ["False", "True", "False"]
