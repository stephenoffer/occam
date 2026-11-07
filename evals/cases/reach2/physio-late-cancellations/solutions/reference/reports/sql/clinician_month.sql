-- Monthly figures, one row per active clinician, for appointments starting in
-- [:month_start, :month_end).
-- Status codes are the practice system's (docs/adr/0001-status-codes-as-integers.md):
--   4 attended, 5 cancelled, 6 DNA, 7 late cancellation (counted as a DNA).
-- "booked" counts every appointment made for the month, whatever happened to it.
SELECT c.id    AS clinician_id,
       c.name  AS clinician,
       k.name  AS clinic,
       COUNT(a.id) AS booked,
       COALESCE(SUM(CASE WHEN a.status = 4 THEN 1 ELSE 0 END), 0)         AS attended,
       COALESCE(SUM(CASE WHEN a.status = 5 THEN 1 ELSE 0 END), 0)         AS cancellations,
       COALESCE(SUM(CASE WHEN a.status IN (6, 7) THEN 1 ELSE 0 END), 0)  AS dna,
       COALESCE(SUM(CASE WHEN a.status = 4 THEN a.minutes ELSE 0 END), 0) AS treatment_minutes
FROM clinicians AS c
JOIN clinics AS k
  ON k.id = c.clinic_id
LEFT JOIN appointments AS a
       ON a.clinician_id = c.id
      AND a.starts_at >= :month_start
      AND a.starts_at <  :month_end
WHERE c.active = 1
GROUP BY c.id, c.name, k.name
ORDER BY k.name, c.name;
