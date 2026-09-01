-- Let an admin browse the member portal "as" a specific member, read-only.
-- The impersonation target lives on the admin's own session row so it vanishes
-- the moment that session is revoked (logout, user-disable, expiry) — it can
-- never outlive the session and no separate cookie has to be trusted.

ALTER TABLE sessions ADD COLUMN view_as_member_id INTEGER REFERENCES members (id);
