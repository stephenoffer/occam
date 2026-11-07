-- DNA fees due: appointments the patient did not attend, once their start time has passed,
-- that haven't been charged a DNA fee yet.
-- Status codes are the practice system's (docs/adr/0001-status-codes-as-integers.md):
--   4 attended, 5 cancelled, 6 DNA.
SELECT a.id         AS appointment_id,
       a.patient_id AS patient_id,
       a.starts_at  AS starts_at,
       a.minutes    AS minutes
FROM appointments AS a
LEFT JOIN charges AS c
       ON c.appointment_id = a.id
      AND c.kind = 'dna'
WHERE a.status = 6
  AND a.starts_at < :run_at
  AND c.id IS NULL
ORDER BY a.starts_at, a.id;
