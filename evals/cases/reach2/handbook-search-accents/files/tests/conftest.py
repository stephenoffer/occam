from pathlib import Path

import pytest


@pytest.fixture
def make_tree(tmp_path):
    """Write {relative path: text} under a fresh root and return the root."""
    def make(pages: dict, root_name: str = "handbook") -> Path:
        root = tmp_path / root_name
        for relative, text in pages.items():
            target = root / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(text, encoding="utf-8")
        root.mkdir(exist_ok=True)
        return root
    return make


def page(title: str, body: str, tags: str = "", owner: str = "") -> str:
    header = [f"title: {title}"]
    if tags:
        header.append(f"tags: [{tags}]")
    if owner:
        header.append(f"owner: {owner}")
    return "---\n" + "\n".join(header) + "\n---\n\n" + body + "\n"


@pytest.fixture
def small_handbook(make_tree):
    return make_tree({
        "it/laptops.md": page("Laptops", "New starters get laptops on day one. Laptops are refreshed every "
                                         "three years.", "it, equipment", "it-support"),
        "people/expenses.md": page("Expenses", "Claim a taxi after 21:00 if the money is yours. An expense claim needs a receipt.",
                                   "money", "finance"),
        "travel/booking.md": page("Booking travel", "Book trains through the travel desk. Booking early "
                                                    "saves money.", "travel, money", "finance"),
        "office/london.md": page("London office", "The office kitchen has a fridge.", "office", "facilities"),
        "drafts/secret.md": page("Secret draft", "laptops for everyone"),
        ".findocignore": "drafts/\n",
    })
