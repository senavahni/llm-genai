// Grafik halaman Usage (SVG murni, tanpa library). CSP konsol melarang atribut style inline,
// jadi warna/ukuran memakai atribut SVG dan posisi tooltip memakai CSSOM (el.style.*).
'use strict';

const UsageCharts = (() => {
  const SVG_NS = 'http://www.w3.org/2000/svg';
  // Palet kategorikal tervalidasi (dataviz validate_palette: CVD ΔE 24.7, kontras ≥ 3:1 di #fff)
  const COLOR = { a: '#2a78d6', b: '#eb6834' };
  const GRID = '#e1e0d9';
  const AXIS = '#c3c2b7';
  const MUTED = '#898781';
  const DAY_MS = 86_400_000;

  function svg(tag, attrs = {}, ...children) {
    const el = document.createElementNS(SVG_NS, tag);
    for (const [k, v] of Object.entries(attrs)) if (v !== null && v !== undefined) el.setAttribute(k, String(v));
    for (const c of children.flat()) if (c) el.append(c instanceof Node ? c : document.createTextNode(String(c)));
    return el;
  }

  const fmtNum = (v) => Number(v || 0).toLocaleString('id-ID');
  const fmtUsd = (v) => `$${Number(v || 0).toFixed(4)}`;
  const shortNum = (v) =>
    v >= 1e6 ? `${(v / 1e6).toLocaleString('id-ID', { maximumFractionDigits: 1 })} jt` : v >= 1e3 ? `${(v / 1e3).toLocaleString('id-ID', { maximumFractionDigits: 1 })} rb` : String(v);

  function niceMax(v) {
    if (v <= 0) return 1;
    const p = 10 ** Math.floor(Math.log10(v));
    return [1, 2, 2.5, 5, 10].map((m) => m * p).find((m) => m >= v);
  }

  function daysBetween(from, to) {
    const out = [];
    for (let t = Date.parse(`${from}T00:00:00Z`); t <= Date.parse(`${to}T00:00:00Z`); t += DAY_MS) out.push(new Date(t).toISOString().slice(0, 10));
    return out;
  }

  function legend(items) {
    const { h } = Kit;
    return h('div', { class: 'chart-legend' }, items.map(([color, label]) => {
      const sw = h('span', { class: 'chart-swatch', 'aria-hidden': 'true' });
      sw.style.background = color;
      return h('span', { class: 'chart-legend-item' }, sw, label);
    }));
  }

  function withTooltip(wrap) {
    const { h } = Kit;
    const tip = h('div', { class: 'chart-tip', role: 'status' });
    tip.hidden = true;
    wrap.append(tip);
    return {
      show(evt, lines) {
        tip.replaceChildren(...lines.map((l, i) => h(i === 0 ? 'strong' : 'div', { text: l })));
        tip.hidden = false;
        const box = wrap.getBoundingClientRect();
        const x = Math.min(evt.clientX - box.left + 12, box.width - tip.offsetWidth - 4);
        tip.style.left = `${Math.max(4, x)}px`;
        tip.style.top = `${Math.max(4, evt.clientY - box.top - tip.offsetHeight - 8)}px`;
      },
      hide() {
        tip.hidden = true;
      },
    };
  }

  /** Kolom bertumpuk token input + output per hari (hari tanpa data = 0). */
  function tokensByDay(rows, from, to) {
    const { h } = Kit;
    const byDay = new Map(rows.map((r) => [r.day, r]));
    const days = daysBetween(from, to).map((d) => {
      const r = byDay.get(d) || {};
      return { day: d, input: r.prompt_tokens || 0, output: r.completion_tokens || 0, cost: Number(r.cost_usd || 0), requests: r.requests || 0 };
    });
    const W = 720, H = 220, L = 52, R = 8, T = 10, B = 26;
    const plotW = W - L - R, plotH = H - T - B;
    const max = niceMax(Math.max(0, ...days.map((d) => d.input + d.output)));
    const y = (v) => T + plotH - (v / max) * plotH;
    const slot = plotW / days.length;
    const barW = Math.max(2, Math.min(28, slot - 2));
    const GAP = days.length > 60 ? 0 : 2;

    const grid = [0, max / 2, max].map((v) =>
      svg('g', {}, svg('line', { x1: L, x2: W - R, y1: y(v), y2: y(v), stroke: v === 0 ? AXIS : GRID, 'stroke-width': 1 }), svg('text', { x: L - 6, y: y(v) + 4, 'text-anchor': 'end', class: 'chart-axis' }, shortNum(v))),
    );
    const labelIdx = [...new Set([0, Math.floor((days.length - 1) / 2), days.length - 1])];
    const xLabels = labelIdx.map((i) => svg('text', { x: L + slot * i + slot / 2, y: H - 8, 'text-anchor': 'middle', class: 'chart-axis' }, days[i].day.slice(8, 10) + '/' + days[i].day.slice(5, 7)));

    const wrap = h('div', { class: 'chart-wrap' });
    const tip = withTooltip(wrap);
    const bars = days.map((d, i) => {
      const x = L + slot * i + (slot - barW) / 2;
      const hIn = (d.input / max) * plotH;
      const hOut = (d.output / max) * plotH;
      const yIn = T + plotH - hIn;
      const yOut = yIn - hOut - (hOut && hIn ? GAP : 0);
      const hit = svg('rect', { x: L + slot * i, y: T, width: slot, height: plotH, fill: 'transparent', class: 'chart-hit' });
      const lines = [d.day, `Input: ${fmtNum(d.input)} token`, `Output: ${fmtNum(d.output)} token`, `Request: ${fmtNum(d.requests)}`, `Estimasi biaya: ${fmtUsd(d.cost)}`];
      hit.addEventListener('mousemove', (e) => tip.show(e, lines));
      hit.addEventListener('mouseleave', () => tip.hide());
      return svg(
        'g',
        {},
        hIn > 0 ? svg('rect', { x, y: yIn, width: barW, height: hIn, rx: 2, fill: COLOR.a }) : null,
        hOut > 0 ? svg('rect', { x, y: yOut, width: barW, height: hOut, rx: 2, fill: COLOR.b }) : null,
        hit,
      );
    });
    const total = days.reduce((s, d) => s + d.input + d.output, 0);
    const chart = svg('svg', { viewBox: `0 0 ${W} ${H}`, class: 'chart-svg', role: 'img', 'aria-label': `Token per hari ${from} sampai ${to}, total ${fmtNum(total)} token. Rincian ada di tabel Per hari.` }, grid, bars, xLabels);
    wrap.prepend(chart);
    return h('div', {}, legend([[COLOR.a, 'Token input'], [COLOR.b, 'Token output']]), wrap);
  }

  /** Batang horizontal per provider: estimasi Gateway vs aktual dari Cost API provider. */
  function costCompare(items) {
    const { h } = Kit;
    const W = 720, rowH = 54, L = 110, R = 96, barH = 16;
    const H = items.length * rowH + 8;
    const max = niceMax(Math.max(0, ...items.flatMap((it) => [it.estimate, it.actual ?? 0])));
    const x = (v) => L + (v / max) * (W - L - R);
    const wrap = h('div', { class: 'chart-wrap' });
    const tip = withTooltip(wrap);
    const rows = items.map((it, i) => {
      const top = 8 + i * rowH;
      const bar = (v, yy, color, label) => {
        if (v === null) return svg('text', { x: L, y: yy + barH - 4, class: 'chart-axis' }, `${label}: tidak tersedia`);
        const w = Math.max(v > 0 ? 2 : 0, x(v) - L);
        const g = svg('g', {}, svg('rect', { x: L, y: yy, width: w, height: barH, rx: 2, fill: color }), svg('text', { x: L + w + 6, y: yy + barH - 4, class: 'chart-value' }, fmtUsd(v)));
        const hit = svg('rect', { x: 0, y: yy - 2, width: W, height: barH + 4, fill: 'transparent', class: 'chart-hit' });
        hit.addEventListener('mousemove', (e) => tip.show(e, [it.label, `${label}: ${fmtUsd(v)}`]));
        hit.addEventListener('mouseleave', () => tip.hide());
        g.append(hit);
        return g;
      };
      return svg(
        'g',
        {},
        svg('text', { x: 0, y: top + barH + 6, class: 'chart-label' }, it.label),
        bar(it.estimate, top, COLOR.a, 'Estimasi Gateway'),
        bar(it.actual, top + barH + 4, COLOR.b, 'Aktual provider'),
      );
    });
    const chart = svg('svg', { viewBox: `0 0 ${W} ${H}`, class: 'chart-svg', role: 'img', 'aria-label': 'Perbandingan biaya estimasi Gateway dan aktual provider. Angka lengkap ada di tabel di bawah.' }, svg('line', { x1: L, x2: L, y1: 0, y2: H, stroke: AXIS }), rows);
    wrap.prepend(chart);
    return h('div', {}, legend([[COLOR.a, 'Estimasi Gateway'], [COLOR.b, 'Aktual provider']]), wrap);
  }

  return { tokensByDay, costCompare };
})();
