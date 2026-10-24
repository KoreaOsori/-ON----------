"""email login + medication sync: 건강정보 medicine_items, 복용 정보 비워 두기 허용

Revision ID: 5c3e1a9b7d24
Revises: 0917450dcdc8
Create Date: 2026-10-25 00:30:00

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "5c3e1a9b7d24"
down_revision: str | Sequence[str] | None = "0917450dcdc8"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

DOSAGE_COLUMNS = [
    ("amount", sa.Integer()),
    ("times_per_day", sa.Integer()),
    ("days", sa.Integer()),
    ("start_date", sa.Date()),
]


def upgrade() -> None:
    # 건강정보에서 약 검색으로 고른 약 (품목기준코드·이름 등)
    op.add_column("health_profiles", sa.Column("medicine_items", sa.JSON(), nullable=True))
    # 건강정보에서 이름만 고른 약도 복용약으로 저장하므로 복용 정보는 모를 수 있다
    for name, type_ in DOSAGE_COLUMNS:
        op.alter_column("medications", name, existing_type=type_, nullable=True)


def downgrade() -> None:
    op.execute(
        "DELETE FROM medications WHERE amount IS NULL OR times_per_day IS NULL OR days IS NULL OR start_date IS NULL"
    )
    for name, type_ in DOSAGE_COLUMNS:
        op.alter_column("medications", name, existing_type=type_, nullable=False)
    op.drop_column("health_profiles", "medicine_items")
