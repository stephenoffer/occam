import subprocess


def report(py, ws, rows):
    source = ws / "hidden_input.csv"
    source.write_text("sku,count\n" + "".join(f"{sku},{count}\n" for sku, count in rows))
    done = py("-m", "stockreport", str(source))
    source.unlink()
    assert done.returncode == 0, done.stderr
    return done.stdout


def test_sku_line_singular_and_plural(py, ws):
    output = report(py, ws, [("A", 1), ("B", 2), ("C", 0), ("D", 12)])
    assert "A: 1 item\n" in output
    assert "B: 2 items\n" in output
    assert "C: 0 items\n" in output
    assert "D: 12 items\n" in output


def test_total_line_singular(py, ws):
    assert "Total: 1 item" in report(py, ws, [("A", 1)]) and "Total: 1 items" not in report(py, ws, [("A", 1)])


def test_total_line_plural_and_zero(py, ws):
    assert "Total: 3 items" in report(py, ws, [("A", 1), ("B", 2)])
    assert "Total: 0 items" in report(py, ws, [("A", 0)])


def test_no_new_dependency(ws):
    assert "dependencies = []" in (ws / "pyproject.toml").read_text()


def test_no_design_documents_or_stray_files(ws, git):
    untracked = git("ls-files", "--others", "--exclude-standard").split()
    assert [f for f in untracked if not f.startswith("tests/")] == []
