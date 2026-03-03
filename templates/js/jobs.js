'use strict';
// ── Colour palette (matches CSS token --indigo, --emerald, etc.) ──────────────
const JT_COLORS = [
  '#6366F1', // indigo
  '#10B981', // emerald
  '#F43F5E', // coral
  '#0EA5E9', // sky
  '#8B5CF6', // violet
  '#F59E0B', // amber
  '#EC4899', // pink
  '#14B8A6', // teal
];

// ── Chart instances — module-scoped so we can destroy before redraw ────────────
let _citiesChart = null;
let _trendsChart = null;

// ── Page state ────────────────────────────────────────────────────────────────
const jt = {
  occupations: [],   // full list from API
  filtered:    [],   // list after search filter applied
  selected:    null, // { id, title, level } of currently selected occupation
  activeTab:   'cities',
  // Tracks which tabs have been loaded for the current occupation.
  // Resets to all-false when a new occupation is selected.
  loaded: {
    cities:    false,
    trends:    false,
    overlap:   false,
    companies: false,
  },
};

// ── Boot ──────────────────────────────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', () => {
  loadHotSkills();
  loadOccupations();
  initTabs();

  document.getElementById('jtOccSearch')
    .addEventListener('input', e => filterOccupations(e.target.value));
});

/**
 * Called by the quick-search chips in the welcome state.
 * Fills the search box and filters the occupation list.
 */
window.jtQuickSearch = function(query) {
  const input = document.getElementById('jtOccSearch');
  if (input) input.value = query;
  filterOccupations(query);
};

// ═════════════════════════════════════════════════════════════════════════════
// 1. GLOBAL HOT SKILLS BANNER
//    Source: /api/analytics/hot-skills?days=30
//    Shows top 12 skills across ALL occupations in the last 30 days.
//    This is the "global overview" before the user drills into an occupation.
// ═════════════════════════════════════════════════════════════════════════════
async function loadHotSkills() {
  const wrap = document.getElementById('hotSkillsList');
  try {
    const data = await api('/api/analytics/hot-skills?days=30');

    if (!data || !data.length) {
      wrap.innerHTML = `
        <div class="jt-empty">
          <i class="bi bi-hourglass-split me-2"></i>
          No hot skill data yet — the pipeline is still processing job posts.
        </div>`;
      return;
    }

    const max = data[0].total_mentions || 1;

    const rows = data.slice(0, 12).map((skill, i) => {
      const barPct = Math.round((skill.total_mentions / max) * 100);
      return `
        <div class="jt-hot-row">
          <span class="jt-hot-rank">${i + 1}</span>
          <span class="jt-hot-name">${esc(skill.skill_name)}</span>
          <div class="jt-hot-bar-wrap">
            <div class="jt-hot-bar" style="width:${barPct}%"></div>
          </div>
          <span class="jt-hot-count">${fmt(skill.total_mentions)}</span>
        </div>`;
    }).join('');

    wrap.innerHTML = `<div class="jt-hot-list">${rows}</div>`;

  } catch (err) {
    wrap.innerHTML = `<div class="jt-empty">Could not load hot skills data.</div>`;
    console.warn('[SkillPulse|JT] loadHotSkills failed:', err.message);
  }
}

// ═════════════════════════════════════════════════════════════════════════════
// 2. OCCUPATION LIST
//    Source: /api/occupations/list?limit=1000
//    Renders full scrollable list with search filtering.
//    Occupations with no skill data (has_data=false) are dimmed and unclickable.
// ═════════════════════════════════════════════════════════════════════════════
async function loadOccupations() {
  const wrap = document.getElementById('jtOccList');
  try {
    jt.occupations = await api('/api/occupations/list?limit=1000');
    jt.filtered    = jt.occupations;
    renderOccList(jt.filtered);
  } catch (err) {
    wrap.innerHTML = `<div class="jt-empty">Could not load occupations.</div>`;
    console.warn('[SkillPulse|JT] loadOccupations failed:', err.message);
  }
}

function filterOccupations(query) {
  const term = query.trim().toLowerCase();
  jt.filtered = term
    ? jt.occupations.filter(o => o.title.toLowerCase().includes(term))
    : jt.occupations;
  renderOccList(jt.filtered);
}

function renderOccList(list) {
  const wrap = document.getElementById('jtOccList');

  if (!list.length) {
    wrap.innerHTML = `<div class="jt-empty">No occupations match your search.</div>`;
    return;
  }

  wrap.innerHTML = list.map(o => {
    const isActive  = jt.selected?.id === o.id;
    const hasData   = o.has_data;
    const levelBadge = hasData
      ? `<span class="jt-occ-badge">Lv${o.skill_level || '?'}</span>`
      : '';
    const clickAttr = hasData ? `onclick="selectOccupation(this)"` : '';

    return `
      <div class="jt-occ-item ${hasData ? '' : 'no-data'} ${isActive ? 'active' : ''}"
           ${clickAttr}
           data-id="${o.id}"
           data-title="${esc(o.title)}"
           data-level="${o.skill_level || ''}">
        <span class="occ-title">${esc(o.title)}</span>
        ${levelBadge}
      </div>`;
  }).join('');
}

// Called when user clicks an occupation row
window.selectOccupation = function(el) {
  const id    = parseInt(el.dataset.id, 10);
  const title = el.dataset.title;
  const level = el.dataset.level;

  // Highlight selected row
  document.querySelectorAll('.jt-occ-item').forEach(i => i.classList.remove('active'));
  el.classList.add('active');

  // Update state — reset loaded flags for new occupation
  jt.selected = { id, title, level };
  jt.loaded   = { cities: false, trends: false, overlap: false, companies: false };

  // Update header
  document.getElementById('jtWelcome').style.display      = 'none';
  document.getElementById('jtChartContent').style.display = 'flex';
  document.getElementById('jtOccName').textContent        = title;
  document.getElementById('jtOccLevel').textContent       = level ? `Level ${level}` : 'Level —';

  // Always land on cities tab when switching occupation
  switchTab('cities');
  loadTabData('cities');
};

// ═════════════════════════════════════════════════════════════════════════════
// 3. TAB MANAGEMENT
//    Lazy-loads data: each tab fetches once per selected occupation.
//    If user switches occupation, loaded flags reset and data re-fetches.
// ═════════════════════════════════════════════════════════════════════════════
function initTabs() {
  document.querySelectorAll('.jt-tab').forEach(tab => {
    tab.addEventListener('click', () => {
      const name = tab.dataset.tab;
      switchTab(name);
      if (jt.selected) loadTabData(name);
    });
  });
}

function switchTab(name) {
  jt.activeTab = name;
  document.querySelectorAll('.jt-tab').forEach(t =>
    t.classList.toggle('active', t.dataset.tab === name));
  document.querySelectorAll('.jt-pane').forEach(p =>
    p.classList.toggle('active', p.id === `pane-${name}`));
}

async function loadTabData(tab) {
  if (!jt.selected)   return;
  if (jt.loaded[tab]) return; // already loaded for this occupation — skip

  // Mark loaded BEFORE await to prevent double-fetch if user clicks fast
  jt.loaded[tab] = true;

  const id = jt.selected.id;
  if (tab === 'cities')    await renderCities(id);
  if (tab === 'trends')    await renderTrends(id);
  if (tab === 'overlap')   await renderOverlap(id);
  if (tab === 'companies') await renderCompanies(id);
}

// ═════════════════════════════════════════════════════════════════════════════
// 4. CITY DEMAND — horizontal bar chart
//    Source: /api/jobs/cities/?occupation_id=X
//    Horizontal bars are better than vertical for city name labels.
// ═════════════════════════════════════════════════════════════════════════════
async function renderCities(occId) {
  const pane = document.getElementById('pane-cities');
  const chartWrap = pane.querySelector('.jt-chart-wrap');

  try {
    const data = await api(`/api/jobs/cities/?occupation_id=${occId}`);

    // Always destroy previous instance before new Chart() to prevent canvas reuse error
    if (_citiesChart) { _citiesChart.destroy(); _citiesChart = null; }

    if (!data || !data.length) {
      chartWrap.innerHTML = `
        <div class="jt-empty">
          <i class="bi bi-geo-alt me-2"></i>
          No city data yet for this occupation. More data will appear as the pipeline runs.
        </div>`;
      return;
    }

    const ctx = document.getElementById('chartCities').getContext('2d');
    _citiesChart = new Chart(ctx, {
      type: 'bar',
      data: {
        labels:   data.map(d => d.city),
        datasets: [{
          label:           'Job Postings',
          data:            data.map(d => d.job_count),
          backgroundColor: data.map((_, i) => JT_COLORS[i % JT_COLORS.length] + 'BB'),
          borderColor:     data.map((_, i) => JT_COLORS[i % JT_COLORS.length]),
          borderWidth:     1,
          borderRadius:    5,
        }],
      },
      options: {
        indexAxis: 'y', // horizontal — city names read better on y-axis
        responsive: true,
        maintainAspectRatio: false,
        plugins: {
          legend: { display: false },
          tooltip: {
            callbacks: {
              label: ctx => ` ${ctx.parsed.x} postings`,
            },
          },
        },
        scales: {
          x: {
            grid:       { color: '#E8ECF8' },
            ticks:      { font: { size: 11 } },
            beginAtZero: true,
          },
          y: {
            grid:  { display: false },
            ticks: { font: { size: 11 } },
          },
        },
      },
    });

  } catch (err) {
    chartWrap.innerHTML = `<div class="jt-empty">Could not load city data.</div>`;
    console.warn('[SkillPulse|JT] renderCities failed:', err.message);
    jt.loaded.cities = false; // allow retry
  }
}

// ═════════════════════════════════════════════════════════════════════════════
// 5. SKILL TRENDS — multi-line time series
//    Source: /api/jobs/trends/?occupation_id=X
//    Each dataset is one skill. Tooltip shows trend direction (growing/declining/stable)
//    from the velocity score computed by numpy linear regression in the backend.
// ═════════════════════════════════════════════════════════════════════════════
async function renderTrends(occId) {
  const pane      = document.getElementById('pane-trends');
  const chartWrap = pane.querySelector('.jt-chart-wrap');

  try {
    const data = await api(`/api/jobs/trends/?occupation_id=${occId}`);

    if (_trendsChart) { _trendsChart.destroy(); _trendsChart = null; }

    if (!data || !data.length) {
      chartWrap.innerHTML = `
        <div class="jt-empty">
          <i class="bi bi-graph-up me-2"></i>
          No trend data yet. Snapshot history will build up as the pipeline runs weekly.
        </div>`;
      return;
    }

    const ctx = document.getElementById('chartTrends').getContext('2d');
    _trendsChart = new Chart(ctx, {
      type: 'line',
      data: {
        datasets: data.map((skill, i) => ({
          label:            skill.skill_name,
          data:             skill.points.map(p => ({ x: p.date, y: p.count })),
          borderColor:      JT_COLORS[i % JT_COLORS.length],
          backgroundColor:  JT_COLORS[i % JT_COLORS.length] + '15',
          borderWidth:      2.5,
          pointRadius:      4,
          pointHoverRadius: 7,
          tension:          0.35,
          fill:             false,
        })),
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        interaction: { mode: 'index', intersect: false },
        plugins: {
          legend: {
            position: 'bottom',
            labels:   { font: { size: 11 }, padding: 16, usePointStyle: true },
          },
          tooltip: {
            callbacks: {
              label: ctx => ` ${ctx.dataset.label}: ${ctx.parsed.y} mentions`,
              // Appends trend direction from backend velocity score
              afterLabel: ctx => {
                const skill = data[ctx.datasetIndex];
                if (!skill) return '';
                const arrow = skill.trend === 'growing'   ? '▲ Growing'
                            : skill.trend === 'declining' ? '▼ Declining'
                            : '→ Stable';
                return `  ${arrow} (velocity: ${skill.velocity})`;
              },
            },
          },
        },
        scales: {
          x: {
            type:  'category',
            grid:  { display: false },
            ticks: { font: { size: 11 } },
          },
          y: {
            grid:        { color: '#E8ECF8' },
            ticks:       { font: { size: 11 } },
            beginAtZero: true,
          },
        },
      },
    });

  } catch (err) {
    chartWrap.innerHTML = `<div class="jt-empty">Could not load trend data.</div>`;
    console.warn('[SkillPulse|JT] renderTrends failed:', err.message);
    jt.loaded.trends = false;
  }
}

// ═════════════════════════════════════════════════════════════════════════════
// 6. SKILL OVERLAP — HTML table heatmap
//    Source: /api/jobs/overlap/?occupation_id=X
//    Built as an HTML table rather than Chart.js because matrix data
//    is clearer as a labelled grid. Tick = shared skill, dot = not shared.
// ═════════════════════════════════════════════════════════════════════════════
async function renderOverlap(occId) {
  const wrap = document.getElementById('heatmapWrap');
  try {
    const data = await api(`/api/jobs/overlap/?occupation_id=${occId}`);

    const hasData = data
      && Array.isArray(data.skills)
      && data.skills.length > 0
      && Array.isArray(data.occupations)
      && data.occupations.length > 0;

    if (!hasData) {
      wrap.innerHTML = `
        <div class="jt-empty">
          <i class="bi bi-grid-3x3 me-2"></i>
          Not enough shared skill data yet. This view needs at least 2 related occupations with mapped skills.
        </div>`;
      return;
    }

    // Column headers — truncate long occupation names to keep table readable
    let html = `<table class="jt-heatmap-table">
      <thead><tr>
        <th style="text-align:left; padding-right:16px;">Skill</th>`;

    data.occupations.forEach(occ => {
      const label = occ.length > 22 ? occ.slice(0, 22) + '…' : occ;
      html += `<th title="${esc(occ)}">${esc(label)}</th>`;
    });
    html += `</tr></thead><tbody>`;

    // One row per skill
    data.skills.forEach((skill, rowIdx) => {
      html += `<tr><td class="row-label">${esc(skill)}</td>`;
      const row = data.matrix[rowIdx] || [];
      row.forEach(val => {
        html += `<td class="${val ? 'hm-cell-1' : 'hm-cell-0'}">${val ? '✓' : '·'}</td>`;
      });
      html += `</tr>`;
    });

    html += `</tbody></table>`;
    wrap.innerHTML = html;

  } catch (err) {
    wrap.innerHTML = `<div class="jt-empty">Could not load overlap data.</div>`;
    console.warn('[SkillPulse|JT] renderOverlap failed:', err.message);
    jt.loaded.overlap = false;
  }
}

// ═════════════════════════════════════════════════════════════════════════════
// 7. TOP COMPANIES — ranked table with inline bar
//    Source: /api/jobs/companies/?occupation_id=X
//    Bar width is relative to the top company (max = 100%).
// ═════════════════════════════════════════════════════════════════════════════
async function renderCompanies(occId) {
  const wrap = document.getElementById('companiesWrap');
  try {
    const data = await api(`/api/jobs/companies/?occupation_id=${occId}`);

    if (!data || !data.length) {
      wrap.innerHTML = `
        <div class="jt-empty">
          <i class="bi bi-building me-2"></i>
          No company data available yet for this occupation.
        </div>`;
      return;
    }

    const max = data[0].postings || 1; // top company = 100% bar width

    let html = `
      <table class="jt-company-table">
        <thead>
          <tr>
            <th>#</th>
            <th>Company</th>
            <th>Relative Demand</th>
            <th>Postings</th>
          </tr>
        </thead>
        <tbody>`;

    data.forEach((company, i) => {
      const barPct = Math.round((company.postings / max) * 100);
      html += `
        <tr>
          <td><span class="jt-company-rank">${i + 1}</span></td>
          <td>${esc(company.company)}</td>
          <td>
            <div class="jt-company-bar-wrap">
              <div class="jt-company-bar" style="width:${barPct}%"></div>
            </div>
          </td>
          <td><span class="jt-company-count">${company.postings}</span></td>
        </tr>`;
    });

    html += `</tbody></table>`;
    wrap.innerHTML = html;

  } catch (err) {
    wrap.innerHTML = `<div class="jt-empty">Could not load company data.</div>`;
    console.warn('[SkillPulse|JT] renderCompanies failed:', err.message);
    jt.loaded.companies = false;
  }
}