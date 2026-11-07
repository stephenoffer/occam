-- Kestrel Physio clinic database.
-- Appointment status is a small integer: the codes are listed in docs/adr/0001-status-codes-as-integers.md.

CREATE TABLE IF NOT EXISTS clinics (
    id          INTEGER PRIMARY KEY,
    name        TEXT NOT NULL,
    phone       TEXT
);

CREATE TABLE IF NOT EXISTS clinicians (
    id            INTEGER PRIMARY KEY,
    name          TEXT NOT NULL,
    clinic_id     INTEGER NOT NULL REFERENCES clinics(id),
    slot_minutes  INTEGER NOT NULL DEFAULT 45,
    active        INTEGER NOT NULL DEFAULT 1
);

-- Weekly working pattern. weekday is Python's: 0 = Monday.
CREATE TABLE IF NOT EXISTS sessions (
    clinician_id  INTEGER NOT NULL REFERENCES clinicians(id),
    weekday       INTEGER NOT NULL CHECK (weekday BETWEEN 0 AND 6),
    starts        TEXT NOT NULL,
    ends          TEXT NOT NULL,
    PRIMARY KEY (clinician_id, weekday, starts)
);

CREATE TABLE IF NOT EXISTS patients (
    id             INTEGER PRIMARY KEY,
    name           TEXT NOT NULL,
    phone          TEXT,
    email          TEXT,
    funding        TEXT NOT NULL DEFAULT 'self' CHECK (funding IN ('self', 'insurer')),
    registered_on  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS appointments (
    id            INTEGER PRIMARY KEY,
    patient_id    INTEGER NOT NULL REFERENCES patients(id),
    clinician_id  INTEGER NOT NULL REFERENCES clinicians(id),
    starts_at     TEXT NOT NULL,
    minutes       INTEGER NOT NULL,
    status        INTEGER NOT NULL,
    booked_at     TEXT NOT NULL,
    cancelled_at  TEXT,
    updated_at    TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS appointments_by_clinician ON appointments (clinician_id, starts_at);
CREATE INDEX IF NOT EXISTS appointments_by_patient ON appointments (patient_id, starts_at);

CREATE TABLE IF NOT EXISTS appointment_events (
    id              INTEGER PRIMARY KEY,
    appointment_id  INTEGER NOT NULL REFERENCES appointments(id),
    status          INTEGER NOT NULL,
    at              TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS charges (
    id              INTEGER PRIMARY KEY,
    appointment_id  INTEGER NOT NULL REFERENCES appointments(id),
    patient_id      INTEGER NOT NULL REFERENCES patients(id),
    kind            TEXT NOT NULL,
    amount_pence    INTEGER NOT NULL,
    raised_at       TEXT NOT NULL,
    UNIQUE (appointment_id, kind)
);

CREATE TABLE IF NOT EXISTS messages (
    id              INTEGER PRIMARY KEY,
    patient_id      INTEGER NOT NULL REFERENCES patients(id),
    appointment_id  INTEGER REFERENCES appointments(id),
    template        TEXT NOT NULL,
    body            TEXT NOT NULL,
    queued_at       TEXT NOT NULL,
    sent_at         TEXT
);
