"""
SQLAlchemy declarative base for api-pilot.

All ORM models must inherit from `Base`:

    from app.db.base import Base

    class MyModel(Base):
        __tablename__ = "my_table"
        ...

Alembic's env.py imports Base.metadata so it can auto-detect table
changes and generate migrations automatically.
"""

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """Shared declarative base — every ORM model inherits from this."""
