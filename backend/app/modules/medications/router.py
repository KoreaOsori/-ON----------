import uuid
from calendar import monthrange
from datetime import date
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, Response, status
from sqlalchemy import select

from app.api.deps import CurrentUser, DbSession
from app.modules.medications.models import IntakeLog, Medication
from app.modules.medications.schemas import IntakeLogRead, IntakeLogUpdate, MedicationCreate, MedicationRead
from app.modules.users.models import User

router = APIRouter(prefix="/medications", tags=["medications"])


async def _get_owned(db: DbSession, user: User, medication_id: uuid.UUID) -> Medication:
    medication = await db.get(Medication, medication_id)
    if medication is None or medication.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "복용약을 찾을 수 없습니다.")
    return medication


@router.get("", response_model=list[MedicationRead], summary="내 복용약 목록")
async def list_medications(user: CurrentUser, db: DbSession):
    return await db.scalars(
        select(Medication).where(Medication.user_id == user.id).order_by(Medication.created_at)
    )


@router.post("", response_model=MedicationRead, status_code=status.HTTP_201_CREATED, summary="복용약 등록")
async def create_medication(payload: MedicationCreate, user: CurrentUser, db: DbSession):
    medication = Medication(user_id=user.id, **payload.model_dump())
    db.add(medication)
    await db.commit()
    await db.refresh(medication)
    return medication


@router.delete("/{medication_id}", status_code=status.HTTP_204_NO_CONTENT, summary="복용약 삭제")
async def delete_medication(medication_id: uuid.UUID, user: CurrentUser, db: DbSession):
    await db.delete(await _get_owned(db, user, medication_id))
    await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/logs", response_model=list[IntakeLogRead], summary="월별 복약 기록 (캘린더)")
async def list_logs(
    user: CurrentUser,
    db: DbSession,
    month: Annotated[str, Query(pattern=r"^\d{4}-\d{2}$", description="YYYY-MM")],
):
    year, month_number = map(int, month.split("-"))
    first, last = date(year, month_number, 1), date(year, month_number, monthrange(year, month_number)[1])
    logs = await db.scalars(
        select(IntakeLog)
        .join(Medication)
        .where(Medication.user_id == user.id, IntakeLog.intake_date.between(first, last))
    )
    return [
        IntakeLogRead(medication_id=log.medication_id, date=log.intake_date, slot=log.slot, taken=log.taken)
        for log in logs
    ]


@router.put("/{medication_id}/logs", status_code=status.HTTP_204_NO_CONTENT, summary="복약 체크")
async def upsert_log(medication_id: uuid.UUID, payload: IntakeLogUpdate, user: CurrentUser, db: DbSession):
    await _get_owned(db, user, medication_id)
    log = await db.scalar(
        select(IntakeLog).where(
            IntakeLog.medication_id == medication_id,
            IntakeLog.intake_date == payload.date,
            IntakeLog.slot == payload.slot,
        )
    ) or IntakeLog(medication_id=medication_id, intake_date=payload.date, slot=payload.slot)
    log.taken = payload.taken
    db.add(log)
    await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
