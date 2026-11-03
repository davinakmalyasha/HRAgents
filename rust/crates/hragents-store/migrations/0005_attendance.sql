-- Attendance: shifts plus daily check-ins. One company per database.
CREATE TABLE IF NOT EXISTS attendance_shifts (
    id            TEXT PRIMARY KEY,
    name          TEXT NOT NULL,
    start_minute  INTEGER NOT NULL CHECK (start_minute BETWEEN 0 AND 1440),
    end_minute    INTEGER NOT NULL CHECK (end_minute BETWEEN 0 AND 1440),
    grace_minutes INTEGER NOT NULL DEFAULT 10 CHECK (grace_minutes BETWEEN 0 AND 120),
    workdays_mask INTEGER NOT NULL DEFAULT 31 CHECK (workdays_mask BETWEEN 1 AND 127),
    created_at    INTEGER NOT NULL
) STRICT;

CREATE TABLE IF NOT EXISTS attendance_checkins (
    id          TEXT PRIMARY KEY,
    employee_id TEXT NOT NULL REFERENCES employees(id),
    date        TEXT NOT NULL,
    in_minute   INTEGER NOT NULL CHECK (in_minute BETWEEN 0 AND 1440),
    out_minute  INTEGER NOT NULL CHECK (out_minute BETWEEN 0 AND 1440),
    source      TEXT NOT NULL DEFAULT 'manual' CHECK (source IN ('manual','import')),
    note        TEXT,
    created_at  INTEGER NOT NULL,
    UNIQUE (employee_id, date)
) STRICT;

CREATE INDEX IF NOT EXISTS attendance_checkins_employee_date_idx
    ON attendance_checkins(employee_id, date);
CREATE INDEX IF NOT EXISTS attendance_checkins_date_idx
    ON attendance_checkins(date);

PRAGMA user_version = 5;
