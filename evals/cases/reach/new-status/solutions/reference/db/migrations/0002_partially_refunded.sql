CREATE TABLE orders_new (
    id INTEGER PRIMARY KEY,
    total_cents INTEGER NOT NULL,
    refunded_cents INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL CHECK (status IN ('PENDING', 'PAID', 'SHIPPED', 'PARTIALLY_REFUNDED', 'REFUNDED', 'CANCELLED'))
);
INSERT INTO orders_new SELECT id, total_cents, refunded_cents, status FROM orders;
DROP TABLE orders;
ALTER TABLE orders_new RENAME TO orders;
