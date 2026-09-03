"""
Application-wide constants.

DEFAULT_WORKSPACE_ID
    The UUID of the single workspace seeded in the initial migration.
    Used as a hardcoded stand-in for real multi-workspace auth throughout
    Sprint 1–8.  Real per-user workspace resolution lands in Sprint 9.
"""

from uuid import UUID

DEFAULT_WORKSPACE_ID: UUID = UUID("00000000-0000-0000-0000-000000000001")
