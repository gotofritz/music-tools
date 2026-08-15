-- The practice schema: modules, exercises, and the day log.
--
-- Durations, subtotals and day totals are computed, never stored. The
-- snapshot columns on practice_entry (description, speed, bpm, log_group) are
-- deliberate duplication: the log is a record and must not change when an
-- exercise is renamed or moved.

CREATE TABLE module (
  id INTEGER PRIMARY KEY,
  name TEXT NOT NULL UNIQUE,          -- "SLAP", "SONGS"
  slug TEXT NOT NULL UNIQUE,
  log_group TEXT NOT NULL,            -- "TECHNIQUE", "REPERTOIRE" (sheet A1)
  instrument TEXT NOT NULL DEFAULT 'bass',
  position INTEGER NOT NULL DEFAULT 0,
  archived_at TEXT
);

CREATE TABLE exercise (
  id INTEGER PRIMARY KEY,
  module_id INTEGER NOT NULL REFERENCES module(id),
  name TEXT NOT NULL,                 -- "Stomp!"
  style TEXT,                         -- the row's own MODULE tag: NEOSOUL, RNB
  speed TEXT,                         -- verbatim: "80%", "66", "66/1", "123/0.5"
  target_bpm REAL,                    -- the goal tempo; null = unknown
  practiced_count INTEGER NOT NULL DEFAULT 0,
  last_practiced TEXT,                -- ISO date
  next_due TEXT,                      -- ISO date
  notes TEXT,
  recorded TEXT,
  last_recorded TEXT,
  extra TEXT,                         -- JSON, per-module oddities
  archived_at TEXT
);

CREATE INDEX exercise_due ON exercise(module_id, next_due);
CREATE UNIQUE INDEX exercise_name ON exercise(module_id, name)
  WHERE archived_at IS NULL;          -- the importer's natural key

CREATE TABLE practice_day (
  id INTEGER PRIMARY KEY,
  day TEXT NOT NULL UNIQUE,           -- ISO date, 4am boundary
  notes TEXT
);

CREATE TABLE practice_entry (
  id INTEGER PRIMARY KEY,
  day_id INTEGER NOT NULL REFERENCES practice_day(id),
  exercise_id INTEGER REFERENCES exercise(id),  -- null = ad-hoc entry
  started_at TEXT NOT NULL,           -- ISO datetime
  ended_at TEXT,                      -- null = the entry running right now
  speed TEXT,                         -- snapshot, verbatim
  bpm REAL,                           -- snapshot, resolved at the time
  description TEXT NOT NULL DEFAULT '',  -- snapshot; exercises get renamed
  log_group TEXT,                     -- snapshot of module.log_group
  notes TEXT
);

-- Not unique: marking two exercises done within the same second closes one
-- entry and opens the next at the same instant. The importer's (day,
-- started_at) natural key is a lookup, not a constraint.
CREATE INDEX entry_day ON practice_entry(day_id, started_at);
