// Poll run status/log while a run is active. Uses textContent only (no HTML injection).
(function () {
  var log = document.getElementById('run-log');
  if (!log) return;
  var statusEl = document.getElementById('run-status');
  var summaryEl = document.getElementById('run-summary');
  var runId = log.getAttribute('data-run-id');
  var status = log.getAttribute('data-status');
  var after = 0;
  var done = { succeeded: 1, failed: 1, cancelled: 1, expired: 1 };
  if (status !== 'running') return;

  // Rebuild from the start so ids line up with what the server holds.
  log.textContent = '';
  function tick() {
    fetch('/runs/' + encodeURIComponent(runId) + '/status.json?after=' + after, { credentials: 'same-origin' })
      .then(function (r) {
        if (r.status === 401) { window.location.href = '/login?expired=1'; throw new Error('expired'); }
        return r.json();
      })
      .then(function (d) {
        d.lines.forEach(function (l) {
          log.textContent += l.ts + ' ' + l.level.toUpperCase() + ' ' + l.message + '\n';
          after = l.id;
        });
        statusEl.textContent = d.status;
        statusEl.className = 'badge badge-status-' + d.status;
        if (d.summary) summaryEl.textContent = d.summary;
        if (done[d.status]) { statusEl.setAttribute('role', 'status'); return; }
        setTimeout(tick, 1500);
      })
      .catch(function () { /* stop polling on error/expiry */ });
  }
  tick();
})();
