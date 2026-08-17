"""The material an exercise is practised from.

An exercise used to be a name and a schedule; the tune itself lived in
Transcribe!, in a folder of scores, on YouTube. Here it is attached: a local
audio or video file, a YouTube URL, a MuseScore file, plain text — or several
at once, since one tune can be audio downloaded from a URL with the score kept
in a file beside it.

This module is to media what `domain/catalogue.py` is to the catalogue: the
decisions live here and the SQL lives in `db/repository.py`. Three of them are
load-bearing.

- **Files stay on disk.** A source row holds an absolute path and nothing is
  ever copied — the rule since Phase 2.
- **Every path in from the browser is confined to configured roots.** The
  scores directory and the app data directory, unless
  `MUSIC_TOOLS_MEDIA_ROOTS` says otherwise. The server binds `127.0.0.1` and
  this is one user's machine, but `?path=/etc/passwd` is still a mistake worth
  not making.
- **Every audio file is in a group, and most groups have one member.** A
  single file gets a group made for it, so a set of one and a set of stems are
  the same shape downstream: Phase 5b plays a set, and Phase 6 hangs markers
  off the group. Adding a file to an existing group is what makes a track set,
  and it is the only way to make one.
"""

import os
import re
import sqlite3
from datetime import datetime
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from pydantic import BaseModel

from music_tools.db import repository as repo
from music_tools.db.connection import default_db_path, transaction
from music_tools.domain.models import MediaGroup, MediaSource

#: What an attachment can be. `file` is audio or video and is the only kind
#: that plays, which is why it is the only one with a group.
KINDS = ("file", "youtube", "musescore", "text")

#: The kinds that name something on disk.
PATH_KINDS = ("file", "musescore")

#: Where a path is allowed to point unless the environment says otherwise: the
#: scores directory, and the directory the database lives in.
DEFAULT_ROOTS = (Path("~/Documents/MuseScore4/Scores/TUNES"),)


class NotFound(LookupError):
    """No exercise with that id."""


class UnknownMedia(LookupError):
    """No media source or group with that id."""


class BadMedia(ValueError):
    """The attachment does not say what it is, or says two things at once."""


class OutsideRoots(ValueError):
    """The path resolves outside the configured roots."""


class MissingFile(ValueError):
    """The path is inside the roots, and there is nothing there."""


class MediaCard(BaseModel):
    """One thing on the page: a track set, or a single non-playing source.

    A set of one and a set of eight are one card either way — that is what the
    group is for. `sources` is never empty.
    """

    group: MediaGroup | None = None
    sources: list[MediaSource]

    @property
    def kind(self) -> str:
        return self.sources[0].kind

    @property
    def is_set(self) -> bool:
        return len(self.sources) > 1

    @property
    def label(self) -> str | None:
        if self.group is not None and self.group.label:
            return self.group.label
        return self.sources[0].label

    @property
    def position(self) -> int:
        """Where this card sits in the exercise, whichever row carries it."""
        return self.group.position if self.group else self.sources[0].position


def youtube_embed(url: str | None) -> str | None:
    """The embed URL for a YouTube link, or `None` if it is not one.

    Downloading is another app's job, so a YouTube attachment is a URL
    rendered as the embedded player. Anything this cannot read is shown as a
    plain link instead — which is also what the page falls back to with the
    network off.
    """
    if not url:
        return None
    parts = urlsplit(url)
    host = parts.netloc.lower().removeprefix("www.")
    video = ""
    if host in ("youtube.com", "m.youtube.com", "youtube-nocookie.com"):
        if parts.path == "/watch":
            video = parse_qs(parts.query).get("v", [""])[0]
        elif parts.path.startswith(("/embed/", "/shorts/", "/live/")):
            video = parts.path.split("/")[2]
    elif host == "youtu.be":
        video = parts.path.lstrip("/")
    if not re.fullmatch(r"[\w-]{6,20}", video):
        return None
    return f"https://www.youtube.com/embed/{video}"


def media_roots() -> tuple[Path, ...]:
    """The directories a path may point into.

    `MUSIC_TOOLS_MEDIA_ROOTS` is a `:`-separated list, the way `PATH` is. The
    default is the scores directory plus the app data directory, which is where
    Phase 5's render cache will live.
    """
    written = os.environ.get("MUSIC_TOOLS_MEDIA_ROOTS")
    if written:
        return tuple(
            Path(part).expanduser() for part in written.split(os.pathsep) if part
        )
    return tuple(root.expanduser() for root in DEFAULT_ROOTS) + (
        default_db_path().parent,
    )


def resolve_within_roots(path: str, *, roots: tuple[Path, ...] | None = None) -> Path:
    """An absolute path inside the roots, or `OutsideRoots`.

    Resolved before it is compared, so `..` and a symlink out of a root are
    both refused rather than followed. A relative path is refused too: an
    attachment is stored absolute, and there is no sensible directory to read
    one against — the browser's idea of "here" is not the server's.
    """
    written = Path(path).expanduser()
    if not written.is_absolute():
        raise OutsideRoots(f"{path} is not an absolute path")
    resolved = written.resolve()
    for root in roots if roots is not None else media_roots():
        if resolved.is_relative_to(root.expanduser().resolve()):
            return resolved
    raise OutsideRoots(f"{path} is outside the configured roots")


def attach(
    conn: sqlite3.Connection,
    *,
    exercise_id: int,
    kind: str,
    now: datetime,
    path: str | None = None,
    url: str | None = None,
    body: str | None = None,
    label: str | None = None,
    group_id: int | None = None,
    roots: tuple[Path, ...] | None = None,
) -> MediaSource:
    """Attach one thing to an exercise, and say what it is.

    A `file` with no `group_id` gets a group of its own; passing one adds a
    track to that set, which is checked by `add_to_set`. Nothing else may
    carry a group: a YouTube embed cannot be sample-locked to anything, and
    text has no timeline.
    """
    if kind not in KINDS:
        raise BadMedia(f"no such kind of media: {kind}")
    if repo.get_exercise(conn, exercise_id) is None:
        raise NotFound(exercise_id)

    given = {"path": path, "url": url, "body": body}
    wanted = {"file": "path", "musescore": "path", "youtube": "url", "text": "body"}[
        kind
    ]
    for name, value in given.items():
        if name != wanted and value:
            raise BadMedia(f"a {kind} attachment has no {name}")
    if not given[wanted]:
        raise BadMedia(f"a {kind} attachment needs a {wanted}")
    if group_id is not None and kind != "file":
        raise BadMedia(f"a {kind} attachment cannot be part of a track set")

    if kind in PATH_KINDS:
        assert path is not None  # the check above; this is for the type checker
        resolved = resolve_within_roots(path, roots=roots)
        if not resolved.is_file():
            raise MissingFile(f"there is nothing at {resolved}")
        path = str(resolved)

    if kind == "file" and group_id is not None:
        return add_to_set(
            conn, group_id=group_id, path=str(path), label=label, now=now, roots=roots
        )

    with transaction(conn):
        if kind != "file":
            return repo.create_media_source(
                conn,
                exercise_id=exercise_id,
                kind=kind,
                position=repo.next_media_position(conn, exercise_id=exercise_id),
                added_at=now,
                path=path,
                url=url,
                body=body,
                label=label,
            )
        group = repo.create_media_group(
            conn,
            exercise_id=exercise_id,
            position=repo.next_media_position(conn, exercise_id=exercise_id),
            added_at=now,
        )
        return repo.create_media_source(
            conn,
            exercise_id=exercise_id,
            group_id=group.id,
            kind=kind,
            position=0,
            added_at=now,
            path=path,
            label=label,
        )


def detach(conn: sqlite3.Connection, *, source_id: int) -> None:
    """Take an attachment off an exercise. The file itself is left alone.

    A group with nothing left in it goes too: an empty set is not a card, and
    keeping one would put a hole in the exercise's ordering.
    """
    source = _source(conn, source_id)
    with transaction(conn):
        repo.delete_media_source(conn, source.id)
        if source.group_id is not None and not repo.media_sources_in_group(
            conn, group_id=source.group_id
        ):
            repo.delete_media_group(conn, source.group_id)


def move(conn: sqlite3.Connection, *, source_id: int, direction: str) -> None:
    """Move a card one place up or down the exercise.

    Positions are swapped rather than renumbered, so a move is one write per
    card and the numbers stay small. Moving the top card up, or the bottom one
    down, does nothing — there is nowhere for it to go.
    """
    if direction not in ("up", "down"):
        raise ValueError(f"a card moves up or down, not {direction}")
    source = _source(conn, source_id)
    cards = exercise_media(conn, exercise_id=source.exercise_id)
    index = next(
        position
        for position, card in enumerate(cards)
        if any(track.id == source.id for track in card.sources)
    )
    other = index - 1 if direction == "up" else index + 1
    if other < 0 or other >= len(cards):
        return
    with transaction(conn):
        _place(conn, cards[index], position=cards[other].position)
        _place(conn, cards[other], position=cards[index].position)


def exercise_media(conn: sqlite3.Connection, *, exercise_id: int) -> list[MediaCard]:
    """What the page shows for an exercise, in the order it shows it.

    One card per group and one per ungrouped source, ordered by the position
    each carries. Reading both sequences here is what lets a track set and a
    YouTube embed sit in one list.
    """
    cards = [
        MediaCard(
            group=group, sources=repo.media_sources_in_group(conn, group_id=group.id)
        )
        for group in repo.media_groups_for_exercise(conn, exercise_id=exercise_id)
    ]
    cards += [
        MediaCard(sources=[source])
        for source in repo.media_sources_for_exercise(conn, exercise_id=exercise_id)
        if source.group_id is None
    ]
    return sorted(cards, key=lambda card: (card.position, card.sources[0].id))


def add_to_set(
    conn: sqlite3.Connection,
    *,
    group_id: int,
    path: str,
    now: datetime,
    label: str | None = None,
    roots: tuple[Path, ...] | None = None,
) -> MediaSource:
    """Add a file to an existing group: the only way to make a track set.

    Step 5 of the plan fills this in with the two checks a set has to pass.
    """
    group = repo.get_media_group(conn, group_id)
    if group is None:
        raise UnknownMedia(group_id)
    resolved = resolve_within_roots(path, roots=roots)
    if not resolved.is_file():
        raise MissingFile(f"there is nothing at {resolved}")
    with transaction(conn):
        return repo.create_media_source(
            conn,
            exercise_id=group.exercise_id,
            group_id=group.id,
            kind="file",
            position=repo.next_track_position(conn, group_id=group.id),
            added_at=now,
            path=str(resolved),
            label=label,
        )


def _place(conn: sqlite3.Connection, card: MediaCard, *, position: int) -> None:
    """Write a card's exercise-level position, wherever that position lives."""
    if card.group is not None:
        repo.update_media_group(conn, card.group.id, position=position)
    else:
        repo.update_media_source(conn, card.sources[0].id, position=position)


def _source(conn: sqlite3.Connection, source_id: int) -> MediaSource:
    source = repo.get_media_source(conn, source_id)
    if source is None:
        raise UnknownMedia(source_id)
    return source
