"""Backup PostgreSQL gateway (pg_dump format custom) ke backups/, simpan 7 terakhir (TASK-19).

    scripts\\backup-db.bat             :: backup harian
    scripts\\backup-db.bat --verify    :: backup lalu restore uji ke DB uji + bandingkan
                                        :: jumlah baris semua tabel (DB uji DITIMPA)

Kredensial diambil dari DATABASE_URL (.env); password dikirim via PGPASSWORD (tidak tampil di
argumen proses). Lokasi bin PostgreSQL: env PG_BIN atau default PortableDev."""

import argparse
import datetime
import os
import subprocess
import sys
from pathlib import Path
from urllib.parse import unquote, urlsplit

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
DEFAULT_PG_BIN = r"D:\Data.Fahrul\Documents\PortableDev\postgres\pgsql\bin"
KEEP = 7


def _conn() -> dict[str, str]:
    from app.core.config import get_settings

    url = urlsplit(get_settings().database_url.replace("+asyncpg", ""))
    return {
        "host": url.hostname or "127.0.0.1",
        "port": str(url.port or 5432),
        "user": unquote(url.username or ""),
        "password": unquote(url.password or ""),
        "db": url.path.lstrip("/"),
    }


def _run(exe: Path, args: list[str], c: dict[str, str]) -> str:
    env = {**os.environ, "PGPASSWORD": c["password"]}
    base = ["-h", c["host"], "-p", c["port"], "-U", c["user"]]
    result = subprocess.run(
        [str(exe), *base, *args], env=env, capture_output=True, text=True, check=False
    )
    if result.returncode != 0:
        raise SystemExit(f"{exe.name} gagal: {result.stderr.strip()}")
    return result.stdout


def _counts(pg_bin: Path, c: dict[str, str], db: str) -> dict[str, int]:
    sql = (
        "SELECT string_agg(format('%s=%s', t, (xpath('/row/c/text()', "
        "query_to_xml(format('select count(*) as c from %I', t), false, true, '')))[1]::text), ';' "
        "ORDER BY t) FROM unnest(ARRAY(SELECT tablename FROM pg_tables "
        "WHERE schemaname = 'public')) AS t"
    )
    out = _run(pg_bin / "psql.exe", ["-d", db, "-At", "-c", sql], c).strip()
    return {k: int(v) for k, v in (item.split("=") for item in out.split(";") if item)}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out-dir", default=str(ROOT / "backups"))
    ap.add_argument("--verify", action="store_true")
    ap.add_argument("--verify-db", default="llm_gateway_test", help="DB uji (akan ditimpa)")
    args = ap.parse_args()

    pg_bin = Path(os.environ.get("PG_BIN") or DEFAULT_PG_BIN)
    c = _conn()
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    target = out_dir / f"{c['db']}_{datetime.date.today().isoformat()}.dump"
    _run(pg_bin / "pg_dump.exe", ["-F", "c", "-f", str(target), c["db"]], c)
    print(f"backup: {target} ({target.stat().st_size / 1e6:.1f} MB)")

    dumps = sorted(out_dir.glob(f"{c['db']}_*.dump"), key=lambda p: p.stat().st_mtime)
    for old in dumps[:-KEEP]:
        old.unlink()
        print(f"hapus backup lama: {old.name}")

    if args.verify:
        if args.verify_db == c["db"]:
            raise SystemExit("--verify-db tidak boleh sama dengan DB produksi")
        _run(
            pg_bin / "pg_restore.exe",
            ["-d", args.verify_db, "-c", "--if-exists", "--no-owner", str(target)],
            c,
        )
        source, restored = _counts(pg_bin, c, c["db"]), _counts(pg_bin, c, args.verify_db)
        diff = {
            t: (source.get(t), restored.get(t)) for t in source if source.get(t) != restored.get(t)
        }
        for table in sorted(source):
            print(f"  {table:<24} {source[table]:>8} → {restored.get(table)}")
        if diff:
            print(f"BEDA: {diff}", file=sys.stderr)
            return 1
        print(f"verifikasi OK: {len(source)} tabel identik di {args.verify_db}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
