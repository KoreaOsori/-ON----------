"""medication item_seq: 약 검색에서 고른 복용약의 품목기준코드

Revision ID: 8f2d4b6a1c37
Revises: 5c3e1a9b7d24
Create Date: 2026-10-25 21:00:00

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "8f2d4b6a1c37"
down_revision: str | Sequence[str] | None = "5c3e1a9b7d24"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # 병용 확인 "내 복용약 불러오기"는 품목기준코드로 판정하므로, 약 검색에서 고른 약은 코드를 함께 저장한다
    op.add_column("medications", sa.Column("item_seq", sa.String(length=20), nullable=True))


def downgrade() -> None:
    op.drop_column("medications", "item_seq")
