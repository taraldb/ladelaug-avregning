-- Release 1B — settlement engine (Epic 6).
--
-- A settlement is one calendar month (period_month 'YYYY-MM', UNIQUE). It moves
-- draft -> posted; posting is irreversible and writes one 'settlement_charge'
-- ledger row per member. The participation / consumption / balance snapshot is
-- frozen into settlement_members at the freeze step (US-602, US-203).
--
-- This migration also rebuilds ledger_transactions to widen its txn_type CHECK
-- and add a settlement_id column (SQLite cannot ALTER a CHECK constraint).

CREATE TABLE settlements (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    period_month        TEXT NOT NULL,
    status              TEXT NOT NULL DEFAULT 'draft' CHECK (status IN ('draft', 'posted')),
    invoice_kwh         TEXT,                       -- admin-entered actual kWh from the invoice
    invoice_total_nok   TEXT,                       -- sum of invoice lines, for cross-check
    grid_kwh            TEXT,                       -- metered total captured at freeze
    attachment_filename TEXT,
    attachment_path     TEXT,                       -- relative to state/
    note                TEXT,
    usage_frozen_at     TEXT,
    created_at          TEXT NOT NULL,
    created_by_user_id  INTEGER REFERENCES users (id),
    posted_at           TEXT,
    posted_by_user_id   INTEGER REFERENCES users (id)
);
CREATE UNIQUE INDEX idx_settlements_month ON settlements (period_month);

CREATE TABLE settlement_invoice_lines (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    settlement_id     INTEGER NOT NULL REFERENCES settlements (id),
    description       TEXT NOT NULL,
    category          TEXT,
    allocation_method TEXT NOT NULL CHECK (allocation_method IN ('equal', 'consumption')),
    amount_ore        INTEGER NOT NULL,
    amount_nok        TEXT NOT NULL,
    sort_order        INTEGER NOT NULL DEFAULT 0,
    created_at        TEXT NOT NULL
);
CREATE INDEX idx_sil_settlement ON settlement_invoice_lines (settlement_id, sort_order);

-- The frozen snapshot: who was in the split, their consumption, balance before.
CREATE TABLE settlement_members (
    id                 INTEGER PRIMARY KEY AUTOINCREMENT,
    settlement_id      INTEGER NOT NULL REFERENCES settlements (id),
    member_id          INTEGER NOT NULL REFERENCES members (id),
    member_reference   TEXT NOT NULL,
    full_name          TEXT NOT NULL,
    is_active          INTEGER NOT NULL,
    participates_equal INTEGER NOT NULL,
    consumption_kwh    TEXT NOT NULL DEFAULT '0',
    session_count      INTEGER NOT NULL DEFAULT 0,
    balance_before_ore INTEGER,
    snapshot_json      TEXT
);
CREATE UNIQUE INDEX idx_sm_settlement_member ON settlement_members (settlement_id, member_id);

CREATE TABLE settlement_allocations (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    settlement_id   INTEGER NOT NULL REFERENCES settlements (id),
    member_id       INTEGER NOT NULL REFERENCES members (id),
    invoice_line_id INTEGER REFERENCES settlement_invoice_lines (id),
    kind            TEXT NOT NULL CHECK (kind IN ('equal', 'consumption')),
    amount_ore      INTEGER NOT NULL,
    amount_nok      TEXT NOT NULL
);
CREATE INDEX idx_sa_settlement ON settlement_allocations (settlement_id, member_id);

CREATE TABLE late_session_flags (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    zaptec_session_id   TEXT NOT NULL,
    charger_zaptec_id   TEXT,
    period_month        TEXT NOT NULL,
    settlement_id       INTEGER REFERENCES settlements (id),
    kind                TEXT NOT NULL CHECK (kind IN ('new', 'changed')),
    detail_json         TEXT,
    detected_at         TEXT NOT NULL,
    resolved_at         TEXT,
    resolved_by_user_id INTEGER REFERENCES users (id),
    note                TEXT
);
CREATE INDEX idx_lsf_month ON late_session_flags (period_month, resolved_at);
CREATE UNIQUE INDEX idx_lsf_session ON late_session_flags (zaptec_session_id, period_month, kind);

-- --- ledger_transactions rebuild (widen txn_type, add settlement_id) ---------

DROP TRIGGER trg_ledger_no_update;
DROP TRIGGER trg_ledger_no_delete;
DROP INDEX idx_ledger_member;
DROP INDEX idx_ledger_one_reversal;

CREATE TABLE ledger_transactions_new (
    id                      INTEGER PRIMARY KEY AUTOINCREMENT,
    member_id               INTEGER NOT NULL REFERENCES members (id),
    txn_type                TEXT NOT NULL CHECK (txn_type IN (
                                'payment', 'payment_reversal',
                                'adjustment_credit', 'adjustment_debit',
                                'settlement_charge', 'settlement_reversal')),
    amount_ore              INTEGER NOT NULL,
    amount_nok              TEXT NOT NULL,
    currency                TEXT NOT NULL DEFAULT 'NOK',
    value_date              TEXT NOT NULL,
    reason                  TEXT,
    reference               TEXT,
    reverses_transaction_id INTEGER REFERENCES ledger_transactions_new (id),
    settlement_id           INTEGER REFERENCES settlements (id),
    created_by_user_id      INTEGER REFERENCES users (id),
    recorded_at             TEXT NOT NULL
);

INSERT INTO ledger_transactions_new
    (id, member_id, txn_type, amount_ore, amount_nok, currency, value_date,
     reason, reference, reverses_transaction_id, settlement_id, created_by_user_id, recorded_at)
SELECT id, member_id, txn_type, amount_ore, amount_nok, currency, value_date,
       reason, reference, reverses_transaction_id, NULL, created_by_user_id, recorded_at
FROM ledger_transactions;

DROP TABLE ledger_transactions;
ALTER TABLE ledger_transactions_new RENAME TO ledger_transactions;

CREATE INDEX idx_ledger_member ON ledger_transactions (member_id, id);
CREATE UNIQUE INDEX idx_ledger_one_reversal
    ON ledger_transactions (reverses_transaction_id)
    WHERE reverses_transaction_id IS NOT NULL;
CREATE INDEX idx_ledger_settlement
    ON ledger_transactions (settlement_id) WHERE settlement_id IS NOT NULL;

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
