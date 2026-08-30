-- Release 1C — forecasting (Epic 8) and low-balance warnings (US-805).
--
-- forecast_settings is a single admin-tunable row (id CHECK = 1) so the
-- forecast knobs live in the DB, not config.yaml. The forecast itself is a pure
-- read-model computed on demand from posted settlements + the ledger; nothing
-- else here is persisted except the notification-history row.
--
-- low_balance_notifications is the send history that de-duplicates the warning
-- emails: one row per enqueued warning, linked to its email_messages id.

CREATE TABLE forecast_settings (
    id                         INTEGER PRIMARY KEY CHECK (id = 1),
    rate_override_ore_per_kwh  INTEGER,
    buffer_months              REAL    NOT NULL DEFAULT 2.0,
    notify_cooldown_days       INTEGER NOT NULL DEFAULT 14,
    lookback_settlements       INTEGER NOT NULL DEFAULT 3,
    updated_at                 TEXT,
    updated_by_user_id         INTEGER REFERENCES users (id)
);
INSERT INTO forecast_settings (id) VALUES (1);

CREATE TABLE low_balance_notifications (
    id                        INTEGER PRIMARY KEY AUTOINCREMENT,
    member_id                 INTEGER NOT NULL REFERENCES members (id),
    severity                  TEXT NOT NULL CHECK (severity IN ('low', 'critical')),
    balance_ore               INTEGER NOT NULL,
    recommended_minimum_ore   INTEGER NOT NULL,
    forecast_monthly_cost_ore INTEGER NOT NULL,
    email_message_id          INTEGER REFERENCES email_messages (id),
    created_at                TEXT NOT NULL
);
CREATE INDEX idx_lbn_member ON low_balance_notifications (member_id, created_at DESC);
