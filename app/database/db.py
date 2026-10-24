"""Database connection.

FinanceOS stores every user's data in one database. Each row (account,
transaction, goal...) carries the owner's user_id, and every query in the
services filters by it, so users only ever see their own data.

Two databases are supported, chosen by DATABASE_URL in .env:

- SQLite (default): a single file, financeos.db, in the project folder.
  Nothing to install. Good for your own laptop and small groups of users.
- PostgreSQL: a proper database server. Use it when the app is online with
  many users at once. Example:
      DATABASE_URL=postgresql://financeos:yourpassword@localhost:5432/financeos
"""

from contextlib import contextmanager

from sqlalchemy import create_engine, event
from sqlalchemy.engine import make_url
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from app import config


def normalize_url(url: str) -> str:
    """Accept the URL formats hosting providers give out and pick the right driver."""
    if url.startswith("postgres://"):
        url = "postgresql://" + url[len("postgres://") :]
    if url.startswith("postgresql://"):
        url = "postgresql+psycopg://" + url[len("postgresql://") :]
    return url


DATABASE_URL = normalize_url(config.DATABASE_URL)
IS_SQLITE = make_url(DATABASE_URL).get_backend_name() == "sqlite"

if IS_SQLITE:
    engine = create_engine(
        DATABASE_URL,
        # Streamlit serves each user from its own thread; wait instead of failing
        # if another user is writing at the same moment.
        connect_args={"check_same_thread": False, "timeout": 30},
    )

    @event.listens_for(engine, "connect")
    def _sqlite_pragmas(dbapi_connection, _record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")  # enforce links between tables
        cursor.execute("PRAGMA journal_mode=WAL")  # readers don't block the writer
        cursor.execute("PRAGMA synchronous=FULL")  # every commit survives a power cut
        cursor.execute("PRAGMA busy_timeout=30000")  # wait up to 30 s for a lock
        cursor.close()
else:
    engine = create_engine(
        DATABASE_URL,
        pool_size=10,
        max_overflow=20,
        pool_pre_ping=True,  # reconnect if the server closed an idle connection
        pool_recycle=1800,
    )


SessionLocal = sessionmaker(
    bind=engine,
    autoflush=False,
    expire_on_commit=False,  # objects stay readable after the session closes
)


class Base(DeclarativeBase):
    pass


@contextmanager
def get_session():
    """Open a session that always commits or rolls back, then closes.

    Usage:
        with get_session() as session:
            session.add(obj)
    """
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


@contextmanager
def use_session(session=None):
    """Join the caller's session if given (so several steps commit together),
    otherwise open a new one."""
    if session is not None:
        yield session
    else:
        with get_session() as new_session:
            yield new_session


def describe() -> str:
    """Human-readable database location, without the password."""
    url = make_url(DATABASE_URL)
    if IS_SQLITE:
        return f"SQLite file: {url.database}"
    return f"PostgreSQL: {url.host}:{url.port or 5432}/{url.database}"
