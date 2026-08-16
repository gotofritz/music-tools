"""Per-request wiring: the connection, the clock, the rng, the templates.

The clock and the rng are dependencies rather than calls to `datetime.now()`
and the global `random`, for the same reason `cli.py` passes both down: a test
pins them with `app.dependency_overrides` and asserts exact dates.

The connection is opened per request and closed after it. SQLite in WAL mode
is happy with that, and it keeps the app free of any long-lived global state —
`create_app` takes a path, not a connection.
"""

import random
import sqlite3
from collections.abc import Iterator
from datetime import date, datetime
from pathlib import Path
from urllib.parse import urlsplit

from fastapi import Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from jinja2 import Environment, FileSystemLoader, select_autoescape

from music_tools.db.connection import open_db
from music_tools.domain.models import Exercise, PracticeEntry
from music_tools.domain.session import (
    entry_duration,
    format_due,
    format_duration,
    format_when,
    practice_day_for,
)
from music_tools.domain.tempo import format_tempo, parse_tempo

TEMPLATES = Path(__file__).parent / "templates"
STATIC = Path(__file__).parent / "static"


def get_conn(request: Request) -> Iterator[sqlite3.Connection]:
    """One connection per request, closed when it finishes."""
    conn = open_db(request.app.state.db_path, check_same_thread=False)
    try:
        yield conn
    finally:
        conn.close()


def get_now() -> datetime:
    """The clock. Overridden in tests; the only caller of `datetime.now()`."""
    return datetime.now()


def get_rng() -> random.Random:
    """The rng the scheduler jitters with. Overridden in tests."""
    return random.Random()


def get_today(now: datetime = Depends(get_now)) -> date:
    """Which practice day we are in, at the 4am boundary."""
    return practice_day_for(now)


def tempo_text(exercise: Exercise) -> str:
    """`88 BPM (66%)` when the row has a target, the raw text when it does not."""
    return format_tempo(parse_tempo(exercise.speed or "", target_bpm=exercise.target_bpm))


def duration_text(entry: PracticeEntry, now: datetime | None) -> str:
    """How long an entry has lasted; a running one counts up to `now`."""
    return format_duration(entry_duration(entry, now=now))


def _environment() -> Environment:
    env = Environment(
        loader=FileSystemLoader(TEMPLATES),
        autoescape=select_autoescape(("html",)),
        trim_blocks=True,
        lstrip_blocks=True,
    )
    env.globals.update(
        format_due=format_due,
        format_duration=format_duration,
        format_when=format_when,
        tempo_text=tempo_text,
        duration_text=duration_text,
    )
    return env


#: One environment for the process: templates are read-only files.
env = _environment()


def render(template: str, /, **context: object) -> str:
    """A fragment, or a whole page — the difference is only which template."""
    return env.get_template(template).render(**context)


def is_htmx(request: Request) -> bool:
    """Whether HTMX sent this, as opposed to a plain browser form."""
    return request.headers.get("HX-Request") == "true"


def fragment_or_redirect(request: Request, html: str) -> Response:
    """Answer HTMX with markup, and a JavaScript-less form with a redirect.

    Every action is a real `<form>` with a real `action`, so a broken or
    disabled `htmx.min.js` degrades to a page reload rather than a dead page.
    """
    if is_htmx(request):
        return HTMLResponse(html)
    return RedirectResponse(_back(request), status_code=303)


def _back(request: Request) -> str:
    """Where a non-HTMX form came from, as long as it came from us."""
    referer = request.headers.get("referer")
    if not referer:
        return "/"
    parts = urlsplit(referer)
    if parts.netloc and parts.netloc != request.url.netloc:
        return "/"
    return parts.path + (f"?{parts.query}" if parts.query else "") or "/"
