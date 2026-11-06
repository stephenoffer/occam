"""sql/invoice_totals.sql, run as the README says, against evaluator-owned exports."""

import random
import sqlite3
import time
from fractions import Fraction

import pytest

SCHEMA = """
CREATE TABLE currencies (code TEXT PRIMARY KEY, minor_digits INTEGER NOT NULL);
CREATE TABLE invoices (
    id INTEGER PRIMARY KEY, customer TEXT NOT NULL,
    currency TEXT NOT NULL REFERENCES currencies (code), issued_on TEXT NOT NULL
);
CREATE TABLE invoice_lines (
    id INTEGER PRIMARY KEY, invoice_id INTEGER NOT NULL REFERENCES invoices (id),
    description TEXT NOT NULL, unit_price TEXT NOT NULL, quantity INTEGER NOT NULL,
    discount_bp INTEGER NOT NULL DEFAULT 0, tax_bp INTEGER NOT NULL DEFAULT 0
);
"""
MINOR_DIGITS = {"USD": 2, "EUR": 2, "GBP": 2, "JPY": 0, "KWD": 3, "BHD": 3, "KRW": 0}
QUERY_SECONDS = 20


def round_half_away(value: Fraction) -> int:
    magnitude = abs(value)
    whole = (2 * magnitude.numerator + magnitude.denominator) // (2 * magnitude.denominator)
    return whole if value >= 0 else -whole


def line_total_minor(unit_price: str, quantity: int, discount_bp: int, tax_bp: int, digits: int) -> int:
    """The README's billing rules, in exact arithmetic. Result is in minor units."""
    scale = 10 ** digits
    net = round_half_away(Fraction(unit_price) * quantity * (10000 - discount_bp) / 10000 * scale)
    tax = round_half_away(Fraction(net) * tax_bp / 10000)
    return net + tax


def format_minor(amount: int, digits: int) -> str:
    sign = "-" if amount < 0 else ""
    whole, fraction = divmod(abs(amount), 10 ** digits)
    return f"{sign}{whole}" + (f".{fraction:0{digits}d}" if digits else "")


def expected_total(currency, lines):
    digits = MINOR_DIGITS[currency]
    return format_minor(sum(line_total_minor(*line, digits) for line in lines), digits)


@pytest.fixture
def run_query(ws):
    """Load invoices into a fresh export and run the query. Invoices map id to (currency, lines)."""
    def run(invoices):
        connection = sqlite3.connect(":memory:")
        connection.executescript(SCHEMA)
        connection.executemany("INSERT INTO currencies VALUES (?, ?)", MINOR_DIGITS.items())
        for invoice_id, (currency, lines) in invoices.items():
            connection.execute("INSERT INTO invoices VALUES (?, 'Customer', ?, '2026-09-01')", (invoice_id, currency))
            connection.executemany(
                "INSERT INTO invoice_lines (invoice_id, description, unit_price, quantity, discount_bp, tax_bp)"
                " VALUES (?, 'Line', ?, ?, ?, ?)",
                [(invoice_id, *line) for line in lines],
            )
        deadline = time.monotonic() + QUERY_SECONDS
        connection.set_progress_handler(lambda: time.monotonic() > deadline, 100_000)
        cursor = connection.execute((ws / "sql" / "invoice_totals.sql").read_text())
        columns = [column[0] for column in cursor.description]
        rows = cursor.fetchall()
        connection.close()
        return columns, rows
    return run


def totals(run_query, invoices):
    columns, rows = run_query(invoices)
    assert columns == ["invoice_id", "currency", "total"]
    assert [row[0] for row in rows] == sorted(invoices), "one row per invoice, ordered by id"
    return {row[0]: row[2] for row in rows}


def check_single_lines(run_query, currency, cases):
    """Each case is (unit_price, quantity, discount_bp, tax_bp, expected total)."""
    invoices = {index: (currency, [case[:4]]) for index, case in enumerate(cases, start=1)}
    actual = totals(run_query, invoices)
    wrong = {cases[index - 1][:4]: (actual[index], cases[index - 1][4])
             for index in actual if actual[index] != cases[index - 1][4]}
    assert not wrong, f"(line): (query's total, billing's total): {wrong}"


def test_expected_values_agree_with_the_rules():
    """Guards the suite itself: every hand-written case below follows the README's rules."""
    for currency, cases in ALL_HAND_WRITTEN:
        for case in cases:
            assert expected_total(currency, [case[:4]]) == case[4], (currency, case)


def test_total_is_text_with_the_currency_minor_digits(run_query):
    actual = totals(run_query, {
        1: ("USD", [("12.3", 1, 0, 0)]),
        2: ("JPY", [("1500", 1, 0, 0)]),
        3: ("KWD", [("1.2", 1, 0, 0)]),
        4: ("USD", [("0", 1, 0, 0)]),
        5: ("JPY", [("0", 1, 0, 0)]),
    })
    assert actual == {1: "12.30", 2: "1500", 3: "1.200", 4: "0.00", 5: "0"}


LINES_ROUND_THEN_SUM = [
    ("USD", [("3.33", 1, 0, 700)] * 3, "10.68"),
    ("USD", [("0.333", 1, 0, 0)] * 3, "0.99"),
    ("USD", [("0.335", 1, 0, 0), ("0.334", 1, 0, 0)], "0.67"),
]


def test_lines_are_rounded_before_summing(run_query):
    invoices = {i: (currency, lines) for i, (currency, lines, _) in enumerate(LINES_ROUND_THEN_SUM, start=1)}
    actual = totals(run_query, invoices)
    assert actual == {i: case[2] for i, case in enumerate(LINES_ROUND_THEN_SUM, start=1)}


TAX_ON_ROUNDED_NET = [
    ("0.145", 1, 0, 1000, "0.17"),
    ("10.125", 1, 0, 2000, "12.16"),
    ("0.045", 1, 0, 5000, "0.08"),
]


def test_tax_uses_the_rounded_net(run_query):
    check_single_lines(run_query, "USD", TAX_ON_ROUNDED_NET)


EXACT_HALVES = [
    ("1.005", 1, 0, 0, "1.01"),
    ("2.675", 1, 0, 0, "2.68"),
    ("1.115", 1, 0, 0, "1.12"),
    ("8.325", 1, 0, 0, "8.33"),
    ("0.285", 1, 0, 0, "0.29"),
    ("1.255", 1, 0, 0, "1.26"),
    ("4.015", 1, 0, 0, "4.02"),
    ("16.115", 1, 0, 0, "16.12"),
    ("10.10", 1, 250, 0, "9.85"),
    ("49.50", 3, 500, 0, "141.08"),
    ("0.35", 3, 5000, 0, "0.53"),
    ("19.99", 1, 2500, 0, "14.99"),
    ("64.70", 1, 2500, 0, "48.53"),
    ("1.10", 1, 2500, 0, "0.83"),
    ("3.00", 1, 0, 2450, "3.74"),
    ("1.00", 1, 0, 1250, "1.13"),
    ("70.00", 1, 0, 75, "70.53"),
    ("2.10", 1, 0, 2500, "2.63"),
]


def test_exact_halves_round_away_from_zero(run_query):
    check_single_lines(run_query, "USD", EXACT_HALVES)


JUST_BELOW_HALF = [
    ("0.004999", 1, 0, 0, "0.00"),
    ("1.004999", 1, 0, 0, "1.00"),
    ("2.674999", 1, 0, 0, "2.67"),
]


def near_half_line():
    """A line whose unrounded net is one ten-billionth below a half cent."""
    for discount_bp in (1, 3, 7, 9, 11):
        keep = 10000 - discount_bp
        price_micros = 49_999_999 * pow(keep, -1, 100_000_000) % 100_000_000
        net_times_1e10 = price_micros * keep
        assert net_times_1e10 % 100_000_000 == 49_999_999
        if price_micros < 100_000_000:
            whole, fraction = divmod(price_micros, 1_000_000)
            return f"{whole}.{fraction:06d}", discount_bp
    raise AssertionError("no such line")


def test_values_just_below_a_half_round_down(run_query):
    price, discount_bp = near_half_line()
    cases = JUST_BELOW_HALF + [(price, 1, discount_bp, 0, expected_total("USD", [(price, 1, discount_bp, 0)]))]
    check_single_lines(run_query, "USD", cases)


CREDIT_LINES = [
    ("1.005", -1, 0, 0, "-1.01"),
    ("2.675", -1, 0, 0, "-2.68"),
    ("10.10", -1, 250, 0, "-9.85"),
    ("0.145", -1, 0, 1000, "-0.17"),
    ("1.00", -1, 0, 1250, "-1.13"),
    ("15.00", -1, 0, 2000, "-18.00"),
]


def test_credit_lines_round_away_from_zero(run_query):
    check_single_lines(run_query, "EUR", CREDIT_LINES)


def test_small_negative_totals_keep_their_sign(run_query):
    actual = totals(run_query, {
        1: ("USD", [("0.05", -1, 0, 0)]),
        2: ("USD", [("0.50", -1, 0, 0)]),
        3: ("KWD", [("0.005", -1, 0, 0)]),
        4: ("USD", [("5.00", 1, 0, 0), ("5.00", -1, 0, 0)]),
        5: ("USD", [("5.25", 1, 0, 0), ("5.30", -1, 0, 0)]),
    })
    assert actual == {1: "-0.05", 2: "-0.50", 3: "-0.005", 4: "0.00", 5: "-0.05"}


ZERO_DIGIT_CURRENCY = [
    ("1500", 1, 0, 0, "1500"),
    ("1500", 1, 250, 0, "1463"),
    ("333", 1, 0, 1000, "366"),
    ("1250", 1, 0, 1000, "1375"),
    ("99.5", 1, 0, 0, "100"),
    ("1500", -1, 250, 0, "-1463"),
    ("150", 3, 3333, 800, "324"),
]


def test_zero_digit_currency(run_query):
    check_single_lines(run_query, "JPY", ZERO_DIGIT_CURRENCY)


THREE_DIGIT_CURRENCY = [
    ("1.2345", 1, 0, 0, "1.235"),
    ("1.2344", 1, 0, 0, "1.234"),
    ("12.500", 3, 250, 0, "36.563"),
    ("0.125", 1, 0, 500, "0.131"),
    ("1.2345", -1, 0, 0, "-1.235"),
    ("10", 1, 0, 0, "10.000"),
]


def test_three_digit_currency(run_query):
    check_single_lines(run_query, "KWD", THREE_DIGIT_CURRENCY)


VARYING_PRICE_PRECISION = [
    ("12", 2, 0, 0, "24.00"),
    ("10.5", 2, 0, 0, "21.00"),
    ("10.50", 2, 0, 0, "21.00"),
    ("0.0125", 1000, 0, 0, "12.50"),
    ("0.000125", 333, 0, 0, "0.04"),
    ("0.000125", 40, 0, 0, "0.01"),
    ("0.012500", 80000, 0, 0, "1000.00"),
    ("7", 1, 0, 825, "7.58"),
]


def test_unit_prices_of_varying_precision(run_query):
    check_single_lines(run_query, "USD", VARYING_PRICE_PRECISION)


LARGE_LINES = [
    ("999999.99", 1, 5000, 0, "500000.00"),
    ("999999.99", 1, 0, 0, "999999.99"),
    ("99999.99", 10, 2500, 825, "811874.92"),
    ("333333.33", 3, 1, 1, "999999.98"),
    ("999999.99", -1, 5000, 0, "-500000.00"),
    ("123456.78", 8, 1250, 1900, "1028394.98"),
]


def test_large_lines_stay_exact(run_query):
    check_single_lines(run_query, "USD", LARGE_LINES)


def test_many_lines_on_one_invoice_add_up_exactly(run_query):
    lines = [("0.10", 1, 0, 0)] * 1000 + [("0.70", 1, 0, 0)] * 300 + [("1.10", -1, 0, 0)] * 100
    assert totals(run_query, {1: ("USD", lines)}) == {1: expected_total("USD", lines)}


def random_price(rng):
    decimals = rng.choice([0, 1, 2, 2, 2, 3, 3, 4, 6])
    whole = rng.choice([0, 1, 2, 9, 19, 49, 120, 999, 2500])
    if decimals == 0:
        return str(whole + rng.randrange(1, 90))
    fraction = rng.randrange(10 ** decimals)
    if decimals == 3 and rng.random() < 0.6:
        fraction = fraction // 10 * 10 + 5
    return f"{whole}.{fraction:0{decimals}d}"


def test_randomized_invoices_match_the_billing_rules(run_query):
    rng = random.Random(20260901)
    invoices = {}
    for invoice_id in range(1, 401):
        currency = rng.choice(["USD", "USD", "EUR", "GBP", "JPY", "KRW", "KWD", "BHD"])
        lines = []
        for _ in range(rng.randrange(1, 5)):
            quantity = rng.choice([1, 1, 2, 3, 7, 12, 25, 50]) * rng.choice([1, 1, 1, -1])
            discount_bp = rng.choice([0, 0, 250, 500, 1250, 2500, 3333, 5000, 7500])
            tax_bp = rng.choice([0, 500, 750, 825, 1000, 1250, 1900, 2000, 2500])
            lines.append((random_price(rng), quantity, discount_bp, tax_bp))
        invoices[invoice_id] = (currency, lines)
    actual = totals(run_query, invoices)
    wrong = {i: (invoices[i], actual[i], expected_total(*invoices[i]))
             for i in invoices if actual[i] != expected_total(*invoices[i])}
    assert not wrong, f"{len(wrong)} of {len(invoices)} wrong, for example {next(iter(wrong.values()))}"


ALL_HAND_WRITTEN = [
    ("USD", TAX_ON_ROUNDED_NET), ("USD", EXACT_HALVES), ("USD", JUST_BELOW_HALF), ("EUR", CREDIT_LINES),
    ("JPY", ZERO_DIGIT_CURRENCY), ("KWD", THREE_DIGIT_CURRENCY), ("USD", VARYING_PRICE_PRECISION),
    ("USD", LARGE_LINES),
]
