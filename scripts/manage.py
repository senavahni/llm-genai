"""CLI operasional gateway.

python scripts\\manage.py seed [--update-local]
python scripts\\manage.py create-admin-key --name bootstrap
python scripts\\manage.py create-project --slug agent-a --name "Agent A" --allow "smart,local/*"
python scripts\\manage.py allow-models --project agent-a --patterns "smart,image"
python scripts\\manage.py create-key --project agent-a --name dev [--scopes chat,models:read]
python scripts\\manage.py replay-usage
"""

import argparse
import asyncio
import sys
import uuid
from datetime import timedelta
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from sqlalchemy import delete, select  # noqa: E402
from sqlalchemy.dialects.postgresql import insert  # noqa: E402
from sqlalchemy.ext.asyncio import AsyncSession  # noqa: E402

from app.core.config import ConfigError, get_settings  # noqa: E402
from app.core.database import SessionLocal, dispose_db  # noqa: E402
from app.models import (  # noqa: E402
    AuditLog,
    Model,
    ModelRoute,
    ModelRouteTarget,
    Project,
    Provider,
)
from app.models.api_key import VALID_SCOPES  # noqa: E402
from app.models.project import ProjectAllowedModel  # noqa: E402
from app.services.key_service import key_service  # noqa: E402
from app.utils.helper import utcnow  # noqa: E402

SEED_FILE = ROOT / "scripts" / "seed_models.yaml"
# kunci yaml yang bukan kolom tabel models
_MODEL_NON_COLUMNS = {"provider", "hf_repo", "convert"}
_LOCAL_UPDATE_FIELDS = (
    "provider_id",
    "upstream_name",
    "model_type",
    "tier",
    "device",
    "runtime_backend",
    "artifact_path",
    "artifact_sha256",
    "vram_mb",
    "is_pinned",
    "is_enabled",
    "supports_streaming",
    "supports_tools",
    "supports_vision",
    "supports_json_mode",
    "supports_fim",
    "context_window",
    "max_output_tokens",
    "embedding_dimensions",
    "license",
    "config",
)
# default kolom bila kunci tidak ada di yaml (agar sinkron = isi yaml, bukan sisa nilai lama)
_LOCAL_DEFAULTS: dict[str, Any] = {
    "is_pinned": False,
    "is_enabled": True,
    "supports_streaming": True,
    "supports_tools": False,
    "supports_vision": False,
    "supports_json_mode": False,
    "supports_fim": False,
    "artifact_sha256": None,
    "embedding_dimensions": None,
    "context_window": None,
    "max_output_tokens": None,
}


def _model_values(item: dict[str, Any], provider_ids: dict[str, Any]) -> dict[str, Any]:
    values = {k: v for k, v in item.items() if k not in _MODEL_NON_COLUMNS}
    values["provider_id"] = provider_ids[item["provider"]]
    config = dict(values.get("config") or {})
    if item.get("hf_repo"):
        config["source"] = {"hf_repo": item["hf_repo"], "convert": bool(item.get("convert"))}
    values["config"] = config
    return values


async def _seed(session: AsyncSession, data: dict[str, Any], update_local: bool) -> None:
    runtime_url = get_settings().runtime_url

    for p in data["providers"]:
        values = dict(p)
        if values.get("base_url") == "${RUNTIME_URL}":
            values["base_url"] = runtime_url
        await session.execute(
            insert(Provider).values(**values).on_conflict_do_nothing(index_elements=["code"])
        )
    provider_ids = {
        code: pid for code, pid in await session.execute(select(Provider.code, Provider.id))
    }

    for item in data["models"]:
        values = _model_values(item, provider_ids)
        await session.execute(
            insert(Model).values(**values).on_conflict_do_nothing(index_elements=["alias"])
        )

    if update_local:
        await _update_local(session, data, provider_ids)

    model_ids = {alias: mid for alias, mid in await session.execute(select(Model.alias, Model.id))}
    for r in data["routes"]:
        await session.execute(
            insert(ModelRoute)
            .values(
                alias=r["alias"],
                description=r.get("description"),
                strategy=r.get("strategy", "priority"),
            )
            .on_conflict_do_nothing(index_elements=["alias"])
        )
        route_id = (
            await session.execute(select(ModelRoute.id).where(ModelRoute.alias == r["alias"]))
        ).scalar_one()
        for t in r["targets"]:
            await session.execute(
                insert(ModelRouteTarget)
                .values(
                    route_id=route_id,
                    model_id=model_ids[t["model"]],
                    priority=t.get("priority", 1),
                    weight=t.get("weight", 1),
                )
                .on_conflict_do_nothing()
            )
    await session.commit()

    n_local = len([m for m in data["models"] if m.get("device", "remote") != "remote"])
    db_local = (
        (await session.execute(select(Model.alias).where(Model.device != "remote"))).scalars().all()
    )
    db_routes = (await session.execute(select(ModelRoute.alias))).scalars().all()
    print(
        f"seed OK: {len(provider_ids)} provider, {len(db_local)} model lokal "
        f"(yaml: {n_local}), {len(db_routes)} route"
    )


async def _update_local(
    session: AsyncSession, data: dict[str, Any], provider_ids: dict[str, Any]
) -> None:
    """Samakan model lokal di DB dengan yaml (semua kolom katalog), nonaktifkan model lokal yang
    sudah tidak ada di yaml. Setiap perubahan dicatat di audit_logs."""
    changed = 0
    in_yaml: set[str] = set()
    for item in data["models"]:
        if item.get("device", "remote") == "remote":
            continue
        in_yaml.add(item["alias"])
        desired = {**_LOCAL_DEFAULTS, **_model_values(item, provider_ids)}
        model = (
            await session.execute(select(Model).where(Model.alias == item["alias"]))
        ).scalar_one()
        before = {f: getattr(model, f) for f in _LOCAL_UPDATE_FIELDS}
        after = {f: desired.get(f, before[f]) for f in _LOCAL_UPDATE_FIELDS}
        if _audit_change(session, model, before, after, "model.update_local"):
            changed += 1
    stale = (
        (
            await session.execute(
                select(Model).where(Model.device != "remote", Model.is_enabled.is_(True))
            )
        )
        .scalars()
        .all()
    )
    for model in stale:
        if model.alias not in in_yaml:
            before = {"is_enabled": True}
            if _audit_change(session, model, before, {"is_enabled": False}, "model.disable_local"):
                changed += 1
    print(f"--update-local: {changed} model diperbarui")
    await session.flush()
    await _prune_disabled_local_targets(session)


async def _prune_disabled_local_targets(session: AsyncSession) -> None:
    """Hapus target route yang menunjuk model lokal nonaktif (katalog lama), dengan audit."""
    rows = (
        await session.execute(
            select(ModelRouteTarget, ModelRoute.alias, Model.alias)
            .join(ModelRoute, ModelRoute.id == ModelRouteTarget.route_id)
            .join(Model, Model.id == ModelRouteTarget.model_id)
            .where(Model.device != "remote", Model.is_enabled.is_(False))
        )
    ).all()
    for target, route_alias, model_alias in rows:
        await session.delete(target)
        session.add(
            AuditLog(
                actor_key_id=None,
                action="route.remove_target",
                entity_type="model_route",
                entity_id=str(target.route_id),
                before={"route": route_alias, "model": model_alias},
                after=None,
            )
        )
        print(f"  route.remove_target: {route_alias} → {model_alias}")
    await session.flush()
    empty = (
        (
            await session.execute(
                select(ModelRoute.alias).where(
                    ~select(ModelRouteTarget.route_id)
                    .where(ModelRouteTarget.route_id == ModelRoute.id)
                    .exists()
                )
            )
        )
        .scalars()
        .all()
    )
    for alias in empty:
        print(f"  ! route '{alias}' tidak punya target lagi (hapus/ubah lewat Admin API)")


def _audit_change(
    session: AsyncSession,
    model: Model,
    before: dict[str, Any],
    after: dict[str, Any],
    action: str,
) -> bool:
    if before == after:
        return False
    for f, v in after.items():
        setattr(model, f, v)
    session.add(
        AuditLog(
            actor_key_id=None,  # actor = system
            action=action,
            entity_type="model",
            entity_id=str(model.id),
            before={"alias": model.alias, **_jsonable(before)},
            after={"alias": model.alias, **_jsonable(after)},
        )
    )
    print(f"  {action}: {model.alias}")
    return True


def _jsonable(values: dict[str, Any]) -> dict[str, Any]:
    return {k: str(v) if isinstance(v, uuid.UUID) else v for k, v in values.items()}


async def cmd_seed(args: argparse.Namespace) -> None:
    data = yaml.safe_load(Path(args.file).read_text(encoding="utf-8"))
    async with SessionLocal() as session:
        await _seed(session, data, args.update_local)


def _print_key(full_key: str) -> None:
    print("\n  " + full_key + "\n")
    print("Simpan key ini sekarang: key TIDAK disimpan dan tidak dapat ditampilkan lagi.")


async def cmd_create_admin_key(args: argparse.Namespace) -> None:
    async with SessionLocal() as session:
        full_key, key = await key_service.create_key(
            session, project_id=None, name=args.name, role="admin"
        )
    print(f"admin key dibuat: id={key.id} prefix={key.key_prefix}")
    _print_key(full_key)


async def cmd_create_project(args: argparse.Namespace) -> None:
    async with SessionLocal() as session:
        project = Project(
            slug=args.slug, name=args.name, owner=args.owner, description=args.description
        )
        session.add(project)
        await session.flush()
        patterns = _patterns(args.allow)
        session.add_all(
            ProjectAllowedModel(project_id=project.id, model_pattern=p) for p in patterns
        )
        await session.commit()
        print(f"project dibuat: id={project.id} slug={project.slug} allow={patterns or '-'}")
    if not patterns:
        print("PERINGATAN: tanpa pola model, semua request project ini ditolak (allow-models).")


async def cmd_allow_models(args: argparse.Namespace) -> None:
    async with SessionLocal() as session:
        project = (
            await session.execute(select(Project).where(Project.slug == args.project))
        ).scalar_one_or_none()
        if project is None:
            raise SystemExit(f"project '{args.project}' tidak ditemukan")
        await session.execute(
            delete(ProjectAllowedModel).where(ProjectAllowedModel.project_id == project.id)
        )
        patterns = _patterns(args.patterns)
        session.add_all(
            ProjectAllowedModel(project_id=project.id, model_pattern=p) for p in patterns
        )
        session.add(
            AuditLog(
                actor_key_id=None,
                action="project.allowed_models",
                entity_type="project",
                entity_id=str(project.id),
                after={"slug": project.slug, "patterns": patterns},
            )
        )
        await session.commit()
    key_service.invalidate()
    print(f"{args.project}: pola model = {patterns or '(kosong: semua ditolak)'}")


def _patterns(raw: str | None) -> list[str]:
    return list(dict.fromkeys(p.strip() for p in (raw or "").split(",") if p.strip()))


async def cmd_replay_usage(args: argparse.Namespace) -> None:
    from app.services.usage_service import usage_service

    ok, failed = await usage_service.replay()
    print(f"replay usage: {ok} record tertulis, {failed} gagal")
    if failed:
        print(f"record gagal tetap di {usage_service.fallback_path}")


async def cmd_create_key(args: argparse.Namespace) -> None:
    async with SessionLocal() as session:
        project = (
            await session.execute(select(Project).where(Project.slug == args.project))
        ).scalar_one_or_none()
        if project is None:
            raise SystemExit(f"project '{args.project}' tidak ditemukan")
        scopes = [s.strip() for s in args.scopes.split(",")] if args.scopes else VALID_SCOPES
        expires_at = utcnow() + timedelta(days=args.expires_days) if args.expires_days else None
        full_key, key = await key_service.create_key(
            session,
            project_id=project.id,
            name=args.name,
            scopes=scopes,
            rpm_limit=args.rpm,
            tpm_limit=args.tpm,
            expires_at=expires_at,
        )
    print(
        f"key dibuat: id={key.id} prefix={key.key_prefix} project={project.slug} "
        f"scopes={','.join(key.scopes)}"
    )
    _print_key(full_key)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="manage.py")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("seed", help="seed providers, models, routes (idempoten)")
    p.add_argument(
        "--update-local",
        action="store_true",
        help="perbarui vram_mb/artifact_sha256/config model lokal dari yaml",
    )
    p.add_argument("--file", default=str(SEED_FILE))
    p.set_defaults(func=cmd_seed)

    p = sub.add_parser("create-admin-key", help="buat admin key (bootstrap)")
    p.add_argument("--name", required=True)
    p.set_defaults(func=cmd_create_admin_key)

    p = sub.add_parser("create-project")
    p.add_argument("--slug", required=True)
    p.add_argument("--name", required=True)
    p.add_argument("--owner")
    p.add_argument("--description")
    p.add_argument("--allow", help="pola model/route yang diizinkan, dipisah koma (glob)")
    p.set_defaults(func=cmd_create_project)

    p = sub.add_parser("allow-models", help="ganti pola model/route yang diizinkan project")
    p.add_argument("--project", required=True, help="slug project")
    p.add_argument("--patterns", required=True, help="dipisah koma, mis. 'smart,code,local/*'")
    p.set_defaults(func=cmd_allow_models)

    p = sub.add_parser("replay-usage", help="tulis ulang logs/usage_fallback.jsonl ke DB")
    p.set_defaults(func=cmd_replay_usage)

    p = sub.add_parser("create-key", help="buat client key untuk project")
    p.add_argument("--project", required=True, help="slug project")
    p.add_argument("--name", required=True)
    p.add_argument("--scopes", help=f"dipisah koma; default semua: {','.join(VALID_SCOPES)}")
    p.add_argument("--rpm", type=int)
    p.add_argument("--tpm", type=int)
    p.add_argument("--expires-days", type=int)
    p.set_defaults(func=cmd_create_key)
    return parser


async def _run(args: argparse.Namespace) -> None:
    try:
        await args.func(args)
    finally:
        await dispose_db()


def main() -> None:
    args = build_parser().parse_args()
    try:
        asyncio.run(_run(args))
    except ConfigError as exc:
        raise SystemExit(str(exc)) from None


if __name__ == "__main__":
    main()
