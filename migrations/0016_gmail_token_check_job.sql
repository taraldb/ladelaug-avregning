-- Daily probe of the Gmail OAuth refresh token (email.backend: gmail).
--
-- A refresh token minted while the Google OAuth app is in "Testing" status is
-- silently revoked by Google 7 days after it is issued; once that happens every
-- settlement/notification email fails at send time with no prior warning. This
-- job forces a refresh_token grant on its own schedule, so a dead token shows
-- up as a failed job on GET /api/system/health (ok -> false) well before the
-- next real send hits it. The body is a no-op unless email.backend is 'gmail'.
--
-- Ships disabled like the other jobs; enable + tune under System -> Bakgrunnsjobber.

INSERT INTO job_schedules (name, enabled, cron) VALUES
    ('gmail_token_check', 0, '0 7 * * *');
