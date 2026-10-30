"""Secret scan (TASK-20): cari pola secret di file log dan isi seluruh tabel DB. Harus 0 temuan.

    python scripts/secret_scan.py                 :: logs/ + DB dev (DATABASE_URL)
    python scripts/secret_scan.py --db test       :: logs/ + DB llm_gateway_test (setelah pytest)
    python scripts/secret_scan.py --db both --no-logs

Pola: key OpenAI `sk-...`, Anthropic `sk-ant-...`, Google `AIza...`, key gateway lengkap
`lgw_<prefix>_<secret>`. Temuan ditampilkan TERSAMAR (6 karakter awal) beserta lokasinya; exit 1
bila ada temuan."""

import argparse
import re
import sys
from collections.abc import Iterator
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

ROOT = Path(__file__).resolve().parents[1]

PATTERNS: dict[str, re.Pattern[str]] = {
    "anthropic": re.compile(r"sk-ant-[A-Za-z0-9_\-]{20,}"),
    "openai": re.compile(r"\bsk-(?!ant-)[A-Za-z0-9_\-]{20,}"),
    "google": re.compile(r"\bAIza[0-9A-Za-z_\-]{35}"),
    "gateway": re.compile(r"\blgw_[a-z0-9]{8}_[A-Za-z0-9_\-]{43}"),
}
LOG_SUFFIXES = {".log", ".out", ".err", ".json", ".jsonl", ".txt"}


def mask(secret: str) -> str:
    return secret[:6] + "***"


def scan_text(text: str) -> Iterator[tuple[str, str]]:
    for kind, pattern in PATTERNS.items():
        for match in pattern.finditer(text):
            yield kind, mask(match.group(0))


def _is_log(path: Path) -> bool:
    # file rotasi: app.log.2026-10-27
    return path.is_file() and any(s in LOG_SUFFIXES for s in path.suffixes)


def scan_logs(log_dir: Path) -> list[str]:
    findings = []
    for path in sorted(log_dir.rglob("*")):
        if not _is_log(path):
            continue
        with path.open(encoding="utf-8", errors="replace") as fh:
            for lineno, line in enumerate(fh, 1):
                for kind, masked in scan_text(line):
                    findings.append(f"{path.relative_to(ROOT)}:{lineno} {kind} {masked}")
    return findings


def _sync_url(url: str, database: str | None = None) -> str:
    parts = urlsplit(url.replace("postgresql+asyncpg://", "postgresql://", 1))
    if database:
        parts = parts._replace(path=f"/{database}")
    return urlunsplit(parts)


def scan_db(url: str) -> list[str]:
    import psycopg

    findings = []
    with psycopg.connect(url, connect_timeout=5) as conn:
        tables = [
            r[0]
            for r in conn.execute(
                "SELECT table_name FROM information_schema.tables "
                "WHERE table_schema = 'public' AND table_type = 'BASE TABLE' ORDER BY 1"
            )
        ]
        name = conn.info.dbname
        for table in tables:
            with conn.cursor(name=f"scan_{table}") as cur:  # server-side, hemat memori
                cur.execute(f'SELECT t::text FROM "{table}" t')  # noqa: S608 (nama dari katalog)
                for row_no, (text,) in enumerate(cur, 1):
                    for kind, masked in scan_text(text):
                        findings.append(f"db:{name}.{table} baris#{row_no} {kind} {masked}")
    return findings


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--db", choices=["dev", "test", "both", "none"], default="dev")
    parser.add_argument("--no-logs", action="store_true")
    parser.add_argument("--log-dir", default=str(ROOT / "logs"))
    args = parser.parse_args()

    findings: list[str] = []
    if not args.no_logs:
        findings += scan_logs(Path(args.log_dir))
    if args.db != "none":
        from dotenv import dotenv_values

        base = dotenv_values(ROOT / ".env").get("DATABASE_URL")
        if not base:
            print("DATABASE_URL tidak ada di .env", file=sys.stderr)
            return 2
        targets = {"dev": [None], "test": ["llm_gateway_test"], "both": [None, "llm_gateway_test"]}
        for database in targets[args.db]:
            findings += scan_db(_sync_url(base, database))

    for line in findings:
        print(line)
    print(f"secret scan: {len(findings)} temuan")
    return 1 if findings else 0


if __name__ == "__main__":
    sys.exit(main())
