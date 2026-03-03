/* ═══════════════════════════════════════════
   SkillPulse — dashboard.js
═══════════════════════════════════════════ */

const state = { occupations:[], filtered:[], selected:null, topN:20 };

document.addEventListener('DOMContentLoaded', () => {
  loadKpiCards();
  loadMajorGroups();
  loadOccupations();

  $('topNSlider').addEventListener('input', e => {
    state.topN = +e.target.value;
    $('topNVal').textContent = state.topN;
    if (state.selected) renderDashboard();
  });
  $('occSearch').addEventListener('input', e => filterAndRender(e.target.value));
  $('filterMajor').addEventListener('change', async e => {
    await loadSubMajorGroups(e.target.value);
    filterAndRender($('occSearch').value);
  });
  $('filterSubMajor').addEventListener('change', async e => {
    await loadMinorGroups(e.target.value);
    filterAndRender($('occSearch').value);
  });
  $('filterMinor').addEventListener('change', () => filterAndRender($('occSearch').value));
});

window.quickSearch = q => {
  $('occSearch').value = q;
  filterAndRender(q);
};

async function loadKpiCards() {
  try {
    const d = await api('/api/skills/summary');
    if ($('kpiOccupations')) $('kpiOccupations').textContent = fmt(d.total_occupations);
    if ($('kpiSkills'))      $('kpiSkills').textContent      = fmt(d.total_skills);
    if ($('kpiJobs'))        $('kpiJobs').textContent        = fmt(d.total_job_posts);
    if ($('kpiMappings'))    $('kpiMappings').textContent    = fmt(d.total_skill_mappings);
  } catch(e) {}
}

async function loadMajorGroups() {
  try {
    const groups = await api('/api/occupations/major-groups');
    groups.forEach(g => {
      const o = document.createElement('option');
      o.value = g.id;
      o.textContent = g.title + (g.occupation_count ? ' (' + g.occupation_count + ')' : '');
      $('filterMajor').appendChild(o);
    });
  } catch(e) {}
}

async function loadSubMajorGroups(id) {
  const sel = $('filterSubMajor');
  sel.innerHTML = '<option value="">All Sub-Major Groups</option>';
  $('filterMinor').innerHTML = '<option value="">All Minor Groups</option>';
  $('filterMinor').disabled = true;
  if (!id) { sel.disabled = true; return; }
  try {
    const g = await api('/api/occupations/sub-major-groups?major_group_id=' + id);
    g.forEach(x => { const o = document.createElement('option'); o.value=x.id; o.textContent=x.title; sel.appendChild(o); });
    sel.disabled = false;
  } catch(e) {}
}

async function loadMinorGroups(id) {
  const sel = $('filterMinor');
  sel.innerHTML = '<option value="">All Minor Groups</option>';
  if (!id) { sel.disabled = true; return; }
  try {
    const g = await api('/api/occupations/minor-groups?sub_major_group_id=' + id);
    g.forEach(x => { const o = document.createElement('option'); o.value=x.id; o.textContent=x.title; sel.appendChild(o); });
    sel.disabled = false;
  } catch(e) {}
}

async function loadOccupations() {
  $('occList').innerHTML = '<div class="sp-spinner-center"><div class="sp-spinner"></div></div>';
  try {
    const occs = await api('/api/occupations/list?limit=500');
    state.occupations = occs;
    state.filtered = occs;
    renderOccList(occs);
  } catch(e) {
    $('occList').innerHTML = '<div class="sp-occ-empty">Failed to load</div>';
  }
}

function filterAndRender(search) {
  let occs = state.occupations;
  const minorId = $('filterMinor').value;
  if (minorId) occs = occs.filter(o => o.minor_group_id == minorId);
  if (search && search.length >= 2) {
    const q = search.toLowerCase();
    occs = occs.filter(o => o.title.toLowerCase().includes(q));
  }
  state.filtered = occs;
  renderOccList(occs);
}

function renderOccList(occs) {
  const list = $('occList');
  if (!occs.length) { list.innerHTML = '<div class="sp-occ-empty">No occupations found</div>'; return; }
  list.innerHTML = occs.map(o =>
    '<div class="sp-occ-item' + (o.has_data?'':' no-data') + (state.selected && state.selected.id===o.id?' active':'') + '"' +
    ' data-id="' + o.id + '" data-title="' + esc(o.title) + '" data-level="' + (o.skill_level||'--') + '" data-skills="' + o.skill_count + '">' +
    '<div class="sp-occ-name">' + esc(o.title) + '</div>' +
    '<div class="sp-occ-meta">' +
    '<span class="sp-occ-tag' + (o.has_data?' has-data':'') + '">' + o.skill_count + ' skills</span>' +
    (o.skill_level ? '<span class="sp-occ-tag">Lv ' + o.skill_level + '</span>' : '') +
    '</div></div>'
  ).join('');

  list.querySelectorAll('.sp-occ-item').forEach(el => {
    el.addEventListener('click', () => {
      state.selected = { id:+el.dataset.id, title:el.dataset.title, level:el.dataset.level, skills:+el.dataset.skills };
      list.querySelectorAll('.sp-occ-item').forEach(e => e.classList.remove('active'));
      el.classList.add('active');
      renderDashboard();
    });
  });
}

async function renderDashboard() {
  const occ = state.selected;
  const panel = $('chartPanel');
  panel.innerHTML = '<div class="sp-panel-loading"><div class="sp-spinner"></div><span>Loading <strong>' + esc(occ.title) + '</strong></span></div>';

  try {
    const [skills, breakdown] = await Promise.all([
      api('/api/skills/top/' + occ.id + '?limit=' + state.topN),
      api('/api/skills/breakdown/' + occ.id)
    ]);

    panel.innerHTML = '';
    panel.appendChild(buildHeader(occ, skills.length));

    if (!skills.length) {
      const nd = document.createElement('div');
      nd.className = 'sp-no-data';
      nd.innerHTML = '<div class="sp-no-data-icon">&#128269;</div><strong>No skill data yet</strong><span>This occupation has not been processed by the AI pipeline yet.</span>';
      panel.appendChild(nd);
      return;
    }

    panel.appendChild(buildBarChart(skills));
    if (breakdown && breakdown.breakdown && breakdown.breakdown.length) panel.appendChild(buildBreakdown(breakdown));
  } catch(err) {
    panel.innerHTML = '<div class="sp-error-bar">' + esc(err.message) + '</div>';
  }
}

function buildHeader(occ, count) {
  const d = document.createElement('div');
  d.className = 'sp-chart-header fade-up';
  d.innerHTML = '<div><div class="sp-chart-title">' + esc(occ.title) + '</div>' +
    '<div class="sp-chart-sub">Top ' + count + ' skills by demand</div></div>' +
    '<div class="sp-chart-badges">' +
    '<span class="sp-cbadge sp-cbadge--indigo">' + count + ' skills</span>' +
    '<span class="sp-cbadge">' + (occ.level !== '--' ? 'Level ' + occ.level : 'Level N/A') + '</span></div>';
  return d;
}

function buildBarChart(skills) {
  const max = Math.max.apply(null, skills.map(s => s.mention_count));
  const colors = { 'knowledge':'var(--emerald)', 'skill/competence':'var(--indigo)', 'attitude':'#F59E0B' };

  function tc(t) {
    if (!t) return '';
    if (t.indexOf('knowledge') >= 0) return 'knowledge';
    if (t.indexOf('skill') >= 0) return 'skill';
    if (t.indexOf('attitude') >= 0) return 'attitude';
    return '';
  }

  const wrap = document.createElement('div');
  wrap.className = 'sp-bars-wrap';
  wrap.innerHTML = '<div class="sp-legend mb-3">' +
    '<div class="sp-legend-item"><div class="sp-legend-dot" style="background:var(--emerald)"></div>Knowledge</div>' +
    '<div class="sp-legend-item"><div class="sp-legend-dot" style="background:var(--indigo)"></div>Skill</div>' +
    '<div class="sp-legend-item"><div class="sp-legend-dot" style="background:#F59E0B"></div>Attitude</div>' +
    '</div>';

  skills.forEach((s, i) => {
    const pct   = (s.mention_count / max) * 100;
    const t     = tc(s.skill_type || '');
    const color = colors[s.skill_type] || 'var(--muted)';

    const row = document.createElement('div');
    row.className = 'sp-bar-row';
    row.style.animationDelay = (i * 0.022) + 's';
    row.innerHTML =
      '<div class="sp-bar-rank">' + (i+1) + '</div>' +
      '<div class="sp-bar-label-col"><div class="sp-bar-label" title="' + esc(s.skill_name) + '">' + esc(s.skill_name) +
        (t ? '<span class="sp-skill-tag sp-skill-tag--' + t + '">' + t + '</span>' : '') +
      '</div></div>' +
      '<div class="sp-bar-track"><div class="sp-bar-fill" style="width:0%;background:' + color + '"></div></div>' +
      '<div class="sp-bar-count-col"><span class="sp-bar-count">' + fmt(s.mention_count) + '</span><span class="sp-bar-count-sub">mentions</span></div>';

    row.addEventListener('mouseenter', (function(skill){ return function(e) {
      showTip(e,
        '<div class="tt-title">' + esc(skill.skill_name) + '</div>' +
        '<div class="tt-row">Mentions: <span>' + skill.mention_count + '</span></div>' +
        '<div class="tt-row">Score: <span>' + skill.demand_score + '</span></div>' +
        '<div class="tt-row">Type: <span>' + (skill.skill_type || 'N/A') + '</span></div>' +
        (skill.first_seen ? '<div class="tt-row">First seen: <span>' + skill.first_seen.split('T')[0] + '</span></div>' : '') +
        (skill.last_seen  ? '<div class="tt-row">Last seen: <span>'  + skill.last_seen.split('T')[0]  + '</span></div>' : '')
      );
    };})(s));
    row.addEventListener('mousemove', moveTip);
    row.addEventListener('mouseleave', hideTip);
    wrap.appendChild(row);
    setTimeout(function(r){ r.querySelector('.sp-bar-fill').style.width = pct + '%'; }.bind(null, row), i * 22 + 60);
  });
  return wrap;
}

function buildBreakdown(data) {
  const wrap = document.createElement('div');
  wrap.className = 'sp-breakdown-wrap fade-up';
  const types = [
    { key:'knowledge',        label:'Knowledge', color:'var(--emerald)' },
    { key:'skill/competence', label:'Skill',     color:'var(--indigo)'  },
    { key:'attitude',         label:'Attitude',  color:'#F59E0B'        }
  ];

  wrap.innerHTML = '<div class="sp-chart-title mb-3" style="font-size:.88rem">Skill Type Distribution</div>' +
    '<div class="sp-breakdown-grid">' +
    '<div class="sp-donut-wrap"><svg viewBox="0 0 100 100"></svg>' +
    '<div class="sp-donut-center"><div class="sp-donut-num">' + data.total_mentions + '</div><div class="sp-donut-lbl">total</div></div></div>' +
    '<div class="sp-type-bars" id="spTypeBars"></div></div>';

  requestAnimationFrame(function() {
    const svg = d3.select(wrap.querySelector('svg'));
    const pie = d3.pie().value(function(d){ return d.total_mentions || 0; }).sort(null);
    const arc = d3.arc().innerRadius(24).outerRadius(43);
    const mapped = types.map(function(t) {
      const b = data.breakdown.find(function(x){ return x.skill_type === t.key; }) || { total_mentions:0, percentage:0 };
      return Object.assign({}, t, b);
    }).filter(function(t){ return t.total_mentions > 0; });

    svg.selectAll('path').data(pie(mapped)).enter().append('path')
      .attr('d', arc).attr('fill', function(d){ return d.data.color; })
      .attr('transform','translate(50,50)').attr('stroke','#fff').attr('stroke-width',2);

    const barsEl = wrap.querySelector('#spTypeBars');
    data.breakdown.forEach(function(b) {
      const t = types.find(function(x){ return x.key === b.skill_type; });
      if (!t) return;
      const row = document.createElement('div');
      row.className = 'sp-type-row';
      row.innerHTML = '<div class="sp-type-name">' + t.label + '</div>' +
        '<div class="sp-type-track"><div class="sp-type-fill" style="width:0%;background:' + t.color + '"></div></div>' +
        '<div class="sp-type-pct" style="color:' + t.color + '">' + b.percentage + '%</div>';
      barsEl.appendChild(row);
      setTimeout(function(r){ r.querySelector('.sp-type-fill').style.width = b.percentage + '%'; }.bind(null, row), 300);
    });
  });
  return wrap;
}