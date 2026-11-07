"""Occam at both ends of the range: a hello-world edit stays cheap, and a run lasting hours keeps its checks and its goal."""

import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "plugin" / "hooks"))

import scale_notes  # noqa: E402
from occam_commands import is_check, rewrites_in_place  # noqa: E402

HOOK = ROOT / "plugin" / "hooks" / "occam_hook.py"
TOOL = ROOT / "plugin" / "skills" / "occam" / "scripts" / "occam.py"
FAKE_KEY = "AKIA" + "A" * 16  # built here so no credential shape sits in the repository


class Session:
    def __init__(self, tmp_path):
        self.project = tmp_path / "project"
        self.project.mkdir()
        self.env = {**os.environ, "CLAUDE_PLUGIN_DATA": str(tmp_path / "data"), "CLAUDE_PLUGIN_ROOT": str(ROOT / "plugin"),
                    "CLAUDE_PROJECT_DIR": str(self.project), "OCCAM_STATE_DIR": str(tmp_path / "state")}
        self.env.pop("OCCAM_HOOKS", None)

    def send(self, handler, **fields):
        event = {"session_id": "s1", "cwd": str(self.project), **fields}
        done = subprocess.run([sys.executable, str(HOOK), handler], input=json.dumps(event), capture_output=True, text=True, env=self.env, timeout=60)
        assert done.returncode == 0 and "failed open" not in done.stderr, done.stderr
        return json.loads(done.stdout) if done.stdout.strip() else {}

    def prompt(self, text):
        return self.send("user-prompt", prompt=text)

    def write_event(self, name, content):
        return {"tool_name": "Write", "tool_input": {"file_path": str(self.project / name), "content": content}}

    def edit_event(self, name, old, new, **extra):
        return {"tool_name": "Edit", "tool_input": {"file_path": str(self.project / name), "old_string": old, "new_string": new, **extra}}

    def attempt(self, event):
        return self.send("pre-tool", **event)

    def finish(self, event):
        return self.send("post-tool", **event)

    def do(self, event):
        """The edit tool's whole life: the hook decides, the edit lands, and the hook hears about it."""
        output = self.attempt(event)
        assert denied(output) is None, output
        tool = event["tool_input"]
        path = Path(tool["file_path"])
        if event["tool_name"] == "Write":
            path.write_text(tool["content"])
        elif path.exists():
            path.write_text(path.read_text().replace(tool["old_string"], tool["new_string"]))
        return output, self.finish(event)

    def bash(self, command, ok=True, output=""):
        event = {"tool_name": "Bash", "tool_input": {"command": command}}
        before = self.attempt(event)
        if denied(before):
            return before
        return self.send("post-tool" if ok else "post-failure", **event, tool_response={"stdout": output})

    def load(self, skill="occam:occam"):
        return self.send("post-tool", tool_name="Skill", tool_input={"skill": skill})

    def stop(self, message="Done.", **extra):
        return self.send("stop", last_assistant_message=message, **extra)


@pytest.fixture
def session(tmp_path):
    return Session(tmp_path)


def spec(output):
    return (output or {}).get("hookSpecificOutput") or {}


def denied(output):
    return spec(output).get("permissionDecisionReason") if spec(output).get("permissionDecision") == "deny" else None


def added(output):
    return spec(output).get("additionalContext", "")


# ---------------------------------------------------------------- a very small edit


@pytest.mark.parametrize("name, body", [("hello.py", 'print("hello world")\n'), ("hello.sh", "echo hello\n"), ("hello.js", 'console.log("hi")\n'),
                                        ("hello.c", '#include <stdio.h>\nint main(void) { puts("hi"); }\n'), ("hello.rb", 'puts "hi"\n'),
                                        ("Main.java", 'class Main { public static void main(String[] a) { System.out.println("hi"); } }\n'),
                                        ("Hello.cs", 'using System;\nclass P { static void Main() { Console.WriteLine("hi"); } }\n'),
                                        ("hello.go", 'package main\nimport "fmt"\nfunc main() { fmt.Println("hi") }\n'), ("hello.rs", 'fn main() { println!("hi"); }\n'),
                                        ("hello.php", '<?php echo "hi";\n'), ("hello.html", '<p>hello</p>\n')])
def test_hello_world_needs_no_skill_and_no_retry(session, name, body):
    session.prompt(f"write {name} that prints hello")
    before, _ = session.do(session.write_event(name, body))
    assert "without the full skill" in added(before)
    assert "everywhere it occurs" in added(before), "the rules arrive without loading the skill"


def test_a_question_with_no_edit_costs_nothing(session):
    assert session.prompt('how do I print hello world in python?') == {}
    assert session.stop('Use print("hello world").') == {}


def test_one_line_fix_in_an_existing_file_goes_through(session):
    (session.project / "app.py").write_text("def greet():\n    return 'helo'\n")
    session.prompt("fix the typo in app.py")
    before, _ = session.do(session.edit_event("app.py", "helo", "hello"))
    assert "without the full skill" in added(before)


def test_small_note_comes_once(session):
    session.prompt("fix it")
    (session.project / "app.py").write_text("a = 1\nb = 2\n")
    first, _ = session.do(session.edit_event("app.py", "a = 1", "a = 3"))
    second, _ = session.do(session.edit_event("app.py", "b = 2", "b = 3"))
    assert "without the full skill" in added(first)
    assert "without the full skill" not in added(second)


def test_a_small_edit_still_needs_a_check_before_stopping(session):
    session.prompt("write hello.py")
    session.do(session.write_event("hello.py", 'print("hi")\n'))
    assert "No check has run" in added(session.stop())
    session.bash("python3 hello.py", output="hi\n")
    assert session.stop("Wrote it and ran it.") == {}


@pytest.mark.parametrize("prompt, name, old, new", [
    ("fix it", "auth.py", "a = 1", "a = 2"),  # one line of access control is still high consequence
    ("fix it", "billing/invoice.py", "a = 1", "a = 2"),
    ("fix it", "migrations/0007.py", "a = 1", "a = 2"),
    ("add it", "requirements.txt", "a==1", "a==2"),
    ("fix the authorization check", "app.py", "a = 1", "a = 2"),
    ("speed up the report, it is too slow", "app.py", "a = 1", "a = 2"),
    ("fix it", "app.py", "a = 1", "async def f(): pass"),
    ("fix it", "app.py", "a = 1", "\n".join(f"x{i} = {i}" for i in range(25))),
    ("fix it", "app.py", "\n".join(f"x{i} = {i}" for i in range(25)), "a = 1"),
    ("fix it", "app.py", "a = 1", "a = '" + "x" * 2000 + "'"),
])
def test_what_is_not_small_is_still_held(session, prompt, name, old, new):
    session.prompt(prompt)
    assert "has not been loaded" in (denied(session.attempt(session.edit_event(name, old, new))) or "")


def test_replacing_a_whole_file_with_a_few_lines_is_held(session):
    (session.project / "app.py").write_text("a = 1\n" * 500)
    session.prompt("fix it")
    assert "has not been loaded" in (denied(session.attempt(session.write_event("app.py", "a = 1\n"))) or "")


def test_replacing_a_file_too_large_to_compare_is_held(session):
    (session.project / "app.py").write_text("a = 1\n" * 500_000)
    session.prompt("fix it")
    assert "has not been loaded" in (denied(session.attempt(session.write_event("app.py", "a = 1\n"))) or "")


def test_replace_all_is_held(session):
    (session.project / "app.py").write_text("a = 1\n")
    session.prompt("rename it")
    assert "has not been loaded" in (denied(session.attempt(session.edit_event("app.py", "a", "b", replace_all=True))) or "")


def test_work_that_grows_past_small_gets_the_skill(session):
    session.prompt("change these")
    for name in ("a.py", "b.py"):
        (session.project / name).write_text("a = 1\nb = 2\nc = 3\nd = 4\n")
    session.do(session.edit_event("a.py", "a = 1", "a = 2"))
    session.do(session.edit_event("b.py", "a = 1", "a = 2"))
    (session.project / "c.py").write_text("a = 1\n")
    assert "has not been loaded" in denied(session.attempt(session.edit_event("c.py", "a = 1", "a = 2"))), "a third file isn't small"
    session.do(session.edit_event("a.py", "b = 2", "b = 3"))
    assert "has not been loaded" in denied(session.attempt(session.edit_event("a.py", "c = 3", "c = 4"))), "a fourth edit isn't small"


def test_guards_unrelated_to_the_skill_still_apply_to_a_small_edit(session):
    session.prompt("review only, don't change anything")
    assert "review-only" in denied(session.attempt(session.write_event("hello.py", "print(1)\n")))
    session.prompt("add the key")
    assert "looks like" in denied(session.attempt(session.write_event("hello.py", f'k = "{FAKE_KEY}"\n')))
    (session.project / "test_a.py").write_text("def test_a():\n    assert f()\n")
    session.prompt("fix it")
    assert "removes 1 assertion" in denied(session.attempt(session.edit_event("test_a.py", "    assert f()\n", "    f()\n")))


def test_the_shadow_note_still_reaches_a_small_edit(session):
    session.prompt("write a calendar helper")
    assert "standard library" in added(session.attempt(session.write_event("calendar.py", "x = 1\n")))


def test_nothing_rewards_keeping_a_fix_small(session):
    """Two paid runs saw a second copy of a bug and left it, after being told edits past a size were held. The size isn't announced, and neither is a penalty for growing."""
    start = added(session.send("session-start", source="startup"))
    assert "small" not in start.lower() and "occam:occam" in start
    session.prompt("fix it")
    (session.project / "app.py").write_text("a = 1\n")
    note = added(session.attempt(session.edit_event("app.py", "a = 1", "a = 2")))
    assert "everywhere it occurs" in note
    for word in ("small", "grows", "held", "required"):
        assert word not in note.lower(), word


@pytest.mark.parametrize("words", [["ruby", "hello.rb"], ["java", "Hello.java"], ["javac", "Hello.java"], ["gcc", "hello.c", "-o", "hello"], ["cc", "hello.c"], ["clang++", "a.cc"],
                                   ["rustc", "hello.rs"], ["php", "a.php"], ["perl", "a.pl"], ["perl", "-e", "print 1"], ["lua", "a.lua"], ["swift", "a.swift"], ["kotlinc", "a.kt"],
                                   ["scala", "a.scala"], ["julia", "a.jl"], ["Rscript", "a.R"], ["elixir", "a.exs"], ["ghc", "a.hs"], ["dart", "a.dart"], ["dotnet", "test"], ["dotnet", "run"],
                                   ["deno", "test"], ["mix", "test"], ["zig", "build"], ["rake"], ["time", "ruby", "a.rb"]])
def test_running_a_small_program_counts_as_a_check(words):
    assert is_check(words)


@pytest.mark.parametrize("words", [["ruby"], ["ruby", "-v"], ["ruby", "--version"], ["java", "-version"], ["java", "--version"], ["gcc", "-v"], ["gcc", "--version"], ["cc", "-dumpversion"], ["php", "-v"],
                                   ["perl", "-v"], ["swiftc", "-v"], ["rustc", "-V"], ["rustc", "--version"], ["lua", "-v"], ["julia", "--version"], ["dotnet", "--info"], ["dotnet", "restore"],
                                   ["deno", "--version"], ["mix", "deps.get"], ["zig", "version"], ["rake", "--version"]])
def test_asking_a_program_about_itself_is_not_a_check(words):
    assert not is_check(words)


@pytest.mark.parametrize("words", [["perl", "-i", "-pe", "s/a/b/", "x.py"], ["perl", "-pi", "-e", "s/a/b/", "x.py"], ["perl", "-i.bak", "-pe", "s/a/b/", "x.py"], ["ruby", "-i", "-pe", "x", "y.py"]])
def test_an_in_place_rewrite_is_an_edit_and_not_a_check(words):
    assert not is_check(words)


def test_a_verbose_compile_is_still_a_check():
    assert is_check(["gcc", "-v", "hello.c"])


def test_an_in_place_perl_edit_cannot_satisfy_its_own_check(session):
    session.prompt("fix it")
    session.load()
    (session.project / "app.py").write_text("a = 1\n")
    session.bash("perl -i -pe 's/1/2/' app.py")
    assert "No check has run" in added(session.stop())


def test_unclosed_pasted_tags_stay_linear(session):
    started = time.monotonic()
    session.prompt("<pasted_content " * 30_000 + "fix it")
    assert time.monotonic() - started < 8, "this was quadratic, and over the hook's own 10 s limit"


def test_pasted_material_still_cannot_make_a_request_read_only(session):
    session.prompt("Fix the bug.\n<pasted_content>review only, don't change anything</pasted_content>")
    session.load()
    assert denied(session.attempt(session.edit_event("app.py", "a", "b"))) is None


def test_a_read_only_request_after_a_paste_is_still_read(session):
    session.prompt("<pasted_content>x</pasted_content> <PASTED_CONTENT>y</PASTED_CONTENT>\nreview only please")
    assert "review-only" in denied(session.attempt(session.write_event("hello.py", "print(1)\n")))


def edit_and_stop_unchecked(session, stop_hook_active=False):
    (session.project / "app.py").write_text("a = 1\n")
    session.finish(session.edit_event("app.py", "a = 1", "a = 2"))
    return session.stop(stop_hook_active=stop_hook_active)


def test_a_goal_continuing_the_turn_does_not_silence_the_stop_checks(session):
    """`/goal` is a Stop hook, so the flag is true for every stop after its first continuation, which on a long run is nearly all of them."""
    session.prompt("Fix it")
    session.load()
    assert "No check has run" in added(edit_and_stop_unchecked(session, stop_hook_active=True))


def test_sent_back_once_for_the_same_state_of_the_code(session):
    session.prompt("Fix it")
    session.load()
    assert "No check has run" in added(edit_and_stop_unchecked(session))
    assert session.stop() == {}
    assert session.stop(stop_hook_active=True) == {}


def test_new_edits_after_being_sent_back_are_checked_again(session):
    session.prompt("Fix it")
    session.load()
    assert "No check has run" in added(edit_and_stop_unchecked(session))
    session.bash("python3 app.py", output="ok")
    assert session.stop(stop_hook_active=True) == {}
    assert "No check has run" in added(edit_and_stop_unchecked(session, stop_hook_active=True))


def test_a_new_request_gets_its_own_send_back(session):
    session.prompt("Fix it")
    session.load()
    assert added(edit_and_stop_unchecked(session))
    session.prompt("Now fix the other thing")
    assert "No check has run" in added(edit_and_stop_unchecked(session))


def many_edits(session, count, files=1):
    notes = []
    for index in range(count):
        name = f"m{index % files}.py"
        (session.project / name).write_text("a = 1\n")
        notes.append(added(session.finish(session.edit_event(name, "a = 1", "a = 2"))))
    return [note for note in notes if "grown to" in note]


def test_a_long_run_hears_about_the_goal_ledger_once(session):
    session.prompt("Migrate everything")
    session.load()
    notes = many_edits(session, 35)
    assert len(notes) == 1
    assert f"{TOOL} goal init" in notes[0]


def test_many_files_count_as_a_long_run_sooner(session):
    session.prompt("Migrate everything")
    session.load()
    assert len(many_edits(session, 12, files=12)) == 1


def test_a_short_run_hears_nothing_about_it(session):
    session.prompt("Fix it")
    session.load()
    assert many_edits(session, 8) == []


def tool(session, *args):
    return subprocess.run([sys.executable, str(TOOL), *args], cwd=session.project, env=session.env, capture_output=True, text=True, timeout=120)


def test_a_long_run_with_a_goal_hears_its_name_since_it_may_be_left_over(session):
    assert tool(session, "goal", "init", "migrate billing to the new client").returncode == 0
    session.prompt("Rename the export button")
    session.load()
    notes = many_edits(session, 35)
    assert len(notes) == 1 and "migrate billing to the new client" in notes[0]
    assert f"{TOOL} goal verify" in notes[0] and f"{TOOL} goal init" in notes[0]


def test_compaction_points_back_to_a_recorded_goal(session):
    assert tool(session, "goal", "init", "migrate everything to the new client").returncode == 0
    assert tool(session, "goal", "add", "old client is gone", "--check", "true").returncode == 0
    note = added(session.send("session-start", source="compact"))
    assert "migrate everything to the new client" in note
    assert "0 of 1 requirements" in note
    assert f"{TOOL} goal status" in note and f"{TOOL} goal clear" in note


def test_compaction_without_a_goal_says_only_what_it_always_did(session):
    note = added(session.send("session-start", source="compact"))
    assert "goal" not in note
    assert "occam:occam" in note


@pytest.mark.parametrize("old, new, small", [
    ("a", "b", True),
    ("", "x\n" * 19, True),
    ("", "x\n" * 20, False),
    ("x\n" * 19, "", True),
    ("x\n" * 20, "", False),
    ("x" * 750, "y" * 750, True),
    ("x" * 750, "y" * 751, False),
    ("", "", False),  # nothing to size
])
def test_what_counts_as_one_small_edit(tmp_path, old, new, small):
    assert scale_notes.small_edit("Edit", {}, str(tmp_path / "missing.py"), old, new) is small


def test_a_write_over_a_file_with_no_old_text_cannot_be_sized(tmp_path):
    existing = tmp_path / "big.py"
    existing.write_text("x\n")
    assert not scale_notes.small_edit("Write", {}, str(existing), "", "x\n")
    assert scale_notes.small_edit("Write", {}, str(tmp_path / "new.py"), "", "x\n")
    assert scale_notes.small_edit("Edit", {}, str(existing), "", "x\n"), "only a whole-file write compares with the file"


def test_notebook_and_replace_all_edits_cannot_be_sized(tmp_path):
    assert not scale_notes.small_edit("NotebookEdit", {}, str(tmp_path / "n.ipynb"), "", "x")
    assert not scale_notes.small_edit("Edit", {"replace_all": True}, str(tmp_path / "a.py"), "a", "b")


@pytest.mark.parametrize("earlier, paths, small", [
    ([], ["a.py"], True),
    (["a.py", "a.py"], ["a.py"], True),
    (["a.py", "a.py", "a.py"], ["a.py"], False),
    (["a.py"], ["b.py"], True),
    (["a.py", "b.py"], ["c.py"], False),
])
def test_what_counts_as_a_small_session(earlier, paths, small):
    entries = [{"kind": "edit", "code": True, "path": path} for path in earlier] + [{"kind": "edit", "code": False, "path": "notes.md"}, {"kind": "check"}]
    assert scale_notes.stays_small(entries, paths) is small


@pytest.mark.parametrize("edits, files, long", [(29, 1, False), (30, 1, True), (9, 9, False), (10, 10, True)])
def test_what_counts_as_a_long_run(edits, files, long):
    assert scale_notes.is_long_run([{"kind": "edit", "code": True, "path": f"m{index % files}.py"} for index in range(edits)]) is long


def test_only_code_edits_count_toward_a_long_run():
    assert not scale_notes.is_long_run([{"kind": "edit", "code": False, "path": f"m{index}.md"} for index in range(100)])


@pytest.mark.parametrize("text, expected", [
    ("before <pasted_content>x</pasted_content> after", "before   after"),
    ("<PASTED_CONTENT id='1'>x\ny</pasted_content>keep", " keep"),
    ("<pasted_content>a</pasted_content>keep<pasted_content>b</pasted_content>", " keep "),
    ("<pasted_content>never closed", "<pasted_content>never closed"),
    ("<pasted_content>a</pasted_content> <pasted_content>unclosed", "  <pasted_content>unclosed"),
    ("no tags at all", "no tags at all"),
])
def test_pasted_material_comes_out_and_nothing_else_does(text, expected):
    assert scale_notes.without_pasted(text) == expected


def test_large_file_note_keeps_what_it_always_said():
    data = b"x\n" * 1001
    assert "a.py is 1001 lines, past the 1000" in scale_notes.large_file_text("a.py", data, 1000, "")
    assert scale_notes.large_file_text("a.py", b"x\n" * 1000, 1000, "") is None
    assert "How to split safely is at guide.md." in scale_notes.large_file_text("a.py", data, 1000, "guide.md")
    assert "How to split" not in scale_notes.large_file_text("a.go", data, 1000, "")
    assert scale_notes.large_file_text("a.sql", data, 1000, "") is None
    assert scale_notes.large_file_text("a.py", b"# @generated\n" + data, 1000, "") is None


def test_a_rewrite_is_a_large_part_of_a_real_file(tmp_path):
    existing = tmp_path / "a.py"
    existing.write_text("x\n" * 30)
    assert scale_notes.replaces_working_code(str(tmp_path), "Write", {}, "a.py")
    existing.write_text("x\n" * 29)
    assert not scale_notes.replaces_working_code(str(tmp_path), "Write", {}, "a.py")
    assert scale_notes.replaces_working_code(str(tmp_path), "Edit", {"old_string": "x\n" * 30}, "a.py")
    assert not scale_notes.replaces_working_code(str(tmp_path), "Edit", {"old_string": "x\n" * 29}, "a.py")
    assert not scale_notes.replaces_working_code(str(tmp_path), "Write", {}, "missing.py")


def test_a_broken_goal_store_only_costs_the_reminder(monkeypatch, tmp_path):
    monkeypatch.setenv("OCCAM_STATE_DIR", str(tmp_path / "state"))
    from occam_tools import workflow

    def broken(_root):
        raise OSError("disk full")

    monkeypatch.setattr(workflow, "_load", broken)
    assert scale_notes.goal_reminder(str(tmp_path)) == ""
    assert "grown to" in scale_notes.long_run_text([{"kind": "edit", "code": True, "path": "a.py"}], str(tmp_path), "guide.md")


@pytest.mark.parametrize("prompt", ["Fix this security bug in app.py", "make this more secure", "fix the password check", "fix the XSS here", "fix the CSRF token check", "encrypt the stored value", "fix the login bug",
                                    "optimize this loop", "make it more efficient", "reduce memory use here", "add requests as a dependency", "upgrade lodash to 4.17.21", "bump numpy", "install redis and use it", "refactor this"])
def test_a_consequential_request_is_not_small_whatever_the_edit(session, prompt):
    session.prompt(prompt)
    assert "has not been loaded" in (denied(session.attempt(session.edit_event("app.py", "a = 1", "a = 2"))) or "")


def test_a_consequential_request_stays_named_after_a_short_reply(session):
    session.prompt("Fix the authentication bypass")
    session.prompt("yes go ahead")
    assert "has not been loaded" in (denied(session.attempt(session.edit_event("app.py", "a = 1", "a = 2"))) or "")


def test_a_consequential_request_past_the_stored_length_still_counts(session):
    session.prompt("x " * 2100 + "this is an authorization bypass, fix it")
    assert "has not been loaded" in (denied(session.attempt(session.edit_event("app.py", "a = 1", "a = 2"))) or "")


def test_a_consequential_word_only_in_a_paste_does_not_count(session):
    session.prompt("fix the typo\n<pasted_content>password token auth</pasted_content>")
    assert denied(session.attempt(session.edit_event("app.py", "helo", "hello"))) is None


@pytest.mark.parametrize("name", ["authentication.py", "authorization.py", "security.py", "encryption.py", "admin.py", "src/AuthService.java", "src/LoginController.ts", "src/PaymentService.kt", "src/userAuth.js", "src/passwordReset.ts",
                                  ".github/workflows/deploy.yml", "terraform/prod.tf", "Dockerfile", "k8s/deployment.yaml", "composer.json", "uv.lock", "package-lock.json", "schema.sql", "config.toml"])
def test_what_a_path_says_or_a_file_type_decides_is_not_small(session, name):
    session.prompt("fix it")
    assert "has not been loaded" in (denied(session.attempt(session.edit_event(name, "a = 1", "a = 2"))) or "")


@pytest.mark.parametrize("name, old, new", [("app.py", "commit()", "await commit()"), ("app.py", "await commit()", "commit()"), ("a.sh", "x", 'rm -rf "$DIR"/*'), ("a.sh", "x", 'eval "$CMD"'), ("a.rb", "x", "eval(params[:x])"),
                                            ("a.php", "x", "eval($_GET['x']);"), ("app.py", "x", 'cur.execute(f"SELECT * FROM t WHERE id = {uid}")'), ("app.py", "x", "shutil.rmtree(path)"), ("app.go", "x", "defer close(ch)"),
                                            ("app.py", "x", 'open(path, "w").write(data)')])
def test_risky_text_is_not_small_whichever_side_of_the_edit_it_is_on(session, name, old, new):
    session.prompt("fix it")
    assert "has not been loaded" in (denied(session.attempt(session.edit_event(name, old, new))) or "")


def test_a_multi_edit_is_read_like_any_other(session):
    (session.project / "app.py").write_text("x = 1\n")
    session.prompt("fix it")
    event = {"tool_name": "MultiEdit", "tool_input": {"file_path": str(session.project / "app.py"), "edits": [{"old_string": "x = 1", "new_string": "async def f(): await g()"}]}}
    assert "has not been loaded" in (denied(session.attempt(event)) or "")


@pytest.mark.parametrize("prompt, name, body", [("write a new hello.c that prints hello", "hello.c", '#include <stdio.h>\nint main(void) { puts("hi"); }\n'), ("delete the extra blank line in hello.cc", "hello.cc", "int main() {}\n"),
                                                ("is null handled? print hello", "hello.js", 'console.log("hello")\n')])
def test_ordinary_wording_does_not_make_a_small_edit_large(session, prompt, name, body):
    session.prompt(prompt)
    assert denied(session.attempt(session.write_event(name, body))) is None


def test_writing_over_an_empty_file_is_small(session):
    (session.project / "hello.py").write_text("")
    session.prompt("write hello.py")
    assert denied(session.attempt(session.write_event("hello.py", "print(1)\n"))) is None


def test_stop_cannot_keep_sending_back_however_much_changes(session):
    session.prompt("Fix it")
    session.load()
    (session.project / "app.py").write_text("a = 1\n")
    sent = 0
    for _ in range(12):
        session.finish(session.edit_event("app.py", "a = 1", "a = 2"))
        sent += bool(added(session.stop(stop_hook_active=True)))
    assert sent == 5


def test_a_false_claim_after_being_sent_back_is_still_caught(session):
    session.prompt("Fix it")
    session.load()
    assert "No check has run" in added(edit_and_stop_unchecked(session))
    session.bash("python3 -m pytest -q", ok=False)
    note = added(session.stop("All tests pass. 12 passed.", stop_hook_active=True))
    assert "failed" in note or "no check passed" in note.lower()
    assert session.stop("All tests pass. 12 passed.", stop_hook_active=True) == {}, "said once"


def test_a_long_run_from_the_shell_hears_about_the_goal_ledger(session):
    session.prompt("Migrate everything")
    session.load()
    (session.project / "app.py").write_text("a = 1\n")
    notes = [added(session.bash("sed -i '' s/a/b/ app.py")) for _ in range(32)]
    assert sum("grown to" in note for note in notes) == 1


def test_a_long_delegated_run_reaches_its_coordinator_when_the_work_comes_back(session):
    session.prompt("Migrate everything")
    session.load()
    for index in range(12):
        session.finish({**session.edit_event(f"m{index}.py", "a", "b"), "agent_id": "a1"})
    assert "grown to" in added(session.finish({"tool_name": "Agent", "tool_input": {"subagent_type": "general-purpose"}}))


@pytest.mark.parametrize("words", [["perl", "-0pi", "-e", "s/a/b/", "x.py"], ["perl", "-0777pi", "-e", "s/a/b/", "x.py"], ["perl", "-00pi", "-e", "s/a/b/", "x.py"], ["ruby", "-0pi", "-e", "x", "y.py"], ["perl", "-pe", "s/a/b/", "-i", "x.py"]])
def test_every_way_of_spelling_an_in_place_rewrite_is_not_a_check(words):
    assert not is_check(words)


@pytest.mark.parametrize("words", [["ruby", "-Ilib", "test/foo_test.rb"], ["perl", "-Ilib", "t/basic.t"], ["ruby", "-rminitest/autorun", "t.rb"], ["perl", "-MList::Util=sum", "-e", "print sum(1)"], ["perl", "a.pl", "-file", "x"], ["gcc", "-Iinclude", "a.c"]])
def test_a_real_run_whose_switches_happen_to_contain_an_i_is_a_check(words):
    assert is_check(words)


@pytest.mark.parametrize("words", [["rustc", "-vV"], ["rustc", "--version", "--verbose"], ["php", "-i"], ["php", "-m"], ["perl", "-V:version"], ["ghc", "--numeric-version"], ["gcc", "-dumpfullversion"], ["swift", "package", "init"], ["dart", "pub", "get"]])
def test_more_ways_of_asking_a_program_about_itself_are_not_checks(words):
    assert not is_check(words)


@pytest.mark.parametrize("prompt", ["fix the oauth callback", "fix the JWT expiry", "the SSO redirect is wrong", "fix the session timeout", "add access control to this endpoint", "fix the SQL query", "add a column to the users table",
                                    "delete all inactive users", "change the tax rate", "this endpoint leaks PII", "disable TLS verification", "fix the `password` check", "the `login` handler is wrong"])
def test_more_consequential_requests_are_not_small(session, prompt):
    session.prompt(prompt)
    assert "has not been loaded" in (denied(session.attempt(session.edit_event("app.py", "a = 1", "a = 2"))) or "")


@pytest.mark.parametrize("prompt", ["write hello world using only the standard library", "make a hello world package", "fix a typo in the install message", "fix the typo in the package description"])
def test_ordinary_small_requests_are_not_held_for_a_word_in_them(session, prompt):
    session.prompt(prompt)
    assert denied(session.attempt(session.edit_event("app.py", "helo", "hello"))) is None


@pytest.mark.parametrize("old, new", [("@login_required", ""), ("if not user.is_admin: raise Forbidden", "pass"), ("check_password(pw, h)", "True"), ("user_password = x", "x"), ("API_TOKEN = a", "API_TOKEN = b"), ("AWS_SECRET_ACCESS_KEY", "X"),
                                      ("execute_query(sql)", "x"), ("delete_user(uid)", "x"), ("drop_table(t)", "x"), ("os.remove(path)", "x"), ("verify=False", "verify=True"), ("amount_due", "x"), ("total_price", "x"), ("isAdmin", "x"),
                                      ("checkPassword(p)", "true"), ("executeQuery(q)", "x"), ("fs.rmSync(p)", "x"), ("execSync(c)", "x")])
def test_consequential_identifiers_are_seen_inside_longer_names(session, old, new):
    session.prompt("fix it")
    assert "has not been loaded" in (denied(session.attempt(session.edit_event("app.py", old, new))) or "")


@pytest.mark.parametrize("old, new", [("# selct a row", "# choose one"), ('"Sytem error"', '"Error"'), ('"Delte file?"', '"Trash file?"'), ('"Total amout"', '"Total"'), ("# Fetch teh data", "# Fetch the data"), ("# see http://example.org", "# see https://example.org")])
def test_everyday_typo_fixes_stay_small(session, old, new):
    session.prompt("fix the typo")
    assert denied(session.attempt(session.edit_event("app.py", old, new))) is None


@pytest.mark.parametrize("name", ["alembic/versions/0007.py", "db/schema.rb", "app/models.py", "schema.py", "database.py", "app/settings.py", "cors.py", "iam.py", "sso.py", "pricing.py", "wallet.py", "subscription.py"])
def test_more_consequential_paths_are_not_small(session, name):
    session.prompt("fix it")
    assert "has not been loaded" in (denied(session.attempt(session.edit_event(name, "a = 1", "a = 2"))) or "")


@pytest.mark.parametrize("name", ["processor.py", "product.py", "lesson.py", "william.py"])
def test_a_name_that_only_contains_a_short_word_stays_small(session, name):
    session.prompt("fix it")
    assert denied(session.attempt(session.edit_event(name, "a = 1", "a = 2"))) is None


@pytest.mark.parametrize("words", [["perl", "-MTime::Piece", "-pi", "-e", "s/1/2/", "app.py"], ["perl", "-MStorable", "-pi", "-e", "x", "a"], ["perl", "-I/opt/site", "-pi", "-e", "x", "a"], ["ruby", "-rtime", "-i", "-pe", "x", "a"],
                                   ["ruby", "-rdate", "-pi", "-e", "x", "a"], ["perl", "-I", "lib", "-pi", "-e", "x", "a"], ["ruby", "-r", "json", "-i", "-pe", "x", "a"], ["swift", "format", "-i", "a.swift"], ["dart", "fix", "--apply"]])
def test_a_rewrite_behind_other_switches_is_still_not_a_check(words):
    assert not is_check(words)


@pytest.mark.parametrize("words", [["rustc", "--print", "sysroot"], ["rustc", "--explain", "E0382"], ["gcc", "--help=warnings"], ["java", "--list-modules"], ["ruby", "--copyright"], ["dart", "info"]])
def test_still_more_ways_of_asking_a_program_about_itself(words):
    assert not is_check(words)


@pytest.mark.parametrize("words", [["bundle", "exec", "rspec"], ["bundle", "exec", "ruby", "a.rb"]])
def test_running_through_bundler_is_a_check(words):
    assert is_check(words)


def test_bundle_install_is_not_a_check():
    assert not is_check(["bundle", "install"])


@pytest.mark.parametrize("command, edited", [("perl -0pi -e 's/1/2/' app.py", True), ("ruby -i -pe 'x' app.py", True), ("perl -Ilib t/basic.t", False), ("perl -MList::Util=sum -e 'print 1'", False)])
def test_what_counts_as_an_edit_agrees_with_what_counts_as_a_check(session, command, edited):
    session.prompt("Fix it")
    session.load()
    (session.project / "app.py").write_text("a = 1\n")
    session.bash(command)
    note = added(session.stop())
    assert ("No check has run" in note) is edited


def test_a_long_switch_cannot_use_up_the_hooks_time():
    """Every shell command reaches these patterns. The first took over 8 s on 28 zeros, and grew exponentially, against a limit of 10 s for the whole hook."""
    start = time.monotonic()
    assert not rewrites_in_place("perl", ["-" + "0" * 28 + "x", "script.pl"])
    assert rewrites_in_place("perl", ["-" + "0" * 20_000 + "i", "script.pl"])
    assert not rewrites_in_place("sed", ["-" + "i" * 60_000 + " ", "script.sed"])
    assert time.monotonic() - start < 2


def test_two_different_packages_are_each_reported(session):
    session.prompt("Fix it")
    session.load()
    (session.project / "app.py").write_text("a = 1\n")
    session.finish(session.edit_event("app.py", "a = 1", "a = 2"))
    session.bash("python3 app.py", output="ok")
    session.bash("pip install pytest-cov")
    first = added(session.stop("Done."))
    session.bash("pip install pytest-xdist")
    second = added(session.stop("Done."))
    assert "pytest-cov" in first and "pytest-xdist" in second


def test_a_passing_check_starts_the_send_back_count_again(session):
    session.prompt("Fix it")
    session.load()
    (session.project / "app.py").write_text("a = 1\n")
    sent = 0
    for _ in range(4):
        for _ in range(5):
            session.finish(session.edit_event("app.py", "a = 1", "a = 2"))
            sent += bool(added(session.stop(stop_hook_active=True)))
        session.bash("python3 app.py", output="ok")
    assert sent == 20, "a long run keeps its checks as long as it keeps passing some"


def test_a_long_run_mixing_edits_and_checks_in_one_command_hears_about_the_goal(session):
    session.prompt("Migrate everything")
    session.load()
    (session.project / "app.py").write_text("a = 1\n")
    notes = [added(session.bash("sed -i '' s/a/b/ app.py && python3 -m pytest -q", output="1 passed")) for _ in range(32)]
    assert sum("grown to" in note for note in notes) == 1


def test_a_huge_edit_never_reaches_the_slow_patterns(tmp_path):
    started = time.monotonic()
    assert not scale_notes.is_small("Edit", {}, str(tmp_path / "a.py"), ["a.py"], "", "open(" * 400_000, None, [])
    assert time.monotonic() - started < 1


@pytest.mark.parametrize("words, expected", [(["rake"], True), (["rake", "test"], True), (["rake", "-T"], False), (["rake", "--tasks"], False), (["rake", "--version"], False),
                                             (["rake", "-v"], True), (["bundle", "exec", "rake", "-T"], False), (["bundle", "exec", "ruby", "-v"], False), (["bundle", "exec", "ruby", "-pi", "-e", "x", "f"], False),
                                             (["node", "--help"], False), (["node", "-h"], False), (["bash", "--version"], False), (["sh", "--help"], False), (["python3", "-VV"], False),
                                             (["node", "a.js"], True), (["bash", "a.sh"], True), (["tsx", "a.ts"], True), (["racket", "a.rkt"], True), (["R", "-f", "a.R"], True)])
def test_what_runs_a_program_and_what_only_asks_about_it(words, expected):
    assert is_check(words) is expected


@pytest.mark.parametrize("word", ["permissions", "secret", "slow performance log", "add a dependency"])
def test_a_consequential_word_only_in_a_paste_does_not_hold_a_small_edit(session, word):
    session.prompt(f"fix the typo\n<pasted_content>{word}</pasted_content>")
    assert denied(session.attempt(session.edit_event("app.py", "helo", "hello"))) is None


@pytest.mark.parametrize("filler", [100, 4000, 9000])
def test_that_holds_however_long_the_paste_is(session, filler):
    session.prompt("fix the typo\n<pasted_content>secret permissions " + "x " * filler + "</pasted_content>")  # the word is kept and the closing tag cut, past 4,000 characters
    assert denied(session.attempt(session.edit_event("app.py", "helo", "hello"))) is None


def test_a_pasted_spec_still_earns_its_reference_note_once_the_skill_is_loaded(session):
    session.prompt("build this\n<pasted_content>the spec says authentication comes first</pasted_content>")
    session.load()
    assert "security" in added(session.attempt(session.edit_event("app.py", "a = 1", "a = 2")))


@pytest.mark.parametrize("source, command", [("hello.c", "cc hello.c -o /tmp/h && /tmp/h"), ("hello.c", "cc hello.c -o /tmp/h"), ("hello.rs", "rustc hello.rs -o /tmp/r"), ("Hello.java", "javac -d /tmp/out Hello.java"),
                                             ("hello.go", "go build -o /tmp/g hello.go"), ("hello.c", "cc hello.c -o hello && ./hello")])
def test_building_this_code_to_a_temp_folder_is_a_check_of_this_code(session, source, command):
    session.prompt("write it")
    session.do(session.write_event(source, "x\n"))
    session.bash(command, output="ok\n")
    assert "No check has run" not in added(session.stop("Built it and ran it."))


@pytest.mark.parametrize("command", ["python3 /tmp/other.py", "pytest /tmp/copy/tests", "cd /tmp/copy && pytest tests"])
def test_a_run_on_something_else_still_is_not(session, command):
    session.prompt("write it")
    (session.project / "tests").mkdir()
    session.do(session.write_event("hello.py", "print(1)\n"))
    session.bash(command, output="1 passed\n")
    assert "No check has run" in added(session.stop("Built it and ran it."))


def test_the_fix_real_agents_write_for_a_trivial_bug_is_small(session):
    """From paid runs of `trivial-fix`: a small helper plus the lines that call it. An earlier limit of 10 lines held all 3 runs."""
    (session.project / "report.py").write_text("def sku_line(sku, count):\n    return f\"{sku}: {count} items\"\n")
    session.prompt("The stock report prints `1 items` when a count is one. It should say `1 item`. Can you fix that?")
    old = "def sku_line(sku, count):\n    return f\"{sku}: {count} items\"\n\n\ndef total_line(rows):\n    total = sum(count for _, count in rows)\n    return f\"Total: {total} items across {len(rows)} SKUs\""
    new = "def plural(count, word):\n    return f\"{count} {word}\" if count == 1 else f\"{count} {word}s\"\n\n\ndef sku_line(sku, count):\n    return f\"{sku}: {plural(count, 'item')}\"\n\n\ndef total_line(rows):\n    total = sum(count for _, count in rows)\n    return f\"Total: {plural(total, 'item')} across {plural(len(rows), 'SKU')}\""
    assert denied(session.attempt(session.edit_event("report.py", old, new))) is None
