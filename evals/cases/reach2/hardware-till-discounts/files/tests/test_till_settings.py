from till.settings import TillSettings, load_settings


def test_defaults_without_a_file(tmp_path):
    assert load_settings(tmp_path) == TillSettings()


def test_reads_till_ini(tmp_path):
    (tmp_path / "till.ini").write_text("[till]\nstore = brh04\nnumber = 3\nfloat_pence = 15000\n")
    settings = load_settings(tmp_path)
    assert (settings.store, settings.number, settings.float_pence) == ("BRH04", 3, 15000)
    assert settings.store_name == TillSettings().store_name
