"""
Models package — re-exports all ORM models.

Import from here so the rest of the app never needs to know which file
a model lives in:

    from app.models import Workspace, User, Spec, Suite, Endpoint

Alembic's env.py does `from app import models` which triggers this
__init__.py and registers every model on Base.metadata automatically.
"""

from app.models.chat_message import ChatMessage
from app.models.dependency import Dependency
from app.models.endpoint import Endpoint
from app.models.environment import Environment
from app.models.execution import Execution, ExecutionResult
from app.models.spec import Spec
from app.models.suite import Suite
from app.models.test import Test
from app.models.user import User
from app.models.workspace import Workspace

__all__ = [
    "Workspace",
    "User",
    "Spec",
    "Suite",
    "Endpoint",
    "Test",
    "Environment",
    "Execution",
    "ExecutionResult",
    "Dependency",
    "ChatMessage",
]
