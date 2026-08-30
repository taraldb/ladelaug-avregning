-- Release 1A initial schema.
-- Frozen once applied: later schema changes go in new NNNN_*.sql files.
--
-- Conventions:
--   * timestamps  -> ISO-8601 UTC TEXT  (datetime.now(UTC).isoformat())
--   * effective dates -> 'YYYY-MM-DD' TEXT, Europe/Oslo calendar days
--   * effective-dated ranges are half-open [effective_from, effective_to);
--     effective_to IS NULL means "still open"
--   * money -> amount_ore INTEGER (signed, + raises balance) plus an exact
--     amount_nok TEXT Decimal string written from the same in-memory Decimal

-- members is referenced by users.member_id, so define it first.
CREATE TABLE members (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    member_reference  TEXT NOT NULL,
    full_name         TEXT NOT NULL,
    email             TEXT,
    join_date         TEXT NOT NULL,
    created_at        TEXT NOT NULL,
    updated_at        TEXT NOT NULL
);
CREATE UNIQUE INDEX idx_members_reference ON members (member_reference);

CREATE TABLE users (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    email               TEXT NOT NULL,
    email_normalized    TEXT NOT NULL,
    password_hash       TEXT,
    role                TEXT NOT NULL CHECK (role IN ('admin', 'member')),
    disabled            INTEGER NOT NULL DEFAULT 0,
    member_id           INTEGER REFERENCES members (id),
    password_changed_at TEXT,
    created_at          TEXT NOT NULL,
    updated_at          TEXT NOT NULL
);
CREATE UNIQUE INDEX idx_users_email_normalized ON users (email_normalized);
CREATE UNIQUE INDEX idx_users_member_id ON users (member_id) WHERE member_id IS NOT NULL;

CREATE TABLE sessions (
    id           TEXT PRIMARY KEY,          -- sha256(token) hex; raw token never stored
    user_id      INTEGER NOT NULL REFERENCES users (id),
    created_at   TEXT NOT NULL,
    expires_at   TEXT NOT NULL,
    last_seen_at TEXT NOT NULL,
    revoked_at   TEXT,
    ip           TEXT,
    user_agent   TEXT
);
CREATE INDEX idx_sessions_user_id ON sessions (user_id);
CREATE INDEX idx_sessions_expires_at ON sessions (expires_at);

CREATE TABLE login_attempts (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    email_normalized TEXT NOT NULL,
    ip               TEXT NOT NULL,
    occurred_at      TEXT NOT NULL,
    succeeded        INTEGER NOT NULL
);
CREATE INDEX idx_login_attempts_lookup
    ON login_attempts (email_normalized, ip, occurred_at);

CREATE TABLE member_status_periods (
    id                 INTEGER PRIMARY KEY AUTOINCREMENT,
    member_id          INTEGER NOT NULL REFERENCES members (id),
    status             TEXT NOT NULL CHECK (status IN ('active', 'inactive')),
    effective_from     TEXT NOT NULL,
    effective_to       TEXT,
    note               TEXT,
    created_at         TEXT NOT NULL,
    created_by_user_id INTEGER REFERENCES users (id)
);
CREATE INDEX idx_msp_member ON member_status_periods (member_id, effective_from);
CREATE UNIQUE INDEX idx_msp_one_open
    ON member_status_periods (member_id) WHERE effective_to IS NULL;

CREATE TABLE settlement_participation (
    id                 INTEGER PRIMARY KEY AUTOINCREMENT,
    member_id          INTEGER NOT NULL REFERENCES members (id),
    participates       INTEGER NOT NULL,
    effective_from     TEXT NOT NULL,
    effective_to       TEXT,
    reason             TEXT,
    created_at         TEXT NOT NULL,
    created_by_user_id INTEGER REFERENCES users (id)
);
CREATE INDEX idx_sp_member ON settlement_participation (member_id, effective_from);
CREATE UNIQUE INDEX idx_sp_one_open
    ON settlement_participation (member_id) WHERE effective_to IS NULL;

-- Append-only. No UPDATE, no DELETE — corrections and reversals are new rows.
CREATE TABLE ledger_transactions (
    id                      INTEGER PRIMARY KEY AUTOINCREMENT,
    member_id               INTEGER NOT NULL REFERENCES members (id),
    txn_type                TEXT NOT NULL CHECK (txn_type IN (
                                'payment', 'payment_reversal',
                                'adjustment_credit', 'adjustment_debit')),
    amount_ore              INTEGER NOT NULL,
    amount_nok              TEXT NOT NULL,
    currency                TEXT NOT NULL DEFAULT 'NOK',
    value_date              TEXT NOT NULL,
    reason                  TEXT,
    reference               TEXT,
    reverses_transaction_id INTEGER REFERENCES ledger_transactions (id),
    created_by_user_id      INTEGER REFERENCES users (id),
    recorded_at             TEXT NOT NULL
);
CREATE INDEX idx_ledger_member ON ledger_transactions (member_id, id);
CREATE UNIQUE INDEX idx_ledger_one_reversal
    ON ledger_transactions (reverses_transaction_id)
    WHERE reverses_transaction_id IS NOT NULL;

CREATE TRIGGER trg_ledger_no_update
BEFORE UPDATE ON ledger_transactions
BEGIN
    SELECT RAISE(ABORT, 'ledger_transactions is append-only');
END;
CREATE TRIGGER trg_ledger_no_delete
BEFORE DELETE ON ledger_transactions
BEGIN
    SELECT RAISE(ABORT, 'ledger_transactions is append-only');
END;

-- Append-only.
CREATE TABLE audit_events (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    occurred_at   TEXT NOT NULL,
    actor_user_id INTEGER REFERENCES users (id),
    actor_label   TEXT NOT NULL,
    event_type    TEXT NOT NULL,
    entity_type   TEXT NOT NULL,
    entity_id     TEXT,
    summary       TEXT NOT NULL,
    detail_json   TEXT,
    ip            TEXT
);
CREATE INDEX idx_audit_time ON audit_events (occurred_at DESC);
CREATE INDEX idx_audit_type_time ON audit_events (event_type, occurred_at DESC);
CREATE INDEX idx_audit_entity ON audit_events (entity_type, entity_id);
CREATE INDEX idx_audit_actor ON audit_events (actor_user_id, occurred_at DESC);

CREATE TRIGGER trg_audit_no_update
BEFORE UPDATE ON audit_events
BEGIN
    SELECT RAISE(ABORT, 'audit_events is append-only');
END;
CREATE TRIGGER trg_audit_no_delete
BEFORE DELETE ON audit_events
BEGIN
    SELECT RAISE(ABORT, 'audit_events is append-only');
END;
