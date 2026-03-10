'use strict';

// ── Boot ─────────────────────────────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', () => {
  loadPipeline();
});

// ── Main loader ───────────────────────────────────────────────────────────────
async function loadPipeline() {
  try {
    const data = await api('/api/pipeline/executions');
    renderStats(data);
    renderLiveBanner(data);
    renderTable(data);
  } catch (err) {
    document.getElementById('pipelineTableWrap').innerHTML = `
      <div class="text-center py-5 text-danger small">
        <i class="bi bi-exclamation-triangle me-2"></i>
        Could not load pipeline data: ${esc(err.message)}
      </div>`;
    console.warn('[SkillPulse|Pipeline]', err);
  }
}

// ── Stats cards ───────────────────────────────────────────────────────────────
function renderStats(data) {
  const total     = data.length;
  const completed = data.filter(r => r.status === 'COMPLETED').length;
  const failed    = data.filter(r => r.status === 'FAILED').length;
  const successPct = total ? Math.round((completed / total) * 100) : 0;

  // Average duration in seconds for completed runs only
  const durations = data
    .filter(r => r.status === 'COMPLETED' && r.duration_seconds != null)
    .map(r => r.duration_seconds);
  const avgDur = durations.length
    ? Math.round(durations.reduce((a, b) => a + b, 0) / durations.length)
    : null;

  document.getElementById('statTotal').textContent       = total;
  document.getElementById('statSuccess').textContent     = `${successPct}%`;
  document.getElementById('statFailed').textContent      = failed;
  document.getElementById('statAvgDuration').textContent = avgDur != null
    ? formatDuration(avgDur)
    : 'N/A';
}

// ── Live status banner ────────────────────────────────────────────────────────
function renderLiveBanner(data) {
  const running = data.find(r => r.status === 'STARTED');
  const banner  = document.getElementById('liveStatusBanner');
  if (running) {
    banner.style.display = 'block';
    document.getElementById('liveStatusText').textContent =
      `Execution #${running.job_execution_id} is currently running — started ${running.start_time}`;
  } else {
    banner.style.display = 'none';
  }
}

// ── Runs table ────────────────────────────────────────────────────────────────
function renderTable(data) {
  if (!data.length) {
    document.getElementById('pipelineTableWrap').innerHTML =
      `<div class="text-center py-5 text-muted small">No executions found.</div>`;
    return;
  }

  let html = `
    <div class="table-responsive">
      <table class="table table-hover table-sm mb-0 align-middle">
        <thead class="table-light">
          <tr>
            <th>#</th>
            <th>Job</th>
            <th>Started</th>
            <th>Duration</th>
            <th>Status</th>
            <th>Exit</th>
            <th></th>
          </tr>
        </thead>
        <tbody>`;

  data.forEach(r => {
    const statusBadge = statusBadgeHtml(r.status);
    const exitBadge   = exitBadgeHtml(r.exit_code);
    const duration    = r.duration_seconds != null ? formatDuration(r.duration_seconds) : '—';
    const hasError    = r.exit_message && r.exit_message.trim().length > 0;

    html += `
      <tr>
        <td class="text-muted" style="font-family:var(--mono); font-size:11px;">${r.job_execution_id}</td>
        <td>
          <div class="fw-semibold text-dark small">${esc(r.job_name || '—')}</div>
          <div class="text-muted" style="font-size:11px;">Instance ${r.job_instance_id}</div>
        </td>
        <td class="small text-muted">${r.start_time ? r.start_time.replace('T', ' ').slice(0, 19) : '—'}</td>
        <td class="small" style="font-family:var(--mono);">${duration}</td>
        <td>${statusBadge}</td>
        <td>${exitBadge}</td>
        <td>
          ${hasError
            ? `<button class="btn btn-sm btn-outline-danger py-0 px-2"
                       style="font-size:11px;"
                       onclick='showError(${r.job_execution_id}, ${JSON.stringify(r.start_time)}, ${JSON.stringify(r.exit_message)})'>
                 <i class="bi bi-file-text me-1"></i>Logs
               </button>`
            : ''}
        </td>
      </tr>`;
  });

  html += `</tbody></table></div>`;
  document.getElementById('pipelineTableWrap').innerHTML = html;
}

// ── Error modal ───────────────────────────────────────────────────────────────
function showError(execId, startTime, message) {
  document.getElementById('errorModalMeta').textContent =
    `Execution #${execId}  ·  Started: ${startTime ? startTime.replace('T', ' ').slice(0, 19) : '—'}`;
  document.getElementById('errorModalBody').textContent = message || 'No error message recorded.';

  const modal = new bootstrap.Modal(document.getElementById('errorModal'));
  modal.show();
}

// ── Helpers ───────────────────────────────────────────────────────────────────
function statusBadgeHtml(status) {
  const map = {
    'COMPLETED': `<span class="badge bg-success">COMPLETED</span>`,
    'FAILED':    `<span class="badge bg-danger">FAILED</span>`,
    'STARTED':   `<span class="badge bg-warning text-dark">
                    <span class="spinner-grow spinner-grow-sm me-1" style="width:.5rem;height:.5rem;"></span>
                    RUNNING
                  </span>`,
    'UNKNOWN':   `<span class="badge bg-secondary">UNKNOWN</span>`,
  };
  return map[status] || `<span class="badge bg-secondary">${esc(status)}</span>`;
}

function exitBadgeHtml(code) {
  if (!code) return '—';
  const map = {
    'COMPLETED': `<span class="badge bg-success-subtle text-success border border-success-subtle">${code}</span>`,
    'FAILED':    `<span class="badge bg-danger-subtle text-danger border border-danger-subtle">${code}</span>`,
    'UNKNOWN':   `<span class="badge bg-secondary-subtle text-secondary border">${code}</span>`,
  };
  return map[code] || `<span class="badge bg-secondary-subtle text-secondary border">${esc(code)}</span>`;
}

function formatDuration(seconds) {
  if (seconds < 60) return `${seconds}s`;
  const m = Math.floor(seconds / 60);
  const s = seconds % 60;
  return `${m}m ${s}s`;
}