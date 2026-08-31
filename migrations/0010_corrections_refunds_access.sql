-- Release 1D — settlement corrections (Epic 7), refunds (US-505), member
-- departure (US-204), charging-access status (US-305).
--
-- This migration widens ledger_transactions.txn_type to add 'refund' and
-- 'settlement_correction' (SQLite cannot ALTER a CHECK constraint, so the table
-- is rebuilt — same pattern as 0005), and adds three tables:
--   * settlement_corrections / settlement_correction_members — the audit trail
--     for a recomputed posted settlement (original preserved, US-703);
--   * charging_access_events — the warned / disabled / restored log (US-305).

-- --- ledger_transactions rebuild (widen txn_type) ---------------------------

DROP TRIGGER trg_ledger_no_update;
DROP TRIGGER trg_ledger_no_delete;
DROP INDEX idx_ledger_member;
DROP INDEX idx_ledger_one_reversal;
DROP INDEX idx_ledger_settlement;

CREATE TABLE ledger_transactions_new (
    id                      INTEGER PRIMARY KEY AUTOINCREMENT,
    member_id               INTEGER NOT NULL REFERENCES members (id),
    txn_type                TEXT NOT NULL CHECK (txn_type IN (
                                'payment', 'payment_reversal',
                                'adjustment_credit', 'adjustment_debit',
                                'settlement_charge', 'settlement_reversal',
                                'settlement_correction', 'refund')),
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
       reason, reference, reverses_transaction_id, settlement_id, created_by_user_id, recorded_at
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

-- --- settlement corrections (Epic 7) ---------------------------------------

CREATE TABLE settlement_corrections (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    settlement_id       INTEGER NOT NULL REFERENCES settlements (id),
    sequence            INTEGER NOT NULL,          -- 1-based, per settlement
    original_total_ore  INTEGER NOT NULL,
    corrected_total_ore INTEGER NOT NULL,
    basis_json          TEXT,                      -- the full assessment dict
    created_at          TEXT NOT NULL,
    created_by_user_id  INTEGER REFERENCES users (id)
);
CREATE UNIQUE INDEX idx_scorr_seq ON settlement_corrections (settlement_id, sequence);

CREATE TABLE settlement_correction_members (
    id                     INTEGER PRIMARY KEY AUTOINCREMENT,
    correction_id          INTEGER NOT NULL REFERENCES settlement_corrections (id),
    member_id              INTEGER NOT NULL REFERENCES members (id),
    consumption_kwh_before TEXT NOT NULL,
    consumption_kwh_after  TEXT NOT NULL,
    original_charge_ore    INTEGER NOT NULL,
    corrected_charge_ore   INTEGER NOT NULL,
    delta_ore              INTEGER NOT NULL,
    ledger_txn_id          INTEGER REFERENCES ledger_transactions (id)
);
CREATE INDEX idx_scm_correction ON settlement_correction_members (correction_id, member_id);

-- --- charging-access status (US-305) -------------------------------------

CREATE TABLE charging_access_events (
    id                 INTEGER PRIMARY KEY AUTOINCREMENT,
    member_id          INTEGER NOT NULL REFERENCES members (id),
    action             TEXT NOT NULL CHECK (action IN ('warned', 'disabled', 'restored')),
    reason             TEXT,
    note               TEXT,
    created_at         TEXT NOT NULL,
    created_by_user_id INTEGER REFERENCES users (id),
    email_message_id   INTEGER REFERENCES email_messages (id)
);
CREATE INDEX idx_cae_member ON charging_access_events (member_id, id DESC);
