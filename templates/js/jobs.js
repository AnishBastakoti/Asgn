'use strict';

// ── Colour palette (matches CSS token --indigo, --emerald, etc.) ──────────────
const JT_COLORS = [
   '#EB5905', // orange
  // '#10B981', // emerald
  // '#F43F5E', // coral
  // '#0EA5E9', // sky
  // '#8B5CF6', // violet
  // '#F59E0B', // amber
  // '#EC4899', // pink
  // '#14B8A6', // teal
];


// ── Utilities ────────────────────────────────────────────────────────────────

/**
 * Converts a hex colour to rgba() so Chart.js canvas renderer
 * handles transparency correctly across all browsers.
 * 8-digit hex is CSS4 but not reliably supported on canvas.
 */
function hexToRgba(hex, alpha) {
  const r = parseInt(hex.slice(1, 3), 16);
  const g = parseInt(hex.slice(3, 5), 16);
  const b = parseInt(hex.slice(5, 7), 16);
  return `rgba(${r},${g},${b},${alpha})`;
}
// ── Chart instances — module-scoped so we can destroy before redraw ────────────
let _citiesChart = null;
let _skillGapsChart = null;

// ── Page state ────────────────────────────────────────────────────────────────
const jt = {
  occupations: [],   // full list from API
  filtered:    [],   // list after search filter applied
  selected:    null, // { id, title, level } of currently selected occupation
  activeTab:   'cities',
  // Tracks which tabs have been loaded for the current occupation.
  // Resets to all-false when a new occupation is selected.
  loaded: { cities: false, 'skills': false, overlap: false, companies: false },
};

// ── Boot ──────────────────────────────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', () => {
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


function togglePicker() {
  document.querySelector('.jt-layout').classList.toggle('picker-collapsed');
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
  jt.loaded   = { cities: false, 'skills': false, overlap: false, companies: false, topskills: false };

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
// TAB MANAGEMENT
//    Lazy-loads data: each tab fetches once per selected occupation.
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
  if (jt.loaded[tab]) return;

  // Mark loaded BEFORE await to prevent double-fetch if user clicks fast
  jt.loaded[tab] = true;
  const pane = document.getElementById(`pane-${tab}`);
  if (pane) {
    if (tab === 'overlap' || tab === 'companies' || tab === 'topskills') {
      // These panes use innerHTML directly — safe to overwrite
      const target = pane.querySelector('#heatmapWrap, #companiesWrap, #topSkillsWrap');
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
  if (tab === 'skills')    await renderTrends(id);
  if (tab === 'overlap')   await renderOverlap(id);
  if (tab === 'companies') await renderCompanies(id);
  if (tab === 'topskills') await renderTopSkills(id);
}

// ═════════════════════════════════════════════════════════════════════════════
// CITY DEMAND — horizontal bar chart
//    Source: /api/jobs/cities/?occupation_id=X
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
// CITY LEAD INDICATOR
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
        <i class="bi bi-geo-alt-fill fs-3" style="color:var(--orange)"></i>
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
// SKILL OVERLAP — HTML table heatmap
//    Source: /api/jobs/overlap/?occupation_id=X
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

    // Column headers — slice long occupation names to keep table readable
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
        html += `<td class="${val ? 'hm-cell-1' : 'hm-cell-0'}">${val ? '✓' : 'x'}</td>`;
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
// COMPANIES — ranked table with inline bar
//    Source: /api/jobs/companies/?occupation_id=X
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

// ═════════════════════════════════════════════════════════════════════════════
// TOP SKILLS PER OCCUPATION
//    Source: /api/jobs/hot-skills/{occupation_id}?days=30
//    Falls back to all-time if no pipeline run in last 30 days.
// ═════════════════════════════════════════════════════════════════════════════
async function renderTopSkills(occId) {
  if (!occId || isNaN(occId)) {
    console.error('[renderTopSkills] Invalid occId:', occId);
    return;
  }

  const wrap = document.getElementById('topSkillsWrap');
  const sub  = document.getElementById('topSkillsSub');

  document.querySelectorAll('#pane-topskills .jt-pane-spinner')
    .forEach(el => el.remove());
  wrap.innerHTML = `<div class="jt-loading"><div class="sp-spinner-sm"></div>&nbsp;Loading…</div>`;

  try {
    const d = await api(`/api/jobs/hot-skills/?occupation_id=${occId}&days=30`);
    const skills = Array.isArray(d) ? d : (d.skills || []);

    if (sub) {
      sub.textContent = 'Most mentioned skills from job posts in the last 30 days';
    }

    if (!skills.length) {
      wrap.innerHTML = `<div class="jt-empty"><i class="bi bi-hourglass-split me-2"></i>No skill data yet.</div>`;
      return;
    }

    const max = skills[0].total_mentions || 1;

    const typeColors = {
      'knowledge':        'var(--violet)',
      'skill/competence': 'var(--orange)',
      'skill':            'var(--orange)',
      'attitude':         '#F59E0B',
      'language':         '#10B981',
    };

    const rows = skills.map((s, i) => {
      //Normalize type inside the loop so 's' is defined
      const typeKey = (s.skill_type || 'unknown').toLowerCase();
      
      //the normalized key to pick the color
      const color = typeColors[typeKey] || 'var(--orange)';
      
      const pct = Math.round((s.total_mentions / max) * 100);
      const skillName = s.skill_name || s.preferred_label || '—'; 

      const nameHtml = s.concept_uri
      ? `<span class="sp-skill-name-wrap">
          <a href="${s.concept_uri}" target="_blank" rel="noopener noreferrer" class="sp-esco-name-link">${esc(skillName)}</a>
          <a href="${s.concept_uri}" target="_blank" rel="noopener noreferrer" class="sp-esco-link"><i class="bi bi-box-arrow-up-right"></i></a>
        </span>`
      : `<span class="sp-skill-name-wrap">${esc(skillName)}</span>`;

      return `
        <div class="jt-hot-row" style="gap:10px; margin-bottom:8px;">
          <span class="jt-hot-rank">${i + 1}</span>
          <span class="jt-hot-name" style="flex:1; font-size:13px;">${nameHtml}</span>
          <div style="width:140px; height:6px; background:var(--orange-l); border-radius:99px; flex-shrink:0; overflow:hidden;">
            <div style="width:${pct}%; height:100%; background:${color}; border-radius:99px; transition:width 0.5s ease;"></div>
          </div>
          <span class="jt-hot-count">${fmt(s.total_mentions)} ${s.total_mentions === 1 ? 'job' : 'jobs'}</span>
        </div>`;
    }).join('');

    wrap.innerHTML = `<div style="margin-top:8px;">${rows}</div>`;
    jt.loaded.topskills = true;

  } catch (err) {
    wrap.innerHTML = `<div class="jt-empty text-danger"><i class="bi bi-exclamation-triangle me-2"></i>Could not load skill data.</div>`;
    console.warn('[SkillPulse] renderTopSkills:', err.message);
  }
}

// ═════════════════════════════════════════════════════════════════════════════
// SKILL GAP RADAR
//    Source: /api/jobs/skill-gap-radar/{occupation_id}
//    Compares official OSCA-mapped skills vs skills found in real job postings.
//    Renders a 5-axis Chart.js radar + per-type coverage cards.
// ═════════════════════════════════════════════════════════════════════════════
let _gapChart = null;
 
async function renderTrends(occId) {
  const pane      = document.getElementById('pane-trends');
  const spinner   = document.getElementById('gapSpinner');
  const summaryRow = document.getElementById('gapSummaryRow');
  const layout    = pane ? pane.querySelector('.jt-gap-layout') : null;
  const typeCards = document.getElementById('gapTypeCards');
  const overallBadge = document.getElementById('gapOverallBadge');
 
  try {
    const data = await api(`/api/jobs/skill-gap-radar/${occId}`);
 
    // Guard: user switched occupation while this was loading
    if (jt.selected?.id !== occId) return;
 
    if (!data) {
      if (spinner) spinner.innerHTML =
        `<div class="jt-empty"><i class="bi bi-exclamation-triangle me-2"></i>No skill data for this occupation.</div>`;
      return;
    }
 
    // ── Destroy previous chart ───────────────────────────────────────────────
    if (_gapChart) { _gapChart.destroy(); _gapChart = null; }
 
    // ── KPI summary row ──────────────────────────────────────────────────────
    const s = data.summary;
    if (summaryRow) {
      summaryRow.style.display = 'grid';
      summaryRow.innerHTML = [
        _gapKpi(s.official_skill_count, 'Official Skills',   '#6366F1', '#EEF2FF'),
        _gapKpi(s.matched_in_postings,  'Found in Postings', '#10B981', '#ECFDF5'),
        _gapKpi(s.unmatched_official,   'Not Demanded',      '#EF4444', '#FEF2F2'),
        _gapKpi(s.shadow_skills,        'Shadow Skills',     '#F59E0B', '#FFFBEB'),
      ].join('');
    }
 
    // ── Radar chart ──────────────────────────────────────────────────────────
    const r   = data.radar;
    const ctx = document.getElementById('chartGap')?.getContext('2d');
 
    if (ctx) {
      _gapChart = new Chart(ctx, {
        type: 'radar',
        data: {
          labels: [
            'Knowledge\nCoverage',
            'Competence\nCoverage',
            'Attitude\nCoverage',
            'Market\nIntensity',
            'Shadow\nSkills',
          ],
          datasets: [{
            label:              'Coverage %',
            data: [
              r.knowledge_coverage,
              r.competence_coverage,
              r.attitude_coverage,
              r.market_intensity,
              r.shadow_ratio,
            ],
            backgroundColor:    'rgba(235,89,5,0.12)',
            borderColor:        '#EB5905',
            borderWidth:        2,
            pointBackgroundColor: '#EB5905',
            pointBorderColor:   '#fff',
            pointBorderWidth:   1.5,
            pointRadius:        5,
            pointHoverRadius:   7,
          }],
        },
        options: {
          responsive:          true,
          maintainAspectRatio: true,
         layout: {
          padding: {
            left:   20,
            right:  20,   
            top:    10,
            bottom: 10,
            }
          },
          scales: {
            r: {
              min:  0,
              max:  100,
              ticks: {
                stepSize: 25,
                display:  false,
              },
              grid:   { color: 'rgba(0,0,0,0.08)' },
              angleLines: { color: 'rgba(0,0,0,0.08)' },
              pointLabels: {
                font:  { size: 10.5, weight: '600' },
                color: 'rgb(235, 89, 5)',
                padding: 8,
              },
            },
          },
          plugins: {
            legend: { display: false },
            tooltip: {
              backgroundColor: 'rgba(17,24,39,0.92)',
              titleColor:      '#F9FAFB',
              bodyColor:       '#E5E7EB',
              padding:         10,
              cornerRadius:    8,
              callbacks: {
                label: ctx => `  ${ctx.raw.toFixed(1)}%`,
              },
            },
          },
        },
      });
    }
 
    // ── Overall badge below radar ────────────────────────────────────────────
    if (overallBadge) {
      const pct   = s.overall_coverage_pct;
      const color = pct >= 75 ? '#10B981' : pct >= 40 ? '#F59E0B' : '#EF4444';
      overallBadge.innerHTML =
        `Overall coverage: <strong style="color:${color}">${pct}%</strong>` +
        ` &mdash; ${s.matched_in_postings} of ${s.official_skill_count} skills`;
    }
 
    // ── Per-type coverage cards ──────────────────────────────────────────────
    if (typeCards && data.by_type?.length) {
      typeCards.innerHTML = data.by_type.map(t => _gapTypeCard(t)).join('');
    } else if (typeCards) {
      typeCards.innerHTML =
        `<div class="jt-empty">No skill type breakdown available.</div>`;
    }
 
    // ── Show layout, hide spinner ────────────────────────────────────────────
    if (layout)  layout.style.display  = 'flex';
    if (spinner) spinner.style.display = 'none';
 
  } catch (err) {
    console.error('[SkillPulse|JT] renderSkillGapRadar:', err);
    if (spinner) {
      const errDetail = err.message || 'Unknown error';
      spinner.innerHTML =
        `<div class="jt-empty">` +
        `<i class="bi bi-exclamation-triangle me-2"></i>` +
        `Gap analysis unavailable.` +
        `<small class="text-muted d-block mt-1">${errDetail}</small></div>`;
    }
    jt.loaded.trends = false;
  }finally {
    //always remove the pane spinner regardless of success/failure
    document.querySelector('#pane-skills .jt-pane-spinner')?.remove();
  }
}
 
 
// ── Gap radar helper: KPI card ───────────────────────────────────────────────
function _gapKpi(value, label, color, bg) {
  return `
    <div class="gap-kpi-card" style="background:${bg};border:1px solid ${color}30;">
      <div class="gap-kpi-val" style="color:${color};">${value}</div>
      <div class="gap-kpi-label">${label}</div>
    </div>`;
}
 
 
// ── Gap radar helper: per-type coverage card ─────────────────────────────────
function _gapTypeCard(t) {
  const bar   = Math.round(t.coverage_pct);
  const color = bar >= 75 ? '#F29762' : bar >= 40 ? '#F59E0B' : '#EF4444';
 
  const matchedPills = t.top_matched.length
    ? `<div class="gap-section-label">&#10003; Present in postings</div>
       <div class="gap-pill-group">
         ${t.top_matched.map(s => `<span class="gap-pill matched" title="${esc(s)}">${esc(s)}</span>`).join('')}
       </div>`
    : '';
 
  const missingPills = t.top_missing.length
    ? `<div class="gap-section-label">&#x2715; Not demanded yet</div>
       <div class="gap-pill-group">
         ${t.top_missing.map(s => `<span class="gap-pill missing" title="${esc(s)}">${esc(s)}</span>`).join('')}
       </div>`
    : '';
 
  return `
    <div class="gap-type-card">
      <div class="gap-type-header">
        <span class="gap-type-label">${t.label}</span>
        <span class="gap-type-pct" style="color:${color};">${t.coverage_pct}%</span>
      </div>
      <div class="gap-progress-track">
        <div class="gap-progress-fill" style="width:${bar}%;background:${color};"></div>
      </div>
      <div class="gap-counts">${t.matched_count} of ${t.official_count} official skills found in postings</div>
      ${matchedPills}
      ${missingPills}
    </div>`;
}
 
