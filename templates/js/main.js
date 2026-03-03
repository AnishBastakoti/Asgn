/* ═══════════════════════════════════════════
   SkillPulse — main.js  (global utilities)
═══════════════════════════════════════════ */
const $   = id => document.getElementById(id);
const fmt = n => n == null ? '—' : n >= 1e6 ? (n/1e6).toFixed(1)+'M' : n >= 1e3 ? (n/1e3).toFixed(1)+'K' : String(n);
const esc = s => String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');

async function api(path) {
  const r = await fetch(path);
  if (!r.ok) throw new Error(`HTTP ${r.status}`);
  return r.json();
}

/* Tooltip */
const tip = $('spTooltip');
window.showTip = (e, html) => { tip.innerHTML = html; tip.classList.add('visible'); moveTip(e); };
window.moveTip = e => {
  tip.style.left = Math.min(e.clientX + 14, window.innerWidth  - 240) + 'px';
  tip.style.top  = Math.min(e.clientY - 10, window.innerHeight - 130) + 'px';
};
window.hideTip = () => tip.classList.remove('visible');

/* Global summary load */
async function loadGlobalSummary() {
  try {
    const d = await api('/api/skills/summary');
    ['Occupations','Skills','Jobs','Mappings'].forEach(k => {
      const el = $('stat'+k);
      if (el) el.textContent = fmt(d['total_'+k.toLowerCase()]);
    });
    if ($('navSig')) $('navSig').textContent = d.signature || '—';
  } catch(e) { console.warn('Summary:', e); }
}

/* Bootstrap tooltips on nav */
function initTooltips() {
  document.querySelectorAll('[data-bs-toggle="tooltip"]').forEach(el => {
    new bootstrap.Tooltip(el, { placement: 'right' });
  });
}

document.addEventListener('DOMContentLoaded', () => {
  loadGlobalSummary();
  initTooltips();
});