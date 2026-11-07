-- Every charge raised for one patient, oldest appointment first.
SELECT c.id            AS charge_id,
       c.kind          AS kind,
       c.amount_pence  AS amount_pence,
       c.raised_at     AS raised_at,
       a.id            AS appointment_id,
       a.starts_at     AS starts_at
FROM charges AS c
JOIN appointments AS a
  ON a.id = c.appointment_id
WHERE c.patient_id = :patient_id
ORDER BY a.starts_at, c.id;
