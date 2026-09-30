// Heuristic verdict panel.
//
// The list is the part's own, and it does not move: one row per heuristic
// that this part actually evaluates, one square per evaluated unit.  Picking
// a square selects and frames the geometry behind it; selecting geometry
// highlights the squares that talk about it but never changes what is on
// screen.  Narrowing to the selection is a switch the reviewer turns on, not
// something the panel does behind their back.
//
// Not-applicable verdicts are deliberately absent from the squares.  "This
// rule says nothing about this instance" is a fact about the rule's domain,
// not a result to scan for; it is counted in the header and in the store
// statistics instead.
//
// Nothing here branches on a heuristic id or a KPI id: rows, labels,
// thresholds, reasons, the KPI a rule affects and the direction it moves all
// come from the part bundle.

import { resolveSelection } from './store.js';
import { kpiArrow, kpiChip, kpiLabel } from './kpichip.js';

const SHOWN = ['FAIL', 'NOT_EVALUABLE', 'PASS'];
const CLASS = { PASS: 'pass', FAIL: 'fail', NOT_EVALUABLE: 'neval', NOT_APPLICABLE: 'na' };
// The stored vocabulary stays PASS / FAIL, but the words on screen do not
// judge: many of these rules are advisory, and not meeting one can be a
// deliberate, perfectly sound design decision.
const LABEL = {
  PASS: 'met',
  FAIL: 'not met',
  NOT_EVALUABLE: 'not evaluable',
  NOT_APPLICABLE: 'not applicable',
};
const SHORT = { PASS: 'met', FAIL: 'not met', NOT_EVALUABLE: 'n/e' };
const MAX_DETAIL_ROWS = 40;

export function createHeuristicsPanel(root, store, callbacks) {
  let model = null;
  let scrolledTo = null;
  let signature = null;

  const head = document.createElement('div');
  head.className = 'pane-head heur-head';
  const title = document.createElement('span');
  title.className = 'heur-title';
  title.textContent = 'Heuristics';
  const scope = document.createElement('span');
  scope.className = 'heur-scope';
  head.append(title, scope);

  const body = document.createElement('div');
  body.className = 'heur-body';
  root.append(head, body);

  function setModel(nextModel) {
    model = nextModel;
    scrolledTo = null;
    signature = null;
    // No part open: the verdicts of the previous one must not stay on screen
    // under the new part's name.
    if (!model) { scope.textContent = ''; body.innerHTML = ''; return; }
    render(store.get(), true);
  }

  /**
   * Re-render only when something the panel shows has actually changed.
   *
   * Every pointer move over the 3D view updates the shared hover state, and
   * rebuilding the list on each of those threw away the scroll position — the
   * panel appeared to slide around on its own while the mouse moved.
   */
  function render(state, force) {
    if (!model) return;
    const key = [
      model.partId,
      state.heuristicFocus,
      state.heuristicsFailsOnly,
      state.heuristicsPickedOnly,
      state.selection ? JSON.stringify(state.selection) : '',
    ].join('|');
    if (!force && key === signature) return;
    signature = key;

    const keepScroll = body.scrollTop;
    draw(state);
    body.scrollTop = keepScroll;
  }

  function draw(state) {
    body.innerHTML = '';

    const data = model.heuristics;
    if (!data) {
      scope.textContent = '';
      body.append(note('This part carries no verdicts. Sync to produce them.'));
      return;
    }

    const picked = pickedTargets(state, model);
    // The header names the narrowing when there is one, and stays empty
    // otherwise: the part is already named by the picker in the top bar and
    // by the details panel directly above, and a third copy of it says
    // nothing the reader did not already have.
    scope.textContent = state.heuristicsPickedOnly && picked ? picked.label : '';

    // The part's own verdicts.  Not applicable is never a verdict in the
    // store - it is counted per rule - so it arrives as a count only.
    const evaluated = data.records.filter((record) => record.outcome !== 'NOT_APPLICABLE');
    const notApplicable = Object.values(data.summary || {})
      .reduce((sum, entry) => sum + ((entry.counts || {}).NOT_APPLICABLE || 0), 0);

    let shown = evaluated;
    if (state.heuristicsPickedOnly && picked) shown = shown.filter((r) => addresses(r, picked));
    if (state.heuristicsFailsOnly) shown = shown.filter((record) => record.outcome === 'FAIL');

    body.append(controls(shown, notApplicable, state, picked));

    if (!shown.length) {
      body.append(note(emptyText(state, picked)));
      return;
    }

    const grouped = new Map();
    for (const record of shown) {
      if (!grouped.has(record.hId)) grouped.set(record.hId, []);
      grouped.get(record.hId).push(record);
    }

    // Worst outcome first: an unmet rule should never be forty rows down.
    const rows = [...grouped.entries()].sort((a, b) => {
      const severity = worst(a[1]) - worst(b[1]);
      return severity !== 0 ? severity : a[0].localeCompare(b[0]);
    });

    for (const [hId, group] of rows) {
      const all = evaluated.filter((record) => record.hId === hId);
      body.append(heuristicRow(hId, group, all, data, state, picked));
    }

    // Deep link from the statistics view: bring the requested row into sight
    // once, without fighting the reviewer's scrolling afterwards.
    if (state.heuristicFocus && scrolledTo !== state.heuristicFocus) {
      // The focus arrives from `?h=` in a link someone was handed, so it is
      // an arbitrary string, not a rule id.  Escaped, a malformed one simply
      // matches nothing; pasted in raw it makes querySelector throw, and the
      // throw travels back out through store.update() into whoever asked for
      // the render - which took the whole page down, not just this panel.
      const target = body.querySelector(`[data-h="${CSS.escape(state.heuristicFocus)}"]`);
      if (target) {
        target.scrollIntoView({ block: 'nearest' });
        scrolledTo = state.heuristicFocus;
      }
    }
  }

  store.subscribe((state) => render(state, false));
  return { setModel };

  // ------------------------------------------------------------- renderers

  function controls(shown, notApplicable, state, picked) {
    const wrap = document.createElement('div');
    wrap.className = 'heur-legend';

    const totals = count(shown);
    for (const outcome of SHOWN) {
      const chip = document.createElement('span');
      chip.className = 'heur-legend-chip ' + CLASS[outcome];
      chip.title = LABEL[outcome];
      chip.innerHTML = `<span class="heur-sq ${CLASS[outcome]}"></span>${totals[outcome] || 0}`;
      wrap.append(chip);
    }
    if (notApplicable) {
      const hidden = document.createElement('span');
      hidden.className = 'heur-legend-note';
      hidden.textContent = `${notApplicable} n/a`;
      hidden.title = `${notApplicable} unit(s) outside what those rules state — counted, not listed`;
      wrap.append(hidden);
    }

    // Three views of the list — everything, the unmet verdicts, the verdicts
    // about the selection.
    const tools = document.createElement('span');
    tools.className = 'heur-switches';
    const seg = document.createElement('div');
    seg.className = 'segmented compact heur-seg';
    seg.style.setProperty('--segments', '3');
    const active = state.heuristicsPickedOnly ? 2 : (state.heuristicsFailsOnly ? 1 : 0);
    seg.dataset.active = String(active);
    seg.innerHTML = '<span class="seg-thumb" aria-hidden="true"></span>';
    [
      ['all', 'every verdict of the part'],
      ['not met', 'only the verdicts that are not met'],
      ['selection', 'only the verdicts about the current selection'],
    ].forEach(([label, hint], position) => {
      const button = document.createElement('button');
      button.type = 'button';
      button.textContent = label;
      button.title = hint;
      button.setAttribute('aria-selected', String(position === active));
      button.addEventListener('click', () => {
        store.update({ heuristicsFailsOnly: position === 1, heuristicsPickedOnly: position === 2 });
      });
      seg.append(button);
    });
    tools.append(seg);
    wrap.append(tools);

    if (state.heuristicsPickedOnly && !picked) {
      const hint = document.createElement('span');
      hint.className = 'heur-legend-note';
      hint.textContent = 'nothing selected';
      wrap.append(hint);
    }
    return wrap;
  }

  function heuristicRow(hId, records, allRecords, data, state, picked) {
    const definition = data.heuristics[hId] || {};
    const open = state.heuristicFocus === hId;

    const wrap = document.createElement('div');
    wrap.className = 'heur-row' + (open ? ' open' : '');
    wrap.dataset.h = hId;

    const header = document.createElement('div');
    header.className = 'heur-row-head';

    const id = document.createElement('span');
    id.className = 'heur-id';
    id.textContent = hId;

    const label = document.createElement('span');
    label.className = 'heur-label';
    label.textContent = plainLabel(definition);

    const tally = document.createElement('span');
    tally.className = 'heur-tally';
    tally.textContent = tallyText(records);

    header.append(id, label, tally);
    header.title = statementTooltip(definition);
    header.addEventListener('click', () => {
      store.update((current) => ({ heuristicFocus: current.heuristicFocus === hId ? null : hId }));
    });

    const squares = document.createElement('div');
    squares.className = 'heur-squares';
    for (const record of [...records].sort(bySeverity)) {
      squares.append(square(record, picked));
    }

    wrap.append(header, squares);
    if (open) wrap.append(detail(definition, allRecords, data, hId, picked));
    return wrap;
  }

  function square(record, picked) {
    const button = document.createElement('button');
    button.className = 'heur-sq ' + CLASS[record.outcome];
    if (picked && addresses(record, picked)) button.classList.add('active');
    button.title = [
      `${record.hId} · ${LABEL[record.outcome]}`,
      record.reason,
      targetNames(record).join(', ') || 'whole part',
      record.outcome === 'FAIL' ? kpiMoves(record.affectsKpi) : '',
    ].filter(Boolean).join('\n');
    button.addEventListener('click', () => callbacks.onPickHeuristic(record));
    return button;
  }

  function detail(definition, allRecords, data, hId, picked) {
    const wrap = document.createElement('div');
    wrap.className = 'heur-detail';

    if (definition.statementEn) wrap.append(line('statement', definition.statementEn));
    for (const threshold of definition.thresholds || []) {
      wrap.append(line(threshold.symbol, `${threshold.value}${threshold.unit ? ' ' + threshold.unit : ''}`));
    }
    if (definition.scope) wrap.append(line('unit', definition.scope));

    const skipped = (data.summary[hId] || {}).counts || {};
    if (skipped.NOT_APPLICABLE) {
      wrap.append(line('not applicable', `${skipped.NOT_APPLICABLE} unit(s), outside what this rule states`));
    }
    if ((definition.affectsKpi || []).length) {
      wrap.append(kpiLine(definition.affectsKpi, allRecords.some((record) => record.outcome === 'FAIL')));
    }

    const list = document.createElement('div');
    list.className = 'heur-records';
    const ordered = [...allRecords].sort(bySeverity);
    for (const record of ordered.slice(0, MAX_DETAIL_ROWS)) {
      list.append(recordRow(record, picked));
    }
    if (ordered.length > MAX_DETAIL_ROWS) {
      list.append(note(`${ordered.length - MAX_DETAIL_ROWS} further verdict(s) not listed`));
    }
    wrap.append(list);
    return wrap;
  }

  function recordRow(record, picked) {
    const row = document.createElement('button');
    row.className = 'heur-record ' + CLASS[record.outcome]
      + (picked && addresses(record, picked) ? ' active' : '');
    const name = document.createElement('span');
    name.className = 'heur-record-target';
    name.textContent = targetNames(record).join(' + ') || 'whole part';
    const reason = document.createElement('span');
    reason.className = 'heur-record-reason';
    reason.textContent = record.reason;
    row.append(name, reason);
    row.addEventListener('click', () => callbacks.onPickHeuristic(record));
    return row;
  }

  /**
   * The KPI this rule affects.  Where one of its verdicts here is not met,
   * the row says where each KPI moves (its declared worse direction);
   * where every verdict is met, the KPI are listed quietly, without a
   * direction, because nothing is pushing them.
   */
  function kpiLine(kpiIds, notMet) {
    const row = document.createElement('div');
    row.className = 'heur-line heur-kpi';
    const k = document.createElement('span');
    k.className = 'k';
    k.textContent = 'KPI';
    const v = document.createElement('span');
    v.className = 'v kpi-chips';
    if (notMet) {
      const lead = document.createElement('span');
      lead.className = 'kpi-lead';
      lead.textContent = 'not met →';
      v.append(lead);
    }
    for (const kpiId of kpiIds) {
      v.append(kpiChip(kpiId, model.kpiTypes, model.kpiColors, { arrow: notMet, muted: !notMet }));
    }
    row.append(k, v);
    return row;
  }

  /** "not met → machining time ↑ · tool changes ↑", for a tooltip. */
  function kpiMoves(kpiIds) {
    if (!(kpiIds || []).length) return '';
    return 'not met → ' + kpiIds
      .map((kpiId) => `${kpiLabel(model.kpiTypes, kpiId)} ${kpiArrow(((model.kpiTypes || {})[kpiId] || {}).worseWhen)}`.trim())
      .join(' · ');
  }
}

// ------------------------------------------------------------------ pieces

function line(key, value) {
  const row = document.createElement('div');
  row.className = 'heur-line';
  const k = document.createElement('span');
  k.className = 'k';
  k.textContent = key;
  const v = document.createElement('span');
  v.className = 'v';
  v.textContent = value;
  row.append(k, v);
  return row;
}

function note(text) {
  const empty = document.createElement('div');
  empty.className = 'insp-empty';
  empty.textContent = text;
  return empty;
}

function count(records) {
  const totals = {};
  for (const record of records) totals[record.outcome] = (totals[record.outcome] || 0) + 1;
  return totals;
}

function tallyText(records) {
  const totals = count(records);
  return SHOWN.filter((outcome) => totals[outcome])
    .map((outcome) => `${totals[outcome]} ${SHORT[outcome]}`)
    .join(' · ');
}

function bySeverity(a, b) {
  return SHOWN.indexOf(a.outcome) - SHOWN.indexOf(b.outcome);
}

function worst(records) {
  return Math.min(...records.map((record) => SHOWN.indexOf(record.outcome)));
}

function targetNames(record) {
  return [...(record.targets.nodeIds || []), ...(record.targets.edgeIds || [])];
}

function plainLabel(definition) {
  // Should a label read "H01 — Hole depth-to-diameter ratio", the id is
  // already in its own column.
  const label = definition.labelEn || '';
  return label.replace(/^H\d+\s*[—–-]\s*/, '');
}

function statementTooltip(definition) {
  return [
    definition.statementEn || '',
    (definition.thresholds || [])
      .map((threshold) => `${threshold.symbol} = ${threshold.value}${threshold.unit ? ' ' + threshold.unit : ''}`)
      .join(', '),
  ].filter(Boolean).join('\n');
}

/** What the page currently has selected, in verdict-target terms. */
function pickedTargets(state, model) {
  const selection = resolveSelection(state, model);
  if (selection.kind === 'edge' && selection.focusEdgeId) {
    return {
      label: selection.focusEdgeId,
      edgeIds: new Set([selection.focusEdgeId]),
      nodeIds: new Set(selection.featureIds),
    };
  }
  if (selection.focusFeatureId) {
    return { label: selection.focusFeatureId, nodeIds: new Set(selection.featureIds) };
  }
  return null;
}

function addresses(record, picked) {
  if (picked.edgeIds) {
    for (const edgeId of record.targets.edgeIds || []) if (picked.edgeIds.has(edgeId)) return true;
  }
  if (picked.nodeIds) {
    for (const nodeId of record.targets.nodeIds || []) if (picked.nodeIds.has(nodeId)) return true;
  }
  return false;
}

function emptyText(state, picked) {
  if (state.heuristicsPickedOnly && !picked) return 'Select a feature or a relation edge.';
  if (state.heuristicsPickedOnly && state.heuristicsFailsOnly) return 'Every heuristic on this selection is met.';
  if (state.heuristicsPickedOnly) return 'No heuristic is evaluated on this selection.';
  if (state.heuristicsFailsOnly) return 'Every evaluated heuristic in this part is met.';
  return 'No heuristic verdict in this part.';
}
