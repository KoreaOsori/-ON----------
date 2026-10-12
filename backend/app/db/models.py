"""Alembic이 모든 모델을 인식하도록 한 곳에서 import 한다. 새 모델을 추가하면 여기에도 등록한다."""

from app.db.base import Base
from app.modules.medications.models import IntakeLog, Medication
from app.modules.users.models import HealthProfile, User, UserConsent

__all__ = ["Base", "HealthProfile", "IntakeLog", "Medication", "User", "UserConsent"]
