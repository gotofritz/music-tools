-- Drop module.instrument.
--
-- It came from the schema sketch in docs/plans/00-practice-app.md, where it
-- was there in case a second instrument ever turned up. It never did: every
-- row said 'bass', nothing read it, and it made the importer explain itself
-- ("the file name gives the instrument") for no benefit. One player, one
-- instrument.

ALTER TABLE module DROP COLUMN instrument;
