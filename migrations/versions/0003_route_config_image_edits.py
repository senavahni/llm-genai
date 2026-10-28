"""model_routes.config (opsi routing, mis. prefer_loaded) + endpoint images.edits

Revision ID: 0003
Revises: 0002
Create Date: 2026-10-28 12:00:00

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

OLD = ("chat.completions", "completions", "embeddings", "images.generations")
NEW = (*OLD, "images.edits")


def _in(values: tuple[str, ...]) -> str:
    return "endpoint IN (" + ", ".join(f"'{v}'" for v in values) + ")"


def upgrade() -> None:
    op.add_column(
        "model_routes",
        sa.Column(
            "config",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
    )
    op.drop_constraint(op.f("ck_requests_endpoint"), "requests", type_="check")
    op.create_check_constraint(op.f("ck_requests_endpoint"), "requests", _in(NEW))


def downgrade() -> None:
    op.execute("DELETE FROM requests WHERE endpoint = 'images.edits'")
    op.drop_constraint(op.f("ck_requests_endpoint"), "requests", type_="check")
    op.create_check_constraint(op.f("ck_requests_endpoint"), "requests", _in(OLD))
    op.drop_column("model_routes", "config")
