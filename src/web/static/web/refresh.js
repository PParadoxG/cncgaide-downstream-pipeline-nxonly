// The store client: status polling, the refresh button, and the write calls.
//
// One poller feeds everybody.  It asks `api/jobs` on a slow cadence while
// nothing runs and on a fast one while a job is in flight, paints the sync
// button, and tells its hooks two things: the latest status payload (for the
// job bar and the row chips) and a change of the index digest (the moment
// the page is holding data a sync just replaced).  A sync started from a
// terminal raises both just the same, because the digest is read from the
// store.
//
// The write helpers are the only places that talk to the write endpoints; all
// carry the custom header the server demands, which a cross-origin page
// cannot set without a preflight the server never answers.

const POLL_IDLE = 5000;
const POLL_RUNNING = 2000;
const HEADER = { 'X-CNCgAIde-Write': '1' };

const LABELS = {
  idle: 'Sync stale',
  running: 'Working…',
  failed: 'Last job failed',
  disabled: 'Read-only',
};

/**
 * Wire the refresh button and start polling.
 *
 * hooks.onStatus(status)          every poll that got an answer
 * hooks.onDataChanged(runId)      the index digest differs from the one given
 * Returns { stop(), poke() } — poke() polls again right now (after a write).
 */
export function setupRefresh(button, labelElement, loadedRunId, hooks = {}) {
  let state = 'idle';
  let timer = null;
  let knownRunId = loadedRunId;
  let stopped = false;

  function paint(next, title) {
    state = next;
    button.dataset.state = next;
    labelElement.textContent = LABELS[next];
    button.disabled = next === 'running' || next === 'disabled';
    button.title = title || '';
  }

  async function poll() {
    if (stopped) return;
    let status;
    try {
      status = await fetch('api/jobs', { cache: 'no-store' }).then((r) => r.json());
    } catch {
      // The server going away is not worth shouting about; keep the last state.
      schedule();
      return;
    }

    if (status.state === 'disabled') {
      paint('disabled', 'started with --no-write-api');
      if (hooks.onStatus) hooks.onStatus(status);
      return; // nothing will ever change; stop polling
    }

    const log = status.log || [];
    if (status.state === 'running') {
      const current = status.current || {};
      paint('running', describeJob(current) + (log.length ? '\n' + log.slice(-1)[0] : ''));
    } else if (status.exitCode !== null && status.exitCode !== undefined && status.exitCode !== 0) {
      paint('failed', log.slice(-6).join('\n') || 'see the terminal');
    } else {
      paint('idle', 'sync the store with the input directory: stale parts only');
    }

    if (hooks.onStatus) hooks.onStatus(status);

    if (status.indexDigest && status.indexDigest !== knownRunId) {
      knownRunId = status.indexDigest;
      if (hooks.onDataChanged) {
        try { await hooks.onDataChanged(status.indexDigest); } catch (error) { console.error(error); }
      }
    }
    schedule();
  }

  function schedule() {
    clearTimeout(timer);
    if (stopped) return;
    timer = setTimeout(poll, state === 'running' ? POLL_RUNNING : POLL_IDLE);
  }

  button.addEventListener('click', async () => {
    if (state === 'running' || state === 'disabled') return;
    paint('running', 'queueing');
    try {
      await postRefresh({ mode: 'stale' });
    } catch (error) {
      paint('failed', error.message);
    }
    clearTimeout(timer);
    timer = setTimeout(poll, 300);
  });

  poll();
  return {
    stop() { stopped = true; clearTimeout(timer); },
    poke() { clearTimeout(timer); timer = setTimeout(poll, 300); },
  };
}

export function describeJob(job) {
  if (!job || !job.kind) return '';
  const args = job.arguments || {};
  if (job.kind === 'remove') {
    return `removing ${args.partId}${args.deleteSource ? ' (and its STEP)' : ''}`;
  }
  const only = args.parts || [];
  if (only.length === 1) return `syncing ${only[0]}`;
  if (only.length > 1) return `syncing ${only.length} parts`;
  return args.all ? 'syncing all parts' : 'syncing stale parts';
}

// ------------------------------------------------------------------ writes

async function expectOk(response, okStatuses = [200, 202]) {
  if (okStatuses.includes(response.status)) return response.json();
  const detail = await response.json().catch(() => ({}));
  throw new Error(detail.error || `HTTP ${response.status}`);
}

/** POST api/sync for {mode, only}: mode "all" rebuilds, `only` narrows to
 *  those part ids.  Resolves to the job payload. */
export function postRefresh(body) {
  const { mode, only } = body || {};
  return fetch('api/sync', {
    method: 'POST',
    headers: { ...HEADER, 'Content-Type': 'application/json' },
    body: JSON.stringify({ parts: only || [], all: mode === 'all' }),
  }).then(expectOk);
}

/** Upload one STEP file as a raw body. Resolves to {partId, file, plan}. */
export function uploadStep(file, name, overwrite) {
  const url = `api/upload?name=${encodeURIComponent(name)}${overwrite ? '&overwrite=1' : ''}`;
  return fetch(url, { method: 'POST', headers: HEADER, body: file }).then((response) => {
    if (response.status === 409) {
      return response.json().then((detail) => { throw Object.assign(new Error(detail.error), { conflict: true }); });
    }
    return expectOk(response);
  });
}

/** POST api/remove; source=true also deletes the STEP file. */
export function deletePart(partId, source) {
  return fetch('api/remove', {
    method: 'POST',
    headers: { ...HEADER, 'Content-Type': 'application/json' },
    body: JSON.stringify({ partId, deleteSource: Boolean(source) }),
  }).then(expectOk);
}

// The index row's `status` -> what the part's own build says, when the light
// has nothing to report.  `current` is the rule and stays quiet.
const BUILD = {
  current: 'PASS',
  error: 'FAIL',
  blocked: 'NOT_BUILT',
  facts: 'NOT_BUILT',
};

/**
 * One `api/index` row as the store state the list reads: the light, the
 * derived-key comparison, the job touching the part, and the part's own
 * build outcome.
 */
export function storeRow(row) {
  const status = BUILD[row.status] || null;
  return {
    partId: row.partId,
    light: { state: row.light || 'fresh', reasons: [] },
    rulesChanged: row.rulesChanged || [],
    job: row.job || null,
    status: row.status || null,
    error: status === 'FAIL' ? (row.detail || null) : null,
    fingerprint: row.sourceSha256 || null,
    producedAt: row.updatedAt || null,
    build: status ? {
      status,
      reason: row.status === 'facts' ? 'facts loaded; the rules have not run' : (row.detail || null),
      producedAt: row.updatedAt || null,
    } : null,
  };
}

/** GET api/index — every part with live freshness, or null if unreachable. */
export async function fetchParts() {
  try {
    const response = await fetch('api/index', { cache: 'no-store' });
    if (!response.ok) return null;
    const payload = await response.json();
    return Array.isArray(payload.parts) ? payload.parts.map(storeRow) : null;
  } catch {
    return null;
  }
}

/**
 * A file name the upload endpoint accepts: letters, digits, `_ . -` and a
 * .step/.stp extension.  Anything else (spaces above all — the local corpus
 * has several) becomes an underscore, so the part id stays readable.
 */
export function safeStepName(name) {
  const dot = name.lastIndexOf('.');
  const stem = (dot > 0 ? name.slice(0, dot) : name)
    .replace(/[^A-Za-z0-9_.-]+/g, '_')
    .replace(/^[_.]+|_+$/g, '');
  let ext = dot > 0 ? name.slice(dot + 1).toLowerCase() : '';
  if (ext !== 'step' && ext !== 'stp') ext = 'step';
  return `${stem || 'part'}.${ext}`;
}
