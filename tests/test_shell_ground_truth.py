"""Is the hook's reading of a command what bash really does? Every program here is a stub that logs itself, in a scratch folder.

This compares against real bash, so a reading can't pass by agreeing with the code that wrote it. The one direction that matters is
a program bash really ran and the hook didn't see. The other direction exists too and is allowed: `true || pytest` reads as pytest.
"""

import json
import random
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "plugin" / "hooks"))
sys.path.insert(0, str(ROOT / "plugin" / "skills" / "occam" / "scripts"))

from occam_commands import head, run_by  # noqa: E402
from shell_reading import parse_shell  # noqa: E402

BASH = shutil.which("bash")
SAMPLE = 600
SEGS = [
 'echo hi', 'echo "a b"', "echo 'a b'", 'echo it\\\'s', 'echo "it\'s"', "echo 'say \"hi\"'", 'echo "say \\"hi\\""', 'echo "say \\"hi\\" "',
 'echo "a\\" "', "echo $'it\\'s'", "echo $'\\''", 'echo \\"', "echo \\'", 'echo "x\ny"', "echo 'x\ny'", 'echo a\\\nb', 'git commit -m "first\nsecond"',
 'git commit --message="first; rm -rf /Users/x/project"', 'git commit --message="a && pytest -q"', 'X="a b" true', "X='a; rm -rf /Users/x/project' true",
 'echo foo"bar; rm -rf /Users/x/project"', "echo foo'bar; pytest -q'", 'echo "rm -rf /Users/x/project"', "echo 'rm -rf /Users/x/project; pytest -q'",
 'echo "a; rm -rf /Users/x/project\nb"', "echo 'a\nrm -rf /Users/x/project\nb'", 'echo "c\\"d; rm -rf /Users/x/project"', 'echo "(c\\"); rm -rf /Users/x/project"',
 '# comment', "# don't", '# a; rm -rf /Users/x/project', 'echo a # b', "echo a # don't", 'echo a#b', "echo a#don\\'t", 'true #', '(true)# x', "(true)# don't", 'echo ${X:-a #b}', 'echo $#', 'echo ${#X}',
 'cat <<E\nit\'s\nE', "cat <<'E'\nrm -rf /Users/x/project\nE", 'cat <<\\E\nit\'s\nE', 'cat <<E-1\nit\'s\nE-1', "cat <<'E-1'\nit's\nE-1", 'cat <<E | cat\nbody\nE', 'cat <<< "a\nb"', "cat <<< 'rm -rf /Users/x/project'",
 'true \\\n  && true', 'echo a\\\n#b', 'echo "$(true)"', 'echo `true`', 'echo $(echo a)', 'echo "$(echo "a b")"', '[ $# -eq 0 ]', 'case a in a) true;; esac', 'for i in 1; do true; done', 'if true; then true; fi', '{ true; }', '(true)', 'true &', 'true |& true',
 'bash -c "true"', "bash -c 'true\ntrue'", 'eval true', 'eval "true"',
]
TARGETS = ['rm -rf /Users/x/project', 'pytest -q', '"rm" -rf /Users/x/project', 'command rm -rf /Users/x/project', 'bash -c "rm -rf /Users/x/project"', "bash -c 'pytest -q'", 'X="a b" rm -rf /Users/x/project', 'X="a b" pytest -q', 'X=1 pytest -q', 'py\\\ntest -q', 'r\\\nm -rf /Users/x/project', '\\rm -rf /Users/x/project', 'eval "rm -rf /Users/x/project"', 'echo "$(rm -rf /Users/x/project)"', 'echo `rm -rf /Users/x/project`', 'echo $(pytest -q)', '(rm -rf /Users/x/project)', '{ pytest -q; }', 'if true; then pytest -q; fi', 'true && pytest -q', 'for i in 1; do rm -rf /Users/x/project; done']
SEPS = ['; ', ' && ', '\n', ' | ', ' || ']


def corpus() -> list[str]:
    rng = random.Random(7)
    found = set()
    for _ in range(SAMPLE):
        first, second, target = rng.choice(SEGS), rng.choice(SEGS), rng.choice(TARGETS)
        one, two = rng.choice(SEPS), rng.choice(SEPS)
        found.add(rng.choice([first + one + target, target + one + first, first + one + target + two + second, target + one + first + two + second]))
    return sorted(found)


@pytest.mark.skipif(not BASH, reason="needs bash")
def test_no_program_bash_really_runs_is_hidden_from_the_hook(tmp_path):
    stubs = tmp_path / "stubs"
    stubs.mkdir()
    log = tmp_path / "log"
    for program in "rm pytest git cat ls sed tail python3 sleep true".split():
        (stubs / program).write_text('#!' + BASH + '\necho "%s" >> "$LOG"\n' % program)
        (stubs / program).chmod(0o755)
    (stubs / "bash").symlink_to(BASH)
    hidden, tried = [], 0
    for command in corpus():
        env = {"PATH": str(stubs), "LOG": str(log), "HOME": str(tmp_path)}
        if subprocess.run([BASH, "-n", "-c", command], capture_output=True, env=env, cwd=tmp_path).returncode:
            continue
        log.unlink(missing_ok=True)
        try:
            subprocess.run([BASH, "-c", command], capture_output=True, env=env, cwd=tmp_path, timeout=5, stdin=subprocess.DEVNULL)
        except subprocess.TimeoutExpired:
            continue
        tried += 1
        ran = log.read_text().split() if log.exists() else []
        seen = {name for words in parse_shell(command)[0] for name in (head(words)[0], run_by(words)[0])}
        hidden += [json.dumps([program, command]) for program in ("rm", "pytest") if program in ran and program not in seen]
    assert tried > SAMPLE / 2, "the corpus should mostly be valid shell"
    assert not hidden, "bash ran these and the hook didn't see them:\n" + "\n".join(hidden[:20])
