This is a sample of the google sheets app used to keep track of music practice.

BASS.csv is a sample of the main page; it keeps tracks of what was practiced on what day. The unit there is a "day", which is a block of rows. The "DAY" column shows where a new block starts
BASS SONGS.csv is a sample of one of the many exercise pages. Each row is an exercise. When completed, the information in the row is logged to BASS.csv (with some processing); and the row in BASS SONGS.csv is rotated and updated (the exact type of rotation depends on the command). The general idea is to implement spaced repetition for music exercises.

The three .gs files are the scripts that make it happen. Code.gs is the entry point, with the menu commands I use.
bass.gs is the meat of the commands. and utils.gs is self-explanatory

