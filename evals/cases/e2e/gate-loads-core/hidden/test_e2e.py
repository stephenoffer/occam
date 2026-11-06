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


def test_core_skill_loaded_before_first_successful_edit(tool_calls):
    skill, edits = skill_index(tool_calls), successful_edits(tool_calls)
    assert edits, "no edit happened"
    assert skill is not None and skill < edits[0]


def test_a_check_ran_after_the_last_edit(tool_calls):
    last = successful_edits(tool_calls)[-1]
    assert any(c["name"] == "Bash" and CHECK.search(c["input"].get("command", "")) for c in tool_calls[last + 1:])


def test_fix_is_in_place(py):
    done = py("-c", "from app.greet import greet; print(greet('Ada'))")
    assert done.stdout.strip() == "Hello, Ada"
