import logging

from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)


def check_database(session: Session) -> bool:
    """Return True if the database answers a trivial query."""
    try:
        session.execute(text("SELECT 1"))
    except SQLAlchemyError as exc:
        logger.warning("database health check failed", extra={"error": str(exc)})
        return False
    return True
