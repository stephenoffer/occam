-- Inputs to the month-end wage accrual. Loaded fresh for every run; nothing is kept.

CREATE TABLE shifts (
    worker_id   TEXT    NOT NULL,
    work_date   TEXT    NOT NULL,            -- ISO date the shift was worked
    start_min   INTEGER NOT NULL,            -- minutes after midnight
    end_min     INTEGER NOT NULL,
    break_min   INTEGER NOT NULL DEFAULT 0,  -- unpaid break
    site        TEXT    NOT NULL,
    cost_centre TEXT    NOT NULL,
    status      TEXT    NOT NULL,
    CHECK (end_min > start_min)
);

CREATE TABLE rates (
    worker_id  TEXT    PRIMARY KEY,
    base_pence INTEGER NOT NULL              -- base hourly rate, in pence
);

-- The pay weeks (by their Monday) that this accrual covers.
CREATE TABLE weeks (
    week_start TEXT PRIMARY KEY
);
