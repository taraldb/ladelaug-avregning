-- Release 1B — outgoing email queue (Epic 10) and single-use auth tokens
-- (US-102 magic-link, US-103 password reset).

CREATE TABLE email_messages (
    id                   INTEGER PRIMARY KEY AUTOINCREMENT,
    to_address           TEXT NOT NULL,
    subject              TEXT NOT NULL,
    body_text            TEXT NOT NULL,
    body_html            TEXT,
    template             TEXT,
    related_entity_type  TEXT,
    related_entity_id    TEXT,
    status               TEXT NOT NULL DEFAULT 'queued'
                             CHECK (status IN ('queued', 'sent', 'failed')),
    attempts             INTEGER NOT NULL DEFAULT 0,
    max_attempts         INTEGER NOT NULL DEFAULT 5,
    last_error           TEXT,
    next_attempt_at      TEXT NOT NULL,
    created_at           TEXT NOT NULL,
    sent_at              TEXT
);
CREATE INDEX idx_email_pending ON email_messages (status, next_attempt_at);
CREATE INDEX idx_email_related ON email_messages (related_entity_type, related_entity_id);

CREATE TABLE auth_tokens (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id       INTEGER NOT NULL REFERENCES users (id),
    kind          TEXT NOT NULL CHECK (kind IN ('magic_link', 'password_reset')),
    token_hash    TEXT NOT NULL,
    created_at    TEXT NOT NULL,
    expires_at    TEXT NOT NULL,
    used_at       TEXT,
    requested_ip  TEXT
);
CREATE UNIQUE INDEX idx_auth_tokens_hash ON auth_tokens (token_hash);
CREATE INDEX idx_auth_tokens_user ON auth_tokens (user_id, kind);
