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


def test_fast_and_equivalent(py):
    code = (
        "import time; from report import top_customers as t;"
        "rows=[{'customer':f'c{i%5000}','amount':i%7} for i in range(200000)];"
        "s=time.time(); r=t(rows,3); assert time.time()-s<5, time.time()-s;"
        "assert t([{'customer':'b','amount':1},{'customer':'a','amount':1}],2)==['a','b'];print('ok')"
    )
    done = py("-c", code, timeout=60)
    assert done.stdout.strip() == "ok", done.stderr[-300:]
