-- Treatment fees due: attended appointments (status 4) of self-funded patients not charged yet.
-- Insurer-funded treatment is invoiced to the insurer from their own portal, not here.
SELECT a.id         AS appointment_id,
       a.patient_id AS patient_id,
       a.starts_at  AS starts_at,
       a.minutes    AS minutes
FROM appointments AS a
JOIN patients AS p
  ON p.id = a.patient_id
LEFT JOIN charges AS c
       ON c.appointment_id = a.id
      AND c.kind = 'treatment'
WHERE a.status = 4
  AND p.funding = 'self'
  AND a.starts_at < :run_at
  AND c.id IS NULL
ORDER BY a.starts_at, a.id;
