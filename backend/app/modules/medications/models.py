import uuid
from datetime import date

from sqlalchemy import Boolean, Date, ForeignKey, Integer, String, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class Medication(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """사용자가 등록한 복용약 (처방전 OCR 또는 직접 입력)"""

    __tablename__ = "medications"

    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(200))
    amount: Mapped[int] = mapped_column(Integer)  # 1회 복용량(정)
    times_per_day: Mapped[int] = mapped_column(Integer)
    days: Mapped[int] = mapped_column(Integer)
    start_date: Mapped[date] = mapped_column(Date)

    logs: Mapped[list["IntakeLog"]] = relationship(back_populates="medication", cascade="all, delete-orphan")


class IntakeLog(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """복약 체크 기록 (날짜 × 복용 시점)"""

    __tablename__ = "intake_logs"
    __table_args__ = (UniqueConstraint("medication_id", "intake_date", "slot"),)

    medication_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("medications.id", ondelete="CASCADE"), index=True
    )
    intake_date: Mapped[date] = mapped_column(Date)
    slot: Mapped[str] = mapped_column(String(20))  # 아침 식후 | 점심 식후 | 저녁 식후 ...
    taken: Mapped[bool] = mapped_column(Boolean, default=False)

    medication: Mapped[Medication] = relationship(back_populates="logs")
