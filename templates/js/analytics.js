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

// ── Called by dashboard.js when occupation is clicked ────────────────────────
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
// 1. Ensure selectOccupation triggers the forecast
window.selectOccupation = function(el) {
  const id    = parseInt(el.dataset.id, 10);
  const title = el.dataset.title;
  const level = el.dataset.level;

  an.selected = { id, title, level };

  document.getElementById('anWelcome').style.display = 'none';
  document.getElementById('anPanels').style.display  = 'flex';
  document.getElementById('anOccName').textContent   = title;
  document.getElementById('anOccLevel').textContent  = level ? `Level ${level}` : 'Level —';

  loadShadowSkills(id);
  loadSkillDecay(id);
  updateForecast(id); // <--- Add this line to trigger the chart
};

// 2. Optimized Forecast Loader
async function updateForecast(occupationId) {
    const canvas = document.getElementById('forecastChart');
    if (!canvas) return; // Safety check
    const ctx = canvas.getContext('2d');
    
    try {
        const response = await fetch(`/api/analytics/predict-demand-by-occ/${occupationId}`);
        if (!response.ok) throw new Error("Forecast data unavailable");
        const data = await response.json();

        if (forecastChartInstance) {
            forecastChartInstance.destroy(); // Prevents memory leaks
        }

        // Render the Predicted vs Actual Demand
        forecastChartInstance = new Chart(ctx, {
            type: 'line', 
            data: {
                labels: ['Current Demand', 'Predicted (30 Days)'],
                datasets: [{
                    label: 'Job Demand Trend',
                    data: [data.current_demand, data.predicted_demand],
                    borderColor: data.growth_rate >= 0 ? '#10b981' : '#ef4444',
                    backgroundColor: data.growth_rate >= 0 ? 'rgba(16, 185, 129, 0.1)' : 'rgba(239, 68, 68, 0.1)',
                    fill: true,
                    tension: 0.3,
                    pointRadius: 6,
                    pointBackgroundColor: '#fff',
                    pointBorderWidth: 2
                }]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: {
                    legend: { display: false },
                    tooltip: {
                        callbacks: {
                            label: (context) => ` Demand: ${context.raw} (${data.growth_rate}% trend)`
                        }
                    }
                },
                scales: {
                    y: { 
                        beginAtZero: true,
                        ticks: { precision: 0 }
                    },
                    x: { grid: { display: false } }
                }
            }
        });
    } catch (error) {
        console.error("[SkillPulse|AN] Forecast error:", error);
    }
}