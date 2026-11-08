import time
import contextvars
import logging
from sqlalchemy import event
from sqlalchemy.engine import Engine

logger = logging.getLogger("smartcart.perf")

db_query_counter = contextvars.ContextVar("db_query_counter", default=0)

@event.listens_for(Engine, "before_cursor_execute")
def receive_before_cursor_execute(conn, cursor, statement, parameters, context, executemany):
    """Listen for query executions across all SQLAlchemy engines and increment the request counter."""
    try:
        count = db_query_counter.get()
        db_query_counter.set(count + 1)
    except Exception:
        pass


def get_query_count() -> int:
    """Return the number of database queries executed in the current request context."""
    return db_query_counter.get()


def reset_query_count() -> contextvars.Token:
    """Reset the database query counter for the current request context."""
    return db_query_counter.set(0)
