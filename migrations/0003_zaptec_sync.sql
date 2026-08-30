-- Release 1B — Zaptec connection + sync bookkeeping (Epic 4 US-401 / US-403).
--
-- Credentials live in config, not the DB. These tables record which
-- installation is mirrored and the outcome of every sync run (US-1104 health).

CREATE TABLE zaptec_installations (
    id                 INTEGER PRIMARY KEY AUTOINCREMENT,
    zaptec_id          TEXT NOT NULL,
    name               TEXT,
    raw_json           TEXT,
    first_connected_at TEXT NOT NULL,
    updated_at         TEXT NOT NULL
);
CREATE UNIQUE INDEX idx_zaptec_installations_zid ON zaptec_installations (zaptec_id);

CREATE TABLE sync_runs (
    id                 INTEGER PRIMARY KEY AUTOINCREMENT,
    kind               TEXT NOT NULL CHECK (kind IN ('chargers', 'sessions', 'intervals')),
    status             TEXT NOT NULL CHECK (status IN ('ok', 'error', 'partial')),
    started_at         TEXT NOT NULL,
    finished_at        TEXT NOT NULL,
    window_from        TEXT,
    window_to          TEXT,
    items_seen         INTEGER NOT NULL DEFAULT 0,
    items_imported     INTEGER NOT NULL DEFAULT 0,
    error              TEXT,
    created_by_user_id INTEGER REFERENCES users (id)
);
CREATE INDEX idx_sync_runs_kind_time ON sync_runs (kind, started_at DESC);
