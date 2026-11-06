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


def test_core_skill_loaded(tool_calls):
    assert skill_index(tool_calls) is not None


def test_cancellation_propagates(py):
    code = (
        "import asyncio, fetcher\n"
        "async def slow(url):\n"
        "    await asyncio.sleep(10)\n"
        "fetcher.fetch = slow\n"
        "async def main():\n"
        "    t = asyncio.create_task(fetcher.fetch_all(['a','b']))\n"
        "    await asyncio.sleep(0.05)\n"
        "    t.cancel()\n"
        "    try:\n"
        "        await asyncio.wait_for(t, 2)\n"
        "    except asyncio.CancelledError:\n"
        "        print('cancelled')\n"
        "asyncio.run(main())\n"
    )
    assert py("-c", code, timeout=30).stdout.strip() == "cancelled"
