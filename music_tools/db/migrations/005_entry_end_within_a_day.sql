-- An edited time used to keep the date its field already had, so an end moved
-- back across midnight (00:05 to 23:58) landed a day in the future, and one
-- moved forward across it (23:55 to 00:10) a day in the past. No line lasts a
-- day or runs backwards, so either is put back within a day of its start.
-- Edited times are whole minutes, so dropping fractions of a second loses
-- nothing.

UPDATE practice_entry
SET ended_at = strftime('%Y-%m-%dT%H:%M:%S', ended_at, '-1 day')
WHERE ended_at IS NOT NULL
  AND julianday(ended_at) >= julianday(started_at) + 1;

UPDATE practice_entry
SET ended_at = strftime('%Y-%m-%dT%H:%M:%S', ended_at, '+1 day')
WHERE ended_at IS NOT NULL
  AND julianday(ended_at) < julianday(started_at);
