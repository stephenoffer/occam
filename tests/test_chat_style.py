"""evals/chat_style.py: what it counts in a saved run, on runs written here."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "evals"))
import chat_style  # noqa: E402


def saved_run(root, arm, blocks, report):
    run = root / "graded" / "case-a" / arm
    run.mkdir(parents=True)
    lines = [json.dumps({"type": "assistant", "message": {"content": [block]}}) for block in blocks]
    (run / "trace.jsonl").write_text("\n".join(lines) + "\n")
    (run / "final_message.txt").write_text(report)


def tool():
    return {"type": "tool_use", "name": "Bash", "input": {}}


def text(words):
    return {"type": "text", "text": words}


def test_it_counts_stamps_self_talk_and_the_longest_silence(tmp_path):
    saved_run(tmp_path, "with-0", [text("Small mode."), tool(), tool(), tool(), text("The hook blocked the edit, so I'll load it."), tool(), text("Done.")],
              "The fix works.\n\n- **Verified:** 4 tests pass.\n- **Not run:** the linter.\n")
    saved_run(tmp_path, "without-0", [tool(), text("The page count rounds down, so I'll fix both clients."), tool(), tool(), text("Fixed.")],
              "Paging now returns all 120 vehicles. The 4 tests pass, and I didn't run a linter. The post-merge hook still reindexes.\n")
    rows = {row["arm"]: row for row in chat_style.runs(tmp_path)}
    assert rows["with"]["labels"] and rows["with"]["self_talk"] and rows["with"]["silence"] == 3
    assert not rows["without"]["labels"] and not rows["without"]["self_talk"], "plain prose, and a repository's own git hook, aren't occam talk"
    assert rows["without"]["silence"] == 2
