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

/* ── HTML escaper (prevents XSS when rendering user/API data) ── */
const esc = s => String(s)
  .replace(/&/g,  '&amp;')
  .replace(/</g,  '&lt;')
  .replace(/>/g,  '&gt;')
  .replace(/"/g,  '&quot;')
  .replace(/'/g,  '&#39;');

/* ── API fetch helper ── */
async function api(path, options = {}) {
  // Attach JWT token from localStorage to every API request
  const token = localStorage.getItem('sp_token');
  const headers = { 'Content-Type': 'application/json', ...options.headers };
  if (token) headers['Authorization'] = `Bearer ${token}`;
 
  const response = await fetch(path, { ...options, headers });
 
  // If 401 Unauthorised — token expired, redirect to login
  if (response.status === 401) {
    localStorage.removeItem('sp_token');
    localStorage.removeItem('sp_user');
    window.location.href = '/login';
    return;
  }
 
  if (!response.ok) {
    throw new Error(`API error ${response.status} on ${path}`);
  }
  return response.json();
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
   Called as: showTip(event, htmlString)
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
  document.querySelector('.sp-shell').classList.toggle('sidebar-collapsed');
}

/* ════════════════════════════════════════════════════
   GLOBAL SUMMARY STATS
   Loads /api/skills/summary and populates:
     - Topbar stat pills  (#statOccupations, #statSkills, #statJobs, #statMappings)
     - Sidebar signature  (#navSig)
   Field names matched exactly to the API response:
     total_occupations, total_skills, total_job_posts, total_skill_mappings
════════════════════════════════════════════════════ */
async function loadGlobalSummary() {
  try {
    const d = await api('/api/skills/summary');

    // Topbar pills (base.html)
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
   the current URL path. Complements the server-side
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
   Activates [data-bs-toggle="tooltip"] elements
   (used on collapsed nav icons at narrow widths).
════════════════════════════════════════════════════ */
function initBootstrapTooltips() {
  if (typeof bootstrap === 'undefined') return;
  document.querySelectorAll('[data-bs-toggle="tooltip"]').forEach(el => {
    new bootstrap.Tooltip(el, { placement: 'right', trigger: 'hover' });
  });
}

/* ── Boot ── */
document.addEventListener('DOMContentLoaded', () => {
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
 
  if (nameEl) nameEl.textContent = user.display_name || user.email;
  if (avatarEl) {
    // Show initials in avatar
    const initials = (user.display_name || user.email)
      .split(' ').map(w => w[0]).join('').toUpperCase().slice(0, 2);
    avatarEl.textContent = initials || 'SP';
  }
}