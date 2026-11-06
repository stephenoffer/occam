import json

from ledgerkit import cli


def write_ledger(tmp_path):
    path = tmp_path / "ledger.json"
    path.write_text(json.dumps([
        {"reference": "Invoice 1", "customer": "Acme", "currency": "USD", "amount": "10.50"},
        {"reference": "Invoice 2", "customer": "Bolt", "currency": "EUR", "amount": "4.25"},
    ]))
    return str(path)


def test_csv_export(tmp_path, capsys):
    assert cli.main(["export", write_ledger(tmp_path), "--format", "csv"]) == 0
    assert "Invoice 1,Acme,USD,10.50" in capsys.readouterr().out


def test_json_export(tmp_path, capsys):
    assert cli.main(["export", write_ledger(tmp_path), "--format", "json"]) == 0
    assert json.loads(capsys.readouterr().out)[1]["total"] == "4.25"


def test_link(capsys):
    assert cli.main(["link", "Invoice 12"]) == 0
    assert capsys.readouterr().out.strip() == "invoice-12"
