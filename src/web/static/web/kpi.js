// KPI view of the launcher page: one row per part, one column per KPI type.
//
// A cell is the pressure on that KPI in that part - how many rules that
// affect the KPI are not met there - drawn as a bar against the largest
// pressure in the column, with the rules in the tooltip.  For a KPI a
// derivation computes, the cell also carries the part's value in the KPI's
// worse direction (the largest tool length, the smallest tool diameter),
// picked by the server from the KPI's declared `worseWhen`.
//
// No KPI id, rule id or class name appears in this file: columns, labels,
// directions, units and colours are all read from `api/kpi`.

import { kpiArrow, kpiLabel } from './kpichip.js';

export function createKpi(root) {
  let data = null;
  let loading = null;
  const state = { search: '', sortKey: 'partId', sortAsc: true };

  /** Forget the answer; the next render asks again. */
  function invalidate() {
    data = null;
  }

  async function load() {
    if (data) return data;
    if (!loading) {
      loading = fetch('api/kpi', { cache: 'no-store' })
        .then(async (response) => {
          const payload = await response.json().catch(() => ({}));
          if (!response.ok) throw new Error(payload.error || `api/kpi: HTTP ${response.status}`);
          return payload;
        })
        .finally(() => { loading = null; });
    }
    data = await loading;
    return data;
  }

  async function render() {
    if (root.hidden) return;
    let payload;
    try {
      payload = await load();
    } catch (error) {
      root.innerHTML = '';
      const note = document.createElement('div');
      note.className = 'empty-state';
      note.textContent = error.message;
      root.append(note);
      return;
    }
    draw(payload);
  }

  function draw(payload) {
    const types = payload.kpiTypes || [];
    const byId = Object.fromEntries(types.map((type) => [type.kpiType, type]));
    const colors = ((payload.display || {}).kpiColors) || {};
    const pressure = (part, kpiId) => Object.keys(((part.pressure || {})[kpiId] || {}).rules || {}).length;
    const columnMax = Object.fromEntries(types.map((type) => [type.kpiType,
      Math.max(0, ...(payload.parts || []).map((part) => pressure(part, type.kpiType)))]));

    root.innerHTML = '';
    const panel = document.createElement('div');
    panel.className = 'stats-panel';
    const head = document.createElement('div');
    head.className = 'stats-panel-head';
    const heading = document.createElement('h2');
    heading.textContent = 'Part × KPI';
    const legend = document.createElement('div');
    legend.className = 'matrix-legend kpi-legend';
    const arrows = document.createElement('span');
    arrows.className = 'kpi-legend-text';
    arrows.textContent = 'arrow = the direction a KPI moves when a rule that affects it is not met';
    const bar = document.createElement('span');
    bar.className = 'kpi-legend-text';
    bar.innerHTML = '<i class="kpi-legend-bar"></i>rules not met, against the column maximum';
    legend.append(arrows, bar);
    head.append(heading, legend);
    panel.append(head);

    const filters = document.createElement('div');
    filters.className = 'stats-filters';
    const search = document.createElement('input');
    search.type = 'search';
    search.placeholder = 'search part…';
    search.value = state.search;
    search.addEventListener('input', (event) => {
      state.search = event.target.value;
      draw(payload);
      const next = root.querySelector('.stats-filters input[type="search"]');
      next.focus();
      next.setSelectionRange(next.value.length, next.value.length);
    });
    filters.append(search);
    panel.append(filters);

    const scroll = document.createElement('div');
    scroll.className = 'kpi-scroll';
    const table = document.createElement('table');
    table.className = 'h-table kpi-table';
    const thead = document.createElement('thead');
    const headRow = document.createElement('tr');
    headRow.append(headCell('partId', 'part', 'col-name', 'part id'));
    for (const type of types) {
      const words = type.label || type.kpiType;
      const cell = headCell(type.kpiType, '', 'kpi-col', [
        `${words} (${type.kpiType})`,
        `worse when ${type.worseWhen}${type.unit ? ' · ' + type.unit : ''}${type.kind ? ' · per ' + type.kind : ''}`,
        type.affectedBy.length ? `affected by ${type.affectedBy.join(', ')}` : 'no rule affects it',
      ].join('\n'));
      cell.style.setProperty('--chip', colors[type.kpiType] || '#8d97a3');
      const stack = document.createElement('span');
      stack.className = 'kpi-col-head';
      const label = document.createElement('span');
      label.className = 'kpi-col-label';
      for (const line of twoLines(words)) {
        const part = document.createElement('span');
        part.textContent = line;
        label.append(part);
      }
      const mark = document.createElement('span');
      mark.className = 'kpi-col-mark';
      const dot = document.createElement('i');
      dot.className = 'kpi-col-dot';
      mark.append(dot);
      const direction = kpiArrow(type.worseWhen);
      if (direction) {
        const arrow = document.createElement('span');
        arrow.className = 'kpi-col-arrow';
        arrow.textContent = direction;
        mark.append(arrow);
      }
      stack.append(label, mark);
      cell.prepend(stack);
      headRow.append(cell);
    }
    thead.append(headRow);

    const needle = state.search.trim().toLowerCase();
    const rows = (payload.parts || [])
      .filter((part) => !needle || part.partId.toLowerCase().includes(needle))
      .sort((a, b) => compare(a, b, pressure, byId));
    const tbody = document.createElement('tbody');
    for (const part of rows) {
      const tr = document.createElement('tr');
      const name = document.createElement('td');
      name.className = 'col-name';
      const link = document.createElement('a');
      link.className = 'kpi-part';
      link.href = `part.html?part=${encodeURIComponent(part.partId)}`;
      link.textContent = part.partId;
      name.append(link);
      tr.append(name);
      for (const type of types) {
        tr.append(valueCell(part, type, byId, colors, columnMax[type.kpiType]));
      }
      tr.addEventListener('click', (event) => {
        if (event.target.closest('a')) return;
        location.href = link.href;
      });
      tbody.append(tr);
    }
    table.append(thead, tbody);
    scroll.append(table);
    panel.append(scroll);
    if (!rows.length) {
      const empty = document.createElement('div');
      empty.className = 'empty-state';
      empty.textContent = (payload.parts || []).length ? 'no part matches the search' : 'no part has verdicts yet';
      panel.append(empty);
    }
    root.append(panel);

    function headCell(key, text, className, title) {
      const cell = document.createElement('th');
      cell.className = className;
      cell.textContent = text;
      cell.title = title;
      cell.dataset.sort = key;
      if (state.sortKey === key) {
        cell.classList.add('sorted');
        cell.dataset.direction = state.sortAsc ? 'asc' : 'desc';
      }
      cell.addEventListener('click', () => {
        if (state.sortKey === key) state.sortAsc = !state.sortAsc;
        else { state.sortKey = key; state.sortAsc = key === 'partId'; }
        draw(payload);
      });
      return cell;
    }
  }

  function compare(a, b, pressure, byId) {
    const direction = state.sortAsc ? 1 : -1;
    const key = state.sortKey;
    if (key === 'partId') return a.partId.localeCompare(b.partId) * direction;
    // A column no rule affects sorts by its value; the others by pressure.
    const byValue = !((byId[key] || {}).affectedBy || []).length;
    const measure = (part) => (byValue
      ? (((part.worst || {})[key] || {}).value ?? -Infinity)
      : pressure(part, key));
    return ((measure(a) - measure(b)) || 0) * direction || a.partId.localeCompare(b.partId);
  }

  function valueCell(part, type, byId, colors, max) {
    const cell = document.createElement('td');
    cell.className = 'kpi-cell';
    cell.style.setProperty('--chip', colors[type.kpiType] || '#8d97a3');
    const rules = ((part.pressure || {})[type.kpiType] || {}).rules || {};
    const ids = Object.keys(rules);
    const bar = document.createElement('span');
    bar.className = 'kpi-bar';
    const fill = document.createElement('i');
    fill.style.width = max ? `${(ids.length / max) * 100}%` : '0%';
    bar.append(fill);
    const count = document.createElement('span');
    count.className = 'kpi-n' + (ids.length ? '' : ' zero');
    count.textContent = String(ids.length);
    const tips = [`${part.partId} · ${kpiLabel(byId, type.kpiType)}`];
    // A KPI no rule affects has no pressure to draw, only (perhaps) a value.
    if ((type.affectedBy || []).length) {
      const line = document.createElement('span');
      line.className = 'kpi-pressure';
      line.append(bar, count);
      cell.append(line);
      tips.push(ids.length
        ? 'not met: ' + ids.map((hId) => `${hId} (${rules[hId]})`).join(', ')
        : 'no rule that affects it is not met');
    }

    const worst = (part.worst || {})[type.kpiType];
    if (worst) {
      const value = document.createElement('span');
      value.className = 'kpi-worst';
      value.textContent = `${formatNumber(worst.value)}${worst.unit ? ' ' + worst.unit : ''}`;
      cell.append(value);
      tips.push(`worst of ${worst.count} feature value(s): ${formatNumber(worst.value)}${worst.unit ? ' ' + worst.unit : ''}`
        + (worst.nodeId ? ` at ${worst.nodeId}` : ''));
    }
    cell.title = tips.join('\n');
    return cell;
  }

  return { render, invalidate };
}

/**
 * A label as at most two lines: one word stays one line; otherwise the break
 * goes at the word boundary that makes the longer line shortest, so a column
 * is as narrow as its label allows and no head runs to a third line.
 */
function twoLines(label) {
  const words = String(label).trim().split(/\s+/);
  if (words.length < 2) return [words.join(' ')];
  let best = null;
  for (let cut = 1; cut < words.length; cut += 1) {
    const lines = [words.slice(0, cut).join(' '), words.slice(cut).join(' ')];
    const longest = Math.max(lines[0].length, lines[1].length);
    if (!best || longest < best.longest) best = { lines, longest };
  }
  return best.lines;
}

function formatNumber(value) {
  if (typeof value !== 'number') return String(value);
  return Number.isInteger(value) ? String(value) : String(Number(value.toFixed(2)));
}
