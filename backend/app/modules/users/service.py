from datetime import UTC, date, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.users.models import HealthProfile, User, UserConsent
from app.modules.users.schemas import HealthProfilePayload


def calculate_age(birth: date, today: date | None = None) -> int:
    today = today or date.today()
    return today.year - birth.year - ((today.month, today.day) < (birth.month, birth.day))


def summarize_health_profile(profile: HealthProfile) -> str:
    """챗봇 프롬프트에 넣을 건강정보 요약"""
    parts = [
        profile.gender,
        profile.birth and f"만 {calculate_age(profile.birth)}세",
        profile.pregnant,
        profile.medicines and f"복용 중인 약: {', '.join(profile.medicines)}",
        profile.conditions and f"지병: {profile.conditions}",
    ]
    return ", ".join(str(part) for part in parts if part)


async def get_or_create_oauth_user(
    db: AsyncSession, *, provider: str, provider_user_id: str, email: str | None, nickname: str | None
) -> User:
    user = await db.scalar(
        select(User).where(User.provider == provider, User.provider_user_id == provider_user_id)
    )
    if user is None:
        user = User(provider=provider, provider_user_id=provider_user_id, email=email, nickname=nickname)
        db.add(user)
        await db.commit()
        await db.refresh(user)
    return user


async def update_consents(db: AsyncSession, user: User, consents: dict[str, bool]) -> None:
    existing = {
        consent.consent_type: consent
        for consent in await db.scalars(select(UserConsent).where(UserConsent.user_id == user.id))
    }
    now = datetime.now(UTC)
    for consent_type, agreed in consents.items():
        consent = existing.get(consent_type) or UserConsent(user_id=user.id, consent_type=consent_type)
        consent.agreed = agreed
        consent.agreed_at = now if agreed else None
        db.add(consent)
    await db.commit()


async def has_required_consents(db: AsyncSession, user: User, required: set[str]) -> bool:
    agreed = set(
        await db.scalars(
            select(UserConsent.consent_type).where(
                UserConsent.user_id == user.id, UserConsent.agreed.is_(True)
            )
        )
    )
    return required <= agreed


async def upsert_health_profile(db: AsyncSession, user: User, payload: HealthProfilePayload) -> HealthProfile:
    profile = await db.get(HealthProfile, user.id) or HealthProfile(user_id=user.id)
    for field, value in payload.model_dump().items():
        setattr(profile, field, value)
    db.add(profile)
    await db.commit()
    await db.refresh(profile)
    return profile
