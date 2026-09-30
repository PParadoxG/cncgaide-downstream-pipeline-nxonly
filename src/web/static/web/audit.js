// Maintenance check for the web viewer.  Load it from any viewer page console:
//
//   await fetch('web/audit.js').then(r => r.text()).then(eval)
//   await runViewerAudit();      // part page: two-way Feature <-> CAD binding
//                                // home page: store, views + similarity API
//                                // compare page: both views, edit path, highlights
//   await runAutoViewAudit();    // part page: does the camera see the feature
//
// It walks every part, every feature and every raw CAD face using only the
// public window.tempVisual / window.tempCompare hooks plus real cytoscape/DOM
// events, so it exercises the same code paths a human reviewer would.  Run it
// after touching anything under src/web/, and after a change to the facts or
// the rules.
//
// `runViewerAudit({ parts: 5 })` limits the part-page sweep to the first
// parts of the picker.

/** Hold every transition still for the length of a measurement.
 *
 *  The geometry pass asks where a control ended up, and a control that slides
 *  there answers with wherever it is mid-slide.  Waiting it out is not enough:
 *  in a document the host never paints - a hidden tab, an embedded pane, a
 *  headless run - the transition does not advance at all, so the thumb stays
 *  at its starting value for ever and the pass reports it as sitting under the
 *  wrong tab.  That was two standing false failures, in exactly the runs where
 *  nobody could look at the screen to know better.
 *
 *  Freezing transitions makes the final value the current value in one frame,
 *  in every host.  It is the layout being checked here, never the animation.
 */
function freezeTransitions() {
  const style = document.createElement('style');
  style.textContent = '*, *::before, *::after '
    + '{ transition: none !important; animation: none !important; }';
  document.head.append(style);
  void document.body.offsetHeight; // force the frozen values to be computed
  return () => style.remove();
}

window.runViewerAudit = async function runViewerAudit(options = {}) {
  if (window.tempCompare) return withGeometry(auditComparePage());
  if (document.getElementById('part-select') && window.tempVisual) {
    const results = await auditPartPage(options);
    results.push(await auditSimilarityApi());
    return withGeometry(results);
  }
  if (document.getElementById('view-tabs')) return withGeometry(auditLauncherPage());
  throw new Error('runViewerAudit: not a page of this interface');
};

/** Every page gets the geometry pass, last, once its own checks have run.
 *
 *  Geometry can only be read off what is on screen, so where a page keeps
 *  several views behind one control every view is brought up in turn and the
 *  reviewer's own choice is put back.  Without that the pass would only ever
 *  measure the view that happens to open first, which is the one that has
 *  never been the broken one. */
async function withGeometry(pending) {
  const results = await pending;
  const thaw = freezeTransitions();
  try {
    const tabs = [...document.querySelectorAll('#view-tabs button[data-view]')];
    if (!tabs.length) {
      results.push(auditGeometry());
      return results;
    }
    const chosen = tabs.find((tab) => tab.getAttribute('aria-selected') === 'true') || tabs[0];
    for (const tab of tabs) {
      tab.click();
      await settled();
      const pass = auditGeometry();
      pass.partId = `(geometry ${tab.dataset.view})`;
      results.push(pass);
    }
    chosen.click();
    await settled();
    return results;
  } finally {
    thaw();
  }
}

/** Wait until the boxes stop moving.
 *
 *  A view switch slides the thumb over a fifth of a second, and measuring
 *  part way through reports it as sitting under the wrong tab.  Rather than
 *  copy that duration out of the stylesheet -- where it can change without
 *  anyone thinking of this file -- watch the geometry itself.  Two equal
 *  frames are not enough: the embedded browser pane holds the thumb still
 *  for a few frames *before* the transition starts, which reads as settled
 *  and the pass then measures the old position.  So the geometry must hold
 *  still for a stretch of wall time longer than any trigger-to-movement
 *  latency -- a property of render scheduling, not of the stylesheet.
 *
 *  The geometry pass freezes transitions before it calls this (see
 *  freezeTransitions), so what is being waited out there is the relayout a
 *  view switch causes, not a slide. */
async function settled(limit = 80) {
  let previous = null;
  let heldSince = performance.now();
  for (let i = 0; i < limit; i += 1) {
    const boxes = [...document.querySelectorAll('.seg-thumb')]
      .map((element) => {
        const box = element.getBoundingClientRect();
        return `${box.left.toFixed(1)},${box.width.toFixed(1)}`;
      })
      .join('|');
    const now = `${boxes}#${document.body.scrollHeight}x${document.body.scrollWidth}`;
    if (now !== previous) {
      previous = now;
      heldSince = performance.now();
    } else if (performance.now() - heldSince >= 150) {
      return;
    }
    await frame();
  }
}

async function auditPartPage(options = {}) {
  const results = [];
  const select = document.getElementById('part-select');
  const allIds = [...select.options].map((option) => option.value);
  const partIds = options.parts ? allIds.slice(0, options.parts) : allIds;

  const indexPayload = await fetch('api/index', { cache: 'no-store' }).then((r) => r.json());
  const meta = new Map((indexPayload.parts || []).map((part) => [part.partId, part]));

  for (const partId of partIds) {
    select.value = partId;
    select.dispatchEvent(new Event('change'));
    await waitFor(() => window.tempVisual.model && window.tempVisual.model.partId === partId, 20000);
    await frame();

    const tv = window.tempVisual;
    const model = tv.model;
    const store = tv.store;
    const failures = [];

    // ---- 0. counts that match the index ------------------------------------
    const row = meta.get(partId) || {};
    if (model.nodes.length !== row.featureCount) {
      failures.push(`view has ${model.nodes.length} nodes, the index says ${row.featureCount}`);
    }
    if (model.edges.length !== row.relationCount) {
      failures.push(`view has ${model.edges.length} edges, the index says ${row.relationCount}`);
    }

    // ---- 1. mesh <-> raw CAD face count -----------------------------------
    const meshFaceIds = Object.keys(tv.viewer.debugFaces()).map(Number).sort((a, b) => a - b);
    if (meshFaceIds.length !== model.stats.rawCadFaceCount) {
      failures.push(`mesh count ${meshFaceIds.length} != rawCadFaceCount ${model.stats.rawCadFaceCount}`);
    }
    for (const cadFaceId of meshFaceIds) {
      if (!model.faceById.has(cadFaceId)) failures.push(`mesh face ${cadFaceId} has no face row`);
    }

    // ---- 2. the data's own display defaults are honoured -------------------
    for (const type of model.defaultHiddenFeatureTypes) {
      if (!store.get().hiddenTypes.has(type)) failures.push(`${type} not hidden by default`);
    }
    const visibleEdgeTypes = store.get().visibleEdgeTypes;
    for (const entry of model.relationTypes) {
      if (entry.defaultVisible && !visibleEdgeTypes.has(entry.edgeType)) {
        failures.push(`${entry.edgeType} should start visible`);
      }
      if (!entry.defaultVisible && visibleEdgeTypes.has(entry.edgeType)) {
        failures.push(`${entry.edgeType} should start hidden`);
      }
    }
    // The background layer is whatever the *data* names as hidden by default;
    // the audit must not carry a class name of its own for it, or it silently
    // stops checking anything the day the display source changes.
    const background = new Set(model.defaultHiddenFeatureTypes);
    const shownNodes = tv.graph.cy.nodes('[!isGroup]').map((element) => element.id());
    const shownNodesSet = new Set(shownNodes);
    for (const nodeId of shownNodes) {
      if (background.has(model.nodeById.get(nodeId).featureType)) {
        failures.push(`background node ${nodeId} visible in graph`);
      }
    }

    // ---- 3. relation edges are copied, never invented ----------------------
    const knownEdgeIds = new Set(model.edges.map((edge) => edge.edgeId));
    tv.graph.cy.edges().forEach((element) => {
      if (!knownEdgeIds.has(element.id())) failures.push(`edge ${element.id()} not in the part bundle`);
      if (!shownNodesSet.has(element.data('source')) || !shownNodesSet.has(element.data('target'))) {
        failures.push(`edge ${element.id()} touches a hidden node`);
      }
      if (!visibleEdgeTypes.has(element.data('edgeType'))) {
        failures.push(`edge ${element.id()} drawn for a switched-off relation type`);
      }
    });

    // ---- 4. feature -> CAD highlight ---------------------------------------
    let featureChecks = 0;
    for (const node of model.nodes) {
      tv.callbacks.onPickFeature(node.nodeId);
      const faces = tv.viewer.debugFaces();
      // Relation neighbours receive a deliberately weaker context glow.  The
      // feature audit is about the primary selection, so inspect the semantic
      // highlight role rather than deriving strength from feature RGB values.
      const lit = Object.keys(faces)
        .filter((id) => faces[id].highlightRole === 'primary')
        .map(Number)
        .sort((a, b) => a - b);
      const expected = [...node.cadFaceIds].sort((a, b) => a - b);
      if (lit.join(',') !== expected.join(',')) {
        failures.push(`feature ${node.nodeId}: lit [${lit}] != owned [${expected}]`);
      }
      featureChecks += 1;
    }
    tv.callbacks.onPickFeature(null);

    // ---- 4b. the derived block renders apart from the attributes -----------
    //
    // A quantity this pipeline measured must never appear where a value the
    // recogniser stated would.  On the page that means its own
    // section: every key of a node's `derived` block shows up under "Derived"
    // and none of them under "Attributes".
    let derivedChecks = 0;
    for (const node of model.nodes.filter((item) => item.derived
        && Object.keys(item.derived).length)) {
      tv.callbacks.onPickFeature(node.nodeId);
      const named = (heading) => {
        const section = [...document.querySelectorAll('.insp-section')]
          .find((element) => (element.querySelector('h3') || {}).textContent === heading);
        return section ? section.textContent : '';
      };
      const derived = named('Derived');
      const attributes = named('Attributes');
      for (const key of Object.keys(node.derived)) {
        derivedChecks += 1;
        if (!derived.includes(key)) failures.push(`${node.nodeId}: ${key} is not in the Derived section`);
        if (attributes.includes(key)) failures.push(`${node.nodeId}: ${key} leaked into Attributes`);
      }
    }
    tv.callbacks.onPickFeature(null);

    // ---- 5. CAD face -> feature reverse selection --------------------------
    let claimedChecks = 0;
    let unclaimedChecks = 0;
    let mergedChecks = 0;
    for (const cadFaceId of model.faceIds) {
      tv.callbacks.onPickFace(cadFaceId);
      const row = model.faceById.get(cadFaceId);
      const resolved = tv.resolveSelection();

      if (!resolved.primaryFaceIds.has(cadFaceId)) {
        failures.push(`face ${cadFaceId}: not primary after pick`);
      }
      const graphSelected = tv.graph.cy.nodes('.sel').map((element) => element.id()).sort();
      const expectedSelected = row.featureIds
        .filter((featureId) => shownNodes.includes(featureId))
        .sort();

      if (row.featureIds.length) {
        claimedChecks += 1;
        // A hidden-type owner is legitimately absent from the graph, but the
        // inspector must still name it.
        if (graphSelected.join(',') !== expectedSelected.join(',')) {
          failures.push(`face ${cadFaceId}: graph sel [${graphSelected}] != [${expectedSelected}]`);
        }
        const faceStates = tv.viewer.debugFaces();
        const lit = Object.keys(faceStates).filter((id) => faceStates[id].lit);
        if (!lit.map(Number).includes(cadFaceId)) failures.push(`face ${cadFaceId}: not lit after pick`);
      } else {
        unclaimedChecks += 1;
        if (graphSelected.length) failures.push(`unclaimed face ${cadFaceId} selected graph node(s)`);
        const title = document.querySelector('.insp-title .id');
        if (!title) failures.push(`unclaimed face ${cadFaceId}: inspector empty`);
      }

      if (row.mergedCadFaceIds.length > 1) {
        mergedChecks += 1;
        for (const sibling of row.mergedCadFaceIds) {
          if (!resolved.allFaceIds.has(sibling)) {
            failures.push(`face ${cadFaceId}: merged sibling ${sibling} not highlighted`);
          }
        }
      }
    }
    tv.callbacks.onPickFace(null);

    // ---- 6. relation edge -> witness CAD highlight -----------------------
    // Expose every relation type *and* every feature type.  Enabling the edge
    // types alone is not enough: an edge is only drawn when both endpoints
    // survive the node filter, and the background layer is hidden by default,
    // which is exactly where most LOCATED_ON edges terminate.
    const previousEdgeTypes = store.get().visibleEdgeTypes;
    const previousHiddenTypes = store.get().hiddenTypes;
    store.update({
      visibleEdgeTypes: new Set(model.relationTypes.map((entry) => entry.edgeType)),
      hiddenTypes: new Set(),
    });
    await frame();
    let edgeChecks = 0;
    let witnessChecks = 0;
    for (const edge of model.edges) {
      tv.callbacks.onPickEdge(edge.edgeId);
      const resolved = tv.resolveSelection();
      if (resolved.kind !== 'edge' || resolved.focusEdgeId !== edge.edgeId) {
        failures.push(`edge ${edge.edgeId}: selection did not resolve as edge`);
      }
      const selectedEdges = tv.graph.cy.edges('.sel').map((element) => element.id());
      if (selectedEdges.includes(edge.edgeId) === false) {
        failures.push(`edge ${edge.edgeId}: graph edge not selected`);
      }
      const faceState = tv.viewer.debugFaces();
      for (const reference of edge.evidenceFaceRefs || []) {
        for (const cadFaceId of reference.cadFaceIds || []) {
          witnessChecks += 1;
          if (!faceState[cadFaceId] || !faceState[cadFaceId].lit) {
            failures.push(`edge ${edge.edgeId}: witness cad face ${cadFaceId} not highlighted`);
          }
        }
      }
      edgeChecks += 1;
    }
    tv.callbacks.onPickEdge(null);

    // ---- 6b. an edge is drawn only when both endpoints are visible --------
    // The contract the check above silently assumed away.  Hide one feature
    // type again and every edge touching it must leave the graph.
    let endpointVisibilityChecks = 0;
    const hiddenProbe = model.nodes.find((node) => (model.incidentEdges.get(node.nodeId) || []).length);
    if (hiddenProbe) {
      store.update({ hiddenTypes: new Set([hiddenProbe.featureType]) });
      await frame();
      const drawn = new Set(tv.graph.cy.edges().map((element) => element.id()));
      for (const edge of model.edges) {
        const touchesHidden = [edge.source, edge.target].some((nodeId) => {
          const node = model.nodeById.get(nodeId);
          return node && node.featureType === hiddenProbe.featureType;
        });
        if (touchesHidden && drawn.has(edge.edgeId)) {
          failures.push(`edge ${edge.edgeId}: drawn although an endpoint type is hidden`);
        }
        endpointVisibilityChecks += 1;
      }
    }
    store.update({ visibleEdgeTypes: previousEdgeTypes, hiddenTypes: previousHiddenTypes });
    await frame();

    // ---- 7. feature relation context glow -------------------------------
    // The context is derived from the currently enabled edge types, not from
    // a relation-name branch.  Pick a visible, face-bearing feature with a
    // visible, face-bearing relation neighbour so both positive and
    // switched-off cases are exercised on every suitable part.
    const contextCandidate = model.nodes.find((node) => {
      if (background.has(node.featureType) || !node.cadFaceIds.length) return false;
      return (model.incidentEdges.get(node.nodeId) || []).some((edge) => {
        const neighbourId = edge.source === node.nodeId ? edge.target : edge.source;
        const neighbour = model.nodeById.get(neighbourId);
        return neighbour
          && !background.has(neighbour.featureType)
          && neighbour.cadFaceIds.length;
      });
    });
    let relationContextChecks = 0;
    if (contextCandidate) {
      const contextTypes = new Set(
        (model.incidentEdges.get(contextCandidate.nodeId) || []).map((edge) => edge.edgeType),
      );
      // A neighbour's faces, minus any the selected feature owns itself.
      // Two features can own the same raw face - NX's do routinely, a boss
      // and the corner notch that opens onto it share one - and such a face
      // stays lit as the selection's own whatever the relation types say.
      // Counting it as a neighbour face makes the switched-off case below
      // read a correct highlight as a failure.
      const neighbourFaces = new Set();
      for (const edge of model.incidentEdges.get(contextCandidate.nodeId) || []) {
        const neighbourId = edge.source === contextCandidate.nodeId ? edge.target : edge.source;
        const neighbour = model.nodeById.get(neighbourId);
        if (!neighbour || background.has(neighbour.featureType)) continue;
        for (const cadFaceId of neighbour.cadFaceIds || []) {
          if (!contextCandidate.cadFaceIds.includes(cadFaceId)) neighbourFaces.add(cadFaceId);
        }
      }

      store.update({ visibleEdgeTypes: contextTypes });
      tv.callbacks.onPickFeature(contextCandidate.nodeId);
      const resolvedContext = tv.resolveSelection();
      const positiveFaces = tv.viewer.debugFaces();
      const mainStrength = Math.max(...contextCandidate.cadFaceIds.map(
        (cadFaceId) => positiveFaces[cadFaceId]?.emissiveStrength || 0,
      ));
      const weakFaces = [...neighbourFaces].map((cadFaceId) => positiveFaces[cadFaceId]);
      if (!resolvedContext.relationNeighbourFaceIds.size || !weakFaces.length) {
        failures.push(`feature ${contextCandidate.nodeId}: relation context is empty`);
      } else if (weakFaces.some((face) => (
        face?.highlightRole !== 'relation-neighbour'
        || (face.emissiveStrength || 0) <= 0
        || (face.emissiveStrength || 0) >= mainStrength
      ))) {
        failures.push(`feature ${contextCandidate.nodeId}: neighbour glow is not weak`);
      }

      store.update({ visibleEdgeTypes: new Set() });
      const hiddenResolved = tv.resolveSelection();
      const hiddenFaces = tv.viewer.debugFaces();
      if (hiddenResolved.relationNeighbourFaceIds.size) {
        failures.push(`feature ${contextCandidate.nodeId}: hidden relation still resolves neighbours`);
      }
      if ([...neighbourFaces].some((cadFaceId) => (
        hiddenFaces[cadFaceId]?.highlightRole !== 'none'
        || (hiddenFaces[cadFaceId]?.emissiveStrength || 0) !== 0
      ))) {
        failures.push(`feature ${contextCandidate.nodeId}: hidden relation still lights neighbours`);
      }
      relationContextChecks = 1;
      tv.callbacks.onPickFeature(null);
      store.update({ visibleEdgeTypes: previousEdgeTypes });
      await frame();
    }

    // ---- 8. isolate hides everything else ----------------------------------
    // A feature rather than a background face, so isolate is exercised on
    // something the reviewer would actually isolate.
    const sample = model.nodes.find((node) => !background.has(node.featureType)) || model.nodes[0];
    if (sample) {
      tv.callbacks.onPickFeature(sample.nodeId);
      store.update({ isolate: true });
      const faces = tv.viewer.debugFaces();
      for (const [cadFaceId, face] of Object.entries(faces)) {
        const shouldShow = sample.cadFaceIds.includes(Number(cadFaceId));
        if (face.visible !== shouldShow) failures.push(`isolate: face ${cadFaceId} visible=${face.visible}`);
      }
      store.update({ isolate: false, selection: null });
    }

    // ---- 9. heuristic verdicts render and address real geometry -----------
    // The panel must be able to show every verdict of the part and every
    // verdict must name identities the page can resolve; a verdict pointing
    // at a node or edge the viewer does not know would be a broken drill-down.
    let heuristicChecks = 0;
    let heuristicSquareChecks = 0;
    const payload = model.heuristics;
    if (payload) {
      for (const record of payload.records) {
        heuristicChecks += 1;
        if (!payload.heuristics[record.hId]) {
          failures.push(`heuristic ${record.hId}: verdict without a catalogue entry`);
        }
        for (const nodeId of record.targets.nodeIds || []) {
          if (!model.nodeById.has(nodeId)) {
            failures.push(`heuristic ${record.hId}: verdict names unknown node ${nodeId}`);
          }
        }
        for (const edgeId of record.targets.edgeIds || []) {
          if (!model.edgeById.has(edgeId)) {
            failures.push(`heuristic ${record.hId}: verdict names unknown edge ${edgeId}`);
          }
        }
      }

      // Default view: one square per *evaluated* unit.  Not-applicable
      // verdicts are counted, never drawn — they say the rule does not talk
      // about that instance, which is not a result to scan for.
      store.update({
        selection: null,
        heuristicFocus: null,
        heuristicsFailsOnly: false,
        heuristicsPickedOnly: false,
      });
      await frame();
      const evaluated = payload.records.filter((record) => record.outcome !== 'NOT_APPLICABLE');
      const drawn = () => document.querySelectorAll('#heuristics .heur-squares .heur-sq').length;
      if (drawn() !== evaluated.length) {
        failures.push(`heuristic panel draws ${drawn()} squares for ${evaluated.length} evaluated verdicts`);
      }
      heuristicSquareChecks = drawn();

      // Selecting geometry must *not* change what the panel lists; it only
      // marks the squares that talk about the selection.
      const probe = model.nodes.find(
        (node) => evaluated.some((record) => (record.targets.nodeIds || []).includes(node.nodeId)),
      );
      if (probe) {
        tv.callbacks.onPickFeature(probe.nodeId);
        await frame();
        if (drawn() !== evaluated.length) {
          failures.push(`heuristic panel: selecting ${probe.nodeId} changed the list to ${drawn()}`);
        }
        const marked = document.querySelectorAll('#heuristics .heur-squares .heur-sq.active').length;
        const about = evaluated.filter(
          (record) => (record.targets.nodeIds || []).includes(probe.nodeId),
        ).length;
        if (marked !== about) {
          failures.push(`heuristic panel: ${probe.nodeId} marks ${marked} squares, expected ${about}`);
        }

        // Only the explicit switch narrows the list.
        store.update({ heuristicsPickedOnly: true });
        await frame();
        if (drawn() !== about) {
          failures.push(`heuristic panel: picked-only shows ${drawn()} of ${about} verdicts`);
        }
        store.update({ heuristicsPickedOnly: false });
        tv.callbacks.onPickFeature(null);
        await frame();
      }

      // The not-met switch must never widen the set.
      store.update({ heuristicsFailsOnly: true });
      await frame();
      const failing = evaluated.filter((record) => record.outcome === 'FAIL').length;
      if (drawn() !== failing) {
        failures.push(`heuristic panel: not-met only shows ${drawn()} of ${failing} verdicts`);
      }
      store.update({ heuristicsFailsOnly: false });
      await frame();
    }

    // ---- 9b. the KPI panel: one group per KPI a not-met rule pushes on ------
    // Derived from the verdicts and the rule definitions of the part, never
    // from a KPI name.
    let kpiChecks = 0;
    if (payload) {
      const pushed = new Set();
      for (const record of payload.records) {
        if (record.outcome !== 'FAIL') continue;
        for (const kpiId of (payload.heuristics[record.hId] || {}).affectsKpi || []) pushed.add(kpiId);
      }
      const groups = new Set([...document.querySelectorAll('#heuristics .kpi-group')]
        .map((element) => element.dataset.kpi));
      for (const kpiId of pushed) {
        kpiChecks += 1;
        if (!groups.has(kpiId)) failures.push(`KPI panel has no group for ${kpiId}, which a not-met rule affects`);
      }
      for (const result of model.kpi || []) {
        if (!groups.has(result.kpiType)) failures.push(`KPI panel has no group for computed ${result.kpiType}`);
      }
    }

    results.push({
      partId,
      rawCadFaces: model.stats.rawCadFaceCount,
      meshedFaces: meshFaceIds.length,
      featureNodes: model.nodes.length,
      graphNodes: shownNodes.length,
      graphEdges: tv.graph.cy.edges().length,
      featureChecks,
      derivedChecks,
      claimedFaceChecks: claimedChecks,
      unclaimedFaceChecks: unclaimedChecks,
      mergedFaceChecks: mergedChecks,
      edgeChecks,
      witnessChecks,
      endpointVisibilityChecks,
      relationContextChecks,
      heuristicChecks,
      heuristicSquareChecks,
      kpiChecks,
      failures,
    });
  }

  // ---- 10. store: the part page has its banner slot, and the index knows
  // every part the picker lists (live freshness for each of them).
  const storeFailures = [];
  let storeChecks = 0;
  if (!document.getElementById('store-banner')) storeFailures.push('store banner element missing');
  for (const partId of partIds) {
    storeChecks += 1;
    const row = meta.get(partId);
    if (!row) { storeFailures.push(`the index does not know ${partId}`); continue; }
    if (!row.light) storeFailures.push(`${partId}: no light state`);
    if (!row.factsKey) storeFailures.push(`${partId}: on the picker but the index holds no facts key`);
  }
  results.push({ partId: '(store)', storeChecks, failures: storeFailures });

  return results;
}

// ---- similarity API (launcher and part page) ------------------------------
//
// configs reachable; a ranking of the first part answers with rows whose
// distances lie in [0, 1] and ascend; a pair result carries the edit path
// whose per-direction sums average to the raw cost.
async function auditSimilarityApi() {
  const failures = [];
  let checks = 0;
  const get = async (path) => {
    const response = await fetch(path, { cache: 'no-store' });
    const payload = await response.json().catch(() => ({}));
    return { ok: response.ok, status: response.status, payload };
  };
  try {
    const configs = await get('api/similarity/configs');
    checks += 1;
    if (!configs.ok) failures.push(`configs HTTP ${configs.status}`);
    else {
      if (!Array.isArray(configs.payload.configs) || !configs.payload.configs.length) failures.push('configs: no preset listed');
      if (!configs.payload.default) failures.push('configs: no default preset');
      if (!configs.payload.weights || !Object.keys(configs.payload.weights).length) failures.push('configs: no weight specs');
      if (!configs.payload.representation) failures.push('configs: no representation named');
      // The compare page folds micro edits at the service's own threshold; if
      // the answer stops carrying it the page silently falls back to a
      // number written in its own source, which is what this replaced.
      if (!(Number(configs.payload.microEditCost) >= 0)) failures.push('configs: no micro-edit threshold');
    }
    const index = await get('api/index');
    const ids = (index.payload.parts || []).filter((part) => part.factsKey).map((part) => part.partId);
    if (ids.length >= 2) {
      const rank = await get(`api/similarity/rank?query=${encodeURIComponent(ids[0])}`);
      checks += 1;
      if (!rank.ok) failures.push(`rank HTTP ${rank.status}: ${rank.payload.error || ''}`);
      else {
        const rows = rank.payload.ranked || [];
        if (!rows.length) failures.push('rank: no row');
        let previous = -1;
        for (const row of rows) {
          if (!(row.distance >= 0 && row.distance <= 1)) failures.push(`rank: ${row.partId} distance ${row.distance} outside [0,1]`);
          if (row.distance < previous - 1e-12) failures.push(`rank: ${row.partId} out of order`);
          previous = row.distance;
          if (!row.breakdown || typeof row.breakdown !== 'object') failures.push(`rank: ${row.partId} without breakdown`);
        }
        if (!rank.payload.config || !rank.payload.config.hash) failures.push('rank: no config hash');
      }
      const pair = await get(`api/similarity/compare?a=${encodeURIComponent(ids[0])}&b=${encodeURIComponent(ids[1])}`);
      checks += 1;
      if (!pair.ok) failures.push(`compare HTTP ${pair.status}: ${pair.payload.error || ''}`);
      else {
        const path = pair.payload.edit_path;
        if (!path || !path.a_to_b || !path.b_to_a) failures.push('compare: edit_path missing a direction');
        else {
          const totals = ['a_to_b', 'b_to_a'].map((direction) => editPathTotal(path[direction]));
          if (Math.abs(0.5 * (totals[0] + totals[1]) - pair.payload.raw_cost) > 1e-6) {
            failures.push(`compare: mean of direction sums ${totals} != raw_cost ${pair.payload.raw_cost}`);
          }
        }
        if (!pair.payload.config || !pair.payload.config.hash) failures.push('compare: no config hash');
      }
    }
  } catch (error) {
    failures.push(`similarity API unreachable: ${error.message}`);
  }
  return { partId: '(similarity)', similarityChecks: checks, failures };
}

function editPathTotal(block) {
  let total = 0;
  for (const value of Object.values(block || {})) {
    const list = Array.isArray(value) ? value : (value && typeof value === 'object' ? [value] : []);
    for (const entry of list) total += Number(entry.cost || 0);
  }
  return total;
}

// ---- home page -------------------------------------------------------------
async function auditLauncherPage() {
  const failures = [];
  let checks = 0;
  const tabs = [...document.querySelectorAll('#view-tabs button[data-view]')];
  for (const tab of tabs) {
    checks += 1;
    if (!document.getElementById(`view-${tab.dataset.view}`)) failures.push(`view-${tab.dataset.view} missing`);
  }
  checks += 1;
  if (tabs.length !== 5) failures.push(`expected 5 view tabs, found ${tabs.length}`);
  const results = [{ partId: '(launcher)', launcherChecks: checks, failures }];
  results.push(await auditLauncherRows());
  results.push(await auditSimilarityApi());
  return results;
}

/** The part list against the index, the statistics view against its answer,
 *  the KPI view against its answer.  Nothing here names a part, a rule or a
 *  KPI: the sweep is over whatever the answers carry. */
async function auditLauncherRows() {
  const failures = [];
  let checks = 0;
  const [index, heuristics, kpi] = await Promise.all(['api/index', 'api/heuristics', 'api/kpi']
    .map((path) => fetch(path, { cache: 'no-store' }).then((r) => r.json())));
  const built = (index.parts || []).filter((part) => part.factsKey);

  const show = async (view) => {
    document.querySelector(`#view-tabs button[data-view="${view}"]`).click();
    await sleep(400);
  };
  const previousView = document.querySelector('#view-tabs button[aria-selected="true"]');

  await show('parts');
  checks += 1;
  if (!document.getElementById('run-line').textContent.includes(`${built.length} parts`)) {
    failures.push(`footer does not state the ${built.length} built parts`);
  }
  checks += 1;
  if (!document.querySelector('.page-foot a[href="ontology.html"]')) failures.push('footer has no Ontology link');
  const sample = built[0];
  if (sample) {
    checks += 1;
    const row = document.querySelector(`#rows .part-row[data-part-id="${CSS.escape(sample.partId)}"]`);
    const cells = row ? row.querySelectorAll('.col-num') : [];
    const features = cells[1] && Number(cells[1].textContent);
    if (features !== sample.featureCount) {
      failures.push(`${sample.partId}: features cell ${features} != index featureCount ${sample.featureCount}`);
    }
    checks += 1;
    if (row && ![...row.querySelectorAll('.col-actions button')].some((button) => button.textContent === 'Similar')) {
      failures.push(`${sample.partId}: row Similar action missing`);
    }
  }

  await show('heuristics');
  const shown = [...document.querySelectorAll('.h-table tbody tr .col-id')]
    .map((cell) => cell.textContent.trim()).filter(Boolean);
  const expected = Object.keys(heuristics.rules || {});
  checks += 1;
  if (shown.length !== expected.length) {
    failures.push(`rule table lists ${shown.length} heuristics, the answer defines ${expected.length}`);
  }
  const matrixRows = document.querySelectorAll('.matrix tbody tr').length;
  checks += 1;
  if (matrixRows !== (heuristics.parts || []).length) {
    failures.push(`matrix has ${matrixRows} part rows, the answer ${(heuristics.parts || []).length}`);
  }
  for (const tr of document.querySelectorAll('.h-table tbody tr')) {
    const hId = (tr.querySelector('.col-id') || {}).textContent;
    if (!hId) continue;
    checks += 1;
    const chips = [...tr.querySelectorAll('.col-kpi .kpi-chip')].map((chip) => chip.dataset.kpi);
    const declared = ((heuristics.rules || {})[hId.trim()] || {}).affectsKpi || [];
    if (chips.join(',') !== declared.join(',')) failures.push(`${hId}: affects-KPI chips [${chips}] != [${declared}]`);
  }

  await show('kpi');
  await waitFor(() => document.querySelector('#view-kpi .kpi-table'), 10000);
  checks += 1;
  const columns = document.querySelectorAll('#view-kpi .kpi-table thead th.kpi-col').length;
  if (columns !== (kpi.kpiTypes || []).length) {
    failures.push(`KPI table has ${columns} KPI columns, the answer ${(kpi.kpiTypes || []).length}`);
  }
  checks += 1;
  const kpiRows = document.querySelectorAll('#view-kpi .kpi-table tbody tr').length;
  if (kpiRows !== (kpi.parts || []).length) failures.push(`KPI table has ${kpiRows} rows, the answer ${(kpi.parts || []).length}`);

  if (previousView) previousView.click();
  await frame();
  return { partId: '(home views)', rowChecks: checks, failures };
}

// ---- compare page ----------------------------------------------------------
//
// Both views render their part; the edit path lists every non-micro entry of
// the shown direction; selecting an entry lights exactly the named features
// on the named sides (a delete only on the left, an insert only on the
// right); the micro switch changes what is listed, never the totals.
async function auditComparePage() {
  const tc = window.tempCompare;
  const failures = [];
  let checks = 0;
  await waitFor(() => tc.state.payload && tc.sides.a.model && tc.sides.b.model, 20000);
  await frame();
  for (const key of ['a', 'b']) {
    const side = tc.sides[key];
    const faces = Object.keys(side.viewer.debugFaces()).length;
    checks += 1;
    if (faces !== side.model.stats.rawCadFaceCount) failures.push(`view ${key}: ${faces} meshes for ${side.model.stats.rawCadFaceCount} faces`);
  }
  if (!document.querySelector('#score .score-item.main')) failures.push('score strip without the main score');

  const payload = tc.state.payload;
  const direction = tc.state.direction;
  const block = payload.edit_path[direction];
  const listedCount = () => document.querySelectorAll('#path .cmp-entry').length;
  const allEntries = Object.values(block).flatMap((value) => (Array.isArray(value) ? value : [value]));
  tc.setMicro(false);
  await frame();
  checks += 1;
  if (listedCount() !== allEntries.length) failures.push(`edit path lists ${listedCount()} of ${allEntries.length} entries with micro folding off`);
  tc.setMicro(true, 1e-3);
  await frame();
  const expectedShown = allEntries.filter((entry) => Number(entry.cost || 0) >= 1e-3).length;
  checks += 1;
  if (listedCount() !== expectedShown) failures.push(`edit path lists ${listedCount()} of ${expectedShown} entries with micro folding on`);
  const totals = document.querySelector('#path .cmp-totals');
  if (!totals || totals.classList.contains('mismatch')) failures.push('per-direction sums do not match the raw cost');

  // Highlight per side for a few entries of each kind.
  const lit = (key) => Object.entries(tc.sides[key].viewer.debugFaces())
    .filter(([, face]) => face.highlightRole === 'primary').map(([id]) => Number(id)).sort((x, y) => x - y);
  const expectedFaces = (key, ids) => {
    const out = new Set();
    for (const id of ids) {
      const node = tc.sides[key].model.nodeById.get(id);
      for (const face of (node && node.cadFaceIds) || []) out.add(face);
    }
    return [...out].sort((x, y) => x - y);
  };
  const seen = new Set();
  let highlightChecks = 0;
  for (let index = 0; index < tc.state.entries.length; index += 1) {
    const item = tc.state.entries[index];
    const kind = `${item.group.key}`;
    if (seen.has(kind) && highlightChecks > 12) continue;
    seen.add(kind);
    tc.selectEntry(index);
    await frame();
    highlightChecks += 1;
    for (const [key, ids] of [['a', item.left], ['b', item.right]]) {
      const expected = expectedFaces(key, ids);
      const actual = lit(key);
      if (expected.join(',') !== actual.join(',')) {
        failures.push(`${kind} #${index}: side ${key} lit [${actual}] expected [${expected}]`);
      }
    }
  }
  tc.selectEntry(null);
  await frame();
  return [{
    partId: `(compare ${tc.sides.a.partId} vs ${tc.sides.b.partId})`,
    compareChecks: checks,
    highlightChecks,
    entries: tc.state.entries.length,
    failures,
  }];
}

function frame() {
  // setTimeout, not requestAnimationFrame: a background/hidden tab never fires
  // rAF and the audit would hang forever.
  return new Promise((resolve) => setTimeout(resolve, 40));
}

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

async function waitFor(predicate, timeout = 10000) {
  const start = performance.now();
  while (!predicate()) {
    if (performance.now() - start > timeout) throw new Error('timeout waiting for condition');
    await new Promise((resolve) => setTimeout(resolve, 30));
  }
}

// Does the picture fit in its box?
//
// Everything above asks whether what is drawn agrees with what was recorded.
// That is half the question, and it is the half that keeps passing while the
// page is visibly broken: a panel squeezed to a fifth of its height still
// holds the right numbers, a slider drawn across the wrong element is still
// one of three tabs, a canvas a quarter too large for its pane still renders
// the right model.  All three shipped.  These checks read geometry only, and
// none of them knows the name of a single feature, relation or rule.
function auditGeometry() {
  const failures = [];
  let checks = 0;

  // The page scrolls down, never sideways.
  checks += 1;
  const root = document.documentElement;
  const sideways = root.scrollWidth - root.clientWidth;
  if (sideways > 1) failures.push(`the page scrolls sideways by ${sideways}px`);

  // An element that hides its overflow and is overflowed anyway is holding
  // content nobody can reach.  A one-line ellipsis is the legitimate use of
  // the same declaration, and it excludes itself by its own two properties
  // rather than by a list of class names.
  for (const element of document.querySelectorAll('*')) {
    const style = getComputedStyle(element);
    if (style.overflowY !== 'hidden' || style.display === 'none') continue;
    if (style.textOverflow === 'ellipsis' && style.whiteSpace === 'nowrap') continue;
    if (!element.clientHeight) continue;
    checks += 1;
    const cut = element.scrollHeight - element.clientHeight;
    if (cut > 2) failures.push(`${describeElement(element)} clips ${cut}px of its own content`);
  }

  // A segmented control's thumb is one segment wide, sits inside the control
  // it belongs to, and sits under the tab that is selected.  The width is
  // derived from the control's own box rather than from the stylesheet's
  // numbers, so padding and border can change without touching this.
  for (const seg of document.querySelectorAll('.segmented')) {
    const thumb = seg.querySelector('.seg-thumb');
    const buttons = [...seg.querySelectorAll('button')];
    const box = seg.getBoundingClientRect();
    if (!thumb || !buttons.length || !box.width) continue;
    const style = getComputedStyle(seg);
    const inner = box.width
      - parseFloat(style.borderLeftWidth) - parseFloat(style.borderRightWidth)
      - parseFloat(style.paddingLeft) - parseFloat(style.paddingRight);
    const segments = Number(style.getPropertyValue('--segments')) || buttons.length;
    const thumbBox = thumb.getBoundingClientRect();
    const expected = inner / segments;

    checks += 3;
    if (Math.abs(thumbBox.width - expected) > 2) {
      failures.push(`${describeElement(seg)}: thumb is ${thumbBox.width.toFixed(0)}px where one of `
        + `${segments} segments is ${expected.toFixed(0)}px`);
    }
    if (thumbBox.left < box.left - 1 || thumbBox.right > box.right + 1) {
      failures.push(`${describeElement(seg)}: thumb is drawn outside its own control`);
    }
    const active = buttons[Number(seg.dataset.active) || 0];
    const activeBox = active && active.getBoundingClientRect();
    const centre = (thumbBox.left + thumbBox.right) / 2;
    if (activeBox && (centre < activeBox.left || centre > activeBox.right)) {
      failures.push(`${describeElement(seg)}: thumb is not under "${active.textContent.trim()}"`);
    }
  }

  return { partId: '(geometry)', geometryChecks: checks, failures };
}

/** Enough of an element to find it in the sheet, and no more. */
function describeElement(element) {
  const id = element.id ? `#${element.id}` : '';
  const classes = typeof element.className === 'string' && element.className.trim()
    ? '.' + element.className.trim().split(/\s+/).join('.')
    : '';
  return (element.tagName.toLowerCase() + id + classes).slice(0, 70);
}

// Second audit: does the auto-view land somewhere the feature is actually
// exposed?  "Exposed" is measured as the share of the feature's own surface
// samples whose first hit from the camera is a face of that same feature —
// the right question for concave features, where a ray aimed at the centroid
// of a bore correctly passes straight through.
window.runAutoViewAudit = async function runAutoViewAudit() {
  const results = [];
  const select = document.getElementById('part-select');
  const partIds = [...select.options].map((option) => option.value);

  for (const partId of partIds) {
    select.value = partId;
    select.dispatchEvent(new Event('change'));
    await waitFor(() => window.tempVisual.model && window.tempVisual.model.partId === partId);
    await frame();

    const tv = window.tempVisual;
    const model = tv.model;
    const baseline = tv.viewer.cameraGoal();  // the default fitted view

    let improved = 0;
    let same = 0;
    let worse = 0;
    let beforeTotal = 0;
    let afterTotal = 0;
    let zeroAfter = 0;
    const regressions = [];

    for (const node of model.nodes) {
      const samples = tv.viewer.debugSamples(node.cadFaceIds, 20);
      if (!samples.length) continue;

      const before = visibility(tv, node, samples, baseline.position);
      tv.callbacks.onPickFeature(node.nodeId); // first click: select only
      tv.callbacks.onPickFeature(node.nodeId); // second click: move the camera
      const goal = tv.viewer.cameraGoal();
      const after = visibility(tv, node, samples, goal.position);

      beforeTotal += before;
      afterTotal += after;
      if (after > before + 1e-6) improved += 1;
      else if (after < before - 1e-6) { worse += 1; regressions.push(`${node.nodeId} ${before.toFixed(2)}->${after.toFixed(2)}`); }
      else same += 1;
      if (after === 0) zeroAfter += 1;
    }
    tv.callbacks.onPickFeature(null);

    const counted = improved + same + worse;
    results.push({
      partId,
      features: counted,
      meanVisibilityDefaultView: +(beforeTotal / counted).toFixed(3),
      meanVisibilityAutoView: +(afterTotal / counted).toFixed(3),
      improved,
      unchanged: same,
      worse,
      invisibleAfter: zeroAfter,
      regressions: regressions.slice(0, 6),
    });
  }
  return results;
};

/** Share of a feature's surface samples the camera can actually see. */
function visibility(tv, node, samples, cameraPosition) {
  const owned = new Set(node.cadFaceIds);
  let seen = 0;
  for (const sample of samples) {
    const hit = tv.viewer.probeFace(cameraPosition, sample.point);
    if (hit !== null && owned.has(hit)) seen += 1;
  }
  return seen / samples.length;
}
