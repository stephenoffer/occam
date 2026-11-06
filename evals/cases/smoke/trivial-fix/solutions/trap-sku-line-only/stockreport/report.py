import csv


def load_counts(path):
    with open(path, newline="") as handle:
        return [(row["sku"], int(row["count"])) for row in csv.DictReader(handle)]


def sku_line(sku, count):
    return f"{sku}: {count} item" + ("" if count == 1 else "s")


def total_line(rows):
    total = sum(count for _, count in rows)
    return f"Total: {total} items across {len(rows)} SKUs"


def render(path):
    rows = load_counts(path)
    return "\n".join([sku_line(sku, count) for sku, count in rows] + [total_line(rows)])
