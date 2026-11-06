// Konsol LLM Gateway: project, API key lgw_, kuota, provider, status .env (memakai Admin API /admin/*).
'use strict';

(() => {
  const { h, api, toast, confirm, showSecret, form, priceLabel, help, badge, table, btn, action, when, genUrlSafe } = Kit;
  const root = document.getElementById('root');
  const MCP_PROJECT = 'marketing-mcp';
  const SCOPES = ['chat', 'completions', 'embeddings', 'images', 'models:read', 'usage:read'];
  const SCOPE_HELP = 'Biasanya cukup chat + embeddings + models:read. MCP memakai chat, embeddings, models:read, usage:read.';

  const pageHead = (eyebrow, title, desc, actions) =>
    h('div', { class: 'page-head' }, h('div', {}, h('div', { class: 'eyebrow', text: eyebrow }), h('h1', { text: title }), desc ? h('p', { text: desc }) : null), actions ? h('div', { class: 'actions' }, actions) : null);

  const usd = (v) => (v === null || v === undefined ? '—' : `$${Number(v).toFixed(2)}`);

  // ============================================================== 01 Mulai
  async function startPage({ go }) {
    const [env, projects] = await Promise.all([api('GET', '/admin/env-status'), api('GET', '/admin/projects')]);
    const mcp = projects.data.find((p) => p.slug === MCP_PROJECT);
    const [keys, quotas] = mcp
      ? await Promise.all([api('GET', `/admin/projects/${mcp.id}/keys`), api('GET', `/admin/projects/${mcp.id}/quotas`)])
      : [{ data: [] }, { data: [] }];
    const remote = env.providers.filter((p) => p.is_enabled && p.key_state !== 'not_needed');
    const providerOk = remote.some((p) => p.key_state === 'ok');
    const activeKeys = keys.data.filter((k) => k.status === 'active');
    const costQuota = quotas.data.some((q) => q.is_enabled && q.max_cost_usd !== null);

    return h(
      'div',
      { class: 'stack' },
      pageHead('01 · Mulai di sini', 'Ringkasan kredensial Gateway', 'Gateway adalah satu-satunya tempat yang memegang API key OpenAI/Anthropic/Gemini. Aplikasi lain (MCP, Dashboard) hanya memegang key lgw_ buatan Gateway.'),
      h(
        'section',
        { class: 'card' },
        h('div', { class: 'card-head' }, h('h2', { text: 'Alur key' })),
        Kit.flow(
          [
            { label: 'Dashboard', sub: 'tidak pegang key LLM' },
            { label: 'MCP', sub: 'key lgw_ per agent (terenkripsi)' },
            { label: 'LLM Gateway', sub: 'konsol ini', here: true },
            { label: 'OpenAI / dll.', sub: 'key provider di .env' },
          ],
          ['mcpk_ / MCP_SERVER_API_KEY', 'lgw_…', 'OPENAI_API_KEY'],
        ),
        h('p', { class: 'muted', text: 'Tiap panah = satu jenis kredensial. Kalau satu bocor, cukup cabut yang itu saja tanpa mengganggu yang lain.' }),
      ),
      Kit.checklist([
        { done: true, title: 'Masuk dengan admin key', detail: 'Admin key berbeda dari key aplikasi: hanya untuk mengelola Gateway, jangan dipasang di aplikasi mana pun.' },
        {
          done: providerOk,
          title: 'API key provider terisi di .env Gateway',
          detail: providerOk ? `Provider siap: ${remote.filter((p) => p.key_state === 'ok').map((p) => p.display_name).join(', ')}.` : 'Isi mis. OPENAI_API_KEY di file .env Gateway lalu restart Gateway.',
          action: providerOk ? null : btn('Lihat provider', () => go('providers'), 'ghost', { class: 'btn btn-ghost btn-sm' }),
        },
        {
          done: !!mcp,
          title: `Project "${MCP_PROJECT}" untuk agent MCP`,
          detail: mcp ? 'Project ada. Semua key agent MCP berada di project ini sehingga biayanya terkumpul dan bisa dibatasi.' : 'Paling mudah: buka Konsol MCP → "Key LLM per agent" → Provision otomatis. Project & key dibuat sekaligus.',
        },
        {
          done: activeKeys.length > 0,
          title: 'Key aktif untuk agent MCP',
          detail: activeKeys.length ? `${activeKeys.length} key aktif (${activeKeys.map((k) => k.name).join(', ')}).` : 'Belum ada key aktif di project MCP.',
        },
        {
          done: costQuota,
          title: 'Batas biaya (kuota USD) diset',
          detail: costQuota ? 'Gateway menolak permintaan saat kuota habis — tagihan tidak bisa kebablasan.' : 'Disarankan: harian $5, bulanan $50. Atur di menu Project & Key.',
          action: mcp && !costQuota ? btn('Atur kuota', () => go('projects'), 'ghost', { class: 'btn btn-ghost btn-sm' }) : null,
        },
      ]),
      help(
        'Istilah yang perlu diketahui',
        [
          h('ul', {}, [
            h('li', {}, h('strong', { text: 'Admin key' }), ' — key role admin untuk konsol & Admin API. Dibuat lewat CLI, tidak bisa dibuat dari konsol (supaya kebocoran sesi tidak bisa mencetak admin baru).'),
            h('li', {}, h('strong', { text: 'Project' }), ' — wadah untuk satu aplikasi/tim. Model yang diizinkan & kuota biaya diatur per project.'),
            h('li', {}, h('strong', { text: 'Key lgw_' }), ' — key aplikasi milik satu project. Ditampilkan sekali saat dibuat; yang tersimpan hanya hash-nya.'),
            h('li', {}, h('strong', { text: 'Rotasi' }), ' — buat key baru & matikan yang lama sekaligus. Aplikasi pemakai harus diberi key baru.'),
            h('li', {}, h('strong', { text: 'Cabut' }), ' — matikan key permanen (mis. bocor). Berlaku dalam hitungan detik.'),
          ]),
        ],
        { open: true },
      ),
    );
  }

  // ===================================================== 02 Project & Key
  let selectedProject = null;

  async function projectsPage({ refresh }) {
    const projects = (await api('GET', '/admin/projects')).data;
    if (!projects.find((p) => p.id === selectedProject)) {
      selectedProject = (projects.find((p) => p.slug === MCP_PROJECT) || projects.find((p) => p.status !== 'archived') || {}).id || null;
    }
    const list = table(
      [
        { label: 'Project', render: (p) => h('button', { type: 'button', class: 'btn btn-sm ' + (p.id === selectedProject ? 'btn-primary' : 'btn-ghost'), onclick: () => { selectedProject = p.id; refresh(); } }, p.name) },
        { label: 'Slug', render: (p) => h('code', { text: p.slug }) },
        { label: 'Status', render: (p) => badge(p.status === 'active' ? 'active' : p.status) },
        { label: 'Pemilik', render: (p) => p.owner || '—' },
      ],
      projects,
      { empty: 'Belum ada project. Buat satu, atau jalankan provisioning dari Konsol MCP.' },
    );
    const detail = selectedProject ? await projectDetail(selectedProject, refresh) : null;
    return h(
      'div',
      { class: 'stack' },
      pageHead('02 · Project & Key', 'Project, API key & kuota', 'Pilih project untuk melihat key-nya. Key lengkap hanya muncul sekali saat dibuat/dirotasi.', [action('+ Project baru', () => createProject(refresh), 'primary')]),
      h('section', { class: 'card' }, list),
      detail,
      help('Kapan rotasi, kapan cabut?', [
        'Rotasi: rutin (mis. 3–6 bulan) atau saat orang yang tahu key-nya keluar tim. Key baru langsung dipakai, key lama mati saat itu juga — siapkan tempat tujuan key baru dulu.',
        'Cabut: saat key bocor/tidak dipakai lagi. Aplikasi yang masih memakainya akan mendapat error 401.',
        'Untuk key agent MCP, lebih aman rotasi dari Konsol MCP (Provision ulang) karena MCP otomatis menyimpan key baru terenkripsi.',
      ]),
    );
  }

  async function projectDetail(id, refresh) {
    const [project, keys, quotas] = await Promise.all([api('GET', `/admin/projects/${id}`), api('GET', `/admin/projects/${id}/keys`), api('GET', `/admin/projects/${id}/quotas`)]);
    const archived = project.status === 'archived';
    const q = Object.fromEntries(quotas.data.map((x) => [x.period, x]));
    const keyRows = keys.data.filter((k) => k.status === 'active').concat(keys.data.filter((k) => k.status !== 'active'));

    const keyTable = table(
      [
        { label: 'Nama', render: (k) => h('div', {}, h('strong', { text: k.name }), h('span', { class: 'sub', text: `dibuat ${when(k.created_at)}` })) },
        { label: 'Prefix', render: (k) => h('code', { text: k.key_prefix }) },
        { label: 'Scope', render: (k) => h('div', {}, k.scopes.map((s) => h('span', { class: 'tag', text: s }))) },
        { label: 'Model diizinkan', render: (k) => keyModels(k) },
        { label: 'RPM', class: 'num', render: (k) => (k.rpm_limit ?? 'default') },
        { label: 'Status', render: (k) => h('div', {}, badge(k.status), k.revoked_reason ? h('span', { class: 'sub', text: k.revoked_reason }) : null) },
        { label: 'Terakhir dipakai', render: (k) => when(k.last_used_at) },
        {
          label: 'Aksi',
          class: 'actions',
          render: (k) =>
            k.status === 'active'
              ? h('span', {}, action('Model', () => editKeyModels(k, refresh), 'ghost', { class: 'btn btn-ghost btn-sm' }), action('Rotasi', () => rotateKey(k, refresh), 'ghost', { class: 'btn btn-ghost btn-sm' }), action('Cabut', () => revokeKey(k, refresh), 'danger', { class: 'btn btn-danger btn-sm' }))
              : '—',
        },
      ],
      keyRows,
      { empty: 'Project ini belum punya key.' },
    );

    return h(
      'div',
      { class: 'stack' },
      h(
        'section',
        { class: 'card' },
        h(
          'div',
          { class: 'card-head' },
          h('div', {}, h('h2', { text: project.name }), h('span', { class: 'sub' }, h('code', { text: project.slug }), ' · ', project.description || 'tanpa deskripsi')),
          h(
            'div',
            { class: 'actions' },
            archived ? null : action('+ Buat key', () => createKey(project, refresh), 'primary'),
            archived ? null : action(project.status === 'active' ? 'Tangguhkan' : 'Aktifkan', () => toggleProject(project, refresh)),
            archived ? null : action('Arsipkan', () => archiveProject(project, refresh), 'danger'),
          ),
        ),
        project.status === 'suspended' ? h('div', { class: 'callout callout-warn' }, h('strong', { text: 'Project ditangguhkan' }), 'Semua key project ini ditolak sampai diaktifkan lagi.') : null,
        keyTable,
      ),
      h(
        'div',
        { class: 'grid-2' },
        h(
          'section',
          { class: 'card' },
          h('div', { class: 'card-head' }, h('h2', { text: 'Kuota biaya' }), archived ? null : action('Ubah', () => editQuotas(project, q, refresh), 'ghost', { class: 'btn btn-ghost btn-sm' })),
          h('dl', { class: 'kv' }, h('dt', { text: 'Harian' }), h('dd', {}, q.daily && q.daily.is_enabled ? usd(q.daily.max_cost_usd) : 'tanpa batas'), h('dt', { text: 'Bulanan' }), h('dd', {}, q.monthly && q.monthly.is_enabled ? usd(q.monthly.max_cost_usd) : 'tanpa batas')),
          h('p', { class: 'muted', text: 'Saat kuota habis, Gateway menolak permintaan project ini sampai periode berganti.' }),
        ),
        h(
          'section',
          { class: 'card' },
          h('div', { class: 'card-head' }, h('h2', { text: 'Model yang diizinkan' }), archived ? null : action('Ubah', () => editModels(project, refresh), 'ghost', { class: 'btn btn-ghost btn-sm' })),
          h('div', {}, (project.allowed_models || []).length ? project.allowed_models.map((m) => h('span', { class: 'tag', text: m })) : h('span', { class: 'muted', text: 'Belum ada — semua permintaan model ditolak.' })),
          h('p', { class: 'muted', text: 'Route (mis. smart) DAN kandidatnya (mis. openai/*) harus diizinkan. Berlaku untuk semua key project ini, kecuali key yang punya pengaturan model khusus (tombol "Model" di tabel key).' }),
        ),
      ),
    );
  }

  async function createProject(refresh) {
    const v = await form({
      title: 'Project baru',
      intro: 'Satu project per aplikasi/tim. Untuk agent MCP tidak perlu dibuat manual — provisioning dari Konsol MCP membuat project "marketing-mcp".',
      fields: [
        { name: 'slug', label: 'Slug', required: true, placeholder: 'mis. riset-tim-a', help: 'huruf kecil, angka, tanda minus; tidak bisa diubah.' },
        { name: 'name', label: 'Nama tampilan', required: true },
        { name: 'owner', label: 'Pemilik / PIC' },
        { name: 'allowed', label: 'Model yang diizinkan', type: 'picker', multiple: true, items: await patternItems(), value: ['fast', 'smart', 'embed-default', 'openai/*'], help: PATTERN_HELP },
      ],
      submitLabel: 'Buat project',
    });
    if (!v) return;
    const created = await api('POST', '/admin/projects', {
      slug: v.slug,
      name: v.name,
      owner: v.owner || null,
      allowed_models: v.allowed,
    });
    selectedProject = created.id;
    toast(`Project ${created.slug} dibuat`);
    refresh();
  }

  async function createKey(project, refresh) {
    const v = await form({
      title: `Key baru · ${project.slug}`,
      fields: [
        { name: 'name', label: 'Nama key', required: true, placeholder: 'mis. backend-prod', help: 'Nama aplikasi pemakai, supaya mudah dilacak.' },
        { name: 'scopes', label: 'Scope', type: 'checks', value: ['chat', 'embeddings', 'models:read'], options: SCOPES.map((s) => ({ value: s, label: s })), help: SCOPE_HELP },
        { name: 'models', label: 'Model khusus key ini', type: 'picker', multiple: true, items: await patternItems(), value: [], placeholder: 'kosong = ikut project; ketik mis. openrouter', help: KEY_MODELS_HELP },
        { name: 'rpm', label: 'Batas request/menit', type: 'number', min: 1, help: 'kosong = default Gateway.' },
        { name: 'expires', label: 'Kedaluwarsa', type: 'date', help: 'kosong = tidak kedaluwarsa.' },
      ],
      submitLabel: 'Buat key',
    });
    if (!v) return;
    if (!v.scopes.length) throw new Error('Pilih minimal satu scope.');
    const created = await api('POST', `/admin/projects/${project.id}/keys`, {
      name: v.name,
      scopes: v.scopes,
      allowed_models: v.models,
      rpm_limit: v.rpm,
      expires_at: v.expires ? new Date(`${v.expires}T23:59:59`).toISOString() : null,
    });
    await showSecret({ title: `Key ${created.name}`, secret: created.key, note: 'Tempel ke aplikasi pemakai (mis. .env-nya). Untuk agent MCP: Konsol MCP → Key LLM per agent → Impor.' });
    refresh();
  }

  const KEY_MODELS_HELP = 'Kosong = ikut "Model yang diizinkan" project. Diisi = HANYA pola ini yang berlaku untuk key ini (pola project diabaikan). Route dan kandidatnya harus tercakup.';
  const PATTERN_HELP = 'Klik untuk melihat pilihan, ketik untuk mencari. Route (mis. smart) DAN kandidatnya (mis. openai/*) harus diizinkan. Harga = estimasi.';

  // ------------------------------------------------- katalog untuk pemilih model
  const capsText = (m) => [m.supports_tools && 'tools', m.supports_json_mode && 'JSON', m.supports_vision && 'vision', m.supports_fim && 'FIM', m.model_type !== 'chat' && m.model_type].filter(Boolean).join(', ');
  const isProviderAuto = (alias) => alias.endsWith('/auto');

  async function loadCatalog() {
    return api('GET', '/admin/catalog');
  }

  // Pilihan pemilih: route global, auto per provider, (pola) semua model 1 provider, model spesifik.
  function catalogItems(cat, { patterns }) {
    const names = Object.fromEntries(cat.providers.map((p) => [p.code, p.display_name]));
    const items = [];
    const routeItem = (r, group) => ({
      value: r.alias,
      label: r.alias + (r.is_enabled ? '' : ' (nonaktif)'),
      group,
      sub: [r.description, priceLabel(r.pricing), `kandidat: ${r.targets.map((t) => t.model_alias).join(' → ')}`].filter(Boolean).join(' · '),
    });
    cat.routes.filter((r) => !isProviderAuto(r.alias)).forEach((r) => items.push(routeItem(r, 'Route global (auto, berpindah antar kandidat)')));
    cat.routes.filter((r) => isProviderAuto(r.alias)).forEach((r) => items.push(routeItem(r, 'Auto per provider')));
    if (patterns) {
      cat.providers.forEach((p) => {
        const own = cat.models.filter((m) => m.provider_code === p.code);
        if (own.length) items.push({ value: `${p.code}/*`, label: `${p.code}/*`, group: 'Semua model satu provider (termasuk auto-nya)', sub: `${p.display_name} · ${own.length} model` });
      });
    }
    cat.models.forEach((m) => {
      items.push({
        value: m.alias,
        label: m.alias + (m.is_enabled ? '' : ' (nonaktif)'),
        group: `Model · ${names[m.provider_code] || m.provider_code}`,
        sub: [priceLabel(m.pricing), capsText(m), m.upstream_name].filter(Boolean).join(' · '),
        search: m.upstream_name,
      });
    });
    return items;
  }

  async function patternItems() {
    return catalogItems(await loadCatalog(), { patterns: true });
  }

  function keyModels(k) {
    const own = k.allowed_models || [];
    if (!own.length) return h('span', { class: 'muted', text: 'ikut project' });
    return h('div', {}, own.map((m) => h('span', { class: 'tag', text: m })), h('span', { class: 'sub', text: 'khusus key' }));
  }

  async function editKeyModels(k, refresh) {
    const v = await form({
      title: `Model khusus key · ${k.name}`,
      intro: 'Kosongkan untuk kembali ikut pola project. Berlaku ≤ 60 detik, tanpa ganti key.',
      fields: [{ name: 'patterns', label: 'Pola model', type: 'picker', multiple: true, items: await patternItems(), value: k.allowed_models || [], placeholder: 'kosong = ikut project; ketik mis. openrouter', help: KEY_MODELS_HELP }],
    });
    if (!v) return;
    const r = await api('PUT', `/admin/keys/${k.id}/allowed-models`, { patterns: v.patterns });
    toast(r.inherits_project ? `Key ${k.name} kembali ikut project` : `Model khusus key ${k.name} disimpan`);
    refresh();
  }

  async function rotateKey(k, refresh) {
    const ok = await confirm({ title: `Rotasi key ${k.name}?`, message: `Key ${k.key_prefix}… langsung tidak berlaku. Aplikasi yang memakainya error sampai diberi key baru.`, confirmLabel: 'Rotasi sekarang', danger: true });
    if (!ok) return;
    const created = await api('POST', `/admin/keys/${k.id}/rotate`);
    await showSecret({ title: `Key baru ${created.name}`, secret: created.key, note: 'Ganti key lama di aplikasi pemakai dengan nilai ini.' });
    refresh();
  }

  async function revokeKey(k, refresh) {
    const v = await form({ title: `Cabut key ${k.name}?`, intro: `Key ${k.key_prefix}… dimatikan permanen. Tidak bisa diaktifkan lagi.`, fields: [{ name: 'reason', label: 'Alasan', required: true, placeholder: 'mis. bocor di log / tidak dipakai' }], submitLabel: 'Cabut key' });
    if (!v) return;
    await api('POST', `/admin/keys/${k.id}/revoke`, { reason: v.reason });
    toast(`Key ${k.name} dicabut`);
    refresh();
  }

  async function toggleProject(p, refresh) {
    const next = p.status === 'active' ? 'suspended' : 'active';
    if (next === 'suspended' && !(await confirm({ title: `Tangguhkan ${p.slug}?`, message: 'Semua key project ini ditolak sementara. Bisa diaktifkan lagi kapan saja.', confirmLabel: 'Tangguhkan', danger: true }))) return;
    await api('PATCH', `/admin/projects/${p.id}`, { status: next });
    toast(next === 'active' ? 'Project diaktifkan' : 'Project ditangguhkan');
    refresh();
  }

  async function archiveProject(p, refresh) {
    const ok = await confirm({ title: `Arsipkan ${p.slug}?`, message: 'Project diarsipkan permanen dan semua key aktifnya dicabut. Riwayat pemakaian tetap tersimpan.', confirmLabel: 'Arsipkan', danger: true, typeToConfirm: p.slug });
    if (!ok) return;
    await api('DELETE', `/admin/projects/${p.id}`);
    toast('Project diarsipkan');
    refresh();
  }

  async function editQuotas(p, q, refresh) {
    const cur = (period) => (q[period] && q[period].is_enabled && q[period].max_cost_usd !== null ? Number(q[period].max_cost_usd) : '');
    const v = await form({
      title: `Kuota biaya · ${p.slug}`,
      intro: 'Kosongkan untuk tanpa batas. Batas request/token yang sudah ada tidak berubah.',
      fields: [
        { name: 'daily', label: 'Maks. biaya harian (USD)', type: 'number', min: 0, step: '0.01', value: cur('daily'), placeholder: 'mis. 5' },
        { name: 'monthly', label: 'Maks. biaya bulanan (USD)', type: 'number', min: 0, step: '0.01', value: cur('monthly'), placeholder: 'mis. 50' },
      ],
    });
    if (!v) return;
    const quota = (period, value) => {
      const old = q[period] || {};
      const hasOther = [old.max_requests, old.max_tokens, old.max_images].some((x) => x !== null && x !== undefined);
      return {
        period,
        max_requests: old.max_requests ?? null,
        max_tokens: old.max_tokens ?? null,
        max_images: old.max_images ?? null,
        max_cost_usd: value === null ? null : value.toFixed(2),
        is_enabled: value !== null || (hasOther && old.is_enabled !== false),
      };
    };
    await api('PUT', `/admin/projects/${p.id}/quotas`, { quotas: [quota('daily', v.daily), quota('monthly', v.monthly)] });
    toast('Kuota disimpan');
    refresh();
  }

  async function editModels(p, refresh) {
    const v = await form({
      title: `Model diizinkan · ${p.slug}`,
      fields: [{ name: 'patterns', label: 'Pola model', type: 'picker', multiple: true, required: true, items: await patternItems(), value: p.allowed_models || [], help: PATTERN_HELP }],
    });
    if (!v) return;
    await api('PUT', `/admin/projects/${p.id}/allowed-models`, { patterns: v.patterns });
    toast('Daftar model disimpan');
    refresh();
  }

  // ======================================================= 03 Provider
  let selectedProvider = null;

  async function providersPage({ refresh }) {
    const [env, cat] = await Promise.all([api('GET', '/admin/env-status'), loadCatalog()]);
    const count = (code) => cat.models.filter((m) => m.provider_code === code).length;
    if (!env.providers.some((p) => p.code === selectedProvider)) selectedProvider = null;
    const selected = env.providers.find((p) => p.code === selectedProvider);
    return h(
      'div',
      { class: 'stack' },
      pageHead('03 · Provider', 'Provider, model & auto', 'Pilih "Model" untuk melihat harga estimasi, menyalakan/mematikan model, dan mengatur route auto provider itu. API key provider tetap hanya di file .env Gateway.'),
      h(
        'section',
        { class: 'card' },
        table(
          [
            { label: 'Provider', render: (p) => h('div', {}, h('strong', { text: p.display_name }), h('span', { class: 'sub', text: p.code })) },
            { label: 'Aktif', render: (p) => badge(p.is_enabled ? 'active' : 'not_needed', p.is_enabled ? 'Aktif' : 'Nonaktif') },
            { label: 'Variabel .env', render: (p) => (p.api_key_env ? h('code', { text: p.api_key_env }) : '—') },
            { label: 'Status key', render: (p) => badge(p.key_state) },
            {
              label: 'Aksi',
              class: 'actions',
              render: (p) =>
                h(
                  'span',
                  {},
                  h('button', { type: 'button', class: 'btn btn-sm ' + (p.code === selectedProvider ? 'btn-primary' : 'btn-ghost'), onclick: () => { selectedProvider = p.code === selectedProvider ? null : p.code; refresh(); } }, `Model (${count(p.code)})`),
                  p.is_enabled
                    ? action('Tes koneksi', async () => {
                        const r = await api('POST', `/admin/providers/${encodeURIComponent(p.code)}/test`);
                        const ok = !!(r && r.ok);
                        toast(ok ? `${p.display_name}: terhubung` : `${p.display_name}: ${(r && r.detail) || 'gagal'}`, ok ? 'ok' : 'err');
                      }, 'ghost', { class: 'btn btn-ghost btn-sm' })
                    : null,
                ),
            },
          ],
          env.providers,
        ),
      ),
      selected ? providerDetail(selected, cat, refresh) : null,
      help(
        'Cara mengisi / mengganti API key provider',
        [
          h('ol', {}, [
            h('li', { text: 'Buka file .env di folder llm-genai dengan Notepad.' }),
            h('li', {}, 'Isi baris sesuai kolom "Variabel .env", mis. ', h('code', { text: 'OPENAI_API_KEY=sk-...' }), '. Jangan beri komentar di akhir baris.'),
            h('li', { text: 'Simpan, lalu restart Gateway (tutup jendela Gateway → jalankan start.bat lagi).' }),
            h('li', { text: 'Kembali ke sini, tekan "Tes koneksi".' }),
          ]),
          'Kenapa tidak bisa diisi dari sini? Supaya key provider (yang terhubung ke tagihan) tidak pernah lewat browser dan tidak tersimpan di database.',
        ],
        { open: true },
      ),
    );
  }

  // (A) model provider + (B) route auto provider `<code>/auto`
  function providerDetail(p, cat, refresh) {
    const models = cat.models.filter((m) => m.provider_code === p.code);
    const autoAlias = `${p.code}/auto`;
    const auto = cat.routes.find((r) => r.alias === autoAlias);
    const usedBy = (alias) => cat.routes.filter((r) => r.targets.some((t) => t.model_alias === alias)).map((r) => r.alias);
    const modelTable = table(
      [
        { label: 'Model', render: (m) => h('div', {}, h('code', { text: m.alias }), h('span', { class: 'sub', text: `upstream: ${m.upstream_name}` })) },
        { label: 'Harga (estimasi)', render: (m) => h('span', { class: m.pricing.kind === 'free' ? 'tag' : '', text: priceLabel(m.pricing) }) },
        { label: 'Kapabilitas', render: (m) => capsText(m) || '—' },
        { label: 'Konteks', class: 'num', render: (m) => (m.context_window ? m.context_window.toLocaleString('id-ID') : '—') },
        { label: 'Dipakai route', render: (m) => h('div', {}, usedBy(m.alias).map((a) => h('span', { class: 'tag', text: a }))) },
        { label: 'Status', render: (m) => badge(m.is_enabled ? 'active' : 'archived', m.is_enabled ? 'Aktif' : 'Nonaktif') },
        { label: 'Aksi', class: 'actions', render: (m) => action(m.is_enabled ? 'Nonaktifkan' : 'Aktifkan', () => toggleModel(m, usedBy(m.alias), refresh), m.is_enabled ? 'danger' : 'ghost', { class: `btn btn-${m.is_enabled ? 'danger' : 'ghost'} btn-sm` }) },
      ],
      models,
      { empty: 'Provider ini belum punya model. Tambahkan lewat Admin API (POST /admin/models) atau seed.' },
    );
    const autoBody = auto
      ? h('div', {},
          h('ol', { class: 'auto-order' }, auto.targets.map((t) => {
            const m = cat.models.find((x) => x.alias === t.model_alias);
            return h('li', {}, h('code', { text: t.model_alias }), ' ', h('span', { class: 'sub', text: m ? `${priceLabel(m.pricing)}${m.is_enabled ? '' : ' · NONAKTIF (dilewati)'}` : '' }));
          })),
          h('p', { class: 'muted', text: `Estimasi: ${priceLabel(auto.pricing)}. Status: ${auto.is_enabled ? 'aktif' : 'nonaktif'}.` }))
      : h('p', { class: 'muted', text: `Belum ada. Atur untuk membuat route ${autoAlias}: pilih model dan urutannya (paling atas dicoba dulu).` });
    return h(
      'div',
      { class: 'stack' },
      h('section', { class: 'card' }, h('div', { class: 'card-head' }, h('h2', { text: `Model ${p.display_name}` }), h('span', { class: 'sub', text: 'Model nonaktif tidak bisa dipakai siapa pun dan dilewati semua route.' })), modelTable),
      h(
        'section',
        { class: 'card' },
        h('div', { class: 'card-head' }, h('h2', {}, 'Auto ', h('code', { text: autoAlias })),
          h('span', { class: 'actions' },
            models.length ? action(auto ? 'Atur' : 'Buat', () => editProviderAuto(p, models, auto, refresh), 'primary', { class: 'btn btn-primary btn-sm' }) : null,
            auto ? action(auto.is_enabled ? 'Matikan' : 'Nyalakan', () => toggleRoute(auto, refresh), 'ghost', { class: 'btn btn-ghost btn-sm' }) : null)),
        autoBody,
        h('p', { class: 'muted', text: `Pakai "${autoAlias}" sebagai model di aplikasi/agent: Gateway mencoba model teratas, lalu turun ke berikutnya bila gagal/limit. Pola ${p.code}/* di project/key otomatis mengizinkannya.` }),
      ),
    );
  }

  async function toggleModel(m, routes, refresh) {
    if (m.is_enabled) {
      const where = routes.length ? ` Model ini kandidat di route: ${routes.join(', ')} — route akan melewatinya.` : '';
      const ok = await confirm({ title: `Nonaktifkan ${m.alias}?`, message: `Request langsung ke model ini ditolak dan semua route melewatinya.${where} Bisa diaktifkan lagi kapan saja.`, confirmLabel: 'Nonaktifkan', danger: true });
      if (!ok) return;
    }
    await api('PATCH', `/admin/models/${m.alias}`, { is_enabled: !m.is_enabled });
    toast(m.is_enabled ? `${m.alias} dinonaktifkan` : `${m.alias} diaktifkan`);
    refresh();
  }

  // targets dari urutan pilihan (pertama = prioritas 1)
  const orderedTargets = (aliases) => aliases.map((a, i) => ({ model_alias: a, priority: i + 1 }));
  const ORDER_HELP = 'Urutan pilihan = urutan dicoba (atas dulu). Untuk mengubah urutan: hapus chip lalu pilih lagi. Harga = estimasi.';

  async function editProviderAuto(p, models, auto, refresh) {
    const items = models.map((m) => ({ value: m.alias, label: m.alias + (m.is_enabled ? '' : ' (nonaktif)'), group: 'Model ' + p.display_name, sub: [priceLabel(m.pricing), capsText(m)].filter(Boolean).join(' · '), search: m.upstream_name }));
    const v = await form({
      title: `Auto · ${p.code}/auto`,
      intro: 'Pilih model provider ini untuk route auto. Saran: model termurah/gratis di urutan atas, model mahal di bawah (atau tidak dipilih sama sekali).',
      fields: [
        { name: 'targets', label: 'Model & urutan', type: 'picker', multiple: true, required: true, items, value: auto ? auto.targets.map((t) => t.model_alias) : [], help: ORDER_HELP },
        { name: 'description', label: 'Deskripsi', value: auto ? auto.description || '' : `auto ${p.display_name}` },
      ],
    });
    if (!v) return;
    const body = { description: v.description || null, targets: orderedTargets(v.targets) };
    if (auto) await api('PATCH', `/admin/routes/${auto.alias}`, body);
    else await api('POST', '/admin/routes', { alias: `${p.code}/auto`, ...body });
    toast(`Route ${p.code}/auto disimpan`);
    refresh();
  }

  async function toggleRoute(r, refresh) {
    if (r.is_enabled && !(await confirm({ title: `Matikan route ${r.alias}?`, message: 'Request ke route ini akan ditolak (404) sampai dinyalakan lagi. Aplikasi/agent yang memakainya ikut gagal.', confirmLabel: 'Matikan', danger: true }))) return;
    await api('PATCH', `/admin/routes/${r.alias}`, { is_enabled: !r.is_enabled });
    toast(r.is_enabled ? `Route ${r.alias} dimatikan` : `Route ${r.alias} dinyalakan`);
    refresh();
  }

  // ========================================================= Route
  async function routesPage({ refresh }) {
    const cat = await loadCatalog();
    const byAlias = Object.fromEntries(cat.models.map((m) => [m.alias, m]));
    const global = cat.routes.filter((r) => !isProviderAuto(r.alias));
    return h(
      'div',
      { class: 'stack' },
      pageHead('Route', 'Route auto (fast, smart, …)', 'Route = daftar kandidat model yang dicoba berurutan. Atur di sini agar auto tidak langsung memakai model mahal. Berlaku tanpa restart, tercatat di audit log.'),
      h(
        'section',
        { class: 'card' },
        table(
          [
            { label: 'Route', render: (r) => h('div', {}, h('code', { text: r.alias }), h('span', { class: 'sub', text: r.description || '' })) },
            {
              label: 'Kandidat (urutan dicoba)',
              render: (r) => h('ol', { class: 'auto-order' }, r.targets.map((t) => {
                const m = byAlias[t.model_alias];
                return h('li', {}, h('code', { text: t.model_alias }), ' ', h('span', { class: 'sub', text: m ? `${priceLabel(m.pricing)}${m.is_enabled ? '' : ' · NONAKTIF (dilewati)'}` : '' }));
              })),
            },
            { label: 'Estimasi', render: (r) => priceLabel(r.pricing) },
            { label: 'Status', render: (r) => badge(r.is_enabled ? 'active' : 'archived', r.is_enabled ? 'Aktif' : 'Nonaktif') },
            { label: 'Aksi', class: 'actions', render: (r) => h('span', {}, action('Ubah kandidat', () => editRoute(r, cat, refresh), 'ghost', { class: 'btn btn-ghost btn-sm' }), action(r.is_enabled ? 'Matikan' : 'Nyalakan', () => toggleRoute(r, refresh), r.is_enabled ? 'danger' : 'ghost', { class: `btn btn-${r.is_enabled ? 'danger' : 'ghost'} btn-sm` })) },
          ],
          global,
          { empty: 'Belum ada route.' },
        ),
      ),
      help('Tips memilih kandidat', [
        'Kandidat yang tidak punya kapabilitas yang diminta (tools, JSON, vision) otomatis dilewati — sisakan minimal satu yang mampu.',
        'Pindah ke kandidat berikutnya hanya terjadi bila kandidat sebelumnya gagal/limit sebelum token pertama, jadi kandidat pertama menentukan biaya sehari-hari.',
        'Route auto per provider (mis. openrouter/auto) diatur di halaman Provider → Model.',
      ]),
    );
  }

  async function editRoute(r, cat, refresh) {
    const items = catalogItems({ ...cat, routes: [] }, { patterns: false });
    const v = await form({
      title: `Kandidat route · ${r.alias}`,
      fields: [
        { name: 'targets', label: 'Model & urutan', type: 'picker', multiple: true, required: true, items, value: r.targets.map((t) => t.model_alias), help: ORDER_HELP },
        { name: 'description', label: 'Deskripsi', value: r.description || '' },
      ],
    });
    if (!v) return;
    await api('PATCH', `/admin/routes/${r.alias}`, { description: v.description || null, targets: orderedTargets(v.targets) });
    toast(`Route ${r.alias} disimpan`);
    refresh();
  }

  // ========================================================= 04 .env
  async function envPage() {
    const env = await api('GET', '/admin/env-status');
    const groups = [...new Set(env.vars.map((v) => v.group))];
    const problems = env.vars.filter((v) => v.required && v.state !== 'ok');
    return h(
      'div',
      { class: 'stack' },
      pageHead('04 · File .env', 'Status .env Gateway', 'Konsol hanya MEMBACA status (terisi / kosong / placeholder). Nilai rahasia tidak pernah ditampilkan dan file .env tidak diubah dari sini.'),
      problems.length ? h('div', { class: 'callout callout-err' }, h('strong', { text: 'Ada variabel wajib yang bermasalah' }), problems.map((p) => p.name).join(', ')) : h('div', { class: 'callout callout-ok' }, h('strong', { text: 'Semua variabel wajib terisi' }), 'Gateway hanya bisa start bila variabel wajib valid.'),
      groups.map((g) =>
        h(
          'section',
          { class: 'card' },
          h('div', { class: 'card-head' }, h('h2', { text: g })),
          table(
            [
              { label: 'Variabel', render: (v) => h('div', {}, h('code', { text: v.name }), v.required ? h('span', { class: 'sub', text: 'wajib' }) : h('span', { class: 'sub', text: 'opsional' })) },
              { label: 'Status', render: (v) => (v.secret ? badge(v.state) : h('code', { text: String(v.value) })) },
              { label: 'Keterangan', render: (v) => v.help },
            ],
            env.vars.filter((v) => v.group === g),
          ),
        ),
      ),
      h(
        'section',
        { class: 'card' },
        h('div', { class: 'card-head' }, h('h2', { text: 'Buat nilai rahasia baru' })),
        h('p', { class: 'muted', text: 'Dibuat di browser ini (crypto acak), tidak dikirim ke server. Tempel ke .env lalu restart.' }),
        h(
          'div',
          { class: 'actions' },
          btn('RUNTIME_TOKEN baru', async () => {
            await showSecret({ title: 'RUNTIME_TOKEN baru', envLine: 'RUNTIME_TOKEN', secret: genUrlSafe(48), note: 'Ganti baris RUNTIME_TOKEN di .env, lalu restart Gateway DAN runtime model lokal bersamaan.' });
          }),
          ' ',
          btn('GATEWAY_KEY_PEPPER baru', async () => {
            const ok = await confirm({ title: 'Ganti GATEWAY_KEY_PEPPER?', message: 'Mengganti pepper membuat SEMUA key lgw_ yang ada (termasuk admin key Anda dan key agent MCP) tidak valid. Hanya untuk instalasi baru atau insiden keamanan besar.', confirmLabel: 'Saya paham, buat nilai', danger: true, typeToConfirm: 'GANTI PEPPER' });
            if (ok) await showSecret({ title: 'GATEWAY_KEY_PEPPER baru', envLine: 'GATEWAY_KEY_PEPPER', secret: genUrlSafe(48), note: 'Setelah diganti: buat admin key baru (CLI), lalu provision ulang key agent dari Konsol MCP dengan opsi "buat ulang semua".' });
          }, 'danger'),
        ),
      ),
      help('Cara aman mengubah .env', [
        h('ol', {}, [
          h('li', { text: 'Salin dulu .env menjadi .env.bak (cadangan).' }),
          h('li', { text: 'Ubah satu baris saja; format NAMA=nilai tanpa spasi di sekitar "=" dan tanpa komentar di akhir baris.' }),
          h('li', { text: 'Restart Gateway. Kalau gagal start, pesan error menyebut nama variabel yang salah (nilainya tidak pernah dicetak).' }),
          h('li', { text: 'Jangan pernah commit .env ke git atau mengirimnya lewat chat.' }),
        ]),
      ]),
    );
  }

  // ========================================================= 05 Usage
  const today = () => new Date().toISOString().slice(0, 10);
  const usageFilter = { from: today().slice(0, 8) + '01', to: today(), project: '' };
  const num = (v) => Number(v || 0).toLocaleString('id-ID');
  const usd4 = (v) => `$${Number(v || 0).toFixed(4)}`;

  const sumUsage = (rows) =>
    rows.reduce(
      (t, r) => ({
        requests: t.requests + r.requests,
        errors: t.errors + r.errors,
        prompt_tokens: t.prompt_tokens + r.prompt_tokens,
        completion_tokens: t.completion_tokens + r.completion_tokens,
        cost_usd: t.cost_usd + Number(r.cost_usd),
      }),
      { requests: 0, errors: 0, prompt_tokens: 0, completion_tokens: 0, cost_usd: 0 },
    );

  function usageTable(title, key, rows, total) {
    const withTotal = rows.length ? rows.concat([{ ...total, [key]: 'TOTAL', isTotal: true }]) : rows;
    const cell = (r, v) => (r.isTotal ? h('strong', { text: v }) : v);
    return h(
      'section',
      { class: 'card' },
      h('div', { class: 'card-head' }, h('h2', { text: title })),
      table(
        [
          { label: title.replace('Per ', ''), render: (r) => (r.isTotal ? h('strong', { text: 'TOTAL' }) : h('code', { text: r[key] })) },
          { label: 'Request', class: 'num', render: (r) => cell(r, num(r.requests)) },
          { label: 'Error', class: 'num', render: (r) => cell(r, num(r.errors)) },
          { label: 'Token input', class: 'num', render: (r) => cell(r, num(r.prompt_tokens)) },
          { label: 'Token output', class: 'num', render: (r) => cell(r, num(r.completion_tokens)) },
          { label: 'Total token', class: 'num', render: (r) => cell(r, num(r.prompt_tokens + r.completion_tokens)) },
          { label: 'Estimasi biaya', class: 'num', render: (r) => cell(r, usd4(r.cost_usd)) },
        ],
        withTotal,
        { empty: 'Belum ada pemakaian di periode ini.' },
      ),
    );
  }

  const PROVIDER_LABEL = { openai: 'OpenAI', anthropic: 'Anthropic (Claude)' };
  const ADMIN_KEY_ENV = { openai: 'OPENAI_ADMIN_KEY', anthropic: 'ANTHROPIC_ADMIN_KEY' };

  /** Biaya aktual dari Cost/Usage API provider vs estimasi Gateway (per provider). */
  function actualSection(billing, byProvider, projectFiltered) {
    if (billing instanceof Error) {
      return h('section', { class: 'card' }, h('div', { class: 'card-head' }, h('h2', { text: 'Biaya aktual dari provider' })), h('div', { class: 'callout callout-err', text: `Gagal memuat: ${billing.message}` }));
    }
    const estimateOf = (code) => Number((byProvider.find((r) => r.provider === code) || {}).cost_usd || 0);
    const rows = billing.providers.map((p) => ({
      ...p,
      label: PROVIDER_LABEL[p.provider] || p.provider,
      estimate: estimateOf(p.provider),
      actual: p.ok ? Number(p.cost_usd) : null,
    }));
    const statusOf = (p) => (p.ok ? badge('active', 'Tersambung') : p.configured ? h('span', { class: 'sub', text: p.error }) : h('span', { class: 'sub' }, 'Isi ', h('code', { text: ADMIN_KEY_ENV[p.provider] }), ' di .env'));
    const diff = (p) => (p.actual === null ? '—' : `${p.actual - p.estimate >= 0 ? '+' : ''}${usd4(p.actual - p.estimate)}`);
    return h(
      'section',
      { class: 'card' },
      h('div', { class: 'card-head' }, h('h2', { text: 'Biaya aktual dari provider' })),
      projectFiltered ? h('div', { class: 'callout callout-warn', text: 'Filter project aktif: angka aktual provider tetap mencakup seluruh organisasi, jadi tidak sebanding dengan estimasi project ini.' }) : null,
      UsageCharts.costCompare(rows),
      table(
        [
          { label: 'Provider', render: (p) => h('strong', { text: p.label }) },
          { label: 'Status', render: statusOf },
          { label: 'Estimasi Gateway', class: 'num', render: (p) => usd4(p.estimate) },
          { label: 'Aktual provider', class: 'num', render: (p) => (p.actual === null ? '—' : usd4(p.actual)) },
          { label: 'Selisih', class: 'num', render: diff },
          { label: 'Token aktual (in/out/cache)', class: 'num', render: (p) => (p.tokens ? `${num(p.tokens.input)} / ${num(p.tokens.output)} / ${num(p.tokens.cached)}` : '—') },
          { label: 'Request aktual', class: 'num', render: (p) => (p.requests === null || p.requests === undefined ? '—' : num(p.requests)) },
        ],
        rows,
      ),
      h('p', { class: 'muted', text: 'Aktual = data tagihan resmi dari Cost API & Usage API provider (per organisasi, termasuk pemakaian di luar Gateway, per hari UTC, tertunda ±5 menit, di-cache 5 menit).' }),
    );
  }

  async function usagePage({ refresh }) {
    const f = usageFilter;
    const qs = (group) => `/admin/usage?from=${f.from}&to=${f.to}&group_by=${group}` + (f.project ? `&project_id=${f.project}` : '');
    const [projects, byProject, byProvider, byModel, byDay, billing] = await Promise.all([
      api('GET', '/admin/projects'),
      api('GET', qs('project')),
      api('GET', qs('provider')),
      api('GET', qs('model')),
      api('GET', qs('day')),
      api('GET', `/admin/provider-billing?from=${f.from}&to=${f.to}`).catch((e) => e),
    ]);
    const total = sumUsage(byProject.data);

    const fromInput = h('input', { type: 'date', class: 'input', value: f.from });
    const toInput = h('input', { type: 'date', class: 'input', value: f.to });
    const projectSelect = h(
      'select',
      { class: 'input' },
      h('option', { value: '', text: 'Semua project' }),
      projects.data.map((p) => h('option', { value: p.id, text: p.slug, selected: p.id === f.project })),
    );
    const apply = () => {
      if (!fromInput.value || !toInput.value) throw new Error('Isi tanggal dari & sampai.');
      if (fromInput.value > toInput.value) throw new Error('Tanggal "dari" harus sebelum "sampai".');
      Object.assign(usageFilter, { from: fromInput.value, to: toInput.value, project: projectSelect.value });
      refresh();
    };
    const field = (label, input) => h('label', { class: 'field' }, h('span', { class: 'field-label', text: label }), input);
    const stat = (label, value, sub) => h('div', { class: 'stat' }, h('span', { class: 'sub', text: label }), h('strong', { text: value }), sub ? h('span', { class: 'sub', text: sub }) : null);

    return h(
      'div',
      { class: 'stack' },
      pageHead('05 · Usage', 'Pemakaian token & biaya', 'Rekap request, token, dan biaya per project, per provider (OpenAI, Gemini, Claude, lokal), dan per model. Diperbarui tiap ±10 menit.'),
      h(
        'div',
        { class: 'callout callout-warn' },
        h('strong', { text: 'Biaya di bawah adalah ESTIMASI. ' }),
        'Dihitung Gateway dari token × harga per 1 juta token di katalog model (Admin API /admin/models). Tagihan resmi bisa berbeda (cache write, tarif bertingkat, pajak); lihat "Biaya aktual dari provider".',
      ),
      h(
        'section',
        { class: 'card' },
        h('div', { class: 'usage-filter' }, field('Dari', fromInput), field('Sampai', toInput), field('Project', projectSelect), action('Tampilkan', apply, 'primary')),
        h(
          'div',
          { class: 'stats' },
          stat('Total request', num(total.requests), `${num(total.errors)} error`),
          stat('Token input', num(total.prompt_tokens)),
          stat('Token output', num(total.completion_tokens)),
          stat('Total token', num(total.prompt_tokens + total.completion_tokens)),
          stat('Estimasi biaya', usd4(total.cost_usd), 'perkiraan Gateway'),
        ),
      ),
      h(
        'section',
        { class: 'card' },
        h('div', { class: 'card-head' }, h('h2', { text: 'Token per hari' })),
        UsageCharts.tokensByDay(byDay.data, f.from, f.to),
      ),
      actualSection(billing, byProvider.data, !!f.project),
      usageTable('Per project', 'project', byProject.data, total),
      usageTable('Per provider', 'provider', byProvider.data, sumUsage(byProvider.data)),
      usageTable('Per model', 'model', byModel.data, sumUsage(byModel.data)),
      usageTable('Per hari', 'day', byDay.data, sumUsage(byDay.data)),
      help('Catatan', [
        'Usage dicatat per project, bukan per API key. Kalau perlu rekap per aplikasi, beri tiap aplikasi project sendiri.',
        'Provider "local" = model lokal (biaya $0). Biaya remote = estimasi dari harga model yang tercatat di Gateway; request sebelum harga diisi tetap $0.',
        'Biaya aktual butuh admin key organisasi di .env Gateway: OPENAI_ADMIN_KEY (sk-admin-…) dan ANTHROPIC_ADMIN_KEY (sk-ant-admin01-…), lalu restart Gateway. Key ini hanya dipakai membaca laporan.',
      ]),
    );
  }

  // ======================================================== login & boot
  const HOW_TO = [
    h('p', { text: 'Admin key dibuat sekali lewat terminal (Anaconda Prompt) di folder llm-genai:' }),
    h('p', {}, h('code', { text: 'python scripts\\manage.py create-admin-key --name konsol' })),
    h('p', { text: 'Key tampil sekali — simpan di password manager. Key admin tidak bisa dibuat dari konsol (sengaja).' }),
  ];

  function showLogin(reason) {
    root.replaceChildren(
      Kit.loginScreen({
        title: 'Konsol LLM Gateway',
        subtitle: 'Kredensial · project · kuota',
        intro: reason || 'Masukkan admin key Gateway untuk mengelola project, API key, kuota, dan memeriksa status .env.',
        keyLabel: 'Admin key Gateway',
        keyPattern: 'lgw_xxxxxxxx_…',
        howTo: HOW_TO,
        onSubmit: async (key) => {
          try {
            await api('GET', '/admin/projects', undefined, { key });
          } catch (e) {
            if (e.status === 403) throw new Error('Key valid, tetapi bukan role admin. Gunakan admin key.');
            if (e.status === 401) throw new Error('Key tidak dikenali / sudah dicabut.');
            throw e;
          }
          Kit.unlock(key);
          boot();
        },
      }),
    );
  }

  function boot() {
    const { root: app, go } = Kit.shell({
      title: 'Konsol LLM Gateway',
      subtitle: location.host,
      onLogout: () => Kit.lock('Sesi dikunci. Admin key sudah dihapus dari memori.'),
      pages: [
        { id: 'start', label: 'Mulai di sini', hint: 'alur key & checklist', render: startPage },
        { id: 'projects', label: 'Project & Key', hint: 'buat, rotasi, cabut, kuota', render: projectsPage },
        { id: 'providers', label: 'Provider', hint: 'model, harga, auto per provider', render: providersPage },
        { id: 'routes', label: 'Route', hint: 'kandidat fast, smart, …', render: routesPage },
        { id: 'env', label: 'File .env', hint: 'status variabel & secret baru', render: envPage },
        { id: 'usage', label: 'Usage', hint: 'token & biaya per project/provider', render: usagePage },
      ],
    });
    root.replaceChildren(app);
    go('start');
  }

  Kit.setOnLock(showLogin);
  showLogin();
})();
