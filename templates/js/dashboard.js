'use strict';

// ── Dashboard state ──
const state = {
  occupations: [],
  filtered: [],
  selected: null,
  topN: 20,
  searchIndex: [] // for quick search
};

// ── DOM Ready ──
document.addEventListener('DOMContentLoaded', () => {
  initDashboard();
});

// ── Initialize dashboard ──
async function initDashboard() {
  if (!document.getElementById('chartPanel')) return;
  await loadKpiCards();
  await loadMajorGroups();
  await loadOccupations();

  // Event listeners
  $('topNSlider')?.addEventListener('input', e => {
    state.topN = +e.target.value;
    $('topNVal').textContent = state.topN;
    if (state.selected) renderDashboard();
  });


  $('filterMajor')?.addEventListener('change', async e => {
    await loadSubMajorGroups(e.target.value);
    await loadOccupations(); // reload occupations to apply new filters
    filterAndRender($('occSearch')?.value || '');
  });

  $('filterSubMajor')?.addEventListener('change', async e => {
    await loadMinorGroups(e.target.value);
    await loadOccupations(); // reload occupations to apply new filters
    filterAndRender($('occSearch')?.value || '');
  });

  $('filterMinor')?.addEventListener('change', async() => {
    await loadOccupations(); // reload occupations to apply new filters
    filterAndRender($('occSearch')?.value || '');
  });

  let searchTimeout;
  $('occSearch')?.addEventListener('input', e => {
    clearTimeout(searchTimeout);
    searchTimeout = setTimeout(() => {
      filterAndRender(e.target.value);
    }, 200); // Wait 200ms after user stops typing
  });
}

// ── Quick search helper ──
window.quickSearch = q => {
  const input = $('occSearch');
  if (input) {
    input.value = q;
    filterAndRender(q); // Call directly for instant result
  }
};
// ── Load KPI cards ──
async function loadKpiCards() {
  try {
    const d = await api('/api/skills/summary');
    $('kpiOccupations') && ($('kpiOccupations').textContent = fmt(d.total_occupations));
    $('kpiSkills') && ($('kpiSkills').textContent = fmt(d.total_skills));
    $('kpiJobs') && ($('kpiJobs').textContent = fmt(d.total_job_posts));
    $('kpiMappings') && ($('kpiMappings').textContent = fmt(d.total_skill_mappings));
  } catch (err) {
    console.warn('Failed to load KPI cards:', err.message);
  }
}

// ── Load hierarchy selects ──
async function loadMajorGroups() {
  try {
    const groups = await api('/api/occupations/major-groups');
    const sel = $('filterMajor');
    groups.forEach(g => {
      const o = document.createElement('option');
      o.value = g.id;
      o.textContent = g.title + (g.occupation_count ? ` (${g.occupation_count})` : '');
      sel.appendChild(o);
    });
  } catch (err) {
    console.warn('Failed to load major groups:', err.message);
  }
}

async function loadSubMajorGroups(majorId) {
  const sel = $('filterSubMajor');
  sel.innerHTML = '<option value="">All Sub-Major Groups</option>';
  const minorSel = $('filterMinor');
  minorSel.innerHTML = '<option value="">All Minor Groups</option>';
  minorSel.disabled = true;

  if (!majorId) { sel.disabled = true; return; }

  try {
    const groups = await api(`/api/occupations/sub-major-groups?major_group_id=${majorId}`);
    groups.forEach(g => {
      const o = document.createElement('option');
      o.value = g.id;
      o.textContent = g.title;
      sel.appendChild(o);
    });
    sel.disabled = false;
  } catch (err) {
    console.warn('Failed to load sub-major groups:', err.message);
  }
}

async function loadMinorGroups(subMajorId) {
  const sel = $('filterMinor');
  sel.innerHTML = '<option value="">All Minor Groups</option>';
  if (!subMajorId) { sel.disabled = true; return; }

  try {
    const groups = await api(`/api/occupations/minor-groups?sub_major_group_id=${subMajorId}`);
    groups.forEach(g => {
      const o = document.createElement('option');
      o.value = g.id;
      o.textContent = g.title;
      sel.appendChild(o);
    });
    sel.disabled = false;
  } catch (err) {
    console.warn('Failed to load minor groups:', err.message);
  }
}

// ── Load occupations ──
async function loadOccupations() {
  // console.log('[loadOccupations called]');
  const list = $('occList');
  // console.log('[occList]', list);
  if (!list) return;
  list.innerHTML = '<div class="sp-spinner-center"><div class="sp-spinner"></div></div>';

  // ── Read current filter values ──
  const majorId    = $('filterMajor')?.value    || '';
  const subMajorId = $('filterSubMajor')?.value || '';
  const minorId    = $('filterMinor')?.value    || '';

  const params = new URLSearchParams();
  if (minorId)         params.set('minor_group_id',     minorId);
  else if (subMajorId) params.set('sub_major_group_id', subMajorId);
  else if (majorId)    params.set('major_group_id',     majorId);
  
  const url = '/api/occupations/list' + (params.toString() ? '?' + params.toString() : '');

  try {
    const occs = await api(url);
    state.occupations = occs;
    
    // Create the Index
    state.searchIndex = occs.map(o => ({
      id: String(o.id),
      title: (o.title || "").toLowerCase(),
      skillIds: o.skill_ids || [], // In case it's missing
      altTitles: o.alt_titles || [], // Include alternative titles
      original: o // Keep reference to original object
    }));

    state.filtered = occs;
    renderOccList(occs.slice(0, 20)); //Limit initial render
  } catch (err) {
    list.innerHTML = '<div class="sp-occ-empty">Failed to load</div>';
    console.warn('Failed to load occupations:', err.message);
  }
}
// ── Filter occupations ──
function filterAndRender(search) {
  const query = search.trim().toLowerCase();
  let results = state.searchIndex;

  if (query.length > 0) {
    results = results.filter(item => {

      const matchTitle = item.title.includes(query);

      const matchOccId = item.id.includes(query);

      const matchSkillId = (item.skillIds || []).some(
        sid => String(sid).includes(query)
      );
      const matchAltTitle = (item.altTitles || []).some(
        alt => alt.toLowerCase().includes(query)
      );

      return matchTitle || matchOccId || matchSkillId || matchAltTitle;
    });
  }

  state.filtered = results.map(r => r.original);

  if (state.filtered.length === 0) {
    $('occList').innerHTML =
      '<div class="sp-occ-empty">No occupations found</div>';
    return;
  }

  renderOccList(state.filtered.slice(0, 50));
}

// ── Render occupation list ──
function renderOccList(occs) {
  const list = $('occList');
  
  if (!list) return;

  if (!occs.length) {
    list.innerHTML = '<div class="sp-occ-empty">No occupations found</div>';
    return;
  }

  list.innerHTML = occs.map(o =>
    `<div class="sp-occ-item${o.has_data?'':' no-data'}${state.selected && state.selected.id===o.id?' active':''}" 
          data-id="${o.id}" data-title="${esc(o.title)}" data-level="${o.skill_level||'--'}" data-skills="${o.skill_count}">
      <div class="sp-occ-name">${esc(o.title)}</div>
      
      <div class="sp-occ-meta">
        <span class="sp-occ-tag${o.has_data?' has-data':''}">${o.skill_count} skills</span>
        ${o.skill_level ? `<span class="sp-occ-tag">Lv ${o.skill_level}</span>` : ''}
      </div>
    </div>`).join('');

  list.querySelectorAll('.sp-occ-item').forEach(el => {
    el.addEventListener('click', () => {
      state.selected = {
        id: +el.dataset.id,
        title: el.dataset.title,
        level: el.dataset.level,
        skills: +el.dataset.skills
      };
      //highlight active class
      list.querySelectorAll('.sp-occ-item').forEach(e => e.classList.remove('active'));
      el.classList.add('active');

      if (document.getElementById('chartPanel')) {
          renderDashboard();    // dashboard page
      } else if (document.getElementById('jtChartContent')) {
          selectOccupation(el); // skills/jobs page
      } else if (document.getElementById('anPanels')) {
          selectOccupation(el);    // analytics page
      }

    });
  });
}


// ── Render dashboard charts ──
async function renderDashboard() {
  const occ = state.selected;
  if (!occ) return;

  const panel = $('chartPanel');
  if (!panel) return;

  panel.innerHTML = `<div class="sp-panel-loading"><div class="sp-spinner"></div>
                     <span>Loading <strong>${esc(occ.title)}</strong></span></div>`;

  try {
    const [skills, breakdown] = await Promise.all([
      api(`/api/skills/top/${occ.id}?limit=${state.topN}`),
      api(`/api/skills/breakdown/${occ.id}`)
    ]);

    panel.innerHTML = '';
    panel.appendChild(buildHeader(occ, skills.length));

    if (!skills.length) {
      const nd = document.createElement('div');
      nd.className = 'sp-no-data';
      nd.innerHTML = `<div class="sp-no-data-icon">&#128269;</div>
                      <strong>No skill data yet</strong>
                      <span>This occupation has not been processed by the pipeline yet.</span>`;
      panel.appendChild(nd);
      return;
    }
    if (breakdown?.breakdown?.length) panel.appendChild(buildBreakdown(breakdown));
    panel.appendChild(buildBarChart(skills));

  } catch (err) {
    panel.innerHTML = `<div class="sp-error-bar">${esc(err.message)}</div>`;
  }
}
// ── Load occupation info card ──
async function loadOccupationInfo(occId) {
  //console.log('[loadOccupationInfo] occId:', occId); // debug
  if (!occId || isNaN(occId)) return;

  const backdropEl = document.getElementById('occModalBackdrop');
  const modalEl = document.getElementById('occDetailModal');
  const body    = $('occModalBody');
  const title   = $('occModalTitle');

  if (!modalEl || !backdropEl) { 
    console.error('Modal elements not found!'); 
    return; 
  }

  body.innerHTML = `<div class="sp-spinner-center"><div class="sp-spinner"></div></div>`;
  modalEl.style.display  = 'block';
  backdropEl.style.display = 'block';
  // close on backdrop click
  modalEl.onclick = (e) => {
    if (e.target === modalEl) modalEl.style.display = 'none';
  };

  try {
    const d = await api(`/api/occupations/${occId}`);
    title.textContent = d.title;

    let html = ``;

    // Skill level badge
    if (d.skill_level) {
      html += `<span class="badge mb-3" style="background:var(--orange)">Skill Level ${d.skill_level}</span>`;
    }

    // Lead statement
    if (d.lead_statement) {
      html += `<p class="text-muted" style="font-size:13px;">${esc(d.lead_statement)}</p>`;
    }

    // Info rows
    const fields = [
      { label: 'NEC Category',     value: d.nec_category },
      { label: 'Licensing',        value: d.licensing },
      { label: 'Caveats',          value: d.caveats },
      { label: 'Skill Attributes', value: d.skill_attributes },
    ];

    fields.forEach(f => {
      if (!f.value) return;
      html += `
        <div class="mb-2 p-2 rounded" style="background:#f8f9fa; font-size:12.5px;">
          <div class="fw-semibold text-dark mb-1">${esc(f.label)}</div>
          <div class="text-muted">${esc(f.value)}</div>
        </div>`;
    });

    // Main tasks
    if (d.main_tasks) {
      const tasks = d.main_tasks.split(';').map(t => t.trim()).filter(Boolean);
      html += `
        <div class="mt-3">
          <div class="fw-semibold text-dark mb-2" style="font-size:12.5px;">
            <i class="bi bi-list-check me-1" style="color:var(--orange)"></i>MAIN TASKS
          </div>
          <ul class="ps-3 text-muted" style="font-size:12.5px;">
            ${tasks.map(t => `<li class="mb-1">${esc(t)}</li>`).join('')}
          </ul>
        </div>`;
    }

    // Specialisations
    if (d.specialisations) {
      html += `
        <div class="mt-3 p-2 rounded border" style="font-size:12.5px;">
          <div class="fw-semibold text-dark mb-1">SPECIALISATIONS</div>
          <div class="text-muted">${esc(d.specialisations)}</div>
        </div>`;
    }

    body.innerHTML = html;

  } catch (err) {
    body.innerHTML = `<div class="text-muted small">
      <i class="bi bi-exclamation-triangle me-1"></i>Could not load details.
    </div>`;
  }
}

// ── Header builder ──
function buildHeader(occ, count) {
  const d = document.createElement('div');
  d.className = 'sp-chart-header fade-up';
  d.innerHTML = `<div>
      <div class="sp-chart-title">${esc(occ.title)}</div>
      <div class="sp-chart-sub">Top ${count} skills by demand</div>
    </div>
    <div class="sp-chart-badges">
      <span class="sp-cbadge sp-cbadge--orange">${count} skills</span>
      <span class="sp-cbadge">${occ.level !== '--' ? 'Level ' + occ.level : 'Level N/A'}</span>
      <button onclick="loadOccupationInfo(${occ.id})"
          class="info">
        <i class="bi bi-info-circle me-1"></i>Info
      </button>
    </div>`;
  return d;
}

// ── Bar chart builder ──
function buildBarChart(skills) {
  const max = Math.max(...skills.map(s => s.mention_count));
  const colors = { knowledge:'var(--violet)', 'skill/competence':'var(--orange)', attitude:'#F59E0B' };

  // ── Column size control ──────────────────
  const COL = {
    rank:    { width: '28px',  flexShrink: '0' },  // rank number
    label:   { width: '50%', flexShrink: '0' },    // skill name + tag
    bar:     { flex: '1',      minWidth: '120px', maxWidth: '400px' },   // bar track
    count:   { width: '70px',  flexShrink: '0',  textAlign: 'right' },  // mentions
  };
  // ─────────────────────────────────────────────────────────────────────

  function tc(t) {
    if (!t) return '';
    if (t.includes('knowledge')) return 'knowledge';
    if (t.includes('skill')) return 'skill';
    if (t.includes('attitude')) return 'attitude';
    return '';
  }

  const wrap = document.createElement('div');
  wrap.className = 'sp-bars-wrap';
  wrap.innerHTML = `<div class="sp-legend mb-3">
      <div class="sp-legend-item"><div class="sp-legend-dot" style="background:var(--violet)"></div>Knowledge</div>
      <div class="sp-legend-item"><div class="sp-legend-dot" style="background:var(--orange)"></div>Skill</div>
      <div class="sp-legend-item"><div class="sp-legend-dot" style="background:#F59E0B"></div>Attitude</div>
    </div>`;

  skills.forEach((s, i) => {
    const pct   = (s.mention_count / max) * 100;
    const t     = tc(s.skill_type || '');
    const color = colors[s.skill_type] || 'var(--muted)';

    // clickable for concept_uri of ESCO_SKIL
    const nameHtml = s.concept_uri
      ? `<span class="sp-skill-name-wrap">
          <a href="${s.concept_uri}"
              target="_blank"
              rel="noopener noreferrer"
              class="sp-esco-name-link"
              title="View on ESCO: ${esc(s.skill_name)}"
              onclick="event.stopPropagation()">
            ${esc(s.skill_name)}
          </a>
          <a href="${s.concept_uri}"
              target="_blank"
              rel="noopener noreferrer"
              class="sp-esco-link"
              title="View on ESCO: ${esc(s.skill_name)}"
              onclick="event.stopPropagation()">
            <i class="bi bi-box-arrow-up-right"></i>
          </a>
        </span>`
      : `<span class="sp-skill-name-wrap">${esc(s.skill_name)}</span>`;

    const row = document.createElement('div');
    row.className = 'sp-bar-row';
    row.style.animationDelay = `${i * 0.022}s`;

    // used nameHtml for clickable
    row.innerHTML = `
      <!-- Rank -->
      <div style="width:${COL.rank.width}; flex-shrink:${COL.rank.flexShrink};
                  font-size:11px; color:var(--muted); font-weight:600;
                  display:flex; align-items:center;">
        ${i + 1}
      </div>

      <!-- Skill Name + Tag -->
      <div style="width:${COL.label.width}; flex-shrink:${COL.label.flexShrink};
                  overflow:hidden; display:flex; align-items:center; gap:6px;">
        <div style="white-space:nowrap; overflow:hidden; text-overflow:ellipsis;
                    font-size:13px; font-weight:500; color:var(--text);">
          ${nameHtml}
          ${t ? `<span class="sp-skill-tag sp-skill-tag--${t}">${t}</span>` : ''}
        </div>
      </div>

      <!-- Bar Track -->
      <div style="flex:${COL.bar.flex}; min-width:${COL.bar.minWidth};
                  max-width:${COL.bar.maxWidth}; display:flex; align-items:center; padding:0 12px;">
        <div style="width:100%; height:8px; background:var(--shell-bg);
                    border-radius:99px; overflow:hidden; border:1px solid var(--border);">
          <div class="sp-bar-fill" style="width:0%; height:100%;
               background:${color}; border-radius:99px; transition:width 0.6s ease;"></div>
        </div>
      </div>

      <!-- Mention Count -->
      <div style="width:${COL.count.width}; flex-shrink:${COL.count.flexShrink};
                  text-align:${COL.count.textAlign}; display:flex; flex-direction:column;
                  align-items:flex-end; justify-content:center;">
        <span style="font-size:13px; font-weight:700; color:var(--text);">${fmt(s.mention_count)}</span>
        <span style="font-size:10px; color:var(--muted);">mentions</span>
      </div>`;

    row.addEventListener('mouseenter', e => {
      showTip(e,
        `<div class="tt-title">${esc(s.skill_name)}</div>
         <div class="tt-row">Mentions: <span>${s.mention_count}</span></div>
         <div class="tt-row">Score: <span>${s.demand_score}</span></div>
         <div class="tt-row">Type: <span>${s.skill_type || 'N/A'}</span></div>
         ${s.first_seen ? `<div class="tt-row">First seen: <span>${s.first_seen.split('T')[0]}</span></div>` : ''}
         ${s.last_seen  ? `<div class="tt-row">Last seen: <span>${s.last_seen.split('T')[0]}</span></div>`  : ''}`
      );
    });
    row.addEventListener('mousemove', moveTip);
    row.addEventListener('mouseleave', hideTip);

    wrap.appendChild(row);
    setTimeout(() => row.querySelector('.sp-bar-fill').style.width = pct + '%', i * 22 + 60);
  });

  return wrap;
}

// ── Breakdown donut ──
function buildBreakdown(data) {
  const wrap = document.createElement('div');
  wrap.className = 'sp-breakdown-wrap fade-up';

  const types = [
    { key:'knowledge', label:'Knowledge', color:'var(--violet)' },
    { key:'skill/competence', label:'Skill', color:'var(--orange)' },
    { key:'attitude', label:'Attitude', color:'#F59E0B' }
  ];

  wrap.innerHTML = `<div class="sp-chart-title mb-3" style="font-size:.88rem">Skill Type Distribution</div>
                    <div class="sp-breakdown-grid">
                      <div class="sp-donut-wrap"><svg viewBox="0 0 100 100"></svg>
                        <div class="sp-donut-center">
                          <div class="sp-donut-num">${data.total_mentions}</div>
                          <div class="sp-donut-lbl">total</div>
                        </div>
                      </div>
                      <div class="sp-type-bars" id="spTypeBars"></div>
                    </div>`;

  requestAnimationFrame(() => {
    const svg = d3.select(wrap.querySelector('svg'));
    const pie = d3.pie().value(d => d.total_mentions || 0).sort(null);
    const arc = d3.arc().innerRadius(24).outerRadius(43);

    const mapped = types.map(t => {
      const b = data.breakdown.find(x => x.skill_type === t.key) || { total_mentions: 0, percentage: 0 };
      return Object.assign({}, t, b);
    }).filter(t => t.total_mentions > 0);

    svg.selectAll('path').data(pie(mapped)).enter()
      .append('path')
      .attr('d', arc)
      .attr('fill', d => d.data.color)
      .attr('transform', 'translate(50,50)')
      .attr('stroke', '#fff')
      .attr('stroke-width', 2);

    const barsEl = wrap.querySelector('#spTypeBars');
    data.breakdown.forEach(b => {
      const t = types.find(x => x.key === b.skill_type);
      if (!t) return;

      const row = document.createElement('div');
      row.className = 'sp-type-row';
      row.innerHTML = `<div class="sp-type-name">${t.label}</div>
        <div class="sp-type-track"><div class="sp-type-fill" style="width:0%;background:${t.color}"></div></div>
        <div class="sp-type-pct" style="color:${t.color}">${b.percentage}%</div>`;
      barsEl.appendChild(row);

      setTimeout(() => row.querySelector('.sp-type-fill').style.width = b.percentage + '%', 300);
    });
  });

  return wrap;
}