"""Session and transaction context managers."""
from __future__ import annotations

from contextlib import contextmanager
from typing import Iterator

from sqlalchemy.orm import Session, sessionmaker


@contextmanager
def session_scope(factory: sessionmaker) -> Iterator[Session]:
    """Yield a session and guarantee rollback-on-error and close-on-exit.

    This helper does not commit implicitly; callers choose their transaction boundary.
    """
    session = factory()
    try:
        yield session
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


@contextmanager
def transaction_scope(factory: sessionmaker) -> Iterator[Session]:
    """Run one explicit transaction and roll it back if its body fails."""
    with session_scope(factory) as session:
        with session.begin():
            yield session
