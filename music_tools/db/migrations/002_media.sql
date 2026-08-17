-- The material an exercise is practised from: audio, video, a score, a URL,
-- a line of text. Files stay where they are on disk and are referenced by
-- absolute path — the rule since Phase 2 — so nothing here holds bytes.
--
-- Every audio file is in a group, and most groups have one member. A single
-- attached file gets a group made for it, so there is one shape downstream:
-- Phase 5b plays a set of one, and Phase 6 hangs markers off the group without
-- caring whether the tune arrived as stems. Adding a second file to an
-- existing group is what makes a track set, and it is the only way to make one.
--
-- Solo is not stored: it is a view over the mute state, and which track is
-- soloed does not deserve to outlive the page.

CREATE TABLE media_group (       -- one player over several files; a track set
  id INTEGER PRIMARY KEY,
  exercise_id INTEGER NOT NULL REFERENCES exercise(id) ON DELETE CASCADE,
  label TEXT,                    -- "stems", "with click"
  position INTEGER NOT NULL,     -- order in the exercise
  added_at TEXT NOT NULL
);

CREATE TABLE media_source (
  id INTEGER PRIMARY KEY,
  exercise_id INTEGER NOT NULL REFERENCES exercise(id) ON DELETE CASCADE,
  group_id INTEGER REFERENCES media_group(id) ON DELETE CASCADE,
                               -- required for 'file'; null for the rest
  kind TEXT NOT NULL,          -- 'file' | 'youtube' | 'musescore' | 'text'
  path TEXT,                   -- absolute; 'file' and 'musescore'
  url TEXT,                    -- 'youtube': the embed target
  body TEXT,                   -- 'text'
  label TEXT,                  -- also the track name in a set: "bass", "drums"
  position INTEGER NOT NULL,   -- order in the exercise, or in the set
  gain REAL NOT NULL DEFAULT 1.0,
  pan REAL NOT NULL DEFAULT 0.0,     -- -1 left … +1 right
  muted INTEGER NOT NULL DEFAULT 0,
  added_at TEXT NOT NULL
);

CREATE INDEX media_source_group ON media_source(group_id, position);
CREATE INDEX media_source_exercise ON media_source(exercise_id, position);
CREATE INDEX media_group_exercise ON media_group(exercise_id, position);
