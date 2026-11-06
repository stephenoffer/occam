from stockreport.report import render


def test_render_lists_each_sku(tmp_path):
    source = tmp_path / "stock.csv"
    source.write_text("sku,count\nA,5\nB,7\n")
    output = render(str(source))
    assert "A: 5 items" in output
    assert "B: 7 items" in output
    assert "Total: 12 items" in output
