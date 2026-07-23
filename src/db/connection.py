"""SQLite connection helpers with explicit lifecycle guarantees."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from types import TracebackType


class ClosingSQLiteConnection(sqlite3.Connection):
    """
    Commit or roll back like the standard connection context manager, then close.

    ``sqlite3.Connection.__exit__`` manages the transaction but does not close
    the underlying database handle. Project code consistently uses
    ``with connect_db(...)`` and expects the handle to live only inside that
    block, so this subclass makes that expectation explicit.
    """

    def __exit__(
        self,
        exception_type: type[BaseException] | None,
        exception: BaseException | None,
        traceback: TracebackType | None,
    ) -> bool:
        try:
            return bool(
                super().__exit__(
                    exception_type,
                    exception,
                    traceback,
                )
            )
        finally:
            self.close()


def open_sqlite_connection(
    db_path: str | Path,
) -> sqlite3.Connection:
    """Open a named-row SQLite connection that closes after a ``with`` block."""

    path = Path(db_path)

    if not path.exists():
        raise FileNotFoundError(f"Database not found: {path}")

    connection = sqlite3.connect(
        path,
        factory=ClosingSQLiteConnection,
    )
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")

    return connection
