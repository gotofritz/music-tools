"""The app factory, and the launcher `practice serve` calls.

`create_app(db_path)` takes a path rather than reading the environment, so a
test gets a database of its own without setting `MUSIC_TOOLS_DB` and two apps
in one process cannot end up sharing one.
"""

from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from music_tools.db.connection import open_db
from music_tools.db.migrate import migrate
from music_tools.web.deps import STATIC
from music_tools.web.routes import practice


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
    app.include_router(practice.router)
    return app


def serve(
    db_path: str | Path, *, host: str = "127.0.0.1", port: int = 8765
) -> None:  # pragma: no cover - the socket is the untestable part
    """Run the app on the loopback interface. One machine, one user, no auth."""
    import uvicorn

    uvicorn.run(create_app(db_path), host=host, port=port, log_level="warning")
