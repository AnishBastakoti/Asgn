'use strict';

/**
 * jobs.js  —  Jobs Trends page
 * SkillPulse | MSIT402
 *
 * Sections:
 *   1. Global hot skills banner  → /api/analytics/hot-skills
 *   2. Occupation picker         → /api/occupations/list
 *   3. Tab management            (lazy-load per occupation)
 *   4. City demand chart         → /api/jobs/cities/
 *   5. Skill trends line chart   → /api/jobs/trends/
 *   6. Skill overlap heatmap     → /api/jobs/overlap/
 *   7. Top companies table       → /api/jobs/companies/
 *
 * Conventions:
 *   - api(), fmt(), esc() are globals injected by main.js
 *   - Chart instances are module-scoped so they can be destroyed before redraw
 *   - jt.loaded flags are set BEFORE await to prevent double-fetch on fast clicks
 *   - Every API response is null-checked; empty states explain WHY data is missing
 */


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


// ── Utilities ────────────────────────────────────────────────────────────────

/**
 * Converts a hex colour to rgba() so Chart.js canvas renderer
 * handles transparency correctly across all browsers.
 * 8-digit hex (#RRGGBBAA) is CSS4 but not reliably supported on canvas.
 */
function hexToRgba(hex, alpha) {
  const r = parseInt(hex.slice(1, 3), 16);
  const g = parseInt(hex.slice(3, 5), 16);
  const b = parseInt(hex.slice(5, 7), 16);
  return `rgba(${r},${g},${b},${alpha})`;
}
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
  loaded: { cities: false, trends: false, overlap: false, companies: false },
};

// ── Boot ──────────────────────────────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', () => {
  loadHotSkills();
  loadOccupations();
  initTabs();

  // Debounce utility to limit how often a function can run — used for search input
  let searchTimeout;
  document.getElementById('occSearch')
      .addEventListener('input', e => {
          clearTimeout(searchTimeout);
          searchTimeout = setTimeout(() => {
              filterAndRender(e.target.value);
          }, 200);
      });
    });
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

    const max = data[0].total_mentions || 1; // avoid divide-by-zero; if no mentions, all bars will be 0% width
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
    wrap.innerHTML = `<span style="font-size:var(--fs-xs);color:var(--muted)">
      Could not load trending skills.</span>`;
    console.warn('[SkillPulse|JT] loadHotSkills:', err.message);
  }
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
  // Show spinner — for chart panes we MUST NOT overwrite .jt-chart-wrap
  // because that destroys the <canvas> element inside it.
  // Instead overlay a spinner above the chart, and only overwrite innerHTML
  // for heatmap/companies panes that don't use a persistent canvas.
  const pane = document.getElementById(`pane-${tab}`);
  if (pane) {
    if (tab === 'overlap' || tab === 'companies') {
      // These panes use innerHTML directly — safe to overwrite
      const target = pane.querySelector('#heatmapWrap, #companiesWrap');
      if (target) target.innerHTML =
        `<div class="jt-loading"><div class="sp-spinner-sm"></div>&nbsp;Loading&hellip;</div>`;
    } else {
      // Chart panes — show spinner above the chart, preserve the canvas
      const header = pane.querySelector('.jt-chart-sub');
      if (header && !pane.querySelector('.jt-pane-spinner')) {
        const spinner = document.createElement('div');
        spinner.className = 'jt-pane-spinner';
        spinner.innerHTML = `<div class="sp-spinner-sm"></div>`;
        header.after(spinner);
      }
    }
  }

  const id = jt.selected.id;
  if (tab === 'cities') {
    await renderCities(id);
    await renderLeadIndicator(id);
  }
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
  let chartWrap;
  try {
    const pane = document.getElementById('pane-cities');
    if (!pane) throw new Error('pane-cities element not found in DOM');
    chartWrap = pane.querySelector('.jt-chart-wrap');
    if (!chartWrap) throw new Error('chart wrap not found inside pane-cities');

    const data = await api(`/api/jobs/cities/?occupation_id=${occId}`);

    // Guard: occupation may have changed while this request was in flight
    if (jt.selected?.id !== occId) return;

    if (_citiesChart) { _citiesChart.destroy(); _citiesChart = null; }

    if (!data || !data.length) {
      chartWrap.innerHTML = `<div class="jt-empty">
        <i class="bi bi-geo-alt me-2"></i>
        No city data yet for this occupation.</div>`;
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
          backgroundColor: data.map((_, i) => hexToRgba(JT_COLORS[i % JT_COLORS.length], 0.75)),
          borderColor:     data.map((_, i) => hexToRgba(JT_COLORS[i % JT_COLORS.length], 1.0)),
          borderWidth:     1,
          borderRadius:    5,
        }],
      },
      options: {
        indexAxis: 'y',
        responsive: true,
        maintainAspectRatio: false,
        plugins: {
          legend: { display: false },
          tooltip: { callbacks: { label: c => ` ${c.parsed.x} postings` } },
        },
        scales: {
          x: { grid: { color: '#E8ECF8' }, ticks: { font: { size: 11, weight: "600" } }, beginAtZero: true },
          y: { grid: { display: false }, ticks: { font: { size: 11, weight: "600" } } },
        },
      },
    });

  } catch (err) {
    console.error('[SkillPulse|JT] renderCities:', err);
    if (chartWrap) chartWrap.innerHTML =
      `<div class="jt-empty"><i class="bi bi-exclamation-triangle me-2"></i>` +
      `City data unavailable. <small class="text-muted d-block mt-1">${err.message}</small></div>`;
    jt.loaded.cities = false;
  } finally {
    // Remove loading spinner overlay regardless of success or failure
    document.querySelector('#pane-cities .jt-pane-spinner')?.remove();
  }
}

// ═══════════════════════════════════════════════════════
// 4b. CITY LEAD INDICATOR
//     Source: /api/jobs/lead-cities/?occupation_id=X
// ═══════════════════════════════════════════════════════
async function renderLeadIndicator(occId) {
  const insightBox = document.getElementById('cityLeadInsight');
  if (!insightBox) return;

  try {
    const data = await api(`/api/jobs/lead-cities/?occupation_id=${occId}`);

    if (!data || !data.length) {
      insightBox.style.display = 'none';
      return;
    }

    const lead = data.find(d => d.is_lead) || data[0];
    insightBox.style.display = 'block';
    insightBox.innerHTML = `
      <div class="d-flex align-items-center gap-3 p-3 rounded border border-primary-subtle bg-primary-subtle">
        <span class="badge bg-primary">
          <i class="bi bi-lightning-fill me-1"></i>Lead Market
        </span>
        <div class="small text-secondary">
          <strong class="text-dark">${esc(lead.city)}</strong>
          was the first city to trend for this role
          <span class="text-muted">(detected: ${lead.first_seen})</span>
        </div>
      </div>`;

  } catch (err) {
    console.warn('[SkillPulse|JT] renderLeadIndicator failed:', err.message);
    insightBox.style.display = 'none';
  }
}

// ═════════════════════════════════════════════════════════════════════════════
// 5. SKILL TRENDS — multi-line time series
//    Source: /api/jobs/trends/?occupation_id=X
//    Each dataset is one skill. Tooltip shows trend direction (growing/declining/stable)
//    from the velocity score computed by numpy linear regression in the backend.
// ═════════════════════════════════════════════════════════════════════════════
async function renderTrends(occId) {
  let chartWrap;
  try {
    const pane = document.getElementById('pane-trends');
    if (!pane) throw new Error('pane-trends element not found in DOM');
    chartWrap = pane.querySelector('.jt-chart-wrap');
    if (!chartWrap) throw new Error('chart wrap not found inside pane-trends');

    const data = await api(`/api/jobs/trends/?occupation_id=${occId}`);

    // Guard: occupation may have changed while this request was in flight
    if (jt.selected?.id !== occId) return;

    if (_trendsChart) { _trendsChart.destroy(); _trendsChart = null; }
    if (!data || !data.length) {
      chartWrap.innerHTML = `<div class="jt-empty">
        <i class="bi bi-graph-up me-2"></i>
        No skill trend data yet for this occupation.</div>`;
      return;
    }
    // Filter out skills with no points — prevents ghost legend entries with strikethrough
    const validSkills = data
    .filter(s => s.points && s.points.length > 0)
    .sort((a,b) =>
      b.points.reduce((t,p)=>t+p.count,0) -
      a.points.reduce((t,p)=>t+p.count,0)
   )
   .slice(0,5); // limit to top 5 skills for readability
    // Compute the max mention count across all skills and points
    // Used to set a sensible y-axis max and force integer steps
    const allCounts = validSkills.flatMap(s => s.points.map(p => p.count));
    const maxCount  = Math.max(...allCounts, 1); // at least 1 to avoid empty axis

    const ctx = document.getElementById('chartTrends').getContext('2d');
    _trendsChart = new Chart(ctx, {
      type: 'line',
      data: {
        //labels: labels,
        datasets: validSkills.map((skill, i) => ({
          label:            skill.skill_name,
          data: skill.points.map(p => ({ x: p.date, y: p.count })),
          borderColor:      hexToRgba(JT_COLORS[i % JT_COLORS.length], 1.0),
          backgroundColor:  hexToRgba(JT_COLORS[i % JT_COLORS.length], 0.08),
          borderWidth:      2.5,
          pointRadius:      4,
          pointHoverRadius: 7,
          cubicInterpolationMode: 'monotone',
          pointBackgroundColor: hexToRgba(JT_COLORS[i % JT_COLORS.length], 1.0),
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
            labels: {
              font: { size: 11, weight: '600' },
              padding: 16,
              usePointStyle: true,
              pointStyle: 'circle',
              pointStyleWidth: 10,
            },
          },
          tooltip: {
            backgroundColor: 'rgba(17,24,39,0.92)',  // near-black, not solid black
            titleColor:      '#A5B4FC',               // indigo-300 — matches brand
            bodyColor:       '#E5E7EB',               // neutral-200
            borderColor:     'rgba(99,102,241,0.3)',
            borderWidth:     1,
            padding:         12,
            cornerRadius:    10,
            titleFont:       { size: 13, weight: '700' },
            bodyFont:        { size: 13, weight: '500' },
            usePointStyle:   true,
            callbacks: {
              // Format ISO date in tooltip title
              title: items => {
                if (!items.length) return '';
                const raw = items[0].label.replace(' ', 'T');
                const d   = new Date(raw);
                return isNaN(d)
                  ? items[0].label   // fallback to raw if parse fails
                  : d.toLocaleDateString('en-AU', {
                      weekday: 'short', day: 'numeric',
                      month: 'long',   year: 'numeric',
                    });
              },
              // Fix "1 mentions" grammar + clean formatting
              label: ctx => {
                const count = ctx.parsed.y;
                const noun  = count === 1 ? 'mention' : 'mentions';
                return `  ${ctx.dataset.label}: ${count} ${noun}`;
              },
              // Only show trend direction if meaningful (velocity != 0)
              afterLabel: ctx => {
                const skill = validSkills[ctx.datasetIndex];
                if (!skill) return '';
                const arrow = skill.trend === 'growing'   ? '▲ Growing'
                            : skill.trend === 'declining' ? '▼ Declining'
                            : '→ Stable';
                return arrow ? `  ${arrow}  (velocity: ${skill.velocity})` : '';
              },
            },
          },
        },
        scales: {
          x: {
            //type: 'category',
            grid: { display: false },
            border: { display: true },
            ticks: {
              font: { size: 11, weight: '600' },
              color: '#6B7280',
              callback: function(val) {
                const raw = this.getLabelForValue(val).replace(' ', 'T');
                const d   = new Date(raw);
                return isNaN(d)
                  ? val
                  : d.toLocaleDateString('en-AU', { day: 'numeric', month: 'short' });
              },
            },
          },
          y: {
            grid:  { color: '#F3F4F6', drawBorder: false },
            border: { display: true },
            min: 0,
            max: maxCount < 5 ? 5 : undefined, // if counts are low, set max to 5 for better scaling
            ticks: {
              font: { size: 11, weight: '600' },
              color: '#6B7280',
              stepSize: 1,
              // integers only, max 6 ticks — keeps axis clean when counts are small
              precision:     0,
              maxTicksLimit: 6,
            },
            beginAtZero: true,
          },
        },
      },
    });

  } catch (err) {
    console.error('[SkillPulse|JT] renderTrends:', err);
    if (chartWrap) chartWrap.innerHTML =
      `<div class="jt-empty"><i class="bi bi-exclamation-triangle me-2"></i>` +
      `Trend data unavailable. <small class="text-muted d-block mt-1">${err.message}</small></div>`;
    jt.loaded.trends = false;
  } finally {
    document.querySelector('#pane-trends .jt-pane-spinner')?.remove();
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
// 7. COMPANIES — ranked table with inline bar
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