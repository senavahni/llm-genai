"""index GIN `requests.tags` untuk agregasi biaya per tag X-Request-Tags (LGW-V1-06)

Kolom `requests.tags jsonb` sudah ada sejak 0001; migrasi ini hanya menambah index GIN
(`jsonb_path_ops`, untuk filter `tags @> '{"job": "…"}'`).

Revision ID: 0006
Revises: 0005
Create Date: 2026-11-10 09:00:00

"""

from collections.abc import Sequence

from alembic import op

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_index(
        "ix_requests_tags_gin",
        "requests",
        ["tags"],
        postgresql_using="gin",
        postgresql_ops={"tags": "jsonb_path_ops"},
    )


def downgrade() -> None:
    op.drop_index("ix_requests_tags_gin", table_name="requests")
