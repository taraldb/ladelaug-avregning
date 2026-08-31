-- More request context on every audit event: the client User-Agent and the
-- actor's role at the time of the action. ADD COLUMN is DDL and is not blocked
-- by the append-only UPDATE/DELETE triggers on audit_events.

ALTER TABLE audit_events ADD COLUMN user_agent TEXT;
ALTER TABLE audit_events ADD COLUMN actor_role TEXT;
