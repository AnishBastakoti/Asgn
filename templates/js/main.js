'use strict';

/* ── DOM helper ── */
const $ = id => document.getElementById(id);

/* ── Number formatter ── */
const fmt = n => {
  if (n == null || n === undefined) return '—';
  if (n >= 1_000_000) return (n / 1_000_000).toFixed(1) + 'M';
  if (n >= 1_000)     return (n / 1_000).toFixed(1) + 'K';
  return String(n);
};
const fmtDate = (raw, template = 'D MMM YYYY') => {
  if (!raw) return '—';
  if (typeof dayjs === 'undefined') return String(raw).split('T')[0];
  const d = dayjs(raw);
  return d.isValid() ? d.format(template) : String(raw).split('T')[0];
};

const BAR_COLOURS = [
  'var(--orange)',
  'var(--emerald)',
  'var(--violet)',
  'var(--sky)',
  '#F59E0B',
  '#EF4444',
  '#10B981',
  '#6366F1',
];
const barColour = i => BAR_COLOURS[i % BAR_COLOURS.length];

/* ── HTML escaper (prevents XSS when rendering user/API data) ── */
const esc = s => String(s)
  .replace(/&/g,  '&amp;')
  .replace(/</g,  '&lt;')
  .replace(/>/g,  '&gt;')
  .replace(/"/g,  '&quot;')
  .replace(/'/g,  '&#39;');

/* ── API fetch helper ── */
async function api(path, options = {}) {
  // Show NProgress loading bar at top of page
  if (typeof NProgress !== 'undefined') NProgress.start();

  try {
    const token = localStorage.getItem('sp_token');
    const headers = { 'Content-Type': 'application/json', ...options.headers };
    if (token) headers['Authorization'] = `Bearer ${token}`;

    const response = await fetch(path, { ...options, headers });

    if (response.status === 401) {
      localStorage.removeItem('sp_token');
      localStorage.removeItem('sp_user');
      window.location.href = '/login';
      return;
    }

    if (!response.ok) throw new Error(`API error ${response.status} on ${path}`);
    return response.json();

  } finally {
    // Always stop — even if request throws
    if (typeof NProgress !== 'undefined') NProgress.done();
  }
}

// ── Auth helpers ─────────────────────────────────────────────
function getCurrentUser() {
  try {
    return JSON.parse(localStorage.getItem('sp_user') || 'null');
  } catch { return null; }
}

function isLoggedIn() {
  return !!localStorage.getItem('sp_token');
}

async function logout() {
  // Clear localStorage
  localStorage.removeItem('sp_token');
  localStorage.removeItem('sp_user');
  // Clear the httpOnly cookie (server-side)
  try {
    await fetch('/api/auth/logout-session', { method: 'POST' });
  } catch (e) { /* ignore */ }
  window.location.href = '/login';
}

/* ════════════════════════════════════════════════════
   TOOLTIP
   Global tooltip used by all chart pages.
════════════════════════════════════════════════════ */
const _tip = $('spTooltip');

function showTip(e, html) {
  if (!_tip) return;
  _tip.innerHTML = html;
  _tip.classList.add('visible');
  moveTip(e);
}

function moveTip(e) {
  if (!_tip) return;
  const x = Math.min(e.clientX + 14, window.innerWidth  - 240);
  const y = Math.min(e.clientY - 10, window.innerHeight - 140);
  _tip.style.left = x + 'px';
  _tip.style.top  = y + 'px';
}

function hideTip() {
  if (_tip) _tip.classList.remove('visible');
}

// Expose globally so page-level scripts can call them
window.showTip = showTip;
window.moveTip = moveTip;
window.hideTip = hideTip;

function toggleSidebar() {
  const shell    = document.querySelector('.sp-shell');
  const icon     = document.getElementById('toggleIcon');
  const label    = document.querySelector('.sp-collapse-label');
  shell.classList.toggle('sidebar-collapsed');
  const collapsed = shell.classList.contains('sidebar-collapsed');
  if (icon)  icon.className  = collapsed ? 'bi bi-chevron-double-right' : 'bi bi-chevron-double-left';
  if (label) label.textContent = collapsed ? '' : 'Collapse';
}

/* ════════════════════════════════════════════════════
   GLOBAL SUMMARY STATS
   Loads /api/skills/summary and populates:
════════════════════════════════════════════════════ */
async function loadGlobalSummary() {
  try {
    const d = await api('/api/skills/summary');
    const statMap = {
      statOccupations: d.total_occupations,
      statSkills:      d.total_skills,
      statJobs:        d.total_job_posts,       //  total_job_posts not total_jobs
      statMappings:    d.total_skill_mappings,  //  total_skill_mappings not total_mappings
    };

    Object.entries(statMap).forEach(([id, val]) => {
      const el = $(id);
      if (el) el.textContent = fmt(val);
    });

    // Sidebar signature fingerprint
    const sig = $('navSig');
    if (sig) sig.textContent = d.signature || d._meta?.fp || '—';

  } catch (err) {
    console.warn('[SkillPulse] Summary stats failed:', err.message);
  }
}

/* ════════════════════════════════════════════════════
   ACTIVE NAV HIGHLIGHTING
   Marks the correct sidebar link as active based on
   the current URL path.
════════════════════════════════════════════════════ */
function highlightActiveNav() {
  const path = window.location.pathname;
  document.querySelectorAll('.sp-nav-link').forEach(link => {
    const href = link.getAttribute('href');
    if (!href) return;
    const isActive = href === '/'
      ? path === '/'
      : path.startsWith(href);
    link.classList.toggle('active', isActive);
  });
}

/* ════════════════════════════════════════════════════
   BOOTSTRAP TOOLTIP INIT
   Activates Bootstrap tooltips for any element with data-bs-toggle="tooltip"
════════════════════════════════════════════════════ */
function initBootstrapTooltips() {
  if (typeof bootstrap === 'undefined') return;
  document.querySelectorAll('[data-bs-toggle="tooltip"]').forEach(el => {
    new bootstrap.Tooltip(el, { placement: 'right', trigger: 'hover' });
  });
}

/* ── Boot ── */
document.addEventListener('DOMContentLoaded', () => {
  // Configure NProgress — thin orange bar at top of page
  if (typeof NProgress !== 'undefined') {
    NProgress.configure({
      showSpinner: false,        // hide the spinner
      trickleSpeed: 200,
      minimum: 0.1,
    });
  }
  loadGlobalSummary();
  highlightActiveNav();
  initBootstrapTooltips();
  populateUserInfo();
});

// ── Populate user name in sidebar ────────────────────────────
function populateUserInfo() {
  const user = getCurrentUser();
  if (!user) return;

  const nameEl   = document.getElementById('navUserName');
  const avatarEl = document.getElementById('navAvatar');

  // Strip email domain wherever it appears — handles display_name = full email
  const rawName     = user.display_name || user.email || '';
  const cleanName   = rawName.includes('@') ? rawName.split('@')[0] : rawName;
  const displayName = cleanName.charAt(0).toUpperCase() + cleanName.slice(1);

  if (nameEl) nameEl.textContent = displayName;

  if (avatarEl) {
    // Split on space, dot, underscore or dash for initials
    const parts    = displayName.split(/[ ._-]+/).filter(Boolean);
    const initials = parts.length > 1
      ? parts.map(w => w[0]).join('').toUpperCase().slice(0, 2)
      : displayName.slice(0, 2).toUpperCase();
    avatarEl.textContent = initials || 'SP';
  }
}

// PWA Service worker

if ('serviceWorker' in navigator) {
  window.addEventListener('load', () => {
    navigator.serviceWorker.register('/service-worker.js')
      .then(reg => console.log('SW Registered!', reg))
      .catch(err => console.log('SW Registration Failed', err));
  });
}