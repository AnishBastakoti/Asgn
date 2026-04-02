'use strict';

// ── State ─────────────────────────────────────────────────────────────────────
const ct = {
  allOccs: [],
  fromId:  null,
  toId:    null,
};

// ── Boot ──────────────────────────────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', () => {
  loadOccupations();
// search filter
  document.getElementById('fromSearch')?.addEventListener('input', e => {
    renderList('fromList', e.target.value, 'from');
  });
  document.getElementById('toSearch')?.addEventListener('input', e => {
    renderList('toList', e.target.value, 'to');
  });
});

// ── Load occupations ──────────────────────────────────────────────────────────
async function loadOccupations() {
  try {
    const data = await api('/api/occupations/list');
    ct.allOccs = data || [];
    renderList('fromList', '', 'from');
    renderList('toList',   '', 'to');
  } catch (err) {
    console.warn('[CT] loadOccupations:', err.message);
  }
}

// ── Render a filtered list ────────────────────────────────────────────────────
function renderList(listId, query, side) {
  const el = document.getElementById(listId);
  const q  = query.trim().toLowerCase();

  const filtered = q
    ? ct.allOccs.filter(o => o.title.toLowerCase().includes(q))
    : ct.allOccs;

  if (!filtered.length) {
    el.innerHTML = `<div style="padding:16px; text-align:center; color:var(--muted); font-size:12px;">No matches</div>`;
    return;
  }

  el.innerHTML = filtered.slice(0, 80).map(o => {
    const activeId = side === 'from' ? ct.fromId : ct.toId;
    const isActive = o.id === activeId;
    const noSkills = !o.skill_count || o.skill_count === 0;
    return `<div class="ct-occ-item ${isActive ? 'active' : ''} ${noSkills ? 'no-skills' : ''}"
                 ${noSkills ? '' : `onclick="selectOcc(${o.id}, '${esc(o.title)}', '${side}')"`}>
      <span>${esc(o.title)}</span>
      ${noSkills
        ? `<span class="ct-occ-tag" style="color:#D1D5DB;">no skills</span>`
        : o.skill_level ? `<span class="ct-occ-tag">Lv ${o.skill_level}</span>` : ''
      }
    </div>`;
  }).join('');
}

// ── Select an occupation ──────────────────────────────────────────────────────
window.selectOcc = function(id, title, side) {
  if (side === 'from') {
    ct.fromId = id;
    const badge = document.getElementById('fromBadge');
    badge.textContent = title;
    badge.classList.add('filled');
    renderList('fromList', document.getElementById('fromSearch').value, 'from');
  } else {
    ct.toId = id;
    const badge = document.getElementById('toBadge');
    badge.textContent = title;
    badge.classList.add('filled');
    renderList('toList', document.getElementById('toSearch').value, 'to');
  }

  const btn = document.getElementById('analyzeBtn');
  btn.disabled = !(ct.fromId && ct.toId && ct.fromId !== ct.toId);
};

// ── Analyze ───────────────────────────────────────────────────────────────────
async function analyzeTransition() {
  const results = document.getElementById('ctResults');
  results.innerHTML = `<div class="ct-loading"><div class="sp-spinner-sm"></div>&nbsp;Analysing transition…</div>`;

  try {    
    const [d, sim] = await Promise.all([
      api(`/api/analytics/career-transition?from_id=${ct.fromId}&to_id=${ct.toId}`),
      api(`/api/analytics/occupation-similarity/${ct.fromId}?top_n=1`)
    ]);

    // Find similarity score for the specific target occupation
    const toMatch = sim.similar?.find(o => o.occupation_id === ct.toId);
    const cosineScore = toMatch ? toMatch.similarity_score : d.overlap_pct;

    if (d.error) {
      results.innerHTML = `<div class="ct-placeholder"><i class="bi bi-exclamation-triangle"></i><div>${esc(d.error)}</div></div>`;
      return;
    }

    results.innerHTML = `
      <!-- Header -->
      <div class="ct-results-header">
        <div class="ct-transition-label">
          <span class="ct-from-chip">${esc(d.from_title)}</span>
          <span class="ct-to-chip">${esc(d.to_title)}</span>
        </div>
        <span style="font-size:11px; color:var(--muted); font-family:var(--mono);">
          Skill Level ${d.from_skill_level ?? '?'} → ${d.to_skill_level ?? '?'}
        </span>
      </div>

      <!-- KPIs — only difficulty is coloured -->
      <div class="ct-kpi-row">
        <div class="ct-kpi">
          <div class="ct-kpi-val">${cosineScore}%</div>
          <div class="ct-kpi-lbl">Cosine Similarity</div>
        </div>
        <div class="ct-kpi">
          <div class="ct-kpi-val">${d.shared_count}</div>
          <div class="ct-kpi-lbl">Shared Skills</div>
        </div>
        <div class="ct-kpi">
          <div class="ct-kpi-val">${d.gap_count}</div>
          <div class="ct-kpi-lbl">Skills to Gain</div>
        </div>
        <div class="ct-kpi">
          <div class="ct-kpi-val" style="color:${d.difficulty_color}">${d.difficulty_label}</div>
          <div class="ct-kpi-lbl">Difficulty</div>
        </div>
      </div>

      <!-- Difficulty bar -->
      <div class="ct-difficulty-bar">
        <div class="ct-diff-label">
          <span>Transition Difficulty</span>
          <span style="font-weight:700; color:${d.difficulty_color}">${d.difficulty_score}%</span>
        </div>
        <div class="ct-diff-track">
          <div class="ct-diff-fill" style="width:${d.difficulty_score}%; background:${d.difficulty_color};"></div>
        </div>
        <div class="ct-diff-zones">
          <span>Easy</span><span>Moderate</span><span>Hard</span>
        </div>
      </div>

      <!-- Score breakdown, Hard/Moderate/Easy -->
      ${d.score_breakdown ? `
      <div style="margin-bottom:16px; padding:12px 14px; background:var(--shell-bg);
                  border:1px solid var(--border); border-radius:8px;">
        <div style="font-size:10.5px; font-weight:700; text-transform:uppercase;
                    letter-spacing:0.08em; color:var(--muted); margin-bottom:10px;">
          Score Breakdown
        </div>
        ${[
          { label: 'Skill Gap (weighted)', val: d.score_breakdown.weighted_skill_gap, w: '45%', tip: 'Missing target skills weighted by job demand frequency' },
          { label: 'Qualification Jump',   val: d.score_breakdown.level_jump,         w: '25%', tip: 'OSCA skill level difference between roles' },
          { label: 'Sector Distance',      val: d.score_breakdown.taxonomy_distance,  w: '20%', tip: 'How far apart the roles sit in the OSCA hierarchy' },
          { label: 'Skill Breadth',        val: d.score_breakdown.breadth_penalty,    w: '10%', tip: 'Target role requires significantly more skills overall' },
        ].map(f => {
          const barColor = f.val >= 65 ? '#EF4444' : f.val >= 35 ? '#F59E0B' : '#10B981';
          return `
            <div style="margin-bottom:8px;" title="${f.tip}">
              <div style="display:flex; justify-content:space-between;
                          font-size:11px; margin-bottom:3px;">
                <span style="color:var(--text2); font-weight:600;">${f.label}</span>
                <span style="display:flex; align-items:center; gap:8px;">
                  <span style="font-size:10px; color:var(--muted);">weight ${f.w}</span>
                  <span style="font-family:var(--mono); color:${barColor}; font-weight:700;">${f.val}%</span>
                </span>
              </div>
              <div style="height:5px; background:var(--border); border-radius:99px; overflow:hidden;">
                <div style="height:100%; width:${f.val}%; background:${barColor};
                            border-radius:99px; transition:width 0.6s ease;"></div>
              </div>
            </div>`;
        }).join('')}
      </div>` : ''}

      <!-- Skill columns -->
      <div class="ct-skills-grid">
        <div class="ct-skill-col">
          <div class="ct-col-head shared">
            <i class="bi bi-check-circle-fill"></i>
            Skills You Already Have (${d.shared_count})
          </div>
          ${d.shared_skills.length
            ? d.shared_skills.map(s => skillRow(s)).join('')
            : '<div style="color:var(--muted);font-size:12px;padding:8px 0;">No overlapping skills found.</div>'
          }
        </div>
        <div class="ct-skill-col">
          <div class="ct-col-head gap">
            <i class="bi bi-plus-circle-fill"></i>
            Skills You Need to Gain (${d.gap_count})
          </div>
          ${d.gap_skills.length
            ? d.gap_skills.map(s => skillRow(s)).join('')
            : '<div style="color:var(--muted);font-size:12px;padding:8px 0;">No skill gaps — perfect match!</div>'
          }
        </div>
      </div>
    `;

  } catch (err) {
    results.innerHTML = `<div class="ct-placeholder"><i class="bi bi-exclamation-triangle"></i><div>Could not load transition data.</div></div>`;
    console.warn('[CT] analyzeTransition:', err.message);
  }
}

// ── Skill row helper ──────────────────────────────────────────────────────────
function skillRow(s) {
  const raw   = s.skill_type || '';
  const label = raw.replace('http://data.europa.eu/esco/skill-type/', '') || 'unknown';
  const cls   = label.toLowerCase().replace(/[^a-z]/g, '');
  return `<div class="ct-skill-row">
    <span class="ct-skill-name">${esc(s.skill_name)}</span>
    <span class="ct-skill-type ${cls}">${esc(label)}</span>
  </div>`;
}
