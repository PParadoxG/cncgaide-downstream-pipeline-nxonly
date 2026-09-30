// Loading + indexing of what the store answers for one part.
//
// Nothing here derives new geometry semantics: feature identity, face
// ownership, relation ends and verdicts arrive in the part bundle
// (`api/part/<id>`), the tessellation in the mesh files.  What happens here is
// re-shaping: the bundle is laid out as the view the panels read (one node
// per feature, one face row per PartModel face, one record per verdict), and
// then indexed exactly as before.

const NEUTRAL = '#8d97a3';

// ------------------------------------------------------------ which build
//
// A part is a bundle and a mesh, fetched one after the other, and a sync can
// replace the part between the two requests.  The guard is a demand rather
// than a check after the fact: the mesh request carries `If-Match` naming the
// facts key the bundle was read from, and the server answers 409 instead of a
// mesh from another build (server.py::if_match_satisfied).  A 409 becomes
// `RunChanged`, which the pages already know what to do with: it is a part
// that failed to load, and the named degradation path takes the part off
// screen and says why.

let expectedRun = null;

/** The index this page read.  Set once, from the index the page loaded. */
export function setExpectedRun(runId) {
  expectedRun = runId || null;
}

export function currentExpectedRun() {
  return expectedRun;
}

/** The validator the server stamps a mesh with; `null` when unknown. */
export function runValidator(partId, factsKey) {
  return partId && factsKey ? `W/"${partId}:${factsKey}"` : null;
}

export class RunChanged extends Error {
  constructor(runId) {
    super('the store was rebuilt while this page was reading it'
      + (runId ? ` (the store now serves ${runId})` : ''));
    this.name = 'RunChanged';
    this.runId = runId || null;
  }
}

async function fetchJson(url) {
  const response = await fetch(url, { cache: 'no-store' });
  if (!response.ok) {
    let detail = null;
    try { detail = (await response.json()).error || null; } catch { detail = null; }
    const error = new Error(detail || `${url}: HTTP ${response.status}`);
    error.status = response.status;
    throw error;
  }
  return response.json();
}

async function fetchMeshFile(url, validator) {
  const options = validator ? { cache: 'no-store', headers: { 'If-Match': validator } } : { cache: 'no-store' };
  const response = await fetch(url, options);
  if (response.status === 409) throw new RunChanged(null);
  return assertOk(response);
}

/** The store's index: one row per part, the display block, the digests. */
export async function loadIndex() {
  const index = await fetchJson('api/index');
  // The part page and the compare page name "the build they read" by this.
  index.runId = index.indexDigest || null;
  return index;
}

/** The part bundle alone (no mesh), for a caller that only needs the words. */
export function loadBundle(partId) {
  return fetchJson(`api/part/${encodeURIComponent(partId)}`);
}

export async function loadPart(partId) {
  const bundle = await loadBundle(partId);
  const base = `api/part/${encodeURIComponent(partId)}/`;
  const validator = runValidator(partId, bundle.factsKey);
  const [meshResponse, bufferResponse] = await Promise.all([
    fetchMeshFile(base + 'mesh.json', validator),
    fetchMeshFile(base + 'mesh.bin', validator),
  ]);
  const [meshHeader, buffer] = await Promise.all([meshResponse.json(), bufferResponse.arrayBuffer()]);
  const { view, mesh } = toView(bundle, meshHeader);
  const model = buildModel(view, mesh, buffer, toHeuristics(bundle));
  model.runValidator = validator;
  model.factsKey = bundle.factsKey || null;
  model.derivedKey = bundle.derivedKey || null;
  model.updatedAt = bundle.updatedAt || null;
  // KPI: the results the rules derived for this part, the declared types
  // (label, unit, the direction a KPI moves when a rule is not met) and the
  // colours the display source gives them.
  model.kpi = bundle.kpi || [];
  model.kpiTypes = bundle.kpiTypes || {};
  model.kpiColors = (bundle.display && bundle.display.kpiColors) || {};
  // The unit of every name the ontology declares one for (see unitFor).
  model.units = bundle.units || {};
  return model;
}

/** The verdicts of one part in the panel's shape, or null when unreadable. */
export async function loadHeuristics(partId) {
  try {
    return toHeuristics(await loadBundle(partId));
  } catch (error) {
    return null;
  }
}

function assertOk(response) {
  if (!response.ok) throw new Error(`${response.url}: HTTP ${response.status}`);
  return response;
}

// --------------------------------------------------------------- re-shaping

/**
 * The drawing key of a mesh face record.
 *
 * The mesh draws one record per PartModel face and names the raw CAD faces
 * behind it; the first of those is the record's key, which keeps the key an
 * integer of the source STEP traversal like everywhere else in the views.
 */
function meshKey(record) {
  if (Array.isArray(record.cadFaceIds) && record.cadFaceIds.length) return Number(record.cadFaceIds[0]);
  const tail = /(\d+)$/.exec(String(record.faceId || ''));
  return tail ? Number(tail[1]) : null;
}

/** Bundle + mesh header -> the view the panels read, and the keyed mesh. */
export function toView(bundle, meshHeader) {
  const display = bundle.display || {};
  const featureColors = display.featureColors || {};
  const keyOf = new Map();
  const meshFaces = [];
  for (const record of (meshHeader && meshHeader.faces) || []) {
    const key = meshKey(record);
    if (key === null) continue;
    keyOf.set(record.faceId, key);
    meshFaces.push(Object.assign({}, record, { cadFaceId: key }));
  }
  const mesh = Object.assign({}, meshHeader, { faces: meshFaces });
  const surfaceOf = new Map((bundle.faces || []).map((face) => [face.faceId, face.surfaceType || null]));
  const recordOf = new Map(meshFaces.map((record) => [record.faceId, record]));

  const faces = {};
  for (const face of bundle.faces || []) {
    const key = keyOf.get(face.faceId);
    if (key === undefined) continue;
    const record = recordOf.get(face.faceId);
    faces[String(key)] = {
      cadFaceId: key,
      displayFaceId: face.faceId,
      partmodelFaceId: face.faceId,
      surfaceType: face.surfaceType || null,
      featureIds: [],
      mergedCadFaceIds: [key],
      hasMesh: Boolean(record && record.indexCount > 0),
    };
  }

  const nodes = [];
  const featureCounts = {};
  const usedAttributes = {};
  for (const feature of bundle.features || []) {
    const faceIds = (feature.faceIds || []).filter((faceId) => keyOf.has(faceId));
    const keys = faceIds.map((faceId) => keyOf.get(faceId));
    for (const key of keys) {
      const row = faces[String(key)];
      if (row && !row.featureIds.includes(feature.nodeId)) row.featureIds.push(feature.nodeId);
    }
    const diagnostics = {};
    if (Object.keys(feature.attributeReading || {}).length) diagnostics.attributeReading = feature.attributeReading;
    nodes.push({
      nodeId: feature.nodeId,
      featureType: feature.featureType,
      color: featureColors[feature.featureType] || NEUTRAL,
      displayFaceIds: faceIds,
      partmodelFaceIds: faceIds,
      cadFaceIds: keys,
      displayFaceDetails: faceIds.map((faceId) => ({
        displayFaceId: faceId,
        cadFaceIds: [keyOf.get(faceId)],
        partmodelFaceId: faceId,
        surfaceType: surfaceOf.get(faceId) || null,
      })),
      properties: feature.attributes || {},
      missingAttributes: feature.attributeGaps || {},
      diagnostics,
      derived: feature.derived || {},
    });
    featureCounts[feature.featureType] = (featureCounts[feature.featureType] || 0) + 1;
    if (Array.isArray(feature.usedAttributes)) usedAttributes[feature.featureType] = feature.usedAttributes;
  }

  const edges = [];
  const relationCounts = new Map();
  for (const relation of bundle.relations || []) {
    const refs = [];
    for (const terminal of relation.terminals || []) {
      if (!terminal.hostFaceId || !keyOf.has(terminal.hostFaceId)) continue;
      refs.push({
        displayFaceId: terminal.hostFaceId,
        partmodelFaceId: terminal.hostFaceId,
        cadFaceIds: [keyOf.get(terminal.hostFaceId)],
      });
    }
    const evidence = Object.assign({}, relation.evidence || {});
    if ((relation.terminals || []).length) evidence.terminals = relation.terminals;
    const diagnostics = Object.assign({}, relation.diagnostics || {});
    if (relation.sourceRule) diagnostics.sourceRule = relation.sourceRule;
    edges.push({
      edgeId: relation.relationId,
      source: relation.source,
      target: relation.target,
      edgeType: relation.edgeType,
      directed: Boolean(relation.directed),
      sharedEdgeCount: null,
      properties: relation.properties || {},
      evidence,
      evidenceFaceRefs: refs,
      diagnostics,
    });
    relationCounts.set(relation.edgeType, (relationCounts.get(relation.edgeType) || 0) + 1);
  }
  const visibleByDefault = new Set(display.relationsVisibleByDefault || []);
  const relationTypes = [...relationCounts.entries()]
    .sort((a, b) => a[0].localeCompare(b[0]))
    .map(([edgeType, count]) => ({
      edgeType,
      count,
      color: (display.relationColors || {})[edgeType] || NEUTRAL,
      defaultVisible: visibleByDefault.has(edgeType),
    }));

  const present = new Set(Object.keys(featureCounts));
  const labels = {};
  for (const type of present) {
    const label = (display.featureLabels || {})[type];
    if (label) labels[type] = label;
  }
  const header = bundle.part || {};
  const view = {
    partId: bundle.partId,
    sourceStep: bundle.sourceStep || null,
    nodes,
    edges,
    relationTypes,
    faces,
    featureCounts,
    defaultHiddenFeatureTypes: (display.hiddenTypes || []).filter((type) => present.has(type)),
    stats: {
      rawCadFaceCount: header.faceCount ?? Object.keys(faces).length,
      manifestPartmodelFaceCount: (bundle.faces || []).length,
      featureNodeCount: nodes.length,
      unclaimedRawCadFaceIds: (header.unclaimedFaceIds || [])
        .filter((faceId) => keyOf.has(faceId)).map((faceId) => keyOf.get(faceId)),
      mergedDisplayFaces: {},
    },
    featureLabels: labels,
    usedAttributes,
  };
  return { view, mesh };
}

/**
 * The verdicts of a bundle as the panel's records.
 *
 * `reason` is the verdict's own content in one line - the values the rule
 * published and the thresholds it compared them with, or the attributes it
 * could not read - so a square's tooltip says what the rule saw.
 */
export function toHeuristics(bundle) {
  const verdicts = bundle.verdicts || [];
  const units = bundle.units || {};
  const rules = bundle.rules || {};
  const records = verdicts.map((verdict) => ({
    hId: verdict.hId,
    scope: verdict.scope,
    targets: verdict.scope === 'pair'
      ? { nodeIds: verdict.targetNodeIds || [], edgeIds: [verdict.target] }
      : { nodeIds: [verdict.target] },
    outcome: verdict.outcome,
    values: verdict.values || {},
    thresholds: verdict.thresholds || [],
    gaps: verdict.gaps || [],
    affectsKpi: verdict.affectsKpi || [],
    evidence: {},
    reason: reasonText(verdict, units, rules[verdict.hId]),
  }));
  const heuristics = {};
  for (const [hId, rule] of Object.entries(bundle.rules || {})) {
    heuristics[hId] = {
      labelEn: rule.label || hId,
      statementEn: rule.statement || '',
      scope: rule.scope || null,
      appliesTo: rule.appliesTo || [],
      thresholds: rule.thresholds || [],
      affectsKpi: rule.affectsKpi || [],
    };
  }
  const summary = {};
  for (const record of records) {
    const entry = summary[record.hId] || (summary[record.hId] = { counts: {} });
    entry.counts[record.outcome] = (entry.counts[record.outcome] || 0) + 1;
  }
  for (const [hId, count] of Object.entries(bundle.notApplicable || {})) {
    const entry = summary[hId] || (summary[hId] = { counts: {} });
    entry.counts.NOT_APPLICABLE = count;
  }
  return { partId: bundle.partId, heuristics, summary, records };
}

function reasonText(verdict, units, rule) {
  if ((verdict.gaps || []).length) {
    return 'cannot read ' + verdict.gaps
      .map((gap) => gap.attribute + (gap.reason ? ` (${gap.reason})` : ''))
      .join(', ');
  }
  // A threshold's unit is in the table like every other; the rule's own
  // definition names it too, which covers a bundle that carries no table.
  const declared = Object.fromEntries(((rule && rule.thresholds) || []).map((entry) => [entry.symbol, entry.unit]));
  const values = Object.entries(verdict.values || {})
    .map(([name, value]) => `${name} ${withUnit(formatNumber(value), unitFor(units, name, value))}`);
  const thresholds = (verdict.thresholds || []).map((entry) => `${entry.symbol} ${withUnit(formatNumber(entry.value),
    unitFor(units, entry.symbol, entry.value) || unitFor(declared, entry.symbol, entry.value))}`);
  return [...values, ...thresholds].join(' · ');
}

function formatNumber(value) {
  if (typeof value !== 'number') return Array.isArray(value) ? value.join(', ') : String(value);
  return Number.isInteger(value) ? String(value) : String(Number(value.toFixed(4)));
}

// ------------------------------------------------------------------ units
//
// `units` in the part bundle is `{name: unit}` for every name the ontology
// declares a unit for: an NX attribute (its unit kind resolved against the
// part's length unit), a derived quantity, a relation property, a threshold.
// A value is printed with its unit when it is a number or a list of numbers
// and its name is in the table; a string, a null and a refusal keep their
// text as it is.  The table is the whole of it: nothing here knows what any
// name means, and a name the table does not hold prints as before.

/** The unit to print after `value`, shown under `name`; null for none. */
export function unitFor(units, name, value) {
  const unit = units ? units[name] : null;
  return typeof unit === 'string' && unit && isQuantity(value) ? unit : null;
}

function isQuantity(value) {
  if (typeof value === 'number') return Number.isFinite(value);
  return Array.isArray(value) && value.length > 0
    && value.every((item) => typeof item === 'number' && Number.isFinite(item));
}

// Between a number and its unit: a no-break space, so that a line or a
// narrow table column never ends on the number and starts on the unit.
const UNIT_SPACE = ' ';

/** `"30"` -> `"30 mm"` in a line of text; unchanged without a unit. */
export function withUnit(text, unit) {
  return unit ? `${text}${UNIT_SPACE}${unit}` : text;
}

/** The unit after the value in a table cell: the space, then its own quieter span. */
export function appendUnit(element, unit) {
  if (!unit) return element;
  const span = document.createElement('span');
  span.className = 'value-unit';
  span.textContent = unit;
  element.append(UNIT_SPACE, span);
  return element;
}

function buildModel(view, mesh, buffer, heuristics) {
  const nodeById = new Map();
  for (const node of view.nodes) nodeById.set(node.nodeId, node);

  const faceById = new Map();
  for (const key of Object.keys(view.faces)) {
    const row = view.faces[key];
    faceById.set(row.cadFaceId, row);
  }

  // Feature types present, in a stable order: most common first, then by name.
  const typeCounts = new Map();
  for (const node of view.nodes) {
    typeCounts.set(node.featureType, (typeCounts.get(node.featureType) || 0) + 1);
  }
  const colorByType = new Map();
  for (const node of view.nodes) colorByType.set(node.featureType, node.color);

  // `label` is the words a human reads for this class, `type` stays the key
  // (STEP1HOLE / "Through Hole"); a class the source gives no label falls
  // back to `type` with no branch anywhere.
  const labels = view.featureLabels || {};
  const featureTypes = [...typeCounts.entries()]
    .sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]))
    .map(([type, count]) => ({
      type,
      label: labels[type] || type,
      count,
      color: colorByType.get(type) || NEUTRAL,
    }));

  const meshFaces = new Map();
  for (const record of mesh.faces) meshFaces.set(record.cadFaceId, record);

  // Relation neighbours, indexed once so edge selection and the graph
  // highlight can both look them up cheaply.  The active relation-type set
  // is applied later by resolveSelection; this index deliberately keeps all
  // materialized edge types available.
  const edges = view.edges || [];
  const edgeById = new Map();
  const neighbours = new Map();
  const incidentEdges = new Map();
  for (const edge of edges) {
    edgeById.set(edge.edgeId, edge);
    for (const [a, b] of [[edge.source, edge.target], [edge.target, edge.source]]) {
      if (!neighbours.has(a)) neighbours.set(a, new Set());
      neighbours.get(a).add(b);
      if (!incidentEdges.has(a)) incidentEdges.set(a, []);
      incidentEdges.get(a).push(edge);
    }
  }

  // Relation types come from the answer, so a rule registered after this file was
  // written still gets a chip, a colour and a default.
  const relationTypes = view.relationTypes || [];

  return {
    partId: view.partId,
    sourceStep: view.sourceStep,
    nodes: view.nodes,
    relationTypes,
    defaultHiddenFeatureTypes: view.defaultHiddenFeatureTypes || [],
    defaultVisibleEdgeTypes: relationTypes.filter((r) => r.defaultVisible).map((r) => r.edgeType),
    edges,
    edgeById,
    neighbours,
    incidentEdges,
    nodeById,
    faceById,
    faceIds: [...faceById.keys()].sort((a, b) => a - b),
    featureTypes,
    featureLabels: labels,
    // What the store evaluated none of, and why it says so.  A layer named
    // here is a deliberate silence; a layer absent is simply unknown, and the
    // two must not look the same on screen.
    notEvaluated: view.notEvaluated || {},
    // `{class: names}` when the answer says which attributes the rules read,
    // `null` when it does not - and `null` means "expand everything".
    usedAttributes: view.usedAttributes || null,
    // Verdicts of the heuristic layer, exactly as written by the pipeline.
    // null when the part carries no verdicts.
    heuristics: heuristics && Array.isArray(heuristics.records) ? heuristics : null,
    stats: view.stats,
    mesh,
    meshFaces,
    buffer,
  };
}

/**
 * Colour a raw CAD face carries.
 *
 * Filtered-out feature types normally fall back to neutral so the CAD view is
 * not drowned in PlanarFace colour, but a face the user explicitly selected
 * keeps its owner's colour — otherwise clicking a filtered face would look
 * like clicking nothing.
 */
/** The words a human reads for one class; the class name when it has none. */
export function featureLabel(model, featureType) {
  return (model && model.featureLabels && model.featureLabels[featureType]) || featureType;
}

export function baseFaceColor(model, cadFaceId, hiddenTypes, ignoreHidden, neutral) {
  const fallback = neutral || NEUTRAL;
  const row = model.faceById.get(cadFaceId);
  if (!row || !row.featureIds.length) return fallback;
  for (const featureId of row.featureIds) {
    const node = model.nodeById.get(featureId);
    if (node && (ignoreHidden || !hiddenTypes.has(node.featureType))) return node.color;
  }
  return fallback;
}

export const NEUTRAL_COLOR = NEUTRAL;
