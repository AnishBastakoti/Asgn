'use strict';

// ── Page state ────────────────────────────────────────────────────────────────
const an = {
  selected: null
};
let forecastChartInstance = null; // Global reference to the Chart instance

// ── Boot ─────────────────────────────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', () => {
  loadOccupations();

  let searchTimeout;
  document.getElementById('occSearch')?.addEventListener('input', e => {
    clearTimeout(searchTimeout);
    searchTimeout = setTimeout(() => filterAndRender(e.target.value), 200);
  });
});

// // ── Called by dashboard.js when occupation is clicked ────────────────────────
window.selectOccupation = function(el) {
  const id    = parseInt(el.dataset.id, 10);
  const title = el.dataset.title;
  const level = el.dataset.level;

  an.selected = { id, title, level };

  // Show panels, hide welcome
  document.getElementById('anWelcome').style.display = 'none';
  document.getElementById('anPanels').style.display  = 'flex';
  document.getElementById('anOccName').textContent   = title;
  document.getElementById('anOccLevel').textContent  = level ? `Level ${level}` : 'Level —';

  loadShadowSkills(id);
  loadSkillDecay(id); 
  updateForecast(id); // Trigger the forecast chart update
  loadOccupationProfile(id); // Load the new occupation profile data
  loadSkillVelocity(id);      
  loadMarketSaturation(id);
  loadOccupationClusters(id);
  loadSimilarOccupations(id);
};

// ── Shadow Skills ─────────────────────────────────────────────────────────────
async function loadShadowSkills(occId) {
  const body = document.getElementById('shadowBody');
  const countBadge = document.getElementById('shadowCount');
  body.innerHTML = `<div class="an-loading"><div class="sp-spinner-sm"></div>&nbsp;Loading…</div>`;

  try {
    const data = await api(`/api/analytics/shadow-skills/${occId}`);

    if (!data || !data.length) {
      countBadge.textContent = '0';
      body.innerHTML = `<div class="an-empty">
        <i class="bi bi-check-circle me-2" style="color:var(--emerald)"></i>
        No shadow skills — all job post skills are officially mapped.
      </div>`;
      return;
    }

    countBadge.textContent = data.length;
    body.innerHTML = `<div class="d-flex flex-wrap gap-2">
        ${data.map(s => `
            <span class="badge rounded-pill border text-dark fw-normal px-3 py-2"
                style="background:var(--indigo-l); border-color:rgba(99,102,241,0.2)!important; font-size:12px;">
            ${esc(s.skill_name)}
            </span>`).join('')}
        </div>`;

  } catch (err) {
    body.innerHTML = `<div class="an-empty text-danger">
      <i class="bi bi-exclamation-triangle me-2"></i>Could not load shadow skills.
    </div>`;
    console.warn('[SkillPulse|AN] loadShadowSkills:', err.message);
  }
}

// ── Skill Decay ───────────────────────────────────────────────────────────────
async function loadSkillDecay(occId) {
  const body = document.getElementById('decayBody');
  const countBadge = document.getElementById('decayCount');
  body.innerHTML = `<div class="an-loading"><div class="sp-spinner-sm"></div>&nbsp;Loading…</div>`;

  try {
    const data = await api(`/api/analytics/skill-decay/${occId}`);

    if (!data || !data.length) {
      countBadge.textContent = '0';
      body.innerHTML = `<div class="an-empty">
        <i class="bi bi-check-circle me-2" style="color:var(--emerald)"></i>
        No decaying skills detected for this occupation.
      </div>`;
      return;
    }

    countBadge.textContent = data.length;

    let html = `<table class="table table-hover table-sm mb-0">
  <thead class="table-light">
    <tr>
      <th>Skill</th>
      <th>Past</th>
      <th>Current</th>
      <th>Drop</th>
      <th>Decline</th>
    </tr>
  </thead><tbody>`;

data.forEach(s => {
  html += `<tr>
    <td class="fw-semibold">${esc(s.skill_name)}</td>
    <td class="text-muted">${s.past_mentions}</td>
    <td class="text-muted">${s.current_mentions}</td>
    <td style="width:120px;">
      <div class="progress" style="height:6px;">
        <div class="progress-bar bg-danger" style="width:${Math.min(s.decline_pct,100)}%"></div>
      </div>
    </td>
    <td><span class="badge bg-danger-subtle text-danger border border-danger-subtle">-${s.decline_pct}%</span></td>
  </tr>`;
});
html += `</tbody></table>`;
    body.innerHTML = html;

  } catch (err) {
    body.innerHTML = `<div class="an-empty text-danger">
      <i class="bi bi-exclamation-triangle me-2"></i>Could not load decay data.
    </div>`;
    console.warn('[SkillPulse|AN] loadSkillDecay:', err.message);
  }
}

// ── Tab switching ─────────────────────────────────────────────────────────────
function switchTab(tabName) {
  // Update button states
  document.querySelectorAll('.an-tab').forEach(btn => {
    btn.classList.toggle('active', btn.dataset.tab === tabName);
  });
  // Show correct panel
  document.querySelectorAll('.an-tab-panel').forEach(panel => {
    panel.classList.toggle('active', panel.id === `tab-${tabName}`);
  });
}

// Optimized Forecast Loader
async function updateForecast(occupationId) {
    const canvas = document.getElementById('forecastChart');
    if (!canvas) return;
    const ctx = canvas.getContext('2d');

    try {
        const response = await fetch(`/api/analytics/predict-demand-by-occ/${occupationId}`);
        if (!response.ok) throw new Error("Forecast data unavailable");
        const data = await response.json();

        // ── KPI strip ──
        const growthColor = data.growth_rate >= 0 ? '#10B981' : '#EF4444';
        const el = id => document.getElementById(id);
        if (el('fcCurrentDemand'))   el('fcCurrentDemand').textContent   = fmt(data.current_demand);
        if (el('fcPredictedDemand')) el('fcPredictedDemand').textContent = fmt(data.predicted_demand);
        if (el('fcGrowthRate')) {
            el('fcGrowthRate').textContent = `${data.growth_rate > 0 ? '+' : ''}${data.growth_rate}%`;
            el('fcGrowthRate').style.color  = growthColor;
        }
        if (el('fcConfidence')) {
            el('fcConfidence').textContent = `${Math.round((data.confidence_score || 0) * 100)}%`;
        }

        // ── Model info footer ──
        const methodLabel = data.method === 'ridge_regression' ? '⚡ Ridge Regression' : '📈 Momentum Forecast';
        const r2Text      = data.r2_score != null ? `R²=${data.r2_score.toFixed(3)}` : '';
        if (el('forecastModelInfo')) {
            el('forecastModelInfo').innerHTML = `
                <span><strong>Model:</strong> ${methodLabel}</span>
                ${r2Text ? `<span><strong>Accuracy:</strong> ${r2Text}</span>` : ''}
                <span><strong>Features:</strong> demand · shadow skills · skill count · city diversity · avg mention</span>
            `;
        }

        // ── Chart ──
        if (forecastChartInstance) forecastChartInstance.destroy();

        forecastChartInstance = new Chart(ctx, {
            type: 'line',
            data: {
                labels: ['Current Demand', 'Predicted (30 Days)'],
                datasets: [{
                    label: 'Job Demand Trend',
                    data: [data.current_demand, data.predicted_demand],
                    borderColor: growthColor,
                    backgroundColor: data.growth_rate >= 0 ? 'rgba(16,185,129,0.08)' : 'rgba(239,68,68,0.08)',
                    fill: true,
                    tension: 0.3,
                    pointRadius: 6,
                    pointBackgroundColor: '#fff',
                    pointBorderWidth: 2,
                    borderWidth: 2,
                }]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: {
                    legend: { display: false },
                    tooltip: {
                        callbacks: {
                            label: ctx => ` ${ctx.raw} jobs (${data.growth_rate > 0 ? '+' : ''}${data.growth_rate}%)`
                        }
                    }
                },
                scales: {
                    y: { beginAtZero: true, ticks: { precision: 0 } },
                    x: { grid: { display: false } }
                }
            }
        });

    } catch (error) {
        console.error("[SkillPulse|AN] Forecast error:", error);
    }
}

 
// ─────────────────────────────────────────────────────────────────────────────
// SKILL VELOCITY
// ─────────────────────────────────────────────────────────────────────────────
async function loadSkillVelocity(occId) {
  const body  = document.getElementById('velocityBody');
  const badge = document.getElementById('velocitySnapshotBadge');
  body.innerHTML = `<div class="an-loading"><div class="sp-spinner-sm"></div>&nbsp;Loading…</div>`;
 
  try {
    const data = await api(`/api/analytics/skill-velocity/${occId}`);
    const snapCount = data.snapshot_count ?? 0;
 
    badge.textContent = `${snapCount} snapshot${snapCount !== 1 ? 's' : ''}`;
 
    // ── Single snapshot — show ranked stable list ──
    if (snapCount < 2) {
      const skills = data.stable ?? [];
      if (!skills.length) {
        body.innerHTML = `<div class="an-empty">
          <i class="bi bi-hourglass-split me-2"></i>
          No snapshot data yet — velocity will appear after the next pipeline run.
        </div>`;
        return;
      }
 
      body.innerHTML = `
        <div class="an-velocity-notice mb-3">
          <i class="bi bi-info-circle me-2" style="color:#6366F1"></i>
          Only <strong>1 snapshot</strong> available. Showing current skill rankings.
          Velocity arrows will appear after the next pipeline run.
        </div>
        <div class="an-vel-cols">
          <div>
            <div class="an-vel-col-head">
              <i class="bi bi-bar-chart-fill me-1" style="color:#6366F1"></i>
              Current Demand Ranking
            </div>
            ${skills.map((s, i) => `
              <div class="an-vel-row">
                <span class="an-vel-rank">${i + 1}</span>
                <span class="an-vel-name">${esc(s.skill_name)}</span>
                <span class="an-vel-count">${s.latest_count}</span>
                <span class="an-vel-badge stable">
                  <i class="bi bi-dash"></i> Stable
                </span>
              </div>`).join('')}
          </div>
        </div>`;
      return;
    }
 
    // ── Multiple snapshots — show rising / falling ──
    const rising  = data.rising  ?? [];
    const falling = data.falling ?? [];
 
    if (!rising.length && !falling.length) {
      body.innerHTML = `<div class="an-empty">
        <i class="bi bi-check-circle me-2" style="color:var(--emerald)"></i>
        All skills are stable — no significant velocity changes detected.
      </div>`;
      return;
    }
 
    const renderGroup = (skills, type) => skills.length
      ? skills.map((s, i) => `
          <div class="an-vel-row">
            <span class="an-vel-rank">${i + 1}</span>
            <span class="an-vel-name">${esc(s.skill_name)}</span>
            <span class="an-vel-count">${s.latest_count}</span>
            <span class="an-vel-badge ${type}">
              <i class="bi bi-arrow-${type === 'rising' ? 'up' : 'down'}-short"></i>
              ${type === 'rising' ? '+' : ''}${s.slope.toFixed(2)}
            </span>
          </div>`).join('')
      : `<div class="text-muted small py-2 ps-2">None detected</div>`;
 
    body.innerHTML = `
      <div class="an-vel-cols">
        <div>
          <div class="an-vel-col-head" style="color:#10B981">
            <i class="bi bi-arrow-up-circle-fill me-1"></i> Rising Skills
          </div>
          ${renderGroup(rising, 'rising')}
        </div>
        <div>
          <div class="an-vel-col-head" style="color:#EF4444">
            <i class="bi bi-arrow-down-circle-fill me-1"></i> Falling Skills
          </div>
          ${renderGroup(falling, 'falling')}
        </div>
      </div>`;
 
  } catch (err) {
    body.innerHTML = `<div class="an-empty text-danger">
      <i class="bi bi-exclamation-triangle me-2"></i>Could not load velocity data.
    </div>`;
    console.warn('[SkillPulse|AN] loadSkillVelocity:', err.message);
  }
}
 
 
// ─────────────────────────────────────────────────────────────────────────────
// MARKET SATURATION
// ─────────────────────────────────────────────────────────────────────────────
async function loadMarketSaturation(occId) {
  const body  = document.getElementById('saturationBody');
  const badge = document.getElementById('saturationStatusBadge');
  body.innerHTML = `<div class="an-loading"><div class="sp-spinner-sm"></div>&nbsp;Loading…</div>`;
 
  try {
    const d = await api(`/api/analytics/market-saturation/${occId}`);
 
    // ── Status badge colour ──
    const badgeStyle = {
      hot:       'background:#DCFCE7; color:#15803D; border:1px solid #86EFAC',
      balanced:  'background:#EFF6FF; color:#1D4ED8; border:1px solid #93C5FD',
      saturated: 'background:#FEF2F2; color:#B91C1C; border:1px solid #FCA5A5',
      no_data:   'background:#F3F4F6; color:#6B7280; border:1px solid #D1D5DB',
      error:     'background:#F3F4F6; color:#6B7280; border:1px solid #D1D5DB',
    };
    const statusIcon = {
      hot: 'bi-fire', balanced: 'bi-check2-circle',
      saturated: 'bi-exclamation-circle', no_data: 'bi-dash-circle', error: 'bi-x-circle'
    };
 
    badge.style.cssText = badgeStyle[d.status] ?? badgeStyle.no_data;
    badge.innerHTML = `<i class="bi ${statusIcon[d.status] ?? 'bi-dash'} me-1"></i>${esc(d.label)}`;
 
    if (d.status === 'no_data' || d.status === 'error') {
      body.innerHTML = `<div class="an-empty">${esc(d.insight)}</div>`;
      return;
    }
 
    // ── Gauge bar (0–2 range mapped to 0–100%) ──
    const gaugePct   = Math.min((d.saturation_score / 2) * 100, 100);
    const gaugeColor = d.status === 'hot' ? '#10B981'
                     : d.status === 'saturated' ? '#EF4444' : '#6366F1';
 
    body.innerHTML = `
      <!-- Score gauge -->
      <div class="mb-4">
        <div class="d-flex justify-content-between align-items-center mb-1">
          <span class="small fw-semibold text-muted">Saturation Score</span>
          <span class="fw-bold" style="color:${gaugeColor}; font-size:18px;">${d.saturation_score.toFixed(2)}</span>
        </div>
        <div class="an-gauge-track">
          <!-- Zone markers -->
          <div class="an-gauge-zone saturated" style="width:40%"></div>
          <div class="an-gauge-zone balanced"  style="width:20%"></div>
          <div class="an-gauge-zone hot"       style="width:40%"></div>
          <!-- Needle -->
          <div class="an-gauge-needle" style="left:${gaugePct}%; background:${gaugeColor};"></div>
        </div>
        <div class="d-flex justify-content-between" style="font-size:10px; color:#9CA3AF; margin-top:4px;">
          <span>Saturated</span><span>Balanced</span><span>Hot</span>
        </div>
      </div>
 
      <!-- Stats grid -->
      <div class="an-sat-grid mb-3">
        <div class="an-sat-stat">
          <div class="an-sat-val">${d.occ_demand}</div>
          <div class="an-sat-lbl">This Occ. Jobs</div>
        </div>
        <div class="an-sat-stat">
          <div class="an-sat-val">${Math.round(d.platform_avg_demand)}</div>
          <div class="an-sat-lbl">Platform Avg</div>
        </div>
        <div class="an-sat-stat">
          <div class="an-sat-val">${d.occ_skill_count}</div>
          <div class="an-sat-lbl">Skills Mapped</div>
        </div>
        <div class="an-sat-stat">
          <div class="an-sat-val">${Math.round(d.platform_avg_skills)}</div>
          <div class="an-sat-lbl">Avg Skills/Occ</div>
        </div>
      </div>
 
      <!-- Insight text -->
      <div class="an-insight-box">
        <i class="bi bi-lightbulb-fill me-2" style="color:#F59E0B"></i>
        ${esc(d.insight)}
      </div>`;
 
  } catch (err) {
    body.innerHTML = `<div class="an-empty text-danger">
      <i class="bi bi-exclamation-triangle me-2"></i>Could not load saturation data.
    </div>`;
    console.warn('[SkillPulse|AN] loadMarketSaturation:', err.message);
  }
}


async function loadOccupationProfile(occId) {
  const body = document.getElementById('profileBody');
  body.innerHTML = `<div class="an-loading"><div class="sp-spinner-sm"></div>&nbsp;Loading…</div>`;
 
  try {
    const d = await api(`/api/analytics/occupation-profile/${occId}`);
 
    if (d.error) {
      body.innerHTML = `<div class="an-empty text-danger">${esc(d.error)}</div>`;
      return;
    }
 
    // Skill type breakdown bar
    const total = d.total_skills || 1;
    const typeColors = {
      'skill':     '#6366F1',
      'knowledge': '#10B981',
      'attitude':  '#F59E0B',
      'unknown':   '#9CA3AF',
    };
 
    const breakdownHtml = Object.entries(d.skill_breakdown).map(([type, cnt]) => {
      const pct   = Math.round((cnt / total) * 100);
      const color = typeColors[type.toLowerCase()] || '#9CA3AF';
      const label = type.replace('http://data.europa.eu/esco/skill-type/', '');
      return `
        <div style="margin-bottom:8px;">
          <div style="display:flex; justify-content:space-between; font-size:11px; margin-bottom:3px;">
            <span style="text-transform:capitalize; font-weight:600; color:var(--text2);">${esc(label)}</span>
            <span style="font-family:var(--mono); color:var(--muted);">${cnt} (${pct}%)</span>
          </div>
          <div style="height:6px; background:var(--shell-bg); border-radius:99px; overflow:hidden; border:1px solid var(--border);">
            <div style="height:100%; width:${pct}%; background:${color}; border-radius:99px; transition:width 0.6s ease;"></div>
          </div>
        </div>`;
    }).join('');
 
    // Section helper
    const section = (icon, color, title, content) => {
      if (!content || content.trim() === '') return '';
      return `
        <div style="margin-bottom:16px; padding-bottom:16px; border-bottom:1px solid #F3F4F6;">
          <div style="font-size:11px; font-weight:700; text-transform:uppercase; letter-spacing:0.08em;
                      color:${color}; margin-bottom:6px; display:flex; align-items:center; gap:6px;">
            <i class="bi ${icon}"></i> ${title}
          </div>
          <div style="font-size:12.5px; color:var(--text2); line-height:1.7;">${esc(content)}</div>
        </div>`;
    };
 
    body.innerHTML = `
      <!-- Skill type breakdown -->
      <div style="margin-bottom:20px; padding-bottom:16px; border-bottom:1px solid #F3F4F6;">
        <div style="font-size:11px; font-weight:700; text-transform:uppercase; letter-spacing:0.08em;
                    color:var(--indigo); margin-bottom:10px; display:flex; align-items:center; gap:6px;">
          <i class="bi bi-pie-chart-fill"></i> Skill Composition (${total} total)
        </div>
        ${breakdownHtml || '<div style="color:var(--muted);font-size:12px;">No skill data.</div>'}
      </div>
 
      ${section('bi-card-text',         '#6366F1', 'Overview',         d.lead_statement)}
      ${section('bi-list-check',        '#10B981', 'Main Tasks',       d.main_tasks)}
      ${section('bi-award-fill',        '#F59E0B', 'Specialisations',  d.specialisations)}
      ${section('bi-shield-lock-fill',  '#0EA5E9', 'Licensing',        d.licensing)}
      ${section('bi-exclamation-circle','#EF4444', 'Caveats',          d.caveats)}
      ${section('bi-stars',             '#8B5CF6', 'Skill Attributes',  d.skill_attributes)}
    `;
 
  } catch (err) {
    body.innerHTML = `<div class="an-empty text-danger">
      <i class="bi bi-exclamation-triangle me-2"></i>Could not load profile data.
    </div>`;
    console.warn('[SkillPulse|AN] loadOccupationProfile:', err.message);
  }
}

// ── Cosine Similarity ─────────────────────────────────────────────────────────
async function loadSimilarOccupations(occId) {
  const badge   = document.getElementById('similarCount');
  const metaEl  = document.getElementById('similarGridMeta');
  const gridEl  = document.getElementById('similarGrid');
  if (!gridEl) return;

  gridEl.innerHTML = '<div class="an-loading"><div class="sp-spinner-sm"></div>&nbsp;Loading…</div>';

  try {
    const data = await api(`/api/analytics/occupation-similarity/${occId}`);

    if (data.error || !data.similar?.length) {
      badge.textContent = '0';
      gridEl.innerHTML = `<div class="an-empty"><i class="bi bi-info-circle me-2"></i>${data.error || 'No similar occupations found.'}</div>`;
      return;
    }

    badge.textContent = data.similar.length;
    if (metaEl) metaEl.innerHTML = `Based on <strong>${data.total_skills}</strong> mapped skills &nbsp;·&nbsp; cos(A,B) = (A·B)/(‖A‖·‖B‖)`;

    const rowData = data.similar.map((o, i) => ({
      rank:       i + 1,
      title:      o.title,
      similarity: o.similarity_score,
      occ_id:     o.occupation_id,
    }));

    const colDefs = [
      { field: 'rank',       headerName: '#',       width: 56,  sortable: false, cellStyle: { color: 'var(--muted)', fontFamily: 'var(--mono)', fontSize: '11px' } },
      { field: 'title',      headerName: 'Occupation', flex: 1, cellStyle: { fontWeight: 600, fontSize: '12.5px' } },
      {
        field: 'similarity',
        headerName: 'Similarity',
        width: 220,
        cellRenderer: p => {
          const pct   = p.value;
          const color = pct >= 75 ? 'var(--emerald)' : pct >= 50 ? 'var(--indigo)' : '#F59E0B';
          return `<div style="display:flex;align-items:center;gap:8px;">
            <div style="flex:1;height:6px;background:var(--shell-bg);border-radius:3px;overflow:hidden;border:1px solid var(--border);">
              <div style="width:${pct}%;height:100%;background:${color};border-radius:3px;"></div>
            </div>
            <span style="font-size:12px;font-weight:700;color:${color};font-family:var(--mono);min-width:38px;text-align:right">${pct}%</span>
          </div>`;
        },
      },
    ];

    gridEl.innerHTML = '';
    const grid = agGrid.createGrid(gridEl, {
      columnDefs: colDefs,
      rowData,
      rowHeight: 40,
      headerHeight: 36,
      defaultColDef: { resizable: true, suppressMovable: true },
      suppressCellFocus: true,
      onRowClicked: e => jumpToOccupation(e.data.occ_id, e.data.title),
      getRowStyle: () => ({ cursor: 'pointer' }),
    });

  } catch (err) {
    gridEl.innerHTML = `<div class="an-empty" style="color:var(--coral);"><i class="bi bi-exclamation-triangle me-2"></i>Could not load similarity data.</div>`;
    console.warn('[SkillPulse|AN] loadSimilarOccupations:', err.message);
  }
}
 
// ── K-Means Clustering ────────────────────────────────────────────────────────
async function loadOccupationClusters(occId) {
  const badge   = document.getElementById('clusterBadge');
  const metaEl  = document.getElementById('clusterGridMeta');
  const gridEl  = document.getElementById('clusterGrid');
  if (!gridEl) return;

  gridEl.innerHTML = '<div class="an-loading"><div class="sp-spinner-sm"></div>&nbsp;Clustering…</div>';

  try {
    const data = await api(`/api/analytics/occupation-clusters/${occId}`);

    if (data.error || !data.cluster_members) {
      badge.textContent = '—';
      gridEl.innerHTML = `<div class="an-empty"><i class="bi bi-info-circle me-2"></i>${data.error || 'Could not compute cluster.'}</div>`;
      return;
    }

    badge.textContent = `Cluster ${data.cluster_id + 1} of ${data.n_clusters}`;

    if (!data.cluster_members.length) {
      gridEl.innerHTML = `<div class="an-empty">This occupation is the only member of its cluster.</div>`;
      return;
    }

    if (metaEl) metaEl.innerHTML = `Cluster <strong>${data.cluster_id + 1}</strong> &nbsp;·&nbsp; <strong>${data.cluster_size}</strong> occupations &nbsp;·&nbsp; K-Means k=<strong>${data.n_clusters}</strong>`;

    const rowData = data.cluster_members.map((o, i) => ({
      rank:       i + 1,
      title:      o.title,
      similarity: o.similarity_score,
      occ_id:     o.occupation_id,
    }));

    const colDefs = [
      { field: 'rank',  headerName: '#',       width: 56,  sortable: false, cellStyle: { color: 'var(--muted)', fontFamily: 'var(--mono)', fontSize: '11px' } },
      { field: 'title', headerName: 'Occupation', flex: 1, cellStyle: { fontWeight: 600, fontSize: '12.5px' } },
      {
        field: 'similarity',
        headerName: 'Skill Match',
        width: 220,
        cellRenderer: p => {
          const pct   = p.value;
          const color = pct >= 75 ? 'var(--violet)' : pct >= 50 ? 'var(--indigo)' : 'var(--muted)';
          return `<div style="display:flex;align-items:center;gap:8px;">
            <div style="flex:1;height:6px;background:var(--shell-bg);border-radius:3px;overflow:hidden;border:1px solid var(--border);">
              <div style="width:${pct}%;height:100%;background:${color};border-radius:3px;"></div>
            </div>
            <span style="font-size:12px;font-weight:700;color:${color};font-family:var(--mono);min-width:38px;text-align:right">${pct}%</span>
          </div>`;
        },
      },
    ];

    gridEl.innerHTML = '';
    agGrid.createGrid(gridEl, {
      columnDefs: colDefs,
      rowData,
      rowHeight: 40,
      headerHeight: 36,
      defaultColDef: { resizable: true, suppressMovable: true },
      suppressCellFocus: true,
      onRowClicked: e => jumpToOccupation(e.data.occ_id, e.data.title),
      getRowStyle: () => ({ cursor: 'pointer' }),
    });

  } catch (err) {
    gridEl.innerHTML = `<div class="an-empty" style="color:var(--coral);"><i class="bi bi-exclamation-triangle me-2"></i>Could not load cluster data.</div>`;
    console.warn('[SkillPulse|AN] loadOccupationClusters:', err.message);
  }
}
// ── Jump to occupation from cluster/similarity row ────────────
function jumpToOccupation(occId, title) {
  // Clear the search box and re-render full occupation list
  const searchBox = document.getElementById('occSearch');
  if (searchBox) {
    searchBox.value = '';
    filterAndRender('');  // reset list to show all occupations
  }

  // Small delay to let the list re-render before trying to click
  setTimeout(() => {
    const items = document.querySelectorAll('.sp-occ-item');
    for (const item of items) {
      if (parseInt(item.dataset.id) === occId) {
        item.click();
        item.scrollIntoView({ behavior: 'smooth', block: 'center' });
        return;
      }
    }

    // Fallback if still not found in list
    const fakeEl = {
      dataset: { id: occId, title: title, level: '' }
    };
    window.selectOccupation(fakeEl);
  }, 100);
}