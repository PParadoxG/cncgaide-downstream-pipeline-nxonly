// One KPI as a chip: its label, its colour and - where a rule is not met -
// the direction the KPI moves.
//
// The direction is the KPI type's own `worseWhen` from the source: a rule
// that is not met moves every KPI it affects in that KPI's worse direction.
// The arrow is looked up from that word, never from a KPI name, and the
// colour comes from the display source through the answer.

const ARROW = { higher: '↑', lower: '↓' };

/** The arrow for a `worseWhen` word; empty for a word the table lacks. */
export function kpiArrow(worseWhen) {
  return ARROW[worseWhen] || '';
}

/** The words a reader sees for a KPI type; the id when the source has none. */
export function kpiLabel(kpiTypes, kpiId) {
  return ((kpiTypes || {})[kpiId] || {}).label || kpiId;
}

/**
 * A tinted chip for one KPI.  `arrow: true` prints the direction; without
 * it the chip is the plain, quiet form used where nothing is pushing the KPI.
 */
export function kpiChip(kpiId, kpiTypes, kpiColors, { arrow = false, muted = false } = {}) {
  const type = (kpiTypes || {})[kpiId] || {};
  const chip = document.createElement('span');
  chip.className = 'chip-tint kpi-chip' + (muted ? ' muted' : '');
  chip.style.setProperty('--chip', (kpiColors || {})[kpiId] || '#8d97a3');
  const label = kpiLabel(kpiTypes, kpiId);
  const direction = arrow ? kpiArrow(type.worseWhen) : '';
  chip.textContent = direction ? `${label} ${direction}` : label;
  chip.dataset.kpi = kpiId;
  chip.title = type.worseWhen
    ? `${kpiId} · worse when ${type.worseWhen}\nnot met → ${label} ${kpiArrow(type.worseWhen)}`
    : kpiId;
  return chip;
}
