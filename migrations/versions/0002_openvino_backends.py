"""runtime lokal hanya OpenVINO (llama.cpp & embedding lokal dihapus)

Model lama tidak dihapus (riwayat request/usage tetap utuh): backend-nya ditandai `retired` dan
model dinonaktifkan. Model yang masih ada di katalog diaktifkan ulang oleh
`manage.py seed --update-local`.

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-28 09:00:00

"""

from collections.abc import Sequence

from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

OLD = ("llama_cpp_python", "llama_server", "openvino_diffusion", "openvino_embedding")
NEW = ("openvino_llm", "openvino_vlm", "openvino_diffusion", "retired")


def _in(values: tuple[str, ...]) -> str:
    return "runtime_backend IN (" + ", ".join(f"'{v}'" for v in values) + ")"


def upgrade() -> None:
    op.drop_constraint(op.f("ck_models_runtime_backend"), "models", type_="check")
    op.execute(
        "UPDATE models SET runtime_backend = 'retired', is_enabled = false "
        "WHERE runtime_backend IN ('llama_cpp_python', 'llama_server', 'openvino_embedding')"
    )
    op.execute("UPDATE providers SET is_enabled = false WHERE code = 'llamacpp'")
    op.create_check_constraint(op.f("ck_models_runtime_backend"), "models", _in(NEW))


def downgrade() -> None:
    op.drop_constraint(op.f("ck_models_runtime_backend"), "models", type_="check")
    op.execute(
        "UPDATE models SET runtime_backend = 'llama_cpp_python' "
        "WHERE runtime_backend IN ('openvino_llm', 'openvino_vlm', 'retired')"
    )
    op.execute("UPDATE providers SET is_enabled = true WHERE code = 'llamacpp'")
    op.create_check_constraint(op.f("ck_models_runtime_backend"), "models", _in(OLD))
