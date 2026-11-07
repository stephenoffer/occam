import pytest

from catalog import DEPARTMENTS, ProductNotFound, department_name, load_catalog
from catalog.products import write_catalog


def test_loads_the_shipped_catalogue():
    catalog = load_catalog()
    assert len(catalog) >= 15
    paint = catalog.get("pnt-1l-wht")
    assert paint.price_pence == 1299 and paint.department == "PNT"
    assert all(p.department in DEPARTMENTS for p in catalog.all())


def test_unknown_sku():
    with pytest.raises(ProductNotFound):
        load_catalog().get("NOPE-1")


def test_department_lookup():
    assert department_name("GDN") == "Garden"
    assert department_name("XYZ") == "XYZ"
    assert [p.sku for p in load_catalog().in_department("PLB")] == ["PLB-PTFE", "PLB-WASHER-SET"]


def test_rejects_bad_rows(tmp_path):
    path = tmp_path / "products.csv"
    path.write_text("sku,description,department,price_pence\nA-1,Thing,NOPE,100\n")
    with pytest.raises(ValueError, match="unknown department"):
        load_catalog(path)
    path.write_text("sku,description,department,price_pence\nA-1,Thing,FIX,100\nA-1,Again,FIX,200\n")
    with pytest.raises(ValueError, match="duplicate"):
        load_catalog(path)


def test_round_trip(tmp_path):
    catalog = load_catalog()
    write_catalog(catalog, tmp_path / "out.csv")
    assert load_catalog(tmp_path / "out.csv").all() == catalog.all()
