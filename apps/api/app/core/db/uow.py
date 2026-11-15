"""Unit of work: one transaction per use case (doc 11 §7.1)."""

from types import TracebackType

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db.engine import get_session_factory


class UnitOfWork:
    """`async with UnitOfWork() as session:` commits on success, rolls back on error.

    Used by jobs and other non-request entrypoints. Request handlers get their
    session from `get_session` and services commit explicitly.
    """

    def __init__(self) -> None:
        self.session: AsyncSession | None = None

    async def __aenter__(self) -> AsyncSession:
        self.session = get_session_factory()()
        return self.session

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        assert self.session is not None
        try:
            if exc_type is None:
                await self.session.commit()
            else:
                await self.session.rollback()
        finally:
            await self.session.close()
