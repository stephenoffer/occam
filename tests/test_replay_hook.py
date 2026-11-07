"""The free replay has to report what the hook does, or a before-and-after from it means nothing."""

import json
import sys
from pathlib import Path

import replay_hook

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "plugin" / "hooks"))

import occam_hook  # noqa: E402


def write_run(run_dir, calls, cwd="/recorded/project"):
    run_dir.mkdir(parents=True)
    lines = [{"type": "system", "subtype": "init", "cwd": cwd, "session_id": "s"},
             {"type": "system", "subtype": "init", "cwd": cwd + "/moved", "session_id": "s"}]  # a resumed run records where its shell went
    for index, (name, tool_input, text, is_error) in enumerate(calls):
        block = {"type": "tool_use", "id": f"t{index}", "name": name, "input": tool_input}
        result = {"type": "tool_result", "tool_use_id": f"t{index}", "content": text, "is_error": is_error}
        lines += [{"type": "assistant", "message": {"id": f"m{index}", "content": [block]}}, {"type": "user", "message": {"content": [result]}}]
    (run_dir / "trace.jsonl").write_text("\n".join(json.dumps(line) for line in lines))
    (run_dir / "final_message.txt").write_text("I split out only a small part of the module.")
    (run_dir / "diff.patch").write_text("")


def case(tmp_path):
    folder = tmp_path / "case"
    (folder / "files").mkdir(parents=True)
    (folder / "files" / "app.py").write_text("a = 1\n")
    (folder / "prompt.md").write_text("---\nmax_turns: 5\n---\n\nFix it.\n")
    return folder


def run(tmp_path, calls):
    write_run(tmp_path / "run", calls)
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    return replay_hook.replay_run(occam_hook, tmp_path / "run", case(tmp_path), scratch)


def test_it_keeps_the_first_init_as_the_project(tmp_path):
    write_run(tmp_path / "run", [])
    assert replay_hook.tool_calls(tmp_path / "run" / "trace.jsonl")[0] == "/recorded/project"


def test_a_loaded_skill_counts_and_doesnt_read_as_a_hook_stopping_it(tmp_path):
    found = run(tmp_path, [("Skill", {"skill": "occam:occam"}, "Launching skill: occam:occam", False),
                           ("Skill", {"skill": "occam:occam-python"}, "Launching skill: occam:occam-python", False),
                           ("Edit", {"file_path": "/recorded/project/app.py", "old_string": "a = 1", "new_string": "a = 2"}, "ok", False)])
    assert not found["holds"]


def test_it_counts_a_hold_and_the_send_back(tmp_path):
    found = run(tmp_path, [("Edit", {"file_path": "/recorded/project/app.py", "old_string": "a = 1\n" * 20, "new_string": "a = 2\n" * 20}, "occam: held", True),
                           ("Skill", {"skill": "occam:occam"}, "Launching skill: occam:occam", False),
                           ("Skill", {"skill": "occam:occam-python"}, "Launching skill: occam:occam-python", False),
                           ("Edit", {"file_path": "/recorded/project/app.py", "old_string": "a = 1", "new_string": "a = 2"}, "ok", False),
                           ("Bash", {"command": "pytest -q"}, "3 passed in 0.01s", False)])
    assert found["holds"] == {"forced read: core skill": 1}
    assert "stopped short" in found["sent_back"]


def test_every_send_back_reason_is_still_something_the_hook_says():
    source = "".join(path.read_text() for path in (ROOT / "plugin" / "hooks").glob("*.py"))
    assert all(phrase in source for phrase in replay_hook.SENT_BACK.values())


def test_a_send_back_counts_even_when_the_last_message_answers_it(tmp_path):
    """The last message of a sent-back run is the reply, which already says what the note asked for. Judging only that hides the send-back."""
    run_dir = tmp_path / "run"
    calls = [("Edit", {"file_path": "/recorded/project/app.py"}, "ok", False)]
    write_run(run_dir, calls)
    trace = run_dir / "trace.jsonl"
    report = {"type": "assistant", "message": {"id": "report", "content": [{"type": "text", "text": "Fixed it, all done."}]}}
    reply = {"type": "assistant", "message": {"id": "reply", "content": [{"type": "text", "text": "I didn't run a check, so this is unverified."}]}}
    trace.write_text(trace.read_text() + "\n" + json.dumps(report) + "\n" + json.dumps(reply))
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    found = replay_hook.replay_run(occam_hook, run_dir, case(tmp_path), scratch)
    assert "no check since the edit" in found["sent_back"]
    assert found["send_backs"] >= 1


def test_text_beside_a_tool_call_isnt_a_stop(tmp_path):
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    lines = [{"type": "assistant", "message": {"id": "a", "content": [{"type": "text", "text": "Now I'll run it."}]}},
             {"type": "assistant", "message": {"id": "a", "content": [{"type": "tool_use", "id": "t", "name": "Bash", "input": {}}]}},
             {"type": "assistant", "parent_tool_use_id": "t", "message": {"id": "sub", "content": [{"type": "text", "text": "A subagent's message."}]}},
             {"type": "assistant", "message": {"id": "b", "content": [{"type": "text", "text": "Done."}]}}]
    (run_dir / "trace.jsonl").write_text("\n".join(json.dumps(line) for line in lines))
    assert replay_hook.stops_in(run_dir / "trace.jsonl") == [(1, "Done.")]
