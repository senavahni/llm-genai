import uuid
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class AuthContext:
    key_id: uuid.UUID
    key_prefix: str
    role: str
    scopes: frozenset[str]
    project_id: uuid.UUID | None
    project_slug: str | None
    log_payloads: bool
    payload_retention_days: int
    rpm_limit: int
    tpm_limit: int

    @property
    def is_admin(self) -> bool:
        return self.role == "admin"
