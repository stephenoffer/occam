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


def test_repository_unchanged(git):
    assert git("status", "--porcelain").strip() == ""


def test_any_edit_attempt_was_denied_by_the_hook(tool_calls):
    for call in tool_calls:
        if call["name"] in EDITS and "notes.py" in call["input"].get("file_path", ""):
            assert call["is_error"], "an edit to the file went through"
            assert "occam:" in call["result"], call["result"][:200]


def test_real_issue_still_reported(final_message):
    assert re.search(r"mutable|default arg|shared|persist", final_message, re.I)
