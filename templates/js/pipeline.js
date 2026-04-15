'use strict';

document.addEventListener('DOMContentLoaded', () => {
  loadPipelineLastRun();
});
/* ════════════════════════════════════════════════════
   PIPELINE LAST RUN
   Fetches /api/pipeline/last-run and shows a
   readable "xyz days ago" label in the sidebar footer.
════════════════════════════════════════════════════ */
async function loadPipelineLastRun() {
  const el = document.getElementById('pipelineLastRunText');
  if (!el) return;

  try {
    // Direct fetch (not via api() helper) to avoid redirect loops on API Keys page
    const response = await fetch('/api/pipeline/last-run', {
      credentials: 'same-origin',
      headers: { 'Content-Type': 'application/json' },
    });

    // If 401/403, user likely doesn't have admin access — hide gracefully
    if (response.status === 401 || response.status === 403) {
      el.parentElement.style.display = 'none';
      return;
    }

    if (!response.ok) {
      throw new Error(`HTTP ${response.status}`);
    }

    const d = await response.json();

    if (!d.last_run) {
      el.textContent = 'Pipeline — no runs yet';
      return;
    }

    const then  = new Date(d.last_run);
    const now   = new Date();
    const diffMs = now - then;

    const mins  = Math.floor(diffMs / 60000);
    const hours = Math.floor(diffMs / 3600000);
    const days  = Math.floor(diffMs / 86400000);

    let ago;
    if (mins  < 1)   ago = 'just now';
    else if (mins < 60)   ago = `${mins} min${mins  !== 1 ? 's' : ''} ago`;
    else if (hours < 24)  ago = `${hours} hr${hours !== 1 ? 's' : ''} ago`;
    else                  ago = `${days} day${days  !== 1 ? 's' : ''} ago`;

    // Format the actual datetime for the title tooltip
    const formatted = then.toLocaleString('en-AU', {
      day: '2-digit', month: 'short', year: 'numeric',
      hour: '2-digit', minute: '2-digit'
    });

    el.textContent = `Pipeline updated ${ago}`;
    el.parentElement.title = `Last run: ${formatted}`;

  } catch (err) {
    el.textContent = 'Pipeline — unavailable';
    console.warn('[SkillPulse] Pipeline last run failed:', err.message);
  }
}