-- Release 1B — imported charging data (Epic 4 US-402 / US-404 / US-405).
--
-- One charging_sessions row per (Zaptec session, local calendar month): a
-- session that crosses a month boundary is split into one row per month
-- (split_method records how the energy was apportioned). member_id is resolved
-- from the charger's assignment on the part's start date; NULL member_id is
-- "unassigned consumption" (US-304) and blocks settlement freeze.

CREATE TABLE charging_sessions (
    id                   INTEGER PRIMARY KEY AUTOINCREMENT,
    zaptec_session_id    TEXT NOT NULL,
    charger_id           INTEGER REFERENCES chargers (id),
    charger_zaptec_id    TEXT NOT NULL,
    member_id            INTEGER REFERENCES members (id),
    period_month         TEXT NOT NULL,               -- 'YYYY-MM', local calendar month
    started_at           TEXT NOT NULL,               -- ISO-8601 UTC (part start)
    ended_at             TEXT,                        -- ISO-8601 UTC (part end)
    energy_kwh           TEXT NOT NULL,               -- Decimal string
    split_method         TEXT NOT NULL DEFAULT 'none' -- none | interval | duration
                             CHECK (split_method IN ('none', 'interval', 'duration')),
    user_full_name       TEXT,
    source               TEXT NOT NULL DEFAULT 'zaptec',
    raw_json             TEXT,
    imported_at          TEXT NOT NULL,
    updated_at           TEXT NOT NULL
);
CREATE UNIQUE INDEX idx_cs_session_month
    ON charging_sessions (zaptec_session_id, period_month);
CREATE INDEX idx_cs_period ON charging_sessions (period_month);
CREATE INDEX idx_cs_member_period ON charging_sessions (member_id, period_month);
CREATE INDEX idx_cs_charger_started ON charging_sessions (charger_zaptec_id, started_at);

CREATE TABLE charging_intervals (
    id                       INTEGER PRIMARY KEY AUTOINCREMENT,
    charger_zaptec_id        TEXT NOT NULL,
    charger_id               INTEGER REFERENCES chargers (id),
    member_id                INTEGER REFERENCES members (id),
    period_month             TEXT NOT NULL,
    interval_start           TEXT NOT NULL,           -- ISO-8601 UTC
    energy_kwh               TEXT NOT NULL,
    source_session_zaptec_id TEXT,
    raw_json                 TEXT,
    imported_at              TEXT NOT NULL
);
CREATE UNIQUE INDEX idx_ci_charger_start
    ON charging_intervals (charger_zaptec_id, interval_start);
CREATE INDEX idx_ci_period ON charging_intervals (period_month);
