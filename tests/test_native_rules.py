"""Team native: the Ruby, PHP, C, C++ and Rust checks warn without sending an agent back, and stay fast on hostile input."""

from __future__ import annotations

import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "plugin" / "skills" / "occam" / "scripts"))
sys.path.insert(0, str(ROOT / "plugin" / "hooks"))

from occam_tools import scan  # noqa: E402
from rule_cases_native import NATIVE_CASES, UNTRUSTED_ON_THE_LINE  # noqa: E402
from scan_notes import _is_serious  # noqa: E402


@pytest.mark.parametrize("rule, path, positive, negative", NATIVE_CASES, ids=[f"{case[0]}-{index}" for index, case in enumerate(NATIVE_CASES)])
def test_a_native_lead_sends_no_one_back_unless_the_request_reaches_the_sink(rule, path, positive, negative):
    found = [finding for finding in scan.scan_text(path, positive) if finding["rule"] == rule]
    assert found
    serious = [finding for finding in found if _is_serious({**finding, "path": path})]
    assert bool(serious) == ((rule, path) in UNTRUSTED_ON_THE_LINE), serious


def test_interpolating_something_other_than_params_is_a_medium_confidence_lead():
    finding = [f for f in scan.scan_text("app/models/a.rb", "class A < ApplicationRecord\n  def self.f(x)\n    where(\"a = #{x}\")\n  end\nend\n") if f["rule"] == "sql-injection"]
    assert [f["confidence"] for f in finding] == ["medium"]


def test_tests_and_migrations_are_left_alone():
    sql = "class AddIndex < ActiveRecord::Migration[7.1]\n  def up\n    execute \"CREATE INDEX idx ON #{table} (email)\"\n  end\nend\n"
    assert not [f for f in scan.scan_text("db/migrate/20240101_add_index.rb", sql) if f["rule"] == "sql-injection"]
    copy = "int f(const uint8_t *p, char *out) {\n    size_t n = p[0] << 8 | p[1];\n    memcpy(out, p + 2, n);\n    return 0;\n}\n"
    assert [f for f in scan.scan_text("src/a.c", copy) if f["rule"] == "unchecked-bound"]
    assert not [f for f in scan.scan_text("tests/a_test.c", copy) if f["rule"] == "unchecked-bound"]


def test_a_heredoc_reading_params_lines_below_the_sink_is_a_medium_confidence_lead():
    """rv3: Stop sends the agent back only when params is read on the sink's own line."""
    text = "class Report < ApplicationRecord\n  def self.for(params)\n    connection.select_all(<<~SQL)\n      SELECT *\n      FROM reports\n      WHERE owner = '#{params[:owner]}'\n    SQL\n  end\nend\n"
    assert [f["confidence"] for f in scan.scan_text("app/models/report.rb", text) if f["rule"] == "sql-injection"] == ["medium"]


def test_a_module_that_breaks_loses_only_its_own_findings(monkeypatch):
    from occam_tools import rules_native

    def broken(*args, **kwargs):
        raise TypeError("odd code")
    monkeypatch.setattr(rules_native, "findings", broken)
    found = {f["rule"] for f in scan.scan_text("src/a.c", "void f(char *c) {\n    system(c);\n    strcpy(d, c);\n}\n")}
    assert {"shell-injection", "unsafe-c-string"} <= found


# rv3: inputs that each made one check quadratic, at a size real files never reach.
REVIEW_HOSTILE = [
    ("rust macros left open", "src/lib.rs", "a!{\n" * 10_000),
    ("rust writes", "src/lib.rs", "fn main() {\n" + "    fs::write(p, x);\n" * 10_000 + "}\n"),
    ("cpp structs", "src/a.cpp", "".join(f"struct S{i} {{ int *p; }};\n" for i in range(10_000))),
    ("cpp indexes", "src/a.cpp", "void f(Message *msg) {\n" + "  if (a) { b; }\n" * 1000 + "  buf[msg->i] = 1;\n" * 10_000 + "}\n"),
    ("c macro heads", "src/a.c", "X(a) {\n" * 10_000 + "}\n" * 10_000),
    ("ruby methods", "app/controllers/a_controller.rb", "class A\n" + "".join(f"  def m{i}\n    send_file params[:f]\n  end\n" for i in range(10_000)) + "end\n"),
    ("ruby sql", "app/models/a.rb", "class A < ApplicationRecord\n" + "".join(f"  def m{i}\n    where(\"a = #{{x}}\")\n  end\n" for i in range(10_000)) + "end\n"),
]


@pytest.mark.parametrize("name, path, text", REVIEW_HOSTILE, ids=[case[0] for case in REVIEW_HOSTILE])
def test_review_hostile_input_stays_fast(name, path, text):
    started = time.monotonic()
    scan.scan_text(path, text)
    assert time.monotonic() - started < 10, f"{name} took too long"


HOSTILE = [
    ("long line", "x" * 300_000 + "\n"),
    ("unclosed brackets", "f(" * 100_000 + "\n"),
    ("unclosed braces", "void f() {" * 30_000 + "\n"),
    ("unclosed quotes", "where(\"#{" * 30_000 + "\n"),
    ("repeated sinks", "memcpy(a, b, n);\n" * 20_000),
    ("repeated defs", "def a\n" * 40_000),
    ("dotted chain", "a." * 150_000 + "update!\n"),
    ("casts", "*(uint32_t*)(" * 30_000 + "\n"),
    ("blade", "{!! " * 75_000 + "\n"),
    ("permit", ".permit(" * 40_000 + "\n"),
    ("switches", "switch (x) { default: __builtin_unreachable(); }\n" * 6_000),
    ("classes", "class A { ~A() { delete p; } int* p;\n" * 8_000),
]


@pytest.mark.parametrize("name, text", HOSTILE, ids=[case[0] for case in HOSTILE])
@pytest.mark.parametrize("path", ["app/a.rb", "app/a.php", "a.blade.php", "src/a.c", "src/a.cpp", "src/a.rs"])
def test_hostile_input_stays_fast(path, name, text):
    started = time.monotonic()
    scan.scan_text(path, "// short first line\n" + text)
    assert time.monotonic() - started < 20, f"{name} took too long on {path}"
