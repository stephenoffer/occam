"""Python facts reach the agent where it already is, only when the trap is present, and never hold anything."""

import time

import pytest

from python_notes_path import python_notes as notes
from test_occam_hook import Agent, added, decision

POSITIVE = {
    "taskgroup": "async with asyncio.TaskGroup() as group:\n    pass\n",
    "to-thread": "await asyncio.to_thread(work)\n",
    "create-task": "    asyncio.create_task(work())\n",
    "cancelled": "except asyncio.CancelledError:\n    log()\n",
    "submit": "executor.submit(work)\n",
    "subprocess": "subprocess.run(['ls'])\n",
    "requests-timeout": "requests.get(url)\n",
    "utcnow": "datetime.utcnow()\n",
    "get-event-loop": "asyncio.get_event_loop()\n",
    "pkg-resources": "import pkg_resources\n",
    "pydantic-v1": "from pydantic import BaseModel\n@validator('x')\n",
    "openai-v0": "openai.ChatCompletion.create()\n",
    "numpy-alias": "np.float(1)\n",
    "mock-patch": "@patch('lib.exists')\n",
    "tuple-assert": 'assert (1 == 2, "message")\n',
    "raises-exception": "with pytest.raises(Exception):\n",
    "tarfile": "import tarfile\narchive.extractall(path)\n",
    "template-injection": "jinja2.Environment().from_string(user)\n",
    "cache-method": "@lru_cache(maxsize=None)\ndef get(self, key):\n",
    "type-checking": "if TYPE_CHECKING:\n    from a import B\n",
    "chained-assign": 'df[mask]["b"] = 5\n',
    "merge-grain": "df.merge(other, on='k')\n",
    "groupby-nan": "df.groupby('k').sum()\n",
}
NEGATIVE = {
    "taskgroup": "group = make_group()\n# asyncio.TaskGroup in a comment\n",
    "to-thread": "await to_threads()\n",
    "create-task": "task = asyncio.create_task(work())\nawait asyncio.create_task(work())\n",
    "cancelled": "except ValueError:\n    log()\n",
    "submit": "form.submit()\n",
    "subprocess": "subprocess.run(['ls', str(path)], check=True, timeout=5)\n",
    "requests-timeout": "requests.get(url(x), timeout=5)\nclient.get(url)\n",
    "utcnow": "datetime.now(timezone.utc)\narrow.utcnow()\n",
    "get-event-loop": "asyncio.get_running_loop()\n",
    "pkg-resources": "import importlib.metadata\n",
    "pydantic-v1": "from pydantic_settings import BaseSettings\n@field_validator('x')\n@attr.validator\n",
    "openai-v0": "client.chat.completions.create()\n",
    "numpy-alias": "np.float64(1)\nnp.nan\n",
    "mock-patch": "client.patch('/users/1')\nmock.call_count\n",
    "tuple-assert": 'assert x == 1, "message"\nassert (x == 1)\nassert (result.loc[idx, "A"] == 0).all()\n',
    "raises-exception": "with pytest.raises(ValueError, match='x'):\n",
    "tarfile": "import tarfile\narchive.extractall(path=str(folder), filter='data')\n",
    "template-injection": "jinja2.Template('fixed {{ name }}')\nEnvironment().from_string('fixed')\n",
    "cache-method": "@lru_cache(maxsize=8)\ndef get(key):\n",
    "type-checking": "checking = TYPE_CHECKING\n",
    "chained-assign": 'settings["a"]["b"] = 5\nx = df[mask]["b"]\npdf_info["pages"][0] = page\ndf[mask]["b"] == 1\n',
    "merge-grain": "df.merge(other, on=key(x), validate='one_to_one')\n",
    "groupby-nan": "df.groupby(key(x), dropna=False).sum()\nitertools.groupby(rows)\n",
}
PLAIN = "def add(left, right):\n    return left + right\n"


def facts(text):
    return {key for key, _ in notes.edit_facts("a.py", False, text, lambda name, skill: name)}


@pytest.mark.parametrize("key, text", [
    ("subprocess", "subprocess.run(\n    ['ls', str(path)],\n    text=True,\n)\n"),
    ("requests-timeout", "requests.post(url(x), json=body(y))\n"),
    ("tuple-assert", 'assert (\n    x == 1,\n    "message",\n)\n'),
    ("chained-assign", 'df[df["a"] > 0]["b"] = 5\n'),
    ("pydantic-v1", "from pydantic import BaseModel, BaseSettings\n"),
    ("pydantic-v1", "@validator('x')\n"),
    ("template-injection", "jinja2.Template(user)\n"),
    ("mock-patch", "with mock.patch('lib.exists'):\n    pass\n"),
    ("cache-method", "@functools.cache\ndef get(self):\n"),
    ("submit", "self._executor.submit(work)\n"),
    ("submit", "self._pool.submit(work)\n"),
    ("submit", "threadpool.submit(work)\n"),
    ("mock-patch", "mocker.patch('a.b')\n"),
    ("utcnow", "dt.utcnow()\n"),
    ("get-event-loop", "loop = get_event_loop()\n"),
    ("template-injection", "from jinja2 import Template\nTemplate(user)\n"),
    ("pydantic-v1", "from pydantic import (\n    BaseModel,\n    BaseSettings,\n)\n"),
])
def test_common_ways_of_writing_a_trap_are_caught(key, text):
    assert f"python-{key}" in facts(text)


def test_a_fragment_that_needs_its_file_for_context_uses_the_file():
    fragment = "orders.merge(customers, on='id')\n"
    assert not notes.edit_facts("a.py", False, fragment, lambda name, skill: name, lambda: "import os\n")
    found = notes.edit_facts("a.py", False, fragment, lambda name, skill: name, lambda: "import pandas as pd\n")
    assert [key for key, _ in found] == ["python-merge-grain"]


def test_the_file_is_read_only_when_a_trap_needs_it():
    def not_needed():
        raise AssertionError("read the file with no candidate trap")
    assert notes.edit_facts("a.py", False, "x = 1\n", lambda name, skill: name, not_needed) == []


def test_text_past_the_scan_limit_is_not_examined():
    assert not facts("x = 1\n" * (notes.MAX_SCANNED_CHARS // 6 + 1) + "datetime.utcnow()\n")


@pytest.mark.parametrize("text", ["\n" * 200_000, " " * 200_000, "pool" * 50_000, "df[" * 66_000, "@cache " * 30_000,
                                  "subprocess.run(" * 13_000, "(" * 200_000, "assert (" * 25_000, "a" * 200_000])
def test_pathological_edits_stay_fast_and_never_raise(text):
    started = time.monotonic()
    facts(text)
    assert time.monotonic() - started < 3


@pytest.mark.parametrize("request_text, audit, split", [
    ("Audit this repo", True, False), ("Please audit the payment code", True, False), ("Add an audit log to the API", False, False),
    ("Audit logging is broken", False, False), ("Fix the audit trail", False, False), ("Fix the audit-log timestamp bug", False, False),
    ("Add an audit service", False, False), ("Perform a security audit of this repo", True, False), ("Audit app.py please", True, False),
    ("Split the file path on the slash", False, False), ("split this into two files", False, True), ("Break up utils.py", False, True),
    ("Split this module into two", False, True), ("Split this into two modules", False, True), ("Split utils.py into two modules", False, True),
    ("Please break up the pricing file", False, True), ("This file should be split", False, True), ("Split the CSV file by region", False, False),
    ("Split the string on commas", False, False), ("Fix the typo", False, False),
    ("Please break it up into sensible modules along its seams", False, True), ("Pull this apart into two modules", False, True),
    ("Break it up, please", False, False), ("Can you go through it and tell me what's actually wrong?", True, False),
    ("Look through the code for bugs", True, False), ("Go through the steps to reproduce", False, False),
])
def test_prompt_facts_match_what_the_request_is(request_text, audit, split):
    found = {key for key, _ in notes.prompt_facts(request_text, lambda name, skill: name)}
    assert ("python-audit" in found) == audit and ("python-split" in found) == split


def test_every_trap_has_a_positive_and_a_negative_case():
    keys = {key for key, *_ in notes.TRAPS} | {"tuple-assert"}
    assert keys == set(POSITIVE) == set(NEGATIVE)


@pytest.mark.parametrize("key", POSITIVE)
def test_the_trap_is_stated_when_it_is_in_the_code(key):
    assert f"python-{key}" in facts(POSITIVE[key])


@pytest.mark.parametrize("key", NEGATIVE)
def test_the_safe_form_gets_no_note_about_that_trap(key):
    assert f"python-{key}" not in facts(NEGATIVE[key])


def test_ordinary_code_gets_no_facts():
    assert facts(PLAIN) == set()


@pytest.mark.parametrize("key, text", [("template-injection", "Money.from_string(user)\n"), ("template-injection", "from string import Template\nTemplate(user)\n"),
                                       ("pydantic-v1", "from pydantic import BaseModel\nfrom pydantic_settings import BaseSettings\n"), ("template-injection", 'import jinja2\nenv.from_string(\n    "fixed"\n)\n'),
                                       ("merge-grain", "session.merge(obj)\n"),
                                       ("groupby-nan", "query.groupby(key)\n")])
def test_the_same_method_name_outside_that_library_gets_no_note(key, text):
    assert f"python-{key}" not in facts(text)


@pytest.mark.parametrize("key, _pattern, _unless, _also, fact", notes.TRAPS, ids=[row[0] for row in notes.TRAPS])
def test_each_fact_stays_short(key, _pattern, _unless, _also, fact):
    assert len(fact.split()) <= 45, key


@pytest.fixture
def agent(tmp_path):
    return Agent(tmp_path)


def try_write(agent, text, name="app.py"):
    return agent.send("pre-tool", tool_name="Edit", tool_input={"file_path": agent.path(name), "new_string": text})


def test_a_one_line_edit_on_ordinary_code_adds_only_the_language_mention(agent):
    agent.prompt("Fix the typo")
    agent.load()
    first = added(try_write(agent, PLAIN))
    assert first.startswith("occam has guidance for Python") and "/occam-python/SKILL.md," in first and len(first.split()) <= 30, first
    assert len(added(try_write(agent, PLAIN, "b.py")).split()) == 0, "nothing further on later ordinary edits"


def test_a_trap_is_stated_before_the_edit_once_per_session_and_nothing_is_held(agent):
    agent.prompt("Fix it")
    agent.load()
    try_write(agent, PLAIN)
    first = try_write(agent, "subprocess.run(['ls'])\n")
    assert decision(first) is None and "check=True" in added(first)
    assert "check=True" not in added(try_write(agent, "subprocess.run(['ls'])\n"))


def test_facts_are_capped_per_edit_and_the_rest_come_later(agent):
    agent.prompt("Fix it")
    agent.load()
    try_write(agent, PLAIN)
    text = "".join(POSITIVE[key] for key in ("taskgroup", "to-thread", "submit", "subprocess", "requests-timeout"))
    phrases = ("ExceptionGroup", "the wait", "`.result()`", "check=True", "hang forever")
    first = added(try_write(agent, text))
    second = added(try_write(agent, text))
    assert sum(phrase in first for phrase in phrases) == 3
    assert sum(phrase in second for phrase in phrases) == 2
    assert all((phrase in first) != (phrase in second) for phrase in phrases), "each stated exactly once"


def test_facts_apply_only_to_python_files(agent):
    agent.prompt("Fix it")
    agent.load()
    assert "check=True" not in added(try_write(agent, "subprocess.run(['ls'])\n", "a.go"))


def test_a_notebook_cell_states_the_fresh_kernel_fact(agent):
    agent.prompt("Fix the cell")
    agent.load()
    output = agent.send("pre-tool", tool_name="NotebookEdit", tool_input={"notebook_path": agent.path("n.ipynb"), "new_source": "x = 1"})
    assert "fresh kernel" in added(output)


def test_a_test_edit_states_how_suites_stay_green(agent):
    agent.prompt("Fix it")
    agent.load()
    assert "--collect-only" in added(try_write(agent, PLAIN, "tests/test_a.py"))


@pytest.mark.parametrize("request_text", ["Split this module into two", "Please break up the pricing file", "This file should be split"])
def test_a_python_split_request_states_what_breaks(agent, request_text):
    (agent.project / "pyproject.toml").write_text("")
    assert "say what stayed and why" in added(agent.prompt(request_text))


@pytest.mark.parametrize("request_text", ["Split the string on commas", "Fix the typo"])
def test_other_requests_get_no_split_fact(agent, request_text):
    (agent.project / "pyproject.toml").write_text("")
    assert "say what stayed and why" not in added(agent.prompt(request_text))


def test_a_split_request_outside_python_gets_no_python_fact(agent):
    assert "say what stayed and why" not in added(agent.prompt("Split this module into two"))


def test_a_python_audit_request_states_what_to_look_for_once_per_session(agent):
    (agent.project / "pyproject.toml").write_text("")
    assert "asserting only on a mock" in added(agent.prompt("Audit this repo"))
    assert "asserting only on a mock" not in added(agent.prompt("Now audit the tests too"))


def test_fixing_a_trap_with_multi_edit_is_not_told_about_that_trap(agent):
    agent.prompt("Fix it")
    agent.load()
    try_write(agent, PLAIN)
    edits = [{"old_string": "requests.get(url)", "new_string": "requests.get(url, timeout=5)"}]
    output = agent.send("pre-tool", tool_name="MultiEdit", tool_input={"file_path": agent.path("app.py"), "edits": edits})
    assert "hang forever" not in added(output)


@pytest.mark.parametrize("edits", ["not a list", [1, None, "x"], [[[["deep"]]]], None])
def test_a_malformed_multi_edit_is_ignored_and_does_not_raise(agent, edits):
    agent.prompt("Fix it")
    agent.load()
    agent.send("pre-tool", tool_name="MultiEdit", tool_input={"file_path": agent.path("app.py"), "edits": edits})


def test_multi_edit_text_is_examined(agent):
    agent.prompt("Fix it")
    agent.load()
    try_write(agent, PLAIN)
    output = agent.send("pre-tool", tool_name="MultiEdit", tool_input={"file_path": agent.path("app.py"), "edits": [{"old_string": "a", "new_string": "subprocess.run(['ls'])\n"}]})
    assert "check=True" in added(output)


def test_an_edit_fragment_gets_context_from_its_file(agent):
    (agent.project / "report.py").write_text("import pandas as pd\n")
    agent.prompt("Fix it")
    agent.load()
    try_write(agent, PLAIN)
    assert "validate=" in added(try_write(agent, "orders.merge(customers, on='id')\n", "report.py"))


def test_deeply_nested_tool_output_does_not_raise(agent):
    nested = "FAILED t.py::x\n"
    for _ in range(600):
        nested = [nested]
    agent.prompt("Fix it")
    agent.load()
    agent.edit()
    agent.send("post-tool", tool_name="Bash", tool_input={"command": "pytest | tail -1"}, tool_response=nested)


@pytest.mark.parametrize("command, phrase", [
    ("cat > pkg/calendar.py <<'EOF'\nx = 1\nEOF", "standard library"),
    ("cat > app.py <<'EOF'\nsubprocess.run(['ls'])\nEOF", "check=True"),
    ("python3 - <<'E'\nsrc = 'subprocess.run([1])'\nopen('app.py', 'w').write(src)\nE", "check=True"),
    ("python3 -I - <<'E'\nimport json\nnb = json.load(open('notebooks/q3.ipynb'))\nE", "fresh kernel"),
    ("cat > tests/test_a.py <<'EOF'\nx = 1\nEOF", "--collect-only"),
    ("echo 'requests.get(url)' >> app.py", "hang forever"),
])
def test_code_written_through_the_shell_gets_the_same_facts(agent, command, phrase):
    agent.prompt("Fix it")
    agent.load()
    output = agent.try_bash(command)
    assert decision(output) is None and phrase in added(output)


@pytest.mark.parametrize("command", ["ls -la", "pytest -q", "grep -n 'subprocess.run(' app.py", "cat app.py", "git status",
                                     "echo hello > notes.txt", "python3 -c 'print(1)'", "cat > existing.md <<'EOF'\nsubprocess.run(x)\nEOF"])
def test_ordinary_shell_commands_add_nothing(agent, command):
    agent.prompt("Fix it")
    agent.load()
    assert not added(agent.try_bash(command))


def test_shell_facts_share_the_once_per_session_limit_with_edits(agent):
    agent.prompt("Fix it")
    agent.load()
    try_write(agent, PLAIN)
    assert "check=True" in added(try_write(agent, "subprocess.run(['ls'])\n"))
    assert "check=True" not in added(agent.try_bash("cat > b.py <<'EOF'\nsubprocess.run(['ls'])\nEOF"))


def test_a_subagent_shell_command_gets_no_facts(agent):
    agent.prompt("Fix it")
    agent.load()
    output = agent.try_bash("cat > app.py <<'EOF'\nsubprocess.run(['ls'])\nEOF", agent_id="a1")
    assert "check=True" not in added(output)


def test_a_mention_of_someone_elses_notebook_gets_no_notebook_fact(agent):
    (agent.project / "pyproject.toml").write_text("")
    assert "fresh kernel" not in added(agent.prompt("The ops team wants a calendar they can pull up in their notebook"))


def test_a_python_request_about_a_notebook_states_the_fresh_kernel_fact_once(agent):
    (agent.project / "pyproject.toml").write_text("")
    assert "fresh kernel" in added(agent.prompt("The number in notebooks/q3.ipynb is off"))
    agent.load()
    output = agent.send("pre-tool", tool_name="NotebookEdit", tool_input={"notebook_path": agent.path("n.ipynb"), "new_source": "x = 1"})
    assert "fresh kernel" not in added(output), "already said at the prompt"


def test_a_very_large_edit_is_bounded(agent):
    agent.prompt("Fix it")
    agent.load()
    assert decision(try_write(agent, "x = 1\n" * 200_000)) is None
