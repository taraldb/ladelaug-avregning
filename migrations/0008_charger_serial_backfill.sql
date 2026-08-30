-- Backfill charger.serial_no for Zaptec-mirrored rows.
--
-- Until now the Zaptec importer stored Zaptec's ``SerialNo`` field as
-- ``serial_no``. In some installations that field just duplicates the display
-- name, so a synced charger showed the same string in both "Navn" and
-- "Serienr.". The real hardware id lives in the payload's ``DeviceId`` (a
-- ``ZPR…`` value), which is what admins hand-entered for manual chargers.
--
-- The importer now maps ``serial_no`` from ``DeviceId``; this fixes the rows
-- that were already synced. Only touch rows whose ``serial_no`` is still the
-- unhelpful default (NULL or equal to the name) so a value an admin corrected
-- by hand is left alone.

UPDATE chargers
   SET serial_no  = json_extract(raw_json, '$.DeviceId'),
       updated_at = strftime('%Y-%m-%dT%H:%M:%SZ', 'now')
 WHERE zaptec_id IS NOT NULL
   AND json_extract(raw_json, '$.DeviceId') IS NOT NULL
   AND json_extract(raw_json, '$.DeviceId') <> ''
   AND (serial_no IS NULL OR serial_no = name);
