"""backend runtime `openvino_embed` (embedding lokal Qwen3-Embedding di GPU, LGW-V1-02)

Revision ID: 0005
Revises: 0004
Create Date: 2026-11-09 09:00:00

"""

from collections.abc import Sequence

from alembic import op

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

OLD = ("openvino_llm", "openvino_vlm", "openvino_diffusion", "retired")
NEW = ("openvino_llm", "openvino_vlm", "openvino_diffusion", "openvino_embed", "retired")


def _in(values: tuple[str, ...]) -> str:
    return "runtime_backend IN (" + ", ".join(f"'{v}'" for v in values) + ")"


def upgrade() -> None:
    op.drop_constraint(op.f("ck_models_runtime_backend"), "models", type_="check")
    op.create_check_constraint(op.f("ck_models_runtime_backend"), "models", _in(NEW))


def downgrade() -> None:
    op.drop_constraint(op.f("ck_models_runtime_backend"), "models", type_="check")
    op.execute(
        "UPDATE models SET runtime_backend = 'retired', is_enabled = false "
        "WHERE runtime_backend = 'openvino_embed'"
    )
    op.create_check_constraint(op.f("ck_models_runtime_backend"), "models", _in(OLD))
