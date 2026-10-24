import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    JSON,
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class User(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "users"
    __table_args__ = (UniqueConstraint("provider", "provider_user_id"),)

    email: Mapped[str | None] = mapped_column(String(320))
    nickname: Mapped[str | None] = mapped_column(String(100))
    provider: Mapped[str] = mapped_column(String(20))  # email (이메일 아이디 로그인)
    provider_user_id: Mapped[str] = mapped_column(String(255))

    health_profile: Mapped["HealthProfile | None"] = relationship(
        back_populates="user", cascade="all, delete-orphan", uselist=False, lazy="selectin"
    )
    consents: Mapped[list["UserConsent"]] = relationship(back_populates="user", cascade="all, delete-orphan")


class UserConsent(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "user_consents"
    __table_args__ = (UniqueConstraint("user_id", "consent_type"),)

    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id", ondelete="CASCADE"), index=True)
    consent_type: Mapped[str] = mapped_column(String(30))  # terms | privacy | health | marketing
    agreed: Mapped[bool] = mapped_column(Boolean, default=False)
    agreed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    version: Mapped[str] = mapped_column(String(20), default="v1")

    user: Mapped[User] = relationship(back_populates="consents")


class HealthProfile(TimestampMixin, Base):
    """건강정보(민감정보). RDS 스토리지 KMS 암호화 + 별도 동의를 전제로 저장한다."""

    __tablename__ = "health_profiles"

    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    birth: Mapped[date | None] = mapped_column(Date)
    gender: Mapped[str | None] = mapped_column(String(10))
    height: Mapped[Decimal | None] = mapped_column(Numeric(5, 1))
    weight: Mapped[Decimal | None] = mapped_column(Numeric(5, 1))
    pregnant: Mapped[str | None] = mapped_column(String(20))
    medicine_status: Mapped[str | None] = mapped_column(String(30))
    medicines: Mapped[list[str]] = mapped_column(JSON, default=list)
    medicine_items: Mapped[list[dict] | None] = mapped_column(JSON, default=list)
    conditions: Mapped[str | None] = mapped_column(Text)

    user: Mapped[User] = relationship(back_populates="health_profile")
