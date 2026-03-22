'use strict';

window.pipelineGridApi = null;

document.addEventListener('DOMContentLoaded', () => {
  initPipelineGrid();
  loadPipeline();
});

// ── Init AG Grid ──────────────────────────────────────────────
function initPipelineGrid() {
  const el = document.getElementById('pipelineGrid');
  if (!el || typeof agGrid === 'undefined') return;

  const colDefs = [
    {
      field: 'job_execution_id',
      headerName: '#',
      width: 64,
      sortable: true,
      cellStyle: { fontFamily: 'var(--mono)', fontSize: '11px', color: 'var(--muted)' },
    },
    {
      field: 'job_name',
      headerName: 'Job',
      flex: 1,
      minWidth: 200,
      cellRenderer: p => `
        <div>
          <div style="font-weight:600;font-size:12.5px;color:var(--text)">${esc(p.value || '—')}</div>
          <div style="font-size:11px;color:var(--muted)">Instance ${p.data.job_instance_id}</div>
        </div>`,
      autoHeight: true,
    },
    {
      field: 'start_time',
      headerName: 'Started',
      width: 160,
      cellStyle: { fontFamily: 'var(--mono)', fontSize: '11.5px' },
      valueFormatter: p => p.value ? fmtDate(p.value, 'D MMM YYYY HH:mm') : '—',
    },
    {
      field: 'duration_seconds',
      headerName: 'Duration',
      width: 110,
      cellStyle: { fontFamily: 'var(--mono)', fontSize: '12px', fontWeight: 600 },
      valueFormatter: p => p.value != null ? formatDuration(p.value) : '—',
    },
    {
      field: 'status',
      headerName: 'Status',
      width: 140,
      cellRenderer: p => statusBadge(p.value),
    },
    {
      field: 'exit_message',
      headerName: 'Logs',
      width: 110,
      sortable: false,
      resizable: false,
      suppressSizeToFit: true,
      cellStyle: { overflow: 'visible', padding: '0 8px' },
      cellRenderer: p => {
        const hasError = p.value && p.value.trim().length > 0;
        if (!hasError) return '';
        const safeMsg = btoa(unescape(encodeURIComponent(p.value)));
        return `<button class="pl-logs-btn"
                        onclick="handleLogClick('${p.data.job_execution_id}','${p.data.start_time}','${safeMsg}')">
                  <i class="bi bi-file-text"></i> Logs
                </button>`;
      },
    },
  ];

  pipelineGridApi = agGrid.createGrid(el, {
    columnDefs: colDefs,
    rowData: [],
    rowHeight: 52,
    headerHeight: 38,
    defaultColDef: { resizable: true, suppressMovable: true },
    suppressCellFocus: true,
    getRowStyle: p => {
      if (p.data?.status === 'FAILED')   return { background: 'rgba(231,24,24,0.03)' };
      if (p.data?.status === 'STARTED')  return { background: 'rgba(245,158,11,0.04)' };
      if (p.data?.status === 'COMPLETED') return { background: 'rgba(62,229,170,0.03)' };
      return {};
    },
  });
}

// ── Load data ─────────────────────────────────────────────────
async function loadPipeline() {
  try {
    const data = await api('/api/pipeline/executions');
    renderStats(data);
    renderLiveBanner(data);
    if (pipelineGridApi) {
      pipelineGridApi.updateGridOptions({ rowData: data });
    }
  } catch (err) {
    const grid = document.getElementById('pipelineGrid');
    if (grid) grid.innerHTML = `<div class="pl-empty" style="color:var(--coral);">
      <i class="bi bi-exclamation-triangle me-2"></i>
      Could not load: ${esc(err.message)}
    </div>`;
    console.warn('[SkillPulse|Pipeline]', err);
  }
}

// ── Stats cards ───────────────────────────────────────────────
function renderStats(data) {
  const total      = data.length;
  const completed  = data.filter(r => r.status === 'COMPLETED').length;
  const failed     = data.filter(r => r.status === 'FAILED').length;
  const successPct = total ? Math.round((completed / total) * 100) : 0;

  const durations = data
    .filter(r => r.status === 'COMPLETED' && r.duration_seconds != null)
    .map(r => r.duration_seconds);
  const avgDur = durations.length
    ? Math.round(durations.reduce((a, b) => a + b, 0) / durations.length)
    : null;

  document.getElementById('statTotal').textContent       = total;
  document.getElementById('statSuccess').textContent     = `${successPct}%`;
  document.getElementById('statFailed').textContent      = failed;
  document.getElementById('statAvgDuration').textContent = avgDur != null ? formatDuration(avgDur) : 'N/A';
}

// ── Live banner ───────────────────────────────────────────────
function renderLiveBanner(data) {
  const running = data.find(r => r.status === 'STARTED');
  const banner  = document.getElementById('liveStatusBanner');
  if (running) {
    banner.style.display = 'block';
    document.getElementById('liveStatusText').textContent =
      `Execution #${running.job_execution_id} is currently running — started ${fmtDate(running.start_time, 'D MMM HH:mm')}`;
  } else {
    banner.style.display = 'none';
  }
}

// ── Logs handler ──────────────────────────────────────────────
function handleLogClick(execId, startTime, encodedMsg) {
  try {
    const msg = decodeURIComponent(escape(atob(encodedMsg)));
    openPlModal(execId, startTime, msg);
  } catch (e) {
    openPlModal(execId, startTime, 'Could not decode log message.');
  }
}

// ── Native modal ──────────────────────────────────────────────
function openPlModal(execId, startTime, message) {
  document.getElementById('errorModalMeta').textContent =
    `Execution #${execId}  ·  Started: ${startTime ? fmtDate(startTime, 'D MMM YYYY HH:mm') : '—'}`;
  document.getElementById('errorModalBody').textContent = message || 'No error message recorded.';
  document.getElementById('plModal').style.display         = 'flex';
  document.getElementById('plModalBackdrop').style.display = 'block';
  document.body.style.overflow = 'hidden';
}

function closePlModal() {
  document.getElementById('plModal').style.display         = 'none';
  document.getElementById('plModalBackdrop').style.display = 'none';
  document.body.style.overflow = '';
}

document.addEventListener('keydown', e => { if (e.key === 'Escape') closePlModal(); });

// ── Badge renderers ───────────────────────────────────────────
function statusBadge(status) {
  const map = {
    COMPLETED: `<span class="pl-badge pl-badge--completed"><i class="bi bi-check-circle-fill"></i> COMPLETED</span>`,
    FAILED:    `<span class="pl-badge pl-badge--failed"><i class="bi bi-x-circle-fill"></i> FAILED</span>`,
    STARTED:   `<span class="pl-badge pl-badge--running"><span class="pl-spinner-dot"></span> RUNNING</span>`,
    UNKNOWN:   `<span class="pl-badge pl-badge--unknown">UNKNOWN</span>`,
  };
  return map[status] || `<span class="pl-badge pl-badge--unknown">${esc(status)}</span>`;
}

function exitBadge(code) {
  if (!code) return `<span style="color:var(--muted);font-family:var(--mono);font-size:11px;">—</span>`;
  const map = {
    COMPLETED: `<span class="pl-badge pl-badge--completed-outline">${code}</span>`,
    FAILED:    `<span class="pl-badge pl-badge--failed-outline">${code}</span>`,
    UNKNOWN:   `<span class="pl-badge pl-badge--unknown-outline">${code}</span>`,
  };
  return map[code] || `<span class="pl-badge pl-badge--unknown-outline">${esc(code)}</span>`;
}

function formatDuration(seconds) {
  if (seconds < 60) return `${seconds}s`;
  const m = Math.floor(seconds / 60);
  const s = seconds % 60;
  return `${m}m ${s}s`;
}