'use strict';

const API = 'http://localhost:8000';

const PAGE_TITLES = {
  dashboard:   'Dashboard',
  skills:      'Skills Demand',
  heatmap:     'Heatmap',
  occupations: 'Occupations',
  pipeline:    'Pipeline',
};

// document.addEventListener('DOMContentLoaded', () => {
//   M.Sidenav.init(document.querySelectorAll('.sidenav'));
//   initNavigation();
//   checkHealth();
// });

// function initNavigation() {
//   document.querySelectorAll('.nav-link').forEach(link => {
//     link.addEventListener('click', e => {
//       e.preventDefault();
//       const page = link.dataset.page;

//       document.querySelectorAll('.nav-link').forEach(l => l.classList.remove('active'));
//       link.classList.add('active');

//       document.querySelectorAll('.page').forEach(p => p.classList.remove('active'));
//       document.getElementById(`page-${page}`).classList.add('active');

//       document.getElementById('page-title').textContent = PAGE_TITLES[page];
//     });
//   });
// }

// async function checkHealth() {
//   try {
//     const res  = await fetch(`${API}/health`);
//     const data = await res.json();

//     if (data.status === 'healthy') {
//       document.getElementById('status-dot').className    = 'status-dot';
//       document.getElementById('status-text').textContent = `${data.app} · DB OK`;
//       loadKPIs();
//     } else {
//       document.getElementById('status-dot').className    = 'status-dot offline';
//       document.getElementById('status-text').textContent = 'DB unreachable';
//     }
//   } catch {
//     document.getElementById('status-dot').className    = 'status-dot offline';
//     document.getElementById('status-text').textContent = 'API offline';
//   }
// }

// async function loadKPIs() {
//   try {
//     const [skills, occs, groups] = await Promise.all([
//         fetch(`${API}/api/skills/count`).then(r => r.json()),
//         fetch(`${API}/api/occupations/?limit=200`).then(r => r.json()),
//         fetch(`${API}/api/occupations/major-groups`).then(r => r.json()),
//     ]);

//     document.getElementById('kpi-skills').textContent      = skills.count.toLocaleString();
//     document.getElementById('kpi-occupations').textContent = occs.count   || '—';
//     document.getElementById('kpi-groups').textContent      = groups.count || '—';
//     document.getElementById('kpi-jobs').textContent        = '—';
//   } catch (e) {
//     console.error('KPI load failed:', e);
//   }
// }


// ── Helpers ───────────────────────────────────────────────
const $  = id  => document.getElementById(id);
const $$ = sel => document.querySelectorAll(sel);
const fmt = n  => n == null ? '—' : n >= 1e6 ? (n/1e6).toFixed(1)+'M' : n >= 1e3 ? (n/1e3).toFixed(1)+'K' : String(n);
const esc = s  => String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');

async function api(path) {
  const res = await fetch(API + path);
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return res.json();
}

// ── Tooltip ───────────────────────────────────────────────
const tooltip = $('tooltip');
function showTip(e, html) { tooltip.innerHTML = html; tooltip.classList.add('visible'); moveTip(e); }
function moveTip(e) {
  tooltip.style.left = Math.min(e.clientX + 14, window.innerWidth  - 240) + 'px';
  tooltip.style.top  = Math.min(e.clientY - 10, window.innerHeight - 140) + 'px';
}
function hideTip() { tooltip.classList.remove('visible'); }

// ── Status ────────────────────────────────────────────────
function setStatus(online, text) {
  $('statusDot').className = 'status-dot ' + (online ? 'online' : 'offline');
  $('statusText').textContent = text;
}

// ── Loading / Error HTML ──────────────────────────────────
function loadingHtml() {
  return `<div class="chart-empty">
    <div class="preloader-wrapper small active">
      <div class="spinner-layer spinner-teal-only">
        <div class="circle-clipper left"><div class="circle"></div></div>
        <div class="gap-patch"><div class="circle"></div></div>
        <div class="circle-clipper right"><div class="circle"></div></div>
      </div>
    </div>
  </div>`;
}
function noDataHtml(msg) {
  return `<div class="no-data-state"><i class="material-icons">search_off</i><strong>No data available</strong><span>${msg||'This occupation has no data for this view yet.'}</span></div>`;
}
function errorHtml(msg) {
  return `<div class="error-banner"><i class="material-icons">error_outline</i>Failed to load: ${esc(msg)}</div>`;
}

// ── Navigation ────────────────────────────────────────────
function initNav() {
  $$('.nav-link').forEach(link => {
    link.addEventListener('click', e => {
      e.preventDefault();
      $$('.nav-link').forEach(l => l.classList.remove('active'));
      link.classList.add('active');
      switchPage(link.dataset.page);
    });
  });
}

function switchPage(page) {
  state.currentPage = page;
  $('welcomeState').style.display = 'none';
  $$('.page').forEach(p => p.style.display = 'none');
  const target = $(`page-${page}`);
  if (target) target.style.display = 'block';
  if (page === 'about') renderAbout();
  if (state.selected) refreshPage(page);
}

function refreshPage(page) {
  switch(page) {
    case 'dashboard':   renderDashboard();  break;
    case 'skills':      renderSkillsPage(); break;
    case 'cities':      renderCities();     break;
    case 'trends':      renderTrends();     break;
    case 'overlap':     renderOverlap();    break;
    case 'companies':   renderCompanies();  break;
    case 'occupations': renderOccDetail();  break;
  }
}

// ── Summary ───────────────────────────────────────────────
async function loadSummary() {
  try {
    const d = await api('/api/skills/summary');
    state.summary = d;
    $('chipSkills').textContent      = fmt(d.total_skills);
    $('chipOccupations').textContent = fmt(d.total_occupations);
    $('chipJobs').textContent        = fmt(d.total_job_posts);
    $('navSig').textContent          = d.signature;
    setStatus(true, 'Connected');
  } catch(e) {
    setStatus(false, 'Offline');
  }
}

// ── KPI Row ───────────────────────────────────────────────
function renderKpiRow() {
  const s = state.summary;
  if (!s) return;
  $('kpiRow').innerHTML = [
    { label:'Total Skills',   value:fmt(s.total_skills),         sub:'ESCO framework',              icon:'psychology',  color:'teal darken-1'   },
    { label:'Occupations',    value:fmt(s.total_occupations),    sub:'OSCA taxonomy',               icon:'work',        color:'blue darken-1'   },
    { label:'Job Postings',   value:fmt(s.total_job_posts),      sub:`${s.processed_job_posts} AI processed`, icon:'description', color:'orange darken-1' },
    { label:'Skill Mappings', value:fmt(s.total_skill_mappings), sub:'Occupation × skill pairs',    icon:'category',    color:'purple darken-1' },
  ].map(c => `
    <div class="kpi-card ${c.color}">
      <div class="kpi-icon"><i class="material-icons">${c.icon}</i></div>
      <div class="kpi-label">${c.label}</div>
      <div class="kpi-value">${c.value}</div>
      <div class="kpi-sub">${c.sub}</div>
    </div>`).join('');
}

// ── Hierarchy Filters ─────────────────────────────────────
async function initFilters() {
  const majors = await api('/api/occupations/major-groups').catch(() => []);
  const sel = $('filterMajor');
  majors.forEach(g => {
    const o = document.createElement('option');
    o.value = g.id;
    o.textContent = `${g.title} (${g.occupation_count})`;
    sel.appendChild(o);
  });
  M.FormSelect.init(sel);

  sel.addEventListener('change', async () => {
    await loadSubMajors(sel.value);
    filterOccupations();
  });
  $('filterSubMajor').addEventListener('change', async () => {
    await loadMinorGroups($('filterSubMajor').value);
    filterOccupations();
  });
  $('filterMinor').addEventListener('change', filterOccupations);
}

async function loadSubMajors(majorId) {
  const sel = $('filterSubMajor');
  sel.innerHTML = '<option value="">All Sub-Major Groups</option>';
  sel.disabled = !majorId;
  $('filterMinor').innerHTML = '<option value="">All Minor Groups</option>';
  $('filterMinor').disabled = true;
  M.FormSelect.init($('filterMinor'));
  if (!majorId) { M.FormSelect.init(sel); return; }
  const groups = await api(`/api/occupations/sub-major-groups?major_group_id=${majorId}`).catch(() => []);
  groups.forEach(g => { const o = document.createElement('option'); o.value=g.id; o.textContent=g.title; sel.appendChild(o); });
  M.FormSelect.init(sel);
}

async function loadMinorGroups(subMajorId) {
  const sel = $('filterMinor');
  sel.innerHTML = '<option value="">All Minor Groups</option>';
  sel.disabled = !subMajorId;
  if (!subMajorId) { M.FormSelect.init(sel); return; }
  const groups = await api(`/api/occupations/minor-groups?sub_major_group_id=${subMajorId}`).catch(() => []);
  groups.forEach(g => { const o = document.createElement('option'); o.value=g.id; o.textContent=g.title; sel.appendChild(o); });
  M.FormSelect.init(sel);
}

function filterOccupations() {
  const q = $('occSearch').value.toLowerCase();
  let list = state.occupations;
  if (q.length >= 2) list = list.filter(o => o.title.toLowerCase().includes(q));
  renderOccList(list);
}

// ── Slider ────────────────────────────────────────────────
function initSlider() {
  $('topNSlider').addEventListener('input', e => {
    state.topN = +e.target.value;
    $('topNVal').textContent = state.topN;
    if (state.selected) renderDashboard();
  });
}

// ── Search ────────────────────────────────────────────────
function initSearch() {
  let t;
  $('occSearch').addEventListener('input', () => { clearTimeout(t); t = setTimeout(filterOccupations, 200); });
}

// ── Occupation List ───────────────────────────────────────
async function loadOccupations() {
  $('occList').innerHTML = loadingHtml();
  const occs = await api('/api/occupations/list?limit=500').catch(() => []);
  state.occupations = occs;
  $('occCount').textContent = occs.length;
  renderOccList(occs);
}

function renderOccList(occs) {
  $('occCount').textContent = occs.length;
  if (!occs.length) { $('occList').innerHTML = '<div class="occ-empty">No occupations found</div>'; return; }
  $('occList').innerHTML = occs.map(o => `
    <div class="occ-item ${o.has_data?'':'no-data'} ${state.selected?.id===o.id?'active':''}"
         data-id="${o.id}" data-title="${esc(o.title)}"
         data-level="${o.skill_level||''}" data-skills="${o.skill_count}">
      <div class="occ-item-name">${esc(o.title)}</div>
      <div class="occ-item-badges">
        <span class="occ-badge ${o.has_data?'has-data':''}">${o.skill_count} skills</span>
        ${o.skill_level?`<span class="occ-badge">Level ${o.skill_level}</span>`:''}
      </div>
    </div>`).join('');

  $$('.occ-item').forEach(el => {
    el.addEventListener('click', () => {
      $$('.occ-item').forEach(e => e.classList.remove('active'));
      el.classList.add('active');
      state.selected = { id:+el.dataset.id, title:el.dataset.title, level:el.dataset.level, skills:+el.dataset.skills };
      $('breadcrumb').innerHTML = `
        <span class="breadcrumb-item">OSCA Occupations</span>
        <span class="breadcrumb-sep">/</span>
        <span class="breadcrumb-item active">${esc(state.selected.title)}</span>`;
      $('welcomeState').style.display = 'none';
      switchPage(state.currentPage || 'dashboard');
    });
  });
}

// ── Dashboard ─────────────────────────────────────────────
async function renderDashboard() {
  const occ = state.selected; if (!occ) return;
  renderKpiRow();
  $('barChartSub').textContent = occ.title;
  $('barChartBody').innerHTML  = loadingHtml();
  $('donutBody').innerHTML     = loadingHtml();
  try {
    const [skills, breakdown] = await Promise.all([
      api(`/api/skills/top/${occ.id}?limit=${state.topN}`),
      api(`/api/skills/breakdown/${occ.id}`)
    ]);
    if (!skills.length) { $('barChartBody').innerHTML = noDataHtml(); $('donutBody').innerHTML = noDataHtml(); return; }
    renderBarChart(skills, 'barChartBody');
    renderDonut(breakdown);
  } catch(e) { $('barChartBody').innerHTML = errorHtml(e.message); }
}

// ── Bar Chart (reusable) ──────────────────────────────────
function renderBarChart(skills, targetId) {
  const max = Math.max(...skills.map(s => s.mention_count));
  const typeColor = t => t?.includes('knowledge')?'#00897b':t?.includes('skill')?'#ff6f00':t?.includes('attitude')?'#f9a825':'#9e9e9e';
  const typeClass = t => t?.includes('knowledge')?'knowledge':t?.includes('skill')?'skill':t?.includes('attitude')?'attitude':'';
  const trendIcon = t => t==='growing'?'<span class="trend-arrow growing">▲</span>':t==='declining'?'<span class="trend-arrow declining">▼</span>':'<span class="trend-arrow stable">→</span>';

  $(targetId).innerHTML = `<div class="bar-list">${
    skills.map((s,i) => {
      const pct = (s.mention_count / max) * 100;
      const tc  = typeClass(s.skill_type);
      return `<div class="bar-row">
        <div class="bar-rank">${i+1}</div>
        <div class="bar-label-col">
          <div class="bar-label" title="${esc(s.skill_name)}">
            ${esc(s.skill_name)}
            ${tc?`<span class="skill-tag ${tc}">${tc}</span>`:''}
            ${s.trend?trendIcon(s.trend):''}
          </div>
        </div>
        <div class="bar-track">
          <div class="bar-fill" style="background:${typeColor(s.skill_type)}" data-pct="${pct}"></div>
        </div>
        <div class="bar-count-col">
          <span class="bar-count">${fmt(s.mention_count)}</span>
          <span class="bar-sub">mentions</span>
        </div>
      </div>`;
    }).join('')
  }</div>`;

  requestAnimationFrame(() => {
    $$(` #${targetId} .bar-fill`).forEach((f,i) => setTimeout(() => { f.style.width = f.dataset.pct+'%'; }, i*30));
    $$(` #${targetId} .bar-row`).forEach((row,i) => {
      const s = skills[i];
      row.addEventListener('mouseenter', e => showTip(e, `
        <div class="tt-title">${esc(s.skill_name)}</div>
        <div class="tt-row">Mentions: <span>${s.mention_count}</span></div>
        <div class="tt-row">Score: <span>${s.demand_score||'—'}</span></div>
        <div class="tt-row">Type: <span>${s.skill_type||'N/A'}</span></div>
        ${s.trend?`<div class="tt-row">Trend: <span>${s.trend}</span></div>`:''}
        ${s.velocity!=null?`<div class="tt-row">Velocity: <span>${s.velocity}</span></div>`:''}
      `));
      row.addEventListener('mousemove', moveTip);
      row.addEventListener('mouseleave', hideTip);
    });
  });
}

// ── Donut Chart ───────────────────────────────────────────
function renderDonut(data) {
  const types = [
    { key:'knowledge',        label:'Knowledge', color:'#00897b' },
    { key:'skill/competence', label:'Skill',     color:'#ff6f00' },
    { key:'attitude',         label:'Attitude',  color:'#f9a825' },
  ];
  const mapped = types.map(t => ({
    ...t, ...(data.breakdown.find(b => b.skill_type===t.key)||{ total_mentions:0, count:0, percentage:0 })
  })).filter(t => t.total_mentions > 0);

  $('donutBody').innerHTML = `
    <div class="donut-wrap">
      <svg viewBox="0 0 120 120" id="donutSvg"></svg>
      <div class="donut-center">
        <div class="donut-val">${data.total_mentions}</div>
        <div class="donut-lbl">mentions</div>
      </div>
    </div>
    <div class="type-list" id="typeList"></div>`;

  const svg = d3.select('#donutSvg');
  const pie = d3.pie().value(d => d.total_mentions).sort(null);
  const arc = d3.arc().innerRadius(32).outerRadius(54);
  svg.selectAll('path').data(pie(mapped)).enter().append('path')
    .attr('d', arc).attr('fill', d => d.data.color)
    .attr('transform','translate(60,60)').attr('stroke','white').attr('stroke-width',2);

  data.breakdown.forEach(b => {
    const t = types.find(t => t.key===b.skill_type); if (!t) return;
    const row = document.createElement('div');
    row.className = 'type-row';
    row.innerHTML = `
      <div class="type-dot" style="background:${t.color}"></div>
      <div class="type-name">${t.label}</div>
      <div class="type-track"><div class="type-fill" style="background:${t.color}"></div></div>
      <div class="type-pct" style="color:${t.color}">${b.percentage}%</div>`;
    $('typeList').appendChild(row);
    setTimeout(() => { row.querySelector('.type-fill').style.width = b.percentage+'%'; }, 300);
  });
}

// ── Skills Page ───────────────────────────────────────────
async function renderSkillsPage() {
  const occ = state.selected; if (!occ) return;
  $('skillsPageBody').innerHTML = loadingHtml();
  $('skillsPageSub').textContent = occ.title;
  try {
    const skills = await api(`/api/skills/top/${occ.id}?limit=${state.topN}`);
    if (!skills.length) { $('skillsPageBody').innerHTML = noDataHtml(); return; }
    renderBarChart(skills, 'skillsPageBody');
  } catch(e) { $('skillsPageBody').innerHTML = errorHtml(e.message); }
}

// ── City Demand ───────────────────────────────────────────
async function renderCities() {
  const occ = state.selected; if (!occ) return;
  $('cityChartBody').innerHTML = loadingHtml();
  $('leadCityBody').innerHTML  = loadingHtml();
  try {
    const [cities, leads] = await Promise.all([
      api(`/api/jobs/cities/${occ.id}`),
      api(`/api/jobs/lead-cities/${occ.id}`)
    ]);

    // City bar chart
    if (!cities.length) { $('cityChartBody').innerHTML = noDataHtml('No city data for this occupation.'); }
    else {
      const max = Math.max(...cities.map(c => c.job_count));
      $('cityChartBody').innerHTML = `<div class="bar-list">${
        cities.map((c,i) => `
          <div class="bar-row">
            <div class="bar-rank">${i+1}</div>
            <div class="bar-label-col"><div class="bar-label">${esc(c.city)}</div></div>
            <div class="bar-track">
              <div class="bar-fill" style="background:#00897b" data-pct="${(c.job_count/max)*100}"></div>
            </div>
            <div class="bar-count-col">
              <span class="bar-count">${c.job_count}</span>
              <span class="bar-sub">postings</span>
            </div>
          </div>`).join('')
      }</div>`;
      requestAnimationFrame(() => {
        $$('#cityChartBody .bar-fill').forEach((f,i) => setTimeout(() => { f.style.width = f.dataset.pct+'%'; }, i*40));
      });
    }

    // Lead city indicators
    if (!leads.length) { $('leadCityBody').innerHTML = noDataHtml('No city lead data available.'); }
    else {
      $('leadCityBody').innerHTML = `<div class="pipeline-stats">${
        leads.slice(0,6).map(l => `
          <div class="pipeline-stat ${l.is_lead?'lead-city':''}">
            ${l.is_lead?'<div class="lead-badge">Lead City</div>':''}
            <div class="p-val">${esc(l.city)}</div>
            <div class="p-lbl">${l.total_postings} postings</div>
            ${l.first_seen?`<div class="p-lbl" style="font-size:10px">First: ${l.first_seen}</div>`:''}
          </div>`).join('')
      }</div>`;
    }
  } catch(e) { $('cityChartBody').innerHTML = errorHtml(e.message); }
}

// ── Skill Trends ──────────────────────────────────────────
async function renderTrends() {
  const occ = state.selected; if (!occ) return;
  $('trendChartBody').innerHTML = loadingHtml();
  try {
    const trends = await api(`/api/jobs/trends/${occ.id}`);
    if (!trends.length) { $('trendChartBody').innerHTML = noDataHtml('No snapshot data available for trend analysis.'); return; }

    const trendIcon = t => t==='growing'?'▲ Growing':t==='declining'?'▼ Declining':'→ Stable';
    const trendColor = t => t==='growing'?'#00897b':t==='declining'?'#f44336':'#ff9800';

    // Velocity summary cards
    const summaryHtml = `<div class="pipeline-stats" style="margin-bottom:16px">${
      trends.map(t => `
        <div class="pipeline-stat">
          <div class="p-val" style="font-size:14px;color:${trendColor(t.trend)}">${trendIcon(t.trend)}</div>
          <div class="p-lbl">${esc(t.skill_name)}</div>
          <div class="p-lbl">Velocity: ${t.velocity > 0 ? '+' : ''}${t.velocity}</div>
        </div>`).join('')
    }</div>`;

    // D3 line chart
    const chartId = 'trendSvgWrap';
    $('trendChartBody').innerHTML = summaryHtml + `<div id="${chartId}" style="width:100%;height:260px"></div>`;

    const margin = {top:20, right:80, bottom:40, left:40};
    const width  = $('trendChartBody').clientWidth - margin.left - margin.right || 600;
    const height = 260 - margin.top - margin.bottom;

    const svg = d3.select(`#${chartId}`).append('svg')
      .attr('width', width + margin.left + margin.right)
      .attr('height', height + margin.top + margin.bottom)
      .append('g')
      .attr('transform', `translate(${margin.left},${margin.top})`);

    const colors = d3.schemeTableau10;
    const allDates = trends.flatMap(t => t.points.map(p => new Date(p.date)));
    const allCounts = trends.flatMap(t => t.points.map(p => p.count));

    const xScale = d3.scaleTime().domain(d3.extent(allDates)).range([0, width]);
    const yScale = d3.scaleLinear().domain([0, d3.max(allCounts)]).range([height, 0]);

    svg.append('g').attr('transform', `translate(0,${height})`).call(d3.axisBottom(xScale).ticks(5));
    svg.append('g').call(d3.axisLeft(yScale).ticks(5));

    const line = d3.line()
      .x(d => xScale(new Date(d.date)))
      .y(d => yScale(d.count))
      .curve(d3.curveMonotoneX);

    trends.forEach((t, i) => {
      svg.append('path')
        .datum(t.points)
        .attr('fill', 'none')
        .attr('stroke', colors[i % colors.length])
        .attr('stroke-width', 2)
        .attr('d', line);

      svg.append('text')
        .attr('x', width + 4)
        .attr('y', yScale(t.points[t.points.length-1]?.count || 0))
        .attr('dy', '0.35em')
        .style('font-size', '10px')
        .style('fill', colors[i % colors.length])
        .text(t.skill_name.slice(0, 15));
    });

  } catch(e) { $('trendChartBody').innerHTML = errorHtml(e.message); }
}

// ── Skill Overlap Heatmap ─────────────────────────────────
async function renderOverlap() {
  const occ = state.selected; if (!occ) return;
  $('overlapBody').innerHTML = loadingHtml();
  try {
    const data = await api(`/api/jobs/overlap/${occ.id}`);
    if (!data.skills.length || !data.occupations.length) {
      $('overlapBody').innerHTML = noDataHtml('No overlap data found for related occupations.');
      return;
    }

    const cellSize = 60;
    const margin   = { top: 20, right: 20, bottom: 120, left: 180 };
    const width    = data.occupations.length * cellSize;
    const height   = data.skills.length * cellSize;

    $('overlapBody').innerHTML = `<svg id="heatmapSvg"></svg>`;

    const svg = d3.select('#heatmapSvg')
      .attr('width',  width  + margin.left + margin.right)
      .attr('height', height + margin.top  + margin.bottom)
      .append('g')
      .attr('transform', `translate(${margin.left},${margin.top})`);

    // Column labels (occupations)
    svg.selectAll('.col-label').data(data.occupations).enter()
      .append('text')
      .attr('class', 'col-label')
      .attr('x', (d,i) => i * cellSize + cellSize/2)
      .attr('y', -5)
      .attr('text-anchor', 'end')
      .attr('transform', (d,i) => `rotate(-45, ${i*cellSize+cellSize/2}, -5)`)
      .style('font-size', '11px')
      .style('fill', '#555')
      .text(d => d.length > 20 ? d.slice(0,18)+'…' : d);

    // Row labels (skills)
    svg.selectAll('.row-label').data(data.skills).enter()
      .append('text')
      .attr('class', 'row-label')
      .attr('x', -8)
      .attr('y', (d,i) => i * cellSize + cellSize/2)
      .attr('text-anchor', 'end')
      .attr('dominant-baseline', 'middle')
      .style('font-size', '11px')
      .style('fill', '#555')
      .text(d => d.length > 25 ? d.slice(0,23)+'…' : d);

    // Cells
    data.skills.forEach((skill, ri) => {
      data.occupations.forEach((occ, ci) => {
        const val = data.matrix[ri][ci];
        svg.append('rect')
          .attr('x', ci * cellSize + 2)
          .attr('y', ri * cellSize + 2)
          .attr('width',  cellSize - 4)
          .attr('height', cellSize - 4)
          .attr('rx', 4)
          .style('fill', val ? '#00897b' : '#f5f5f5')
          .style('stroke', '#e0e0e0')
          .style('stroke-width', 1)
          .on('mouseenter', function(e) {
            showTip(e, `
              <div class="tt-title">${esc(skill)}</div>
              <div class="tt-row">Occupation: <span>${esc(occ)}</span></div>
              <div class="tt-row">Shared: <span>${val ? 'Yes ✓' : 'No'}</span></div>
            `);
          })
          .on('mousemove', moveTip)
          .on('mouseleave', hideTip);

        if (val) {
          svg.append('text')
            .attr('x', ci * cellSize + cellSize/2)
            .attr('y', ri * cellSize + cellSize/2)
            .attr('text-anchor', 'middle')
            .attr('dominant-baseline', 'middle')
            .style('fill', 'white')
            .style('font-size', '16px')
            .text('✓');
        }
      });
    });

  } catch(e) { $('overlapBody').innerHTML = errorHtml(e.message); }
}

// ── Top Companies ─────────────────────────────────────────
async function renderCompanies() {
  const occ = state.selected; if (!occ) return;
  $('companyBody').innerHTML = loadingHtml();
  try {
    const companies = await api(`/api/jobs/companies/${occ.id}`);
    if (!companies.length) { $('companyBody').innerHTML = noDataHtml('No company data for this occupation.'); return; }
    const max = Math.max(...companies.map(c => c.postings));
    $('companyBody').innerHTML = `<div class="bar-list">${
      companies.map((c,i) => `
        <div class="bar-row">
          <div class="bar-rank">${i+1}</div>
          <div class="bar-label-col"><div class="bar-label">${esc(c.company)}</div></div>
          <div class="bar-track">
            <div class="bar-fill" style="background:#5c6bc0" data-pct="${(c.postings/max)*100}"></div>
          </div>
          <div class="bar-count-col">
            <span class="bar-count">${c.postings}</span>
            <span class="bar-sub">postings</span>
          </div>
        </div>`).join('')
    }</div>`;
    requestAnimationFrame(() => {
      $$('#companyBody .bar-fill').forEach((f,i) => setTimeout(() => { f.style.width = f.dataset.pct+'%'; }, i*40));
    });
  } catch(e) { $('companyBody').innerHTML = errorHtml(e.message); }
}

// ── Occupation Detail ─────────────────────────────────────
async function renderOccDetail() {
  const occ = state.selected; if (!occ) return;
  $('occDetailBody').innerHTML = loadingHtml();
  try {
    const detail = await api(`/api/occupations/${occ.id}`);
    const bcHtml = detail.breadcrumb.filter(b => b.title).map((b,i,a) => `
      <span class="bc-level">${b.level}</span>
      <span class="bc-title ${i===a.length-1?'active':''}">${esc(b.title)}</span>
      ${i<a.length-1?'<span class="bc-sep">/</span>':''}
    `).join('');
    $('occDetailBody').innerHTML = `
      <div class="occ-detail-breadcrumb">${bcHtml}</div>
      ${detail.lead_statement?`<div class="occ-detail-info"><div class="info-label">Lead Statement</div><div class="info-text">${esc(detail.lead_statement)}</div></div>`:''}
      <div style="margin-top:16px"><div class="info-label">Skill Level</div><div class="info-text">${detail.skill_level||'Not specified'}</div></div>
    `;
  } catch(e) { $('occDetailBody').innerHTML = errorHtml(e.message); }
}

// ── About Page ────────────────────────────────────────────
function renderAbout() {
  const s = state.summary;
  $('aboutBody').innerHTML = `
    <div style="padding:20px;max-width:700px">
      <div class="info-label" style="margin-bottom:16px">Data Sources</div>
      <table class="striped">
        <thead><tr><th>Source</th><th>Description</th><th>Records</th></tr></thead>
        <tbody>
          <tr><td>OSCA</td><td>Australian Standard Classification of Occupations</td><td>${s?fmt(s.total_occupations):'—'}</td></tr>
          <tr><td>ESCO</td><td>European Skills/Competences/Qualifications Framework</td><td>${s?fmt(s.total_skills):'—'}</td></tr>
          <tr><td>Job Postings</td><td>Australian job advertisements (ingested via Spring Batch)</td><td>${s?fmt(s.total_job_posts):'—'}</td></tr>
          <tr><td>AI Processed</td><td>Job postings analysed for skill extraction</td><td>${s?s.processed_job_posts:'—'}</td></tr>
          <tr><td>Skill Mappings</td><td>Occupation × Skill demand pairs</td><td>${s?fmt(s.total_skill_mappings):'—'}</td></tr>
        </tbody>
      </table>
      <div class="info-label" style="margin-top:24px;margin-bottom:12px">Technology Stack</div>
      <div class="pipeline-stats">
        <div class="pipeline-stat"><div class="p-val" style="font-size:13px">PostgreSQL + pgvector</div><div class="p-lbl">Database</div></div>
        <div class="pipeline-stat"><div class="p-val" style="font-size:13px">FastAPI + SQLAlchemy</div><div class="p-lbl">Backend</div></div>
        <div class="pipeline-stat"><div class="p-val" style="font-size:13px">D3.js + Materialize</div><div class="p-lbl">Frontend</div></div>
        <div class="pipeline-stat"><div class="p-val" style="font-size:13px">Spring Batch</div><div class="p-lbl">ETL Pipeline</div></div>
        <div class="pipeline-stat"><div class="p-val" style="font-size:13px">NumPy</div><div class="p-lbl">Trend Analysis</div></div>
      </div>
      <div class="info-label" style="margin-top:24px;margin-bottom:8px">System Signature</div>
      <div class="info-text" style="font-family:monospace">${s?s.signature:'—'} — MSIT402 CIM-10236</div>
    </div>`;
}

// ── Boot ──────────────────────────────────────────────────
async function init() {
  M.Sidenav.init(document.querySelector('.sidenav'), { edge: 'left' });
  setStatus(false, 'Connecting…');
  await loadSummary();
  await initFilters();
  initSlider();
  initSearch();
  initNav();
  await loadOccupations();
  switchPage('dashboard');
  renderKpiRow();
}

document.addEventListener('DOMContentLoaded', init);
//hot skills in last N days


async function loadHotSkills(days = 30) {
  return api(`/analytics/hot-skills?days=${days}`);
}

async function loadShadowSkills(oscaCode) {
  return api(`/analytics/shadow-skills/${oscaCode}`);
}

async function loadSkillDecay(oscaCode) {
  return api(`/analytics/skill-decay/${oscaCode}`);
}

document.querySelectorAll('.nav-link').forEach(link => {
  link.addEventListener('click', async e => {
    e.preventDefault();

    document.querySelectorAll('.nav-link').forEach(l => l.classList.remove('active'));
    link.classList.add('active');

    const page = link.dataset.page;

    if (page === 'skills') {
      renderHotSkills();
    }

    if (page === 'pipeline' && state.selected) {
      renderSkillDecay(state.selected.id);
    }
  });
});

async function renderHotSkills() {
  const area = $('chartArea');
  area.innerHTML = `<div class="loading-card fade-up"><div class="spinner"></div><span>Loading hot skills…</span></div>`;

  try {
    const skills = await loadHotSkills(30);

    area.innerHTML = '';
    area.appendChild(buildHotSkillsCard(skills));

  } catch(err) {
    area.innerHTML = `<div class="error-card fade-up">${err.message}</div>`;
  }
}

function buildHotSkillsCard(skills) {
  const max = Math.max(...skills.map(s => s.total_mentions));

  const card = document.createElement('div');
  card.className = 'card fade-up';

  card.innerHTML = `
    <div class="card-header">
      <div>
        <div class="card-title">National Hot Skills</div>
        <div class="card-sub">Top 50 skills · Last 30 days</div>
      </div>
    </div>
    <div class="bar-chart"></div>
  `;

  const wrap = card.querySelector('.bar-chart');

  skills.slice(0, 20).forEach((s, i) => {
    const pct = (s.total_mentions / max) * 100;

    const row = document.createElement('div');
    row.className = 'bar-row';
    row.innerHTML = `
      <div class="bar-rank">${i+1}</div>
      <div class="bar-label-col">
        <div class="bar-label">${esc(s.skill_name)}</div>
      </div>
      <div class="bar-track">
        <div class="bar-fill" style="width:0%;background:var(--accent)" data-pct="${pct}"></div>
      </div>
      <div class="bar-count-col">
        <span class="bar-count">${fmt(s.total_mentions)}</span>
        <span class="bar-count-sub">mentions</span>
      </div>
    `;
    wrap.appendChild(row);

    setTimeout(() => {
      row.querySelector('.bar-fill').style.width = pct + '%';
    }, i * 40 + 100);
  });

  return card;
}

//skill decay

async function renderSkillDecay(oscaCode) {
  const area = $('chartArea');
  area.innerHTML = `<div class="loading-card fade-up"><div class="spinner"></div><span>Loading skill decay…</span></div>`;

  try {
    const data = await loadSkillDecay(oscaCode);

    area.innerHTML = '';

    if (!data.length) {
      area.innerHTML = `<div class="no-data fade-up">
        <div class="no-data-icon">📉</div>
        <strong>No declining skills found</strong>
      </div>`;
      return;
    }

    area.appendChild(buildDecayCard(data));

  } catch(err) {
    area.innerHTML = `<div class="error-card fade-up">${err.message}</div>`;
  }
}

function buildDecayCard(data) {
  const max = Math.max(...data.map(s => s.decline));

  const card = document.createElement('div');
  card.className = 'card fade-up';

  card.innerHTML = `
    <div class="card-header">
      <div>
        <div class="card-title">Skill Decline</div>
        <div class="card-sub">Significant demand drop (12 months)</div>
      </div>
    </div>
    <div class="bar-chart"></div>
  `;

  const wrap = card.querySelector('.bar-chart');

  data.forEach((s, i) => {
    const pct = (s.decline / max) * 100;

    const row = document.createElement('div');
    row.className = 'bar-row';
    row.innerHTML = `
      <div class="bar-rank">${i+1}</div>
      <div class="bar-label-col">
        <div class="bar-label">${esc(s.skill_name)}</div>
      </div>
      <div class="bar-track">
        <div class="bar-fill" style="width:0%;background:var(--amber)" data-pct="${pct}"></div>
      </div>
      <div class="bar-count-col">
        <span class="bar-count">${fmt(s.decline)}</span>
        <span class="bar-count-sub">decline</span>
      </div>
    `;
    wrap.appendChild(row);

    setTimeout(() => {
      row.querySelector('.bar-fill').style.width = pct + '%';
    }, i * 40 + 100);
  });

  return card;
}