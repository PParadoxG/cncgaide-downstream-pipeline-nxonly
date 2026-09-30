// KPI panel of the part page, folded under the verdict list.
//
// One group per KPI type the part has something to say about, in the order
// the source declares them: the direction the KPI moves when a rule that
// affects it is not met, the values the rules derived for it on this part
// (the worst few first, worst in the KPI's own worse direction), and the
// rules that are not met here and push on it.  A rule is a link to its
// verdict card; a value is a link to its feature.
//
// Nothing here branches on a KPI id or a rule id: which rule affects which
// KPI, the direction, the label, the unit and the colour all arrive with the
// part.

import { kpiArrow, kpiLabel } from './kpichip.js';

const OPEN_KEY = 'cncgaideKpiPanelOpen';
const VALUES_SHOWN = 3;

export function createKpiPanel(root, store, callbacks) {
  let model = null;

  // A plain section with a toggle rather than <details>: the open panel has
  // to be a flex column that shares the pane with the verdict list, and a
  // <details> element does not lay its content out as one everywhere.
  const panel = document.createElement('section');
  panel.className = 'kpi-panel';
  const head = document.createElement('button');
  head.type = 'button';
  head.className = 'pane-head kpi-head';
  const title = document.createElement('span');
  title.className = 'heur-title';
  title.textContent = 'KPI';
  const scope = document.createElement('span');
  scope.className = 'heur-scope';
  head.append(title, scope);
  const body = document.createElement('div');
  body.className = 'kpi-body';
  panel.append(head, body);
  let open = false;
  try { open = localStorage.getItem(OPEN_KEY) === '1'; } catch (error) { open = false; }
  const paint = () => {
    panel.classList.toggle('open', open);
    head.setAttribute('aria-expanded', String(open));
    body.hidden = !open;
    head.title = open ? 'fold the KPI panel' : 'show the KPI this part pushes on';
  };
  head.addEventListener('click', () => {
    open = !open;
    try { localStorage.setItem(OPEN_KEY, open ? '1' : '0'); } catch (error) { /* the choice just will not survive a reload */ }
    paint();
  });
  paint();
  root.append(panel);

  function setModel(nextModel) {
    model = nextModel;
    body.innerHTML = '';
    scope.textContent = '';
    if (!model) return;
    draw();
  }

  function draw() {
    const types = model.kpiTypes || {};
    const colors = model.kpiColors || {};
    const data = model.heuristics || { heuristics: {}, records: [] };

    // Which rules here affect which KPI, and how many of their verdicts are
    // not met on this part.
    const notMet = new Map();
    for (const record of data.records || []) {
      if (record.outcome !== 'FAIL') continue;
      notMet.set(record.hId, (notMet.get(record.hId) || 0) + 1);
    }
    const affectedBy = new Map();
    for (const [hId, definition] of Object.entries(data.heuristics || {})) {
      for (const kpiId of definition.affectsKpi || []) {
        if (!affectedBy.has(kpiId)) affectedBy.set(kpiId, []);
        affectedBy.get(kpiId).push(hId);
      }
    }
    const values = new Map();
    for (const result of model.kpi || []) {
      if (!values.has(result.kpiType)) values.set(result.kpiType, []);
      values.get(result.kpiType).push(result);
    }

    let pushed = 0;
    const quiet = [];
    for (const [kpiId, type] of Object.entries(types)) {
      const failing = (affectedBy.get(kpiId) || []).filter((hId) => notMet.has(hId)).sort();
      const results = values.get(kpiId) || [];
      if (!failing.length && !results.length) {
        if ((affectedBy.get(kpiId) || []).length) quiet.push(kpiId);
        continue;
      }
      if (failing.length) pushed += 1;
      body.append(group(kpiId, type, colors[kpiId], failing, notMet, results, data));
    }
    scope.textContent = pushed ? `${pushed} pushed by a rule not met` : '';
    if (quiet.length) {
      const line = document.createElement('div');
      line.className = 'kpi-quiet';
      line.textContent = 'every rule met: ' + quiet.map((kpiId) => kpiLabel(types, kpiId)).join(' · ');
      line.title = 'KPI a rule evaluated on this part affects, with every verdict of those rules met';
      body.append(line);
    }
    if (!body.childElementCount) {
      const empty = document.createElement('div');
      empty.className = 'insp-empty';
      empty.textContent = 'No KPI is affected by a rule evaluated on this part.';
      body.append(empty);
    }
  }

  function group(kpiId, type, color, failing, notMet, results, data) {
    const wrap = document.createElement('div');
    wrap.className = 'kpi-group';
    wrap.style.setProperty('--chip', color || '#8d97a3');
    wrap.dataset.kpi = kpiId;

    const head = document.createElement('div');
    head.className = 'kpi-group-head';
    const name = document.createElement('span');
    name.className = 'chip-tint kpi-chip';
    name.style.setProperty('--chip', color || '#8d97a3');
    name.textContent = kpiLabel(model.kpiTypes, kpiId);
    name.title = `${kpiId}${type.unit ? ' · ' + type.unit : ''}${type.kind ? ' · per ' + type.kind : ''}`;
    const arrow = document.createElement('span');
    arrow.className = 'kpi-arrow' + (failing.length ? ' on' : '');
    arrow.textContent = kpiArrow(type.worseWhen);
    arrow.title = `worse when ${type.worseWhen}; a rule not met moves it that way`;
    head.append(name, arrow);
    if (failing.length) {
      const count = document.createElement('span');
      count.className = 'kpi-count';
      count.textContent = `${failing.length} rule${failing.length === 1 ? '' : 's'} not met`;
      head.append(count);
    }
    wrap.append(head);

    if (results.length) {
      const higherIsWorse = type.worseWhen !== 'lower';
      const ordered = [...results].sort((a, b) => (higherIsWorse ? b.value - a.value : a.value - b.value));
      const list = document.createElement('div');
      list.className = 'kpi-values';
      for (const result of ordered.slice(0, VALUES_SHOWN)) {
        const row = document.createElement('button');
        row.type = 'button';
        row.className = 'kpi-value';
        const node = document.createElement('span');
        node.className = 'kpi-node';
        node.textContent = result.nodeId || 'whole part';
        const value = document.createElement('span');
        value.className = 'kpi-number';
        value.textContent = `${formatNumber(result.value)}${result.unit ? ' ' + result.unit : ''}`;
        row.append(node, value);
        row.title = `${result.derivation || kpiId}`;
        if (result.nodeId) row.addEventListener('click', () => callbacks.onPickFeature(result.nodeId));
        list.append(row);
      }
      if (ordered.length > VALUES_SHOWN) {
        const more = document.createElement('div');
        more.className = 'kpi-more';
        more.textContent = `${ordered.length} features · ${ordered.length - VALUES_SHOWN} more`;
        list.append(more);
      }
      wrap.append(list);
    }

    if (failing.length) {
      const rules = document.createElement('div');
      rules.className = 'kpi-rules';
      for (const hId of failing) {
        const definition = (data.heuristics || {})[hId] || {};
        const link = document.createElement('button');
        link.type = 'button';
        link.className = 'kpi-rule';
        const id = document.createElement('span');
        id.className = 'heur-id';
        id.textContent = hId;
        const label = document.createElement('span');
        label.className = 'kpi-rule-label';
        label.textContent = definition.labelEn || '';
        const tally = document.createElement('span');
        tally.className = 'heur-tally';
        tally.textContent = `${notMet.get(hId)} not met`;
        link.append(id, label, tally);
        link.title = 'show this rule’s verdicts';
        link.addEventListener('click', () => {
          store.update({ heuristicFocus: hId, heuristicsPickedOnly: false });
        });
        rules.append(link);
      }
      wrap.append(rules);
    }
    return wrap;
  }

  return { setModel };
}

function formatNumber(value) {
  if (typeof value !== 'number') return String(value);
  return Number.isInteger(value) ? String(value) : String(Number(value.toFixed(3)));
}
