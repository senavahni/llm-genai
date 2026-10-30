# To-Do (diperbarui 30 Oktober 2026)

TASK-01 s/d TASK-23 dikerjakan (rilis 0.1.0, lihat `CHANGELOG.md`). Profil aktif: **remote-only**
(semua model lokal nonaktif sementara; `scripts\start-all.bat --no-runtime`).

## Perlu tindakan pemilik proyek

- **Isi minimal satu API key** di `.env` (OpenAI/Anthropic/Gemini, atau provider custom seperti
  DeepSeek/Groq lewat `POST /admin/providers`, lihat `docs/model-catalog.md`). Tanpa key, profil
  `remote-only` tidak punya model yang bisa melayani request. Isi harga per 1 juta token lewat
  Admin API (seed = 0).
- **RAM**: model lokal 7B butuh RAM bebas ±6 GB setelah warmup (`docs/perf-report.md`). Setelah
  upgrade RAM: `manage.py apply-profile full` → `start-all.bat` → `test-hardware.bat`.

## Pekerjaan lanjutan

- Coder-1.5B: hint `tool_followup_hint` per model di runtime (disetujui, "pilihan 2") agar tidak
  mengulang tool call setelah menerima hasil tool; diperlukan saat profil `ram16` dipakai dengan MCP.
- Uji Traefik (Mode B): streaming real-time, 403 `/admin` dari luar allowlist, `client_ip` asli.
- Jalankan contoh `examples/` terhadap gateway (butuh API key remote atau profil `ram16`).
- Live smoke test provider remote (`tests/live`) setelah key diisi.
- Throughput > 80 RPS: write-behind batch untuk finalisasi usage (`docs/perf-report.md`).
- Uji swap 100× ulang setelah RAM cukup.
