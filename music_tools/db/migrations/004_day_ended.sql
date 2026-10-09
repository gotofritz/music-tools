-- A day can be ended by hand: its log moves into the history, and today starts
-- blank. Nothing is deleted; starting anything on the day clears the mark and
-- the log comes back. Null is a day still being practised.

ALTER TABLE practice_day ADD COLUMN ended_at TEXT;
