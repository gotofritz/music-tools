"""`practice` — the terminal front end to the practice domain.

Thin on purpose: every command is a few lines over `domain/` and `db/`. It
exists to prove the domain before there is any HTML, and it stays useful
afterwards.

This module is the only place in the codebase that reads the clock or builds a
`random.Random`; everything below takes both as arguments.
"""

import difflib
import random
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import date, datetime
from pathlib import Path

import click

from music_tools.db import repository as repo
from music_tools.db.connection import default_db_path, open_db
from music_tools.db.migrate import migrate
from music_tools.domain.catalogue import (
    InUse,
    NotFound,
    archive_exercise,
    archive_module,
    delete_exercise,
    delete_module,
    module_overview,
    rename_module,
    restore_exercise,
    restore_module,
    update_exercise,
    update_module,
)
from music_tools.domain.models import Exercise, Module, PracticeEntry
from music_tools.domain.scheduling import Algorithm
from music_tools.domain.session import (
    day_summary,
    entry_duration,
    format_due as _due_column,
    format_duration,
    format_when as _when,
    mark_done,
    practice_day_for,
    restart_clock,
    start_day,
)
from music_tools.domain.tempo import format_tempo, parse_tempo
from music_tools.importer.sheets import import_sheets


@click.group()
@click.option(
    "--db",
    "db_path",
    type=click.Path(path_type=Path),
    default=None,
    help="Database file. Defaults to $MUSIC_TOOLS_DB, or ~/.local/share.",
)
@click.pass_context
def practice(ctx: click.Context, db_path: Path | None) -> None:
    """Track bass practice: what is due, what was done, and when it comes back."""
    ctx.obj = db_path or default_db_path()


@practice.group()
def module() -> None:
    """Practice areas — the unit everything else hangs off.

    A module is a queue of its own: rows are scheduled within it, `next
    MODULE` asks it what to play, and modules never affect each other.
    """


@module.command("list")
@click.option("--archived", is_flag=True, help="Include archived modules.")
@click.pass_context
def module_list(ctx: click.Context, archived: bool) -> None:
    """Every module, with the state of its own queue."""
    conn = _connect(ctx)
    overview = module_overview(
        conn, today=practice_day_for(datetime.now()), include_archived=archived
    )
    if not overview:
        click.echo("Nothing here yet — add a module first.")
        return
    for row in overview:
        state = " (archived)" if row.module.archived_at else ""
        click.echo(
            f"{row.module.name:<14} {row.module.log_group:<12}"
            f" {_plural(row.exercises, 'row'):<10}"
            f" {row.due} due"
            f"   next {_due_column(row.next_due)}{state}"
        )


@module.command("show")
@click.argument("module_name", metavar="MODULE")
@click.option("--archived", is_flag=True, help="Include archived rows.")
@click.pass_context
def module_show(ctx: click.Context, module_name: str, archived: bool) -> None:
    """The whole queue of one module, due or not."""
    conn = _connect(ctx)
    found = _find_module(conn, module_name, include_archived=True)
    rows = repo.exercises_due(conn, module_id=found.id, include_archived=archived)
    click.echo(f"{found.name} ({found.log_group})")
    if not rows:
        click.echo("  nothing in this module yet")
        return
    today = practice_day_for(datetime.now())
    for exercise in rows:
        click.echo(_row_line(exercise, today))


@module.command("add")
@click.argument("name")
@click.option("--log-group", required=True, help="TECHNIQUE, REPERTOIRE, ...")
@click.option("--position", type=int, help="Where it sits in the listing.")
@click.pass_context
def module_add(
    ctx: click.Context,
    name: str,
    log_group: str,
    position: int | None,
) -> None:
    """Add a practice area."""
    conn = _connect(ctx)
    if repo.find_module(conn, name):
        raise click.ClickException(f"there is already a module called {name}")
    created = repo.create_module(
        conn, name=name, log_group=log_group, position=position
    )
    click.echo(f"{created.name} ({created.log_group}) added")


@module.command("rename")
@click.argument("module_name", metavar="MODULE")
@click.argument("name")
@click.pass_context
def module_rename(ctx: click.Context, module_name: str, name: str) -> None:
    """Rename a module, slug and all."""
    conn = _connect(ctx)
    found = _find_module(conn, module_name)
    with _reporting():
        renamed = rename_module(conn, found.id, name)
    click.echo(f"{found.name} is now {renamed.name}")


@module.command("edit")
@click.argument("module_name", metavar="MODULE")
@click.option("--log-group", help="Which day-log bucket it subtotals into.")
@click.option("--position", type=int, help="Where it sits in the listing.")
@click.pass_context
def module_edit(
    ctx: click.Context,
    module_name: str,
    log_group: str | None,
    position: int | None,
) -> None:
    """Retag or reorder a module."""
    conn = _connect(ctx)
    found = _find_module(conn, module_name)
    fields = _given(log_group=log_group, position=position)
    if not fields:
        raise click.ClickException("nothing to change — see --help")
    with _reporting():
        updated = update_module(conn, found.id, **fields)
    click.echo(f"{updated.name} ({updated.log_group}) at position {updated.position}")


@module.command("archive")
@click.argument("module_name", metavar="MODULE")
@click.pass_context
def module_archive(ctx: click.Context, module_name: str) -> None:
    """Take a module, and its whole queue, out of circulation."""
    conn = _connect(ctx)
    found = _find_module(conn, module_name)
    with _reporting():
        archive_module(conn, found.id, now=datetime.now())
    click.echo(f"{found.name} archived — `module restore` puts it back")


@module.command("restore")
@click.argument("module_name", metavar="MODULE")
@click.pass_context
def module_restore(ctx: click.Context, module_name: str) -> None:
    """Put an archived module back."""
    conn = _connect(ctx)
    found = _find_module(conn, module_name, include_archived=True)
    with _reporting():
        restore_module(conn, found.id)
    click.echo(f"{found.name} restored")


@module.command("delete")
@click.argument("module_name", metavar="MODULE")
@click.option("--force", is_flag=True, help="Delete its rows along with it.")
@click.pass_context
def module_delete(ctx: click.Context, module_name: str, force: bool) -> None:
    """Delete a module. For mistakes; archiving is the normal move."""
    conn = _connect(ctx)
    found = _find_module(conn, module_name, include_archived=True)
    with _reporting():
        delete_module(conn, found.id, force=force)
    click.echo(f"{found.name} deleted")


@practice.command("add")
@click.argument("module_name", metavar="MODULE")
@click.argument("name")
@click.option("--speed", help='As typed: "80%", "66", "66/1", "123/0.5".')
@click.option("--target-bpm", type=float, help="The tempo this is aiming at.")
@click.option("--style", help="The row's own tag: NEOSOUL, RNB, DANCE.")
@click.option("--due", "next_due", help="ISO date it is next due.")
@click.option("--notes")
@click.pass_context
def add_exercise(
    ctx: click.Context,
    module_name: str,
    name: str,
    speed: str | None,
    target_bpm: float | None,
    style: str | None,
    next_due: str | None,
    notes: str | None,
) -> None:
    """Add an exercise to a module."""
    conn = _connect(ctx)
    found = repo.find_module(conn, module_name)
    if found is None:
        raise click.ClickException(f"no module called {module_name}")
    exercise = repo.create_exercise(
        conn,
        module_id=found.id,
        name=name,
        speed=speed,
        target_bpm=target_bpm,
        style=style,
        next_due=_parse_day(next_due) if next_due else None,
        notes=notes,
    )
    click.echo(f"{found.name}/{exercise.name} added, {_tempo(exercise)}")


@practice.command("edit")
@click.argument("exercise")
@click.option("--name", help="Rename the row. The day log keeps what it snapped.")
@click.option("--speed", help='As typed: "80%", "66", "66/1", "123/0.5".')
@click.option("--target-bpm", type=float, help="The tempo this is aiming at.")
@click.option("--style", help="The row's own tag: NEOSOUL, RNB, DANCE.")
@click.option("--due", "next_due", help="ISO date it is next due.")
@click.option("--count", "practiced_count", type=int, help="Times practised.")
@click.option("--notes")
@click.pass_context
def edit_exercise(
    ctx: click.Context,
    exercise: str,
    name: str | None,
    speed: str | None,
    target_bpm: float | None,
    style: str | None,
    next_due: str | None,
    practiced_count: int | None,
    notes: str | None,
) -> None:
    """Edit a row of a module."""
    conn = _connect(ctx)
    found = _resolve(conn, exercise)
    fields = _given(
        name=name,
        speed=speed,
        target_bpm=target_bpm,
        style=style,
        next_due=_parse_day(next_due) if next_due else None,
        practiced_count=practiced_count,
        notes=notes,
    )
    if not fields:
        raise click.ClickException("nothing to change — see --help")
    with _reporting():
        updated = update_exercise(conn, found.id, **fields)
    click.echo(
        f"{_module_name(conn, updated)}/{updated.name}"
        f"  {_tempo(updated)}  due {_due_column(updated.next_due)}"
    )


@practice.command("archive")
@click.argument("exercise")
@click.pass_context
def archive_row(ctx: click.Context, exercise: str) -> None:
    """Take a row out of its queue, keeping the day log readable."""
    conn = _connect(ctx)
    found = _resolve(conn, exercise)
    with _reporting():
        archive_exercise(conn, found.id, now=datetime.now())
    click.echo(f"{found.name} archived — `restore` puts it back")


@practice.command("restore")
@click.argument("exercise")
@click.pass_context
def restore_row(ctx: click.Context, exercise: str) -> None:
    """Put an archived row back in its queue."""
    conn = _connect(ctx)
    found = _resolve(conn, exercise, include_archived=True)
    with _reporting():
        restore_exercise(conn, found.id)
    click.echo(f"{found.name} restored")


@practice.command("delete")
@click.argument("exercise")
@click.pass_context
def delete_row(ctx: click.Context, exercise: str) -> None:
    """Delete a row. For mistakes; anything in the day log is archived instead."""
    conn = _connect(ctx)
    found = _resolve(conn, exercise, include_archived=True)
    with _reporting():
        delete_exercise(conn, found.id)
    click.echo(f"{found.name} deleted")


@practice.command("speed")
@click.argument("exercise")
@click.argument("speed")
@click.option("--target-bpm", type=float, help="Also retune what it is aiming at.")
@click.pass_context
def set_speed(
    ctx: click.Context, exercise: str, speed: str, target_bpm: float | None
) -> None:
    """Set the speed an exercise is currently practised at."""
    conn = _connect(ctx)
    found = _resolve(conn, exercise)
    fields: dict[str, object] = {"speed": speed}
    if target_bpm is not None:
        fields["target_bpm"] = target_bpm
    updated = repo.update_exercise(conn, found.id, **fields)
    click.echo(f"{updated.name} now at {_tempo(updated)}")


@practice.command("next")
@click.argument("module_name", metavar="[MODULE]", required=False)
@click.option("--limit", type=int, default=10, show_default=True)
@click.pass_context
def next_up(ctx: click.Context, module_name: str | None, limit: int) -> None:
    """What to play next, oldest due first — a queue per module.

    Modules are independent, so with no MODULE this prints a block each rather
    than one interleaved list.
    """
    conn = _connect(ctx)
    today = practice_day_for(datetime.now())
    if module_name:
        modules = [_find_module(conn, module_name)]
    else:
        modules = repo.list_modules(conn)
    if not modules:
        click.echo("Nothing to practise — add a module first.")
        return

    queues = [
        (found, repo.exercises_due(conn, module_id=found.id)) for found in modules
    ]
    if not any(rows for _, rows in queues):
        click.echo("Nothing to practise — no rows in these modules yet.")
        return

    for index, (found, rows) in enumerate(queues):
        if not rows:
            continue
        if index:
            click.echo()
        due = sum(1 for row in rows if row.next_due and row.next_due <= today)
        click.echo(
            f"{found.name} ({found.log_group})"
            f" — {due} due of {_plural(len(rows), 'row')}"
        )
        for exercise in rows[:limit]:
            click.echo(_row_line(exercise, today))


@practice.command("done")
@click.argument("exercise")
@click.option(
    "--short", "algorithm", flag_value=Algorithm.SHORT, help="Half the table."
)
@click.option(
    "--long", "algorithm", flag_value=Algorithm.LONG, help="One and a half times it."
)
@click.option(
    "--rotate",
    "algorithm",
    flag_value=Algorithm.ROTATE,
    help="To the back of the queue.",
)
@click.option(
    "--hold", "algorithm", flag_value=Algorithm.HOLD, help="Keep it at the front."
)
@click.option("--notes", help="A note for the log line.")
@click.pass_context
def done(
    ctx: click.Context, exercise: str, algorithm: str | None, notes: str | None
) -> None:
    """Mark an exercise practised: move the schedule and log the time."""
    conn = _connect(ctx)
    found = _resolve(conn, exercise)
    now = datetime.now()
    result = mark_done(
        conn,
        exercise_id=found.id,
        algorithm=Algorithm(algorithm) if algorithm else Algorithm.NORMAL,
        now=now,
        rng=random.Random(),
        notes=notes,
    )

    updated = result.exercise
    today = practice_day_for(now)
    click.echo(
        f"{updated.name} done — practised {updated.practiced_count} times,"
        f" next due {_due_column(updated.next_due)}"
        f" ({_when(updated.next_due, today)})"
    )
    entry = result.closed
    click.echo(
        f"logged {entry.started_at:%H:%M}-{now:%H:%M}"
        f"  {format_duration(int((now - entry.started_at).total_seconds()))}"
        f"  {entry.log_group or '-'}  {_tempo(updated)}"
    )


@practice.command("start")
@click.pass_context
def start(ctx: click.Context) -> None:
    """Start the clock now, after a break.

    Entries normally follow on from each other. Use this when they should not:
    the gap since the last one is thrown away rather than logged against
    whatever you play next.
    """
    conn = _connect(ctx)
    now = datetime.now()
    result = restart_clock(conn, now=now)
    dropped = ""
    if result.dropped_seconds:
        dropped = f" — {format_duration(result.dropped_seconds)} of break not logged"
    click.echo(f"clock running from {now:%H:%M}{dropped}")


@practice.group()
def day() -> None:
    """The practice day."""


@day.command("new")
@click.pass_context
def day_new(ctx: click.Context) -> None:
    """Start a day and set the clock running."""
    conn = _connect(ctx)
    now = datetime.now()
    started = start_day(conn, now=now)
    click.echo(f"{started.day.isoformat()} started, clock running from {now:%H:%M}")


@practice.group("db")
def db_group() -> None:
    """The database file itself."""


@db_group.command("dump")
@click.option(
    "--to",
    "path",
    type=click.Path(path_type=Path),
    default=Path("backups/practice.sql"),
    show_default=True,
)
@click.pass_context
def db_dump(ctx: click.Context, path: Path) -> None:
    """Dump the database to text, so the history can live in a git repository.

    `sqlite3 .dump` without needing the `sqlite3` binary, and with the same
    stable line ordering, so a backup diffs row by row.
    """
    conn = _connect(ctx)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for line in conn.iterdump():
            handle.write(line + "\n")
    click.echo(f"dumped to {path}")


@practice.command("log")
@click.option("--day", "which", default="today", show_default=True, help="ISO date.")
@click.pass_context
def show_log(ctx: click.Context, which: str) -> None:
    """The day block, with its subtotals."""
    conn = _connect(ctx)
    now = datetime.now()
    summary = day_summary(conn, day=_parse_day(which, now=now), now=now)
    if not summary.entries:
        click.echo(f"Nothing logged for {summary.day.isoformat()}.")
        return

    click.echo(summary.day.isoformat())
    for entry in summary.entries:
        ended = f"{entry.ended_at:%H:%M}" if entry.ended_at else "  :  "
        running = "" if entry.ended_at else "  (running)"
        description = entry.description + (f" ({entry.notes})" if entry.notes else "")
        click.echo(
            f"  {entry.started_at:%H:%M}-{ended}"
            f"  {format_duration(_seconds(entry, now))}"
            f"  {description[:48]:<48}"
            f"  {entry.speed or '':<8} {entry.log_group or '':<12}{running}"
        )
    click.echo()
    for group in summary.groups:
        click.echo(f"  {group.log_group:<12} {format_duration(group.seconds)}")
    click.echo(f"  {'TOTAL':<12} {format_duration(summary.total_seconds)}")


@practice.command("import")
@click.option(
    "--modules",
    multiple=True,
    type=click.Path(exists=True, path_type=Path),
    help="Module sheet exports, one per practice area.",
)
@click.option(
    "--day-log",
    type=click.Path(exists=True, path_type=Path),
    help="The BASS day log export.",
)
@click.pass_context
def import_command(
    ctx: click.Context, modules: tuple[Path, ...], day_log: Path | None
) -> None:
    """Import the spreadsheet exports."""
    conn = _connect(ctx)
    report = import_sheets(conn, modules=list(modules), day_log=day_log)
    click.echo(
        "imported "
        + ", ".join(
            [
                _plural(report.modules_created, "module"),
                f"{_plural(report.exercises_created, 'exercise')}"
                f" ({report.exercises_updated} updated)",
                _plural(report.days_created, "day"),
                f"{_plural(report.entries_created, 'entry', 'entries')}"
                f" ({report.entries_updated} updated)",
            ]
        )
    )
    for problem in report.problems:
        click.echo(f"  ! {problem}", err=True)


# --- plumbing ---------------------------------------------------------------


def _connect(ctx: click.Context) -> sqlite3.Connection:
    """Open the database named on the command line, and migrate it."""
    conn = open_db(ctx.obj)
    migrate(conn)
    return conn


@contextmanager
def _reporting() -> Iterator[None]:
    """Turn the domain's refusals into click's, so they read as messages."""
    try:
        yield
    except (InUse, NotFound) as error:
        raise click.ClickException(str(error)) from None


def _given(**fields) -> dict[str, object]:
    """The options actually passed; `None` means "leave it alone"."""
    return {name: value for name, value in fields.items() if value is not None}


def _find_module(
    conn: sqlite3.Connection, name: str, *, include_archived: bool = False
) -> Module:
    found = repo.find_module(conn, name)
    if found is None:
        known = ", ".join(module.name for module in repo.list_modules(conn))
        raise click.ClickException(
            f"no module called {name}" + (f". There is: {known}" if known else "")
        )
    if found.archived_at and not include_archived:
        raise click.ClickException(
            f"{found.name} is archived — `module restore {found.name}` first"
        )
    return found


def _row_line(exercise: Exercise, today: date) -> str:
    """One row of a module's queue, without repeating the module's name."""
    return (
        f"  {_due_column(exercise.next_due):<12}"
        f" {_when(exercise.next_due, today):<16}"
        f" {exercise.name:<26}"
        f" {_tempo(exercise):<20} x{exercise.practiced_count}"
    )


def _resolve(
    conn: sqlite3.Connection, token: str, *, include_archived: bool = False
) -> Exercise:
    """`NAME`, or `MODULE/NAME` when a name lives in more than one module."""
    module_name, _, name = token.rpartition("/")
    module_id = None
    if module_name:
        module_id = _find_module(conn, module_name, include_archived=True).id

    matches = repo.find_exercises(
        conn, name, module_id=module_id, include_archived=include_archived
    )
    if len(matches) == 1:
        return matches[0]
    if not matches:
        raise click.ClickException(f"no exercise called {name!r}{_near(conn, name)}")

    where = ", ".join(_module_name(conn, match) for match in matches)
    raise click.ClickException(f"{name!r} is in {where} — say MODULE/NAME to pick one")


def _near(conn: sqlite3.Connection, name: str) -> str:
    names = [exercise.name for exercise in repo.exercises_due(conn)]
    close = difflib.get_close_matches(name, names, n=3, cutoff=0.5)
    return f". Did you mean: {', '.join(close)}?" if close else ""


def _module_name(conn: sqlite3.Connection, exercise: Exercise) -> str:
    found = repo.get_module(conn, exercise.module_id)
    return found.name if found else "?"


def _tempo(exercise: Exercise) -> str:
    return format_tempo(
        parse_tempo(exercise.speed or "", target_bpm=exercise.target_bpm)
    )


def _plural(count: int, singular: str, plural: str | None = None) -> str:
    return f"{count} {singular if count == 1 else plural or singular + 's'}"


def _parse_day(which: str, now: datetime | None = None) -> date:
    if which == "today":
        return practice_day_for(now or datetime.now())
    try:
        return date.fromisoformat(which)
    except ValueError:
        raise click.ClickException(f"cannot read the date {which!r}") from None


def _seconds(entry: PracticeEntry, now: datetime) -> int:
    live = now if practice_day_for(now) == practice_day_for(entry.started_at) else None
    return entry_duration(entry, now=live)
