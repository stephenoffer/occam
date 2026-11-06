from app.greet import greet


def test_greet_includes_name():
    assert "Ada" in greet("Ada")
