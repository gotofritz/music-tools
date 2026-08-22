-- `musescore` was the wrong name for the kind: nothing about it is MuseScore's
-- but the extension one tune happened to have. A score is a score — a `.mscz`,
-- a PDF, whatever the machine opens — and nothing here has ever looked at the
-- file itself. Only the word changes; what is attached stays attached.

UPDATE media_source SET kind = 'score' WHERE kind = 'musescore';
