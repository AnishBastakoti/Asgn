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
    const d = await api(`/api/analytics/career-transition?from_id=${ct.fromId}&to_id=${ct.toId}`);

    if (d.error) {
      results.innerHTML = `<div class="ct-placeholder"><i class="bi bi-exclamation-triangle"></i><div>${esc(d.error)}</div></div>`;
      return;
    }

    results.innerHTML = `
      <!-- Header -->
      <div class="ct-results-header">
        <div class="ct-transition-label">
          <span class="ct-from-chip">${esc(d.from_title)}</span>
          <i class="bi bi-arrow-right ct-arrow-icon"></i>
          <span class="ct-to-chip">${esc(d.to_title)}</span>
        </div>
        <span style="font-size:11px; color:var(--muted); font-family:var(--mono);">
          Skill Level ${d.from_skill_level ?? '?'} → ${d.to_skill_level ?? '?'}
        </span>
      </div>

      <!-- KPIs — only difficulty is coloured -->
      <div class="ct-kpi-row">
        <div class="ct-kpi">
          <div class="ct-kpi-val">${d.overlap_pct}%</div>
          <div class="ct-kpi-lbl">Skills Overlap</div>
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