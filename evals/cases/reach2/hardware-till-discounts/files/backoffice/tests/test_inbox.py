from datetime import date

from backoffice.inbox import stores_reporting, tapes_for_day


def test_finds_tapes_for_the_day_including_the_archive(tmp_path):
    (tmp_path / "BRH01-2026-10-05.tape").write_text("")
    (tmp_path / "BRH01-2026-10-06.tape").write_text("")
    archive = tmp_path / "archive" / "2026-10"
    archive.mkdir(parents=True)
    (archive / "BRH03-2026-10-05.tape").write_text("")
    (archive / "BRH01-2026-10-05.tape").write_text("")
    names = [p.name for p in tapes_for_day(tmp_path, date(2026, 10, 5))]
    assert names == ["BRH01-2026-10-05.tape", "BRH03-2026-10-05.tape"]
    assert stores_reporting(tmp_path, date(2026, 10, 5)) == ["BRH01", "BRH03"]
