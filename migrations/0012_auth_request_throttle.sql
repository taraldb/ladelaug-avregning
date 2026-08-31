-- Rate limiting for the passwordless flows (magic-link sign-in, password
-- reset). Mirrors login_attempts: one row per issuance attempt, swept after
-- 24h. Checked before the account lookup so throttling never reveals whether
-- an email is registered.

CREATE TABLE auth_request_attempts (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    scope        TEXT NOT NULL,          -- 'magic_link' | 'password_reset'
    email_key    TEXT NOT NULL,          -- normalised email the request targeted
    ip           TEXT NOT NULL,
    occurred_at  TEXT NOT NULL
);
CREATE INDEX idx_auth_req_scope_email ON auth_request_attempts (scope, email_key, occurred_at);
CREATE INDEX idx_auth_req_scope_ip ON auth_request_attempts (scope, ip, occurred_at);
