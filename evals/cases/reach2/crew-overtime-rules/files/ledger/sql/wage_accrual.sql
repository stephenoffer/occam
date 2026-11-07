-- Month-end wage accrual: what we owe crews for the pay weeks listed in `weeks`, by cost centre.
--
-- Worked time on each shift is rounded to the nearest quarter hour. Within a worker's pay week,
-- shifts are taken in date and start order, and every minute past base_week_min is premium time,
-- accrued at premium_factor times the base rate. Premium minutes land on the cost centre of the
-- shift they fall in.
--
-- Finance's auditors re-run this exact query against the archived inputs. Keep every step here.

WITH params AS (
    SELECT 2400 AS base_week_min,     -- 40 hours
           1.5  AS premium_factor
),
worked AS (
    SELECT s.worker_id,
           s.work_date,
           s.start_min,
           s.cost_centre,
           date(s.work_date, '-' || ((CAST(strftime('%w', s.work_date) AS INTEGER) + 6) % 7) || ' days') AS week_start,
           ((s.end_min - s.start_min - s.break_min + 7) / 15) * 15 AS minutes
    FROM shifts s
    WHERE s.status = 'approved'
),
in_period AS (
    SELECT w.*
    FROM worked w
    JOIN weeks k ON k.week_start = w.week_start
),
running AS (
    SELECT i.*,
           SUM(i.minutes) OVER (
               PARTITION BY i.worker_id, i.week_start
               ORDER BY i.work_date, i.start_min
               ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
           ) AS week_to_date
    FROM in_period i
),
split AS (
    SELECT r.worker_id,
           r.cost_centre,
           r.minutes,
           MAX(0, MIN(r.minutes, r.week_to_date - p.base_week_min)) AS premium_min
    FROM running r
    CROSS JOIN params p
)
SELECT sp.cost_centre,
       SUM(sp.minutes)     AS minutes,
       SUM(sp.premium_min) AS premium_minutes,
       CAST(ROUND(SUM((sp.minutes - sp.premium_min) * rt.base_pence
                      + sp.premium_min * rt.base_pence * p.premium_factor) / 60.0) AS INTEGER) AS accrued_pence
FROM split sp
JOIN rates rt ON rt.worker_id = sp.worker_id
CROSS JOIN params p
GROUP BY sp.cost_centre
ORDER BY sp.cost_centre;
