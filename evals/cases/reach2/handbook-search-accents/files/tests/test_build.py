from datetime import datetime, timezone

from indexing import build, store

NOW = datetime(2026, 11, 2, 9, 30, tzinfo=timezone.utc)


def test_first_build_adds_every_page(small_handbook):
    report = build.update(small_handbook, now=NOW)
    assert report.added == ["it/laptops.md", "office/london.md", "people/expenses.md", "travel/booking.md"]
    assert store.load(small_handbook).built_at == "2026-11-02T09:30:00+00:00"


def test_unchanged_pages_are_reused(small_handbook):
    build.update(small_handbook, now=NOW)
    (small_handbook / "it/laptops.md").write_text("# Laptops\nLaptops are now refreshed every four years.\n")
    (small_handbook / "office/london.md").unlink()
    (small_handbook / "office/zurich.md").write_text("# Zurich office\n")
    report = build.update(small_handbook, now=NOW)
    assert report.changed == ["it/laptops.md"]
    assert report.added == ["office/zurich.md"]
    assert report.removed == ["office/london.md"]
    assert report.reused == ["people/expenses.md", "travel/booking.md"]
    assert "four" in store.load(small_handbook).entries["it/laptops.md"].counts


def test_full_rebuild_reads_everything(small_handbook):
    build.update(small_handbook, now=NOW)
    report = build.update(small_handbook, full=True, now=NOW)
    assert report.reused == [] and len(report.added) == 4


def test_scan_matches_a_saved_build(small_handbook):
    build.update(small_handbook, now=NOW)
    saved = store.load(small_handbook)
    scanned = build.scan(small_handbook)
    assert {path: entry.counts for path, entry in saved.entries.items()} == \
        {path: entry.counts for path, entry in scanned.entries.items()}


def test_summary_line(small_handbook):
    assert build.update(small_handbook, now=NOW).summary() == \
        "indexed 4 pages (4 added, 0 changed, 0 unchanged, 0 removed)"
