-- Let the board publish a frozen settlement draft to its members for preview
-- before posting. A draft is visible to a member only once an admin has
-- explicitly shared it (draft_shared_at set) AND it is frozen AND the member is
-- in its snapshot. The member-facing report is watermarked "UTKAST".

ALTER TABLE settlements ADD COLUMN draft_shared_at TEXT;
ALTER TABLE settlements ADD COLUMN draft_shared_by_user_id INTEGER REFERENCES users (id);
