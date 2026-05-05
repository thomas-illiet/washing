"""Shared SQLAlchemy base types and helpers."""

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import DateTime, MetaData
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.types import JSON, Text, TypeDecorator

from internal.infra.security import decrypt_json_value, encrypt_json_value


convention = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}

metadata = MetaData(naming_convention=convention)
JSONType = JSONB().with_variant(JSON(), "sqlite")
JsonDict = dict[str, Any]


class EncryptedJSONType(TypeDecorator):
    """SQLAlchemy type that transparently encrypts JSON dictionaries."""
    impl = Text
    cache_ok = True

    def process_bind_param(self, value: JsonDict | None, dialect) -> str | None:
        """Encrypt JSON values before persisting them."""
        if value is None:
            return None
        return encrypt_json_value(value)

    def process_result_value(self, value: Any, dialect) -> JsonDict:
        """Decrypt persisted JSON values when loading them."""
        return decrypt_json_value(value)


def utcnow() -> datetime:
    """Return the current UTC datetime."""
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    """Base declarative class for all ORM models."""
    metadata = metadata


class TimestampMixin:
    """Mixin providing created and updated timestamps."""
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utcnow,
        onupdate=utcnow,
        nullable=False,
    )
