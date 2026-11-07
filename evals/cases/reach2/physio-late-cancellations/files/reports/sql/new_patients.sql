-- Patients whose first appointment with us starts in [:month_start, :month_end).
SELECT COUNT(*) AS new_patients
FROM (
    SELECT patient_id, MIN(starts_at) AS first_start
    FROM appointments
    GROUP BY patient_id
)
WHERE first_start >= :month_start
  AND first_start <  :month_end;
