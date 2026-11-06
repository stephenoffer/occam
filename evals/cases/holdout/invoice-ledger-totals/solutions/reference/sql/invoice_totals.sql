WITH parsed AS (
    SELECT
        l.invoice_id,
        l.quantity,
        l.discount_bp,
        l.tax_bp,
        CAST(replace(l.unit_price, '.', '') AS INTEGER) AS price_digits,
        CASE WHEN instr(l.unit_price, '.') = 0 THEN 0
             ELSE length(l.unit_price) - instr(l.unit_price, '.') END AS price_decimals,
        CAST('1' || substr('000', 1, c.minor_digits) AS INTEGER) AS minor_per_major
    FROM invoice_lines AS l
    JOIN invoices AS i ON i.id = l.invoice_id
    JOIN currencies AS c ON c.code = i.currency
),
net_parts AS (
    SELECT
        invoice_id,
        tax_bp,
        price_digits * quantity * (10000 - discount_bp) * minor_per_major AS numerator,
        CAST('1' || substr('000000', 1, price_decimals) AS INTEGER) * 10000 AS denominator
    FROM parsed
),
net_lines AS (
    SELECT
        invoice_id,
        tax_bp,
        CASE WHEN numerator < 0 THEN -((-numerator + denominator / 2) / denominator)
             ELSE (numerator + denominator / 2) / denominator END AS net
    FROM net_parts
),
line_totals AS (
    SELECT
        invoice_id,
        net + CASE WHEN net < 0 THEN -((-net * tax_bp + 5000) / 10000)
                   ELSE (net * tax_bp + 5000) / 10000 END AS line_total
    FROM net_lines
),
invoice_totals AS (
    SELECT invoice_id, SUM(line_total) AS total_minor
    FROM line_totals
    GROUP BY invoice_id
)
SELECT
    i.id AS invoice_id,
    i.currency AS currency,
    CASE WHEN t.total_minor < 0 THEN '-' ELSE '' END
        || (abs(t.total_minor) / CAST('1' || substr('000', 1, c.minor_digits) AS INTEGER))
        || CASE WHEN c.minor_digits = 0 THEN ''
                ELSE '.' || substr('000' || (abs(t.total_minor) % CAST('1' || substr('000', 1, c.minor_digits) AS INTEGER)),
                                   -c.minor_digits) END AS total
FROM invoices AS i
JOIN invoice_totals AS t ON t.invoice_id = i.id
JOIN currencies AS c ON c.code = i.currency
ORDER BY i.id;
