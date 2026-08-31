-- In-process job scheduler.
--
-- One row per recurring job. The scheduler loop (started from the FastAPI
-- lifespan when scheduler.enabled is true) reads this table every tick and runs
-- any enabled job whose next_run_at has passed, one at a time. Schedules are
-- admin-tunable at runtime via /api/system/jobs — same "knobs live in the DB"
-- idea as forecast_settings (migration 0007).
--
-- No catch-up: next_run_at is always recomputed forward from "now" after a run,
-- so a process that was down across several scheduled slots runs each job at
-- most once when it comes back.

CREATE TABLE job_schedules (
    name               TEXT PRIMARY KEY,
    enabled            INTEGER NOT NULL DEFAULT 0,
    cron               TEXT NOT NULL,
    last_run_at        TEXT,               -- ISO8601 UTC of the last completed run
    last_status        TEXT,               -- 'ok' | 'error' | 'running'
    last_error         TEXT,
    last_duration_ms   INTEGER,
    next_run_at        TEXT,               -- ISO8601 UTC; NULL until first scheduled
    updated_at         TEXT,
    updated_by_user_id INTEGER REFERENCES users (id)
);

INSERT INTO job_schedules (name, enabled, cron) VALUES
    ('drain_mail',           0, '*/10 * * * *'),
    ('low_balance_scan',     0, '0 * * * *'),
    ('zaptec_sync_sessions', 0, '30 3 * * *');
