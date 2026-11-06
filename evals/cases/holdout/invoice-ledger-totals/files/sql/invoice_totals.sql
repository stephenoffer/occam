SELECT
    i.id AS invoice_id,
    i.currency AS currency,
    printf('%.2f', ROUND(SUM(
        l.unit_price * l.quantity * (1 - l.discount_bp / 10000.0) * (1 + l.tax_bp / 10000.0)
    ), 2)) AS total
FROM invoices AS i
JOIN invoice_lines AS l ON l.invoice_id = i.id
GROUP BY i.id, i.currency
ORDER BY i.id;
