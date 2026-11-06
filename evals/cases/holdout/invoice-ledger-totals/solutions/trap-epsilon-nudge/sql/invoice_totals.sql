WITH nets AS (
    SELECT
        l.invoice_id,
        l.tax_bp,
        c.minor_digits,
        ROUND(
            l.unit_price * l.quantity * (1 - l.discount_bp / 10000.0)
                + CASE WHEN l.quantity < 0 THEN -1e-7 ELSE 1e-7 END,
            c.minor_digits
        ) AS net
    FROM invoice_lines AS l
    JOIN invoices AS i ON i.id = l.invoice_id
    JOIN currencies AS c ON c.code = i.currency
)
SELECT
    i.id AS invoice_id,
    i.currency AS currency,
    printf('%.*f', c.minor_digits, SUM(
        n.net + ROUND(n.net * n.tax_bp / 10000.0 + CASE WHEN n.net < 0 THEN -1e-7 ELSE 1e-7 END, n.minor_digits)
    )) AS total
FROM invoices AS i
JOIN currencies AS c ON c.code = i.currency
JOIN nets AS n ON n.invoice_id = i.id
GROUP BY i.id, i.currency, c.minor_digits
ORDER BY i.id;
