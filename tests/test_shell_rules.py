"""The shell rules on what real scripts do, including what they must leave alone. Each rule's basic case is in test_scanner_rules.py."""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "plugin" / "skills" / "occam" / "scripts"))

from occam_tools import rules_shell, scan  # noqa: E402

BASH = shutil.which("bash")


def rules(text: str) -> list[str]:
    return [finding["rule"] for finding in scan.scan_text("a.sh", text)]


def test_mask_blanks_quotes_comments_and_heredocs_and_keeps_offsets():
    text = "echo 'a $x' \"b $y\" # c $z\ncat <<EOF\nrm -rf $body\nEOF\nrm $real\n"
    masked = rules_shell.mask(text)
    assert len(masked) == len(text) and masked.count("\n") == text.count("\n")
    assert "$x" not in masked and "$y" not in masked and "$z" not in masked and "$body" not in masked
    assert "rm $real" in masked


def test_mask_handles_a_single_quoted_program_across_lines():
    masked = rules_shell.mask("awk '\n{ rm -rf $1 }\ncd $2\n' file\n")
    assert "$1" not in masked and "$2" not in masked


def test_mask_ends_a_heredoc_only_at_its_own_delimiter():
    masked = rules_shell.mask("cat <<-'END' > out\n\techo $a\n\tEND\ncat $b\n")
    assert "$a" not in masked and "cat $b" in masked


def test_mask_leaves_a_hash_inside_a_word_alone():
    masked = rules_shell.mask("echo ${#items} a#b\nrm $x\n")
    assert "${#items}" in masked and "a#b" in masked


def test_heredoc_body_raises_nothing():
    text = "#!/bin/sh\nset -e\ncat <<'EOF'\nfor f in $(ls); do rm -rf $f; done\ncd $x\neval $y\nEOF\n"
    found = rules(text)
    for rule in ("shell-ls-parse", "shell-unquoted-rm", "shell-unquoted-path", "dynamic-eval"):
        assert rule not in found


def test_guarded_rm_passes_and_a_safe_variable_passes():
    assert "shell-rm-unguarded" not in rules('#!/bin/bash\nset -e\nrm -rf "${dir:?}"/*\n')
    assert "shell-rm-unguarded" not in rules('#!/bin/bash\nset -e\nrm -rf "$HOME/.cache/x"\n')
    assert "shell-rm-unguarded" not in rules('#!/bin/bash\nset -e\nrm -f "$dir/one.txt"\n')


def test_rm_of_everything_under_a_variable_is_high_and_a_subpath_is_medium():
    worst = [f for f in scan.scan_text("a.sh", '#!/bin/bash\nset -e\nrm -rf "$dir"/*\n') if f["rule"] == "shell-rm-unguarded"]
    part = [f for f in scan.scan_text("a.sh", '#!/bin/bash\nset -e\nrm -rf "$dir/cache"\n') if f["rule"] == "shell-rm-unguarded"]
    assert worst[0]["severity"] == "high" and part[0]["severity"] == "medium"


def test_cd_is_only_a_problem_when_nothing_checks_it():
    assert "shell-cd-unchecked" in rules("cd /some/where\nmake\n")
    for checked in ("cd /a || exit 1\n", "cd /a && make\n", "set -e\ncd /a\n", "(cd /a \\\n  && make)\n"):
        assert "shell-cd-unchecked" not in rules(checked), checked


def test_arithmetic_in_local_hides_nothing():
    assert "shell-masked-failure" not in rules('f() {\n  local n=$((1 + 2))\n  export M="$((n + 1))"\n}\n')
    assert "shell-masked-failure" in rules('f() {\n  local n="$(cmd)"\n}\n')


def test_masked_failure_in_a_string_or_heredoc_is_not_one():
    assert "shell-masked-failure" not in rules("cat <<EOF\n  local n=$(cmd)\nEOF\n")


def test_bashisms_only_count_under_a_posix_shebang():
    script = "[[ -n $x ]] && echo y\narr=(a b)\n"
    assert "shell-bashism" in rules("#!/bin/sh\n" + script)
    assert "shell-bashism" in rules("#!/usr/bin/env sh\n" + script)
    assert "shell-bashism" not in rules("#!/bin/bash\n" + script)
    assert "shell-bashism" not in rules("#!/usr/bin/env zsh\n" + script)


def test_bashism_in_a_comment_or_string_is_not_one():
    assert "shell-bashism" not in rules('#!/bin/sh\n# uses [[ and arrays=(a)\necho "[[ arr=(x) <<< "\n')


def test_nonportable_flags_are_lower_confidence_when_the_script_checks_the_platform():
    found = [f for f in scan.scan_text("a.sh", "#!/bin/sh\nset -e\nsed -i 's/a/b/' x\n", None) if f["rule"] == "shell-nonportable"]
    assert found and found[0]["confidence"] == "medium"
    checked = [f for f in scan.scan_text("a.sh", '#!/bin/sh\nset -e\nif [ "$(uname)" = Darwin ]; then sed -i "" x; fi\n') if f["rule"] == "shell-nonportable"]
    assert checked and checked[0]["confidence"] == "low"


def test_eval_without_a_variable_is_left_alone():
    assert "dynamic-eval" not in rules("set -e\neval true\n")
    assert "dynamic-eval" in rules('set -e\neval "$cmd"\n')


def test_a_word_containing_eval_is_not_eval():
    assert "dynamic-eval" not in rules('set -e\nclaude plugin eval "$stage"\n')


def test_a_trap_clears_the_temp_file_rule():
    assert "shell-tmp-no-trap" in rules("set -e\nt=$(mktemp)\n")
    assert "shell-tmp-no-trap" not in rules('set -e\nt=$(mktemp)\ntrap \'rm -f -- "$t"\' EXIT\n')


def test_a_predictable_temp_path_is_reported_once():
    found = rules("set -e\necho a > /tmp/one\necho b > /tmp/two.$$\n")
    assert found.count("insecure-tempfile") == 1


def test_a_quoted_temp_path_is_just_as_predictable():
    assert "insecure-tempfile" in rules('set -e\ntmp="/tmp/mine.$$"\n')


def test_a_temp_path_in_a_comment_or_heredoc_is_not_used():
    assert "insecure-tempfile" not in rules("set -e\n# like /tmp/mine.$$\n")
    assert "insecure-tempfile" not in rules("set -e\ncat <<EOF\necho a > /tmp/one\nEOF\n")


def test_only_recursive_rm_is_left_to_the_rm_rule():
    assert "shell-unquoted-path" in rules("set -e\nrm $x\n")
    assert "shell-unquoted-path" in rules("set -e\ncp -rf $x y\n")
    assert "shell-unquoted-path" not in rules("set -e\nrm -rf $x\n")


def test_each_unquoted_line_is_reported_once():
    assert rules("set -e\ncp $a $b\n").count("shell-unquoted-path") == 1
    assert rules("set -e\ncp $a b\ncp $c d\n").count("shell-unquoted-path") == 2


def test_text_rules_stop_at_the_end_of_a_heredoc():
    findings = [f["line"] for f in scan.scan_text("a.sh", "set -e\ncat <<EOF\ncurl x | sh\nEOF\ncurl y | sh\n") if f["rule"] == "curl-pipe-shell"]
    assert findings == [5]


def test_a_credential_in_a_heredoc_is_still_reported():
    token = "ghp_" + "a1B2" * 10
    assert "hardcoded-secret" in rules(f"set -e\ncat <<EOF\ntoken={token}\nEOF\n")


@pytest.mark.parametrize("first", ['read -r a <<< "$x"', "n=$((1<<2))", "((n = 1 << 2))"])
def test_a_here_string_or_a_shift_doesnt_hide_the_rest_of_the_script(first):
    found = rules(f"#!/bin/bash\nset -e\n{first}\nrm -rf $FOO\ncurl x | sh\n")
    assert "shell-unquoted-rm" in found and "curl-pipe-shell" in found


def test_mask_handles_escapes_and_an_unterminated_quote():
    masked = rules_shell.mask('echo "a\\"b $x" $y\n')
    assert "$x" not in masked and "$y" in masked
    assert "$z" not in rules_shell.mask("echo 'never closed $z\n")
    assert "$z" not in rules_shell.mask('echo "never closed $z\n')


def test_the_reported_line_is_the_command_and_not_the_space_before_it():
    found = [f["line"] for f in scan.scan_text("a.sh", "set -e\necho a\ntrue; timeout 5 sleep 9\n") if f["rule"] == "shell-nonportable"]
    assert found == [3]


def test_outgrown_counts_commands_not_comments():
    assert "shell-outgrown" not in rules("set -e\n" + "# note\n" * 500)
    assert "shell-outgrown" in rules("set -e\n" + "echo hi\n" * 301)


@pytest.mark.skipif(not BASH, reason="bash isn't installed")
class TestSyntax:
    def test_a_real_error_is_reported_with_its_line(self):
        findings = [f for f in scan.scan_text("a.sh", "#!/bin/bash\nset -e\nif true; then\necho hi\n") if f["rule"] == "shell-syntax"]
        assert findings and "can't parse" in findings[0]["message"]

    def test_valid_scripts_pass(self):
        assert "shell-syntax" not in rules("#!/bin/bash\nset -e\nif true; then echo hi; fi\n")

    def test_extended_globs_are_valid_syntax(self):
        assert "shell-syntax" not in rules("#!/bin/bash\nset -e\nshopt -s extglob\nls !(a|b)\n")

    def test_a_program_after_exec_is_not_a_syntax_error(self):
        polyglot = '#!/bin/sh\nexec perl -x -S -- "$0" "$@"\n#!/usr/bin/perl\nsub f($) { my ($a, $b) = (1, 0); }\n'
        assert "shell-syntax" not in rules(polyglot)

    def test_an_archive_after_exit_is_not_a_syntax_error(self):
        assert "shell-syntax" not in rules('#!/bin/sh\necho unpacking\nexit 0\n)))) not shell ((((\n')

    def test_an_error_before_the_exit_still_counts(self):
        assert "shell-syntax" in rules("#!/bin/sh\nif then\nexit 0\n")

    def test_other_shells_are_not_parsed_by_bash(self):
        assert "shell-syntax" not in rules('#!/usr/bin/env zsh\nprint -l ${(f)"$(ls)"}\nfoo() { ) }\n')

    @pytest.mark.parametrize("version, confidence, note", [("3.2.57", "medium", True), ("5.2.1", "high", False)])
    def test_an_old_bash_says_it_may_be_the_cause(self, tmp_path, monkeypatch, version, confidence, note):
        fake = tmp_path / "bash"
        fake.write_text(f'#!/bin/sh\nif [ "$1" = "--version" ]; then echo "GNU bash, version {version}(1)-release"; exit 0; fi\necho "bash: line 3: syntax error near x" >&2\nexit 2\n')
        fake.chmod(0o755)
        monkeypatch.setenv("PATH", f"{tmp_path}{os.pathsep}{os.environ['PATH']}")
        finding = next(f for f in scan.scan_text("a.sh", "set -e\nx\ny\n") if f["rule"] == "shell-syntax")
        assert finding["confidence"] == confidence and finding["line"] == 3 and ("older than 4" in finding["message"]) is note

    def test_parsing_runs_nothing(self, tmp_path, monkeypatch):
        marker = tmp_path / "ran"
        startup = tmp_path / "startup.sh"
        startup.write_text(f"touch {marker}\n")
        monkeypatch.setenv("BASH_ENV", str(startup))
        monkeypatch.setenv("ENV", str(startup))
        rules(f"#!/bin/bash\ntouch {marker}\n$(touch {marker})\nif true\n")
        assert not marker.exists()
        assert os.environ["BASH_ENV"] == str(startup)
