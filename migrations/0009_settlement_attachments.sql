-- Multiple invoice attachments per settlement.
--
-- Until now a settlement held at most one invoice file, in
-- ``settlements.attachment_filename`` / ``attachment_path``. Admins need to keep
-- several supplier invoices per month and to add/remove them after the
-- settlement is posted. This table is the new source of truth; the two legacy
-- columns are left in place (unused) so old backups still load.

CREATE TABLE settlement_attachments (
    id                   INTEGER PRIMARY KEY,
    settlement_id        INTEGER NOT NULL REFERENCES settlements(id),
    filename             TEXT NOT NULL,          -- sanitised original name
    path                 TEXT NOT NULL,          -- relative to state/
    bytes                INTEGER NOT NULL DEFAULT 0,
    uploaded_at          TEXT NOT NULL,
    uploaded_by_user_id  INTEGER REFERENCES users(id)
);

CREATE INDEX idx_satt_settlement ON settlement_attachments (settlement_id, id);

-- Carry the existing single attachment over as the first row.
INSERT INTO settlement_attachments
    (settlement_id, filename, path, bytes, uploaded_at, uploaded_by_user_id)
SELECT id,
       attachment_filename,
       attachment_path,
       0,
       COALESCE(posted_at, created_at),
       COALESCE(posted_by_user_id, created_by_user_id)
FROM settlements
WHERE attachment_path IS NOT NULL
  AND attachment_filename IS NOT NULL;
