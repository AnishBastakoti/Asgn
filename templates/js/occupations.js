/**
 * SkillPulse — City Demand Page
 * occupations.js
 *
 * Handles:
 *  - City list rendering with demand bars
 *  - KPI cards population
 *  - Top N occupation bar chart per city
 *  - Slider interaction
 *  - Tooltips on bar hover
 */

'use strict';

// ── State ──────────────────────────────────────────────
const cdState = {
  cities:       [],   // full city summary list
  selectedCity: null, // currently selected city name
  topN:         10,   // current slider value
};

// ── DOM helpers (reuse global $ from main.js) ──────────
const cdEl = id => document.getElementById(id);

// ── Colour palette for bars (cycles through) ──────────
const BAR_COLOURS = [
  'var(--indigo)',
  'var(--emerald)',
  'var(--violet, #8B5CF6)',
  'var(--sky, #0EA5E9)',
  '#F59E0B',
  '#EF4444',
  '#10B981',
  '#6366F1',
];
const barColour = i => BAR_COLOURS[i % BAR_COLOURS.length];

// ── Format helpers ─────────────────────────────────────
const fmtNum = n => n >= 1000 ? (n / 1000).toFixed(1) + 'k' : String(n);

// ── Init ───────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', () => {
  initSlider();
  loadCitySummary();
});

// ── Slider ─────────────────────────────────────────────
function initSlider() {
  const slider = cdEl('cdTopNSlider');
  const label  = cdEl('cdTopNVal');
  if (!slider) return;

  slider.addEventListener('input', () => {
    cdState.topN  = +slider.value;
    label.textContent = slider.value;
    if (cdState.selectedCity) loadCityDetail(cdState.selectedCity);
  });
}

// ── Load all cities ────────────────────────────────────
async function loadCitySummary() {
  const list = cdEl('cityList');
  if (!list) return;

  try {
    const cities = await api('/api/analytics/city-demand');
    cdState.cities = cities;

    // ── KPI cards ──
    const totalJobs = cities.reduce((s, c) => s + c.total_jobs, 0);
    const topCity   = cities[0]?.city ?? '—';

    setKpi('kpiCities',    cities.length);
    setKpi('kpiTotalJobs', fmtNum(totalJobs));
    setKpi('kpiTopCity',   topCity);
    setKpi('kpiSelectedJobs', '—');

    // ── Render city list ──
    renderCityList(cities);

    // ── Auto-select first city ──
    if (cities.length > 0) {
      selectCity(cities[0].city);
    }

  } catch (err) {
    list.innerHTML = `<div class="sp-occ-empty">Failed to load cities</div>`;
    console.warn('[SkillPulse] loadCitySummary:', err.message);
  }
}

// ── Render city list ───────────────────────────────────
function renderCityList(cities) {
  const list = cdEl('cityList');
  if (!list) return;

  list.innerHTML = cities.map(c => `
    <div class="cd-city-item" data-city="${esc(c.city)}" title="${esc(c.city)}">
      <div class="cd-city-name">${esc(c.city)}</div>
      <div class="cd-city-meta">
        <span class="cd-city-jobs">${fmt(c.total_jobs)} jobs · ${c.occupation_count} roles</span>
      </div>
      <div class="cd-city-bar-track">
        <div class="cd-city-bar-fill" style="width:0%" data-pct="${c.demand_pct}"></div>
      </div>
    </div>
  `).join('');

  // Animate bars in after render
  requestAnimationFrame(() => {
    list.querySelectorAll('.cd-city-bar-fill').forEach(el => {
      setTimeout(() => el.style.width = el.dataset.pct + '%', 100);
    });
  });

  // Click handlers
  list.querySelectorAll('.cd-city-item').forEach(el => {
    el.addEventListener('click', () => selectCity(el.dataset.city));
  });
}

// ── Select a city ──────────────────────────────────────
function selectCity(cityName) {
  cdState.selectedCity = cityName;

  // Highlight active city in list
  document.querySelectorAll('.cd-city-item').forEach(el => {
    el.classList.toggle('active', el.dataset.city === cityName);
  });

  // Update KPI
  const cityData = cdState.cities.find(c => c.city === cityName);
  if (cityData) setKpi('kpiSelectedJobs', fmt(cityData.total_jobs));

  // Load detail chart
  loadCityDetail(cityName);
}

// ── Load city detail ───────────────────────────────────
async function loadCityDetail(cityName) {
  const welcome = cdEl('cdWelcome');
  const content = cdEl('cdChartContent');
  const header  = cdEl('cdChartHeader');
  const bars    = cdEl('cdBarsWrap');

  if (!content) return;

  // Show loading state
  welcome.classList.add('d-none');
  content.classList.remove('d-none');
  bars.innerHTML = `<div class="sp-spinner-center"><div class="sp-spinner"></div></div>`;

  try {
    const data = await api(`/api/analytics/city-demand/${encodeURIComponent(cityName)}?limit=${cdState.topN}`);

    if (!data.length) {
      bars.innerHTML = `<div class="sp-occ-empty">No occupation data available for ${esc(cityName)}</div>`;
      return;
    }

    // ── Header ──
    const cityData = cdState.cities.find(c => c.city === cityName);
    header.innerHTML = `
      <div>
        <div class="cd-chart-title">
          <i class="bi bi-geo-alt-fill me-2" style="color:var(--indigo)"></i>${esc(cityName)}
        </div>
        <div class="cd-chart-sub">Top ${data.length} occupations by job demand</div>
      </div>
      <div class="cd-chart-badges">
        <span class="sp-cbadge sp-cbadge--indigo">${data.length} roles</span>
        <span class="sp-cbadge">${cityData ? fmt(cityData.total_jobs) + ' total jobs' : ''}</span>
      </div>`;

    // ── Bars ──
    bars.innerHTML = '';
    const maxJobs = data[0].total_jobs;

    data.forEach((row, i) => {
      const pct   = (row.total_jobs / maxJobs) * 100;
      const color = barColour(i);

      const el = document.createElement('div');
      el.className = 'cd-bar-row';
      el.style.animationDelay = `${i * 0.04}s`;
      el.innerHTML = `
        <div class="cd-bar-rank">${i + 1}</div>
        <div class="cd-bar-label" title="${esc(row.occupation_title)}">${esc(row.occupation_title)}</div>
        <div class="cd-bar-track">
          <div class="cd-bar-fill" style="width:0%; background:${color}"></div>
        </div>
        <div>
          <span class="cd-bar-count">${fmt(row.total_jobs)}</span>
          <span class="cd-bar-count-sub">jobs</span>
        </div>`;

      // Tooltip
      el.addEventListener('mouseenter', e => {
        showTip(e,
          `<div class="tt-title">${esc(row.occupation_title)}</div>
           <div class="tt-row">Job Posts: <span>${row.total_jobs}</span></div>
           <div class="tt-row">Demand Score: <span>${row.demand_pct}%</span></div>
           <div class="tt-row">City: <span>${esc(cityName)}</span></div>`
        );
      });
      el.addEventListener('mousemove', moveTip);
      el.addEventListener('mouseleave', hideTip);

      bars.appendChild(el);

      // Animate bar fill after insert
      setTimeout(() => {
        el.querySelector('.cd-bar-fill').style.width = pct + '%';
      }, i * 40 + 80);
    });

  } catch (err) {
    bars.innerHTML = `
      <div class="sp-occ-empty">
        <i class="bi bi-exclamation-triangle me-2"></i>Failed to load data for ${esc(cityName)}
      </div>`;
    console.warn('[SkillPulse] loadCityDetail:', err.message);
  }
}

// ── KPI helper ─────────────────────────────────────────
function setKpi(id, value) {
  const el = cdEl(id);
  if (el) el.textContent = value;
}