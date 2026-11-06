INSERT INTO currencies (code, minor_digits) VALUES
    ('USD', 2), ('EUR', 2), ('GBP', 2), ('JPY', 0), ('KWD', 3);

INSERT INTO invoices (id, customer, currency, issued_on) VALUES
    (1001, 'Northwind Traders', 'USD', '2026-09-01'),
    (1002, 'Lindqvist AB', 'EUR', '2026-09-01'),
    (1003, 'Harbor Freight Co', 'USD', '2026-09-02'),
    (1004, 'Blue Heron Press', 'USD', '2026-09-03'),
    (1005, 'Lindqvist AB', 'EUR', '2026-09-04');

INSERT INTO invoice_lines (invoice_id, description, unit_price, quantity, discount_bp, tax_bp) VALUES
    (1001, 'Annual seat', '19.99', 2, 0, 825),
    (1002, 'Support plan', '120.00', 1, 1000, 1900),
    (1003, 'Label roll', '3.33', 1, 0, 700),
    (1003, 'Label roll, matte', '3.33', 1, 0, 700),
    (1003, 'Label roll, gloss', '3.33', 1, 0, 700),
    (1004, 'Ink cartridge', '49.60', 3, 500, 0),
    (1005, 'Support plan credit', '15.00', -1, 0, 2000);
