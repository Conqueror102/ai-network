"""Custom column types."""

from typing import Any

from sqlalchemy import Text
from sqlalchemy.engine import Dialect
from sqlalchemy.types import TypeDecorator

from app.core.security import crypto


class EncryptedText(TypeDecorator[str]):
    """Transparently AES-GCM encrypts on write and decrypts on read."""

    impl = Text
    cache_ok = True

    def process_bind_param(self, value: str | None, dialect: Dialect) -> Any:
        return None if value is None else crypto.encrypt(value)

    def process_result_value(self, value: Any, dialect: Dialect) -> str | None:
        return None if value is None else crypto.decrypt(value)
