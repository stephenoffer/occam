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


import subprocess


def test_core_skill_loaded(tool_calls):
    assert skill_index(tool_calls) is not None


def test_fix_works(ws):
    code = "const {listUsers:l}=require('./src/users');console.log(l([1,2],0).length,l([1,2]).length)"
    done = subprocess.run(["node", "-e", code], cwd=ws, capture_output=True, text=True, timeout=30)
    assert done.stdout.split() == ["0", "2"], done.stderr
