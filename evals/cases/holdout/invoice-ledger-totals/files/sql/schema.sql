CREATE TABLE currencies (
    code TEXT PRIMARY KEY,
    minor_digits INTEGER NOT NULL
);

CREATE TABLE invoices (
    id INTEGER PRIMARY KEY,
    customer TEXT NOT NULL,
    currency TEXT NOT NULL REFERENCES currencies (code),
    issued_on TEXT NOT NULL
);

CREATE TABLE invoice_lines (
    id INTEGER PRIMARY KEY,
    invoice_id INTEGER NOT NULL REFERENCES invoices (id),
    description TEXT NOT NULL,
    unit_price TEXT NOT NULL,
    quantity INTEGER NOT NULL,
    discount_bp INTEGER NOT NULL DEFAULT 0,
    tax_bp INTEGER NOT NULL DEFAULT 0
);
