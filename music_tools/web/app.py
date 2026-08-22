"""The app factory, and the launcher `practice serve` calls.

`create_app(db_path)` takes a path rather than reading the environment, so a
test gets a database of its own without setting `MUSIC_TOOLS_DB` and two apps
in one process cannot end up sharing one.
"""

from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, Response
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException

from music_tools.db.connection import open_db
from music_tools.db.migrate import migrate
from music_tools.web.deps import STATIC, is_htmx, render
from music_tools.web.routes import media, modules, practice


def create_app(db_path: str | Path) -> FastAPI:
    """A practice app over one database file, migrated to the current schema."""
    app = FastAPI(title="practice", docs_url=None, redoc_url=None)
    app.state.db_path = Path(db_path)

    conn = open_db(db_path)
    try:
        migrate(conn)
    finally:
        conn.close()

    app.mount("/static", StaticFiles(directory=STATIC), name="static")
    app.add_exception_handler(HTTPException, refused)
    app.include_router(practice.router)
    app.include_router(modules.router)
    app.include_router(media.router)
    return app


def refused(request: Request, exc: Exception) -> Response:
    """A refusal the player can read, instead of the JSON nobody sees.

    A mistyped path, a set that will not take another track: the domain wrote
    a sentence about it, and the routes turned it into a status code. As JSON
    it reached nobody — HTMX throws a 4xx body away by default, so the click
    did nothing at all and the page said nothing about why. The status is
    unchanged; only the body is. HTMX is told to put it in the page's problem
    slot rather than in the list the write was aimed at, so what is already on
    screen stays there, and a browser with no JavaScript gets the same message
    as a page.
    """
    assert isinstance(exc, HTTPException)  # the only class this is registered for
    if is_htmx(request):
        return HTMLResponse(
            render("_problem.html", problem=exc.detail),
            status_code=exc.status_code,
            headers={"HX-Retarget": "#problem", "HX-Reswap": "outerHTML"},
        )
    return HTMLResponse(
        render("problem.html", problem=exc.detail, status=exc.status_code, modules=[]),
        status_code=exc.status_code,
    )


def serve(
    db_path: str | Path,
    *,
    host: str = "127.0.0.1",
    port: int = 8567,
    open_browser: bool = True,
) -> None:
    """Run the app on the loopback interface. One machine, one user, no auth.

    The browser is launched before `uvicorn.run` blocks, which is a race the
    browser loses every time: starting one takes far longer than binding a
    socket does.
    """
    import webbrowser

    import uvicorn

    app = create_app(db_path)
    if open_browser:
        webbrowser.open(f"http://{host}:{port}/")
    uvicorn.run(app, host=host, port=port, log_level="warning")
