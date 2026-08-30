-- Release 1B — charger management (Epic 3, deferred from 1A).
--
-- A charger is a physical unit (usually mirrored from Zaptec, but an admin may
-- also enter one by hand). Consumption is attributed to whichever member holds
-- the charger's assignment on the charging session's start date. Assignments are
-- effective-dated half-open ranges [effective_from, effective_to) with at most
-- one open row per charger; a member may hold several chargers at once (US-303).

CREATE TABLE chargers (
    id                     INTEGER PRIMARY KEY AUTOINCREMENT,
    zaptec_id              TEXT,                       -- Zaptec device id; NULL for a hand-entered charger
    name                   TEXT NOT NULL,
    serial_no              TEXT,
    installation_zaptec_id TEXT,
    circuit_zaptec_id      TEXT,
    device_type            TEXT,
    is_active              INTEGER NOT NULL DEFAULT 1,  -- mirrors Zaptec "deleted/decommissioned"
    last_synced_at         TEXT,
    raw_json               TEXT,
    created_at             TEXT NOT NULL,
    updated_at             TEXT NOT NULL
);
CREATE UNIQUE INDEX idx_chargers_zaptec_id ON chargers (zaptec_id) WHERE zaptec_id IS NOT NULL;

CREATE TABLE charger_assignments (
    id                 INTEGER PRIMARY KEY AUTOINCREMENT,
    charger_id         INTEGER NOT NULL REFERENCES chargers (id),
    member_id          INTEGER NOT NULL REFERENCES members (id),
    effective_from     TEXT NOT NULL,
    effective_to       TEXT,
    note               TEXT,
    created_at         TEXT NOT NULL,
    created_by_user_id INTEGER REFERENCES users (id)
);
CREATE INDEX idx_ca_charger ON charger_assignments (charger_id, effective_from);
CREATE INDEX idx_ca_member ON charger_assignments (member_id, effective_from);
CREATE UNIQUE INDEX idx_ca_one_open
    ON charger_assignments (charger_id) WHERE effective_to IS NULL;
