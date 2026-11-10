"""The Java, Kotlin and Go checks in rules_go.py and rules_jvm.py: none sends an agent back at Stop, each stays fast on input built to
be slow, and the Go gate note for unsafe code. Their cases fire and stay quiet through test_scanner_rules.py. Team jvmgo."""

from __future__ import annotations

import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "plugin" / "skills" / "occam" / "scripts"))
sys.path.insert(0, str(ROOT / "plugin" / "hooks"))

from occam_tools import rules_go, rules_jvm, scan  # noqa: E402
from occam_tools.source import load  # noqa: E402
from rule_cases_jvmgo import JVMGO_CASES  # noqa: E402
from scan_notes import _is_serious  # noqa: E402
from test_change_checks import notes_on, repository, write  # noqa: E402

@pytest.mark.parametrize("rule, path, positive, negative", JVMGO_CASES, ids=[f"{case[0]}-{index}" for index, case in enumerate(JVMGO_CASES)])
def test_nothing_added_sends_an_agent_back(rule, path, positive, negative):
    found = [finding for finding in scan.scan_text(path, positive) if finding["rule"] == rule]
    assert found
    serious = [finding for finding in found if _is_serious({**finding, "path": path})]
    assert not serious, f"{rule} would send the agent back: {serious}"


N = 300_000
GO = {
    "query calls in one function": "func f() {\n" + "\tq := \"SELECT a FROM t WHERE x = \" + v\n\tdb.Query(q)\n" * 6000 + "}\n",
    "query calls left open": "func f() {\n" + "db.Query(fmt.Sprintf(\"SELECT %s\", " * 8000,
    "sh -c repeated": "func f() {\n" + 'exec.Command("sh", "-c", ' * 12000,
    "function heads left open": "func f(a int) (int, error) {\n" * 15000,
    "function heads nested": "func f(a interface{}) map[string]interface{} {\n" * 5000 + "}\n" * 5000,
    "retry loops nested": "func f() {\n" + "for attempt := 0; attempt < max; attempt++ {\ntime.Sleep(1)\nclient.CreateX(ctx)\n" * 8000 + "}\n" * 8000 + "}\n",
    "error branches": "func f() {\nreturn handler(ctx, req)\ncodes.PermissionDenied\n" + "ok, err := a.Check(x)\nif err != nil {\nlog()\n}\n" * 8000 + "}\n",
    "field changes": "func f() {\n" + "c.N--\ndb.Exec(\"UPDATE t SET n = $1\", c.N)\n" * 8000 + "}\n",
    "checkpoints": "func f() {\n" + "s.kv.Set(ctx, cursorKey, 1)\ns.crm.CreateX(ctx)\n" * 8000 + "}\n",
    "package maps": "var m = map[string]int{}\nfunc h(w http.ResponseWriter) {\n" + "m[k] = 1\n" * 20000 + "}\n" + "var m2 = map[string]int{}\n" * 5000,
    "stat then write": "func f() {\n" + "if _, err := os.Stat(p); err == nil { return }\nos.Create(p)\n" * 8000 + "}\n",
    "route groups": "".join(f"g{i} := g{i - 1}.Group(\"/a\", RequireRole(x))\n" for i in range(1, 6000)) + "g5999.GET(\"/admin/x\", h)\n" * 5000,
    "builder writes": "func f() {\nvar b strings.Builder\n" + "b.WriteString(x)\n" * 20000 + "db.Query(b.String())\n" * 200 + "}\n",
    "dotted exec": "func f() {\n" + "a." * N + "Exec(\"INSERT\")\n}\n",
    "const blocks left open": "const (\n" * 40000,
    "log verbs": "log.Printf(\"" + "%" * N + "\n",
    "long line": "x := \"" + "a+" * N + "\n",
}
JVM = {
    "jdbc calls in one method": "class A {\n void f() {\n" + "  String sql = \"SELECT a FROM t WHERE x = '\" + v + \"'\";\n  jdbc.query(sql, M);\n" * 6000 + " }\n}\n",
    "append chains": "class A {\n void f() {\n StringBuilder sql = new StringBuilder(\"SELECT 1\");\n" + "  sql.append(x).append(y).append(z);\n" * 15000
                     + "  jdbc.query(sql.toString());\n" * 200 + " }\n}\n",
    "catch blocks": "class A {\n boolean isAllowed() {\n" + "try { x(); } catch (E e) { return true; }\n" * 15000 + "}\n}\n",
    "catches left open": "class A {\n" + "try {} catch (E e) {\n" * 15000,
    "method heads left open": "class A {\n" + "  public ResponseEntity<Map<String, Object>> m(@RequestParam String u) throws IOException {\n" * 10000,
    "annotated methods": "class A {\n" + "@GetMapping(\"/x\")\n@PreAuthorize(\"y\")\npublic void m() {}\n" * 10000 + "}\n",
    "process builders left open": "new ProcessBuilder(\"sh\", \"-c\", " * 12000,
    "resolve checks": "class A {\n void f() {\n" + "Path p = root.resolve(n);\np.startsWith(root);\n" * 8000 + " }\n}\n",
    "setters": "class A {\n @Transactional void f() {\n a = repo.findById(1);\n" + "a.setX(a.getX().add(1));\n" * 15000 + " }\n}\n",
    "fields": "@Service\nclass A {\n" + "private final Map<String, Integer> m = new HashMap<>();\nprivate long n;\n" * 8000 + "void f() { n++; }\n}\n",
    "retry loops": "class A {\n void f() {\n" + "for (int attempt = 0; attempt < MAX; attempt++) { try { http.POST(x); } catch (E e) { Thread.sleep(1); }\n" * 8000 + "}\n }\n}\n",
    "dotted chain": "if (" + "a." * N + "existsByX(y)) {}\n",
    "origin word": "x" * N + "origin.endsWith(\"a\")\nAccess-Control-Allow-Origin\n",
    "long line": "String x = \"" + "a+" * N + "\n",
    "braces": "{" * N + "\n",
}
CASES = [("a.go", name, text) for name, text in GO.items()] + [(path, name, text) for path in ("A.java", "A.kt") for name, text in JVM.items()]


# Short lines first: a file whose first 4,000 characters hold a very long line is skipped as minified, so the rules would never see it.
PAD = "// a short line\n" * 300


@pytest.mark.parametrize("path, name, text", CASES, ids=[f"{path}-{name}" for path, name, _ in CASES])
def test_hostile_input_stays_fast(path, name, text):
    """These modules alone, since the shared rules have their own test in test_scanner_rules.py."""
    source = load(path, PAD + text)
    started = time.monotonic()
    (rules_go if path.endswith(".go") else rules_jvm).findings(source, False)
    assert time.monotonic() - started < 10, f"{name} took too long"


def test_unsafe_go_gets_the_memory_safety_note(tmp_path):
    base = {"wire/record.go": "package wire\n\nfunc key(frame []byte, n int) []byte {\n\treturn frame[:n]\n}\n"}
    root = repository(tmp_path / "bad", base)
    write(root, {"wire/record.go": "package wire\n\nimport \"unsafe\"\n\nfunc key(frame []byte, n int) []byte {\n\treturn unsafe.Slice(&frame[0], n)\n}\n"})
    assert "memory-safety-added" in {note["rule"] for note in notes_on(root)[0]}
    other = repository(tmp_path / "near", base)
    write(other, {"wire/record.go": "package wire\n\nfunc key(frame []byte, n int) []byte {\n\treturn frame[:min(n, len(frame))]\n}\n"})
    assert "memory-safety-added" not in {note["rule"] for note in notes_on(other)[0]}
