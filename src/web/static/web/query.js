// Query view of the launcher page: a section on top to ask in plain English,
// then the preset questions on the left, a read-only SPARQL editor and the
// store's answer in the middle, and the vocabulary a query can use on the
// right.
//
// The endpoint behind it is read-only and says so: a request that uses an
// update keyword is refused before the store is asked anything, and the
// refusal names the keyword.  The vocabulary is names and values only; a
// click puts the name into the editor at the cursor.
//
// The section on top drafts a query from a question in plain English with an
// external language model (api/draft-query).  It belongs to no preset
// question: the draft fills the editor and nothing runs until Run is pressed.
// The question line is offered when the server says a model is configured
// (api/status -> llm.available); the Settings popover reads and writes
// api/settings, which never answers the key itself, only a masked form of it.

import { escapeHtml } from './html.js';
import { installMenus } from './menu.js';

const VOCAB_KEY = 'cncgaideVocabularyOpen';

export function createQuery(root) {
  let built = false;
  let questions = [];
  let lastResult = null;
  const elements = {};

  async function render() {
    if (built) return;
    built = true;
    build();
    refreshDraftState();
    try {
      const [cq, vocabulary] = await Promise.all([
        getJson('api/cq'),
        getJson('api/vocabulary'),
      ]);
      questions = cq.questions || [];
      renderList();
      renderVocabulary(vocabulary);
      const wanted = new URLSearchParams(location.search).get('cq');
      const first = questions.find((question) => question.id === wanted) || questions[0];
      if (first) choose(first, true);
    } catch (error) {
      status(error.message, true);
    }
  }

  function build() {
    root.innerHTML = '';
    const ask = document.createElement('section');
    ask.className = 'pane query-ask';
    ask.innerHTML = `
      <div class="pane-head">
        <span class="heur-title">Ask in plain English</span>
        <details class="menu draft-settings">
          <summary class="btn-text" title="The language model that drafts queries">Settings</summary>
          <div class="menu-list draft-pop">
            <div class="draft-pop-title">Language model</div>
            <label class="draft-field"><span>API key</span>
              <input class="set-key" type="password" autocomplete="off" spellcheck="false"></label>
            <div class="draft-meta set-key-now"></div>
            <label class="draft-field"><span>Base URL</span>
              <input class="set-url" type="text" spellcheck="false" placeholder="https://api.deepseek.com"></label>
            <div class="draft-meta">Any OpenAI-compatible chat completions endpoint.</div>
            <label class="draft-field"><span>Model</span>
              <input class="set-model" type="text" spellcheck="false" placeholder="deepseek-chat"></label>
            <div class="draft-meta set-env" hidden></div>
            <div class="draft-pop-actions">
              <button class="btn set-save" type="button">Save</button>
              <button class="btn-text set-clear" type="button">Clear key</button>
              <span class="draft-meta set-status"></span>
            </div>
          </div>
        </details>
      </div>
      <div class="ask-body">
        <div class="draft-row" hidden>
          <input class="draft-input" type="text" spellcheck="false" maxlength="2000"
            placeholder="e.g. which parts hold the most pockets?"
            aria-label="Question in plain English">
          <button class="btn draft-go" type="button">Draft query</button>
        </div>
        <div class="draft-empty" hidden></div>
        <div class="draft-out" hidden><span class="draft-note"></span><span class="draft-model"></span></div>
      </div>`;
    root.append(ask);
    const layout = document.createElement('div');
    layout.className = 'query-layout';
    layout.innerHTML = `
      <section class="pane query-questions">
        <div class="pane-head"><span class="heur-title">Questions</span></div>
        <div class="cq-list"></div>
      </section>
      <section class="pane query-main">
        <div class="pane-head">
          <span class="heur-title query-title">SPARQL</span>
        </div>
        <div class="query-editor-wrap">
          <textarea class="query-editor" spellcheck="false" aria-label="SPARQL query"></textarea>
          <div class="query-actions">
            <button class="btn-primary query-run" type="button" title="Run the query (Ctrl+Enter)">Run</button>
            <button class="btn query-csv" type="button" disabled>Download CSV</button>
            <span class="query-status"></span>
          </div>
        </div>
        <div class="result-wrap"></div>
      </section>
      <details class="pane query-vocab">
        <summary class="pane-head"><span class="heur-title">Vocabulary</span></summary>
        <div class="vocab-body"></div>
      </details>`;
    root.append(layout);
    elements.list = layout.querySelector('.cq-list');
    elements.editor = layout.querySelector('.query-editor');
    elements.run = layout.querySelector('.query-run');
    elements.download = layout.querySelector('.query-csv');
    elements.status = layout.querySelector('.query-status');
    elements.result = layout.querySelector('.result-wrap');
    elements.title = layout.querySelector('.query-title');
    elements.vocab = layout.querySelector('.query-vocab');
    elements.vocabBody = layout.querySelector('.vocab-body');
    elements.draftRow = ask.querySelector('.draft-row');
    elements.draftInput = ask.querySelector('.draft-input');
    elements.draftGo = ask.querySelector('.draft-go');
    elements.draftEmpty = ask.querySelector('.draft-empty');
    elements.draftOut = ask.querySelector('.draft-out');
    elements.draftNote = ask.querySelector('.draft-note');
    elements.draftModel = ask.querySelector('.draft-model');
    elements.settings = ask.querySelector('.draft-settings');
    elements.setKey = ask.querySelector('.set-key');
    elements.setKeyNow = ask.querySelector('.set-key-now');
    elements.setUrl = ask.querySelector('.set-url');
    elements.setModel = ask.querySelector('.set-model');
    elements.setEnv = ask.querySelector('.set-env');
    elements.setSave = ask.querySelector('.set-save');
    elements.setClear = ask.querySelector('.set-clear');
    elements.setStatus = ask.querySelector('.set-status');
    installMenus();
    elements.draftGo.addEventListener('click', draftQuery);
    elements.draftInput.addEventListener('keydown', (event) => {
      if (event.key === 'Enter') draftQuery();
    });
    elements.settings.addEventListener('toggle', () => {
      if (elements.settings.open) loadSettings();
    });
    elements.setSave.addEventListener('click', () => saveSettings(false));
    elements.setClear.addEventListener('click', () => saveSettings(true));
    try { elements.vocab.open = localStorage.getItem(VOCAB_KEY) !== '0'; } catch (error) { elements.vocab.open = true; }
    elements.vocab.addEventListener('toggle', () => {
      try { localStorage.setItem(VOCAB_KEY, elements.vocab.open ? '1' : '0'); } catch (error) { /* not kept */ }
    });

    elements.run.addEventListener('click', run);
    elements.editor.addEventListener('keydown', (event) => {
      if ((event.ctrlKey || event.metaKey) && event.key === 'Enter') run();
    });
    elements.download.addEventListener('click', () => {
      if (!lastResult) return;
      const blob = new Blob([toCsv(lastResult)], { type: 'text/csv' });
      const link = document.createElement('a');
      link.href = URL.createObjectURL(blob);
      link.download = 'query.csv';
      link.click();
      URL.revokeObjectURL(link.href);
    });
  }

  function renderList() {
    elements.list.innerHTML = '';
    for (const question of questions) {
      const button = document.createElement('button');
      button.type = 'button';
      button.className = 'cq-item';
      button.dataset.id = question.id;
      button.innerHTML = `<span class="cq-id">${escapeHtml(question.id)}</span>`
        + escapeHtml(question.question || '');
      button.addEventListener('click', () => choose(question, true));
      elements.list.append(button);
    }
  }

  function choose(question, send) {
    for (const button of elements.list.children) {
      button.classList.toggle('on', button.dataset.id === question.id);
    }
    elements.title.textContent = question.question || question.id;
    elements.editor.value = question.sparql || '';
    if (send) run();
    else status('');
  }

  // ------------------------------------------------------------ vocabulary

  function renderVocabulary(vocabulary) {
    const body = elements.vocabBody;
    body.innerHTML = '';
    const search = document.createElement('input');
    search.type = 'search';
    search.placeholder = 'filter names…';
    search.spellcheck = false;
    body.append(search);

    const groups = [];
    const add = (title, items, open) => {
      const group = document.createElement('details');
      group.className = 'vocab-group';
      group.open = Boolean(open);
      const head = document.createElement('summary');
      head.innerHTML = `${escapeHtml(title)} <span class="vocab-n">${items.length}</span>`;
      const list = document.createElement('div');
      list.className = 'vocab-list';
      for (const item of items) list.append(term(item));
      group.append(head, list);
      body.append(group);
      groups.push({ group, list, open: Boolean(open) });
    };

    add('graphs', (vocabulary.graphs || []).map((name) => ({ insert: `<${name}>`, text: name })), true);
    add('prefixes', Object.entries(vocabulary.prefixes || {}).map(([prefix, iri]) => ({
      insert: `${prefix}:`, text: `${prefix}:`, title: iri })), true);
    add('classes', classTree(vocabulary.classes || []), false);
    add('attributes', (vocabulary.attributes || []).map((name) => ({ insert: `nx:${name}`, text: name })), false);
    add('derived quantities', (vocabulary.derivedQuantities || []).map((name) => ({ insert: `cg:${name}`, text: name })), false);
    add('relation types', (vocabulary.relationTypes || []).map((name) => ({ insert: `cg:${name}`, text: name })), false);
    add('thresholds', (vocabulary.thresholds || []).map((entry) => ({
      insert: `cg:${entry.symbol}`, text: entry.symbol,
      value: `${Array.isArray(entry.value) ? entry.value.join(', ') : entry.value}${entry.unit ? ' ' + entry.unit : ''}`,
    })), false);
    add('heuristics', (vocabulary.heuristics || []).map((name) => ({ insert: `cg:${name}`, text: name })), false);
    add('KPI', (vocabulary.kpiTypes || []).map((entry) => ({
      insert: `cg:${entry.kpiType}`, text: entry.kpiType, title: entry.label || '' })), false);

    search.addEventListener('input', () => {
      const needle = search.value.trim().toLowerCase();
      for (const { group, list, open } of groups) {
        let shown = 0;
        for (const item of list.children) {
          const hit = !needle || item.dataset.name.includes(needle);
          item.hidden = !hit;
          if (hit) shown += 1;
        }
        group.hidden = needle && !shown;
        group.open = needle ? shown > 0 : open;
      }
    });
  }

  /** Classes as a tree: each child indented under its parent. */
  function classTree(classes) {
    const children = new Map();
    const names = new Set(classes.map((entry) => entry.name));
    for (const entry of classes) {
      const parent = entry.parent && names.has(entry.parent) ? entry.parent : null;
      if (!children.has(parent)) children.set(parent, []);
      children.get(parent).push(entry);
    }
    const out = [];
    const walk = (parent, depth) => {
      for (const entry of (children.get(parent) || []).sort((a, b) => a.name.localeCompare(b.name))) {
        out.push({ insert: `nx:${entry.name}`, text: entry.name, depth, title: entry.label || '',
          muted: entry.abstract });
        walk(entry.name, depth + 1);
      }
    };
    walk(null, 0);
    return out;
  }

  function term(item) {
    const button = document.createElement('button');
    button.type = 'button';
    button.className = 'vocab-term' + (item.muted ? ' muted' : '');
    button.dataset.name = item.text.toLowerCase();
    if (item.depth) button.style.paddingLeft = `${6 + item.depth * 10}px`;
    const name = document.createElement('span');
    name.className = 'vocab-name';
    name.textContent = item.text;
    button.append(name);
    if (item.value !== undefined) {
      const value = document.createElement('span');
      value.className = 'vocab-value';
      value.textContent = item.value;
      button.append(value);
    }
    button.title = [item.insert, item.title].filter(Boolean).join('\n');
    button.addEventListener('click', () => insertAtCursor(item.insert));
    return button;
  }

  function insertAtCursor(text) {
    const editor = elements.editor;
    const start = editor.selectionStart ?? editor.value.length;
    const end = editor.selectionEnd ?? start;
    editor.value = editor.value.slice(0, start) + text + editor.value.slice(end);
    editor.focus();
    editor.setSelectionRange(start + text.length, start + text.length);
  }

  // ------------------------------------------------------------ drafting

  /** Offer the draft line when the server says a model is configured. */
  async function refreshDraftState() {
    let llm = { available: false };
    try {
      const answer = await getJson('api/status');
      llm = answer.llm || llm;
      elements.writeApi = answer.writeApi !== false;
    } catch (error) { /* no status: the line stays hidden */ }
    elements.draftRow.hidden = !llm.available;
    elements.draftEmpty.hidden = Boolean(llm.available);
    elements.draftEmpty.textContent = llm.error
      ? `Fill in Settings to draft queries (${llm.error}).`
      : 'Add an API key, a base URL and a model in Settings to draft queries.';
    if (!llm.available) elements.draftOut.hidden = true;
  }

  async function draftQuery() {
    const question = elements.draftInput.value.trim();
    if (!question) {
      draftMessage('Type a question first.', '', true);
      return;
    }
    elements.draftGo.disabled = true;
    draftMessage('drafting…', '', false);
    try {
      const response = await fetch('api/draft-query', {
        method: 'POST',
        cache: 'no-store',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ question }),
      });
      const answer = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(answer.error || `api/draft-query: HTTP ${response.status}`);
      elements.editor.value = answer.sparql || '';
      elements.title.textContent = question;
      // The table below answered another query; it goes until this one runs.
      lastResult = null;
      elements.result.innerHTML = '';
      elements.download.disabled = true;
      for (const button of elements.list.children) button.classList.remove('on');
      draftMessage(answer.note || 'Draft ready.', answer.model || '', false);
      status('Draft in the editor; press Run to ask the store.');
    } catch (error) {
      draftMessage(error.message, '', true);
    } finally {
      elements.draftGo.disabled = false;
    }
  }

  function draftMessage(note, model, isError) {
    elements.draftOut.hidden = false;
    elements.draftOut.classList.toggle('error', Boolean(isError));
    elements.draftNote.textContent = note;
    elements.draftModel.textContent = model;
    elements.draftModel.hidden = !model;
  }

  async function loadSettings() {
    setStatus('');
    elements.setKey.value = '';
    try {
      showSettings((await getJson('api/settings')).llm || {});
    } catch (error) {
      setStatus(error.message, true);
    }
    const writable = elements.writeApi !== false;
    elements.setSave.disabled = !writable;
    elements.setClear.disabled = !writable;
    if (!writable) setStatus('This server was started with the write API off; settings are read-only here.', true);
  }

  function showSettings(llm) {
    elements.setKey.placeholder = llm.hasApiKey ? llm.apiKeyMasked : 'sk-...';
    elements.setKeyNow.textContent = llm.hasApiKey
      ? `Current key ${llm.apiKeyMasked}, from ${llm.source === 'env' ? 'the environment' : 'settings.json'}.`
      : 'No key saved.';
    elements.setUrl.value = llm.baseUrl || '';
    elements.setModel.value = llm.model || '';
    const overrides = llm.envOverrides || [];
    elements.setEnv.hidden = !overrides.length;
    elements.setEnv.textContent = overrides.length
      ? `Set in the environment, which wins over settings.json: ${overrides.join(', ')}.` : '';
  }

  async function saveSettings(clearKey) {
    const llm = clearKey ? { apiKey: '' } : {
      baseUrl: elements.setUrl.value.trim(),
      model: elements.setModel.value.trim(),
    };
    const key = elements.setKey.value.trim();
    if (!clearKey && key) llm.apiKey = key;
    elements.setSave.disabled = true;
    elements.setClear.disabled = true;
    setStatus('saving…');
    try {
      const response = await fetch('api/settings', {
        method: 'POST',
        cache: 'no-store',
        headers: { 'Content-Type': 'application/json', 'X-CNCgAIde-Write': '1' },
        body: JSON.stringify({ llm }),
      });
      const answer = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(answer.error || `api/settings: HTTP ${response.status}`);
      elements.setKey.value = '';
      showSettings(answer.llm || {});
      setStatus(clearKey ? 'Key cleared.' : 'Saved.');
      await refreshDraftState();
    } catch (error) {
      setStatus(error.message, true);
    } finally {
      elements.setSave.disabled = false;
      elements.setClear.disabled = false;
    }
  }

  function setStatus(text, isError) {
    elements.setStatus.textContent = text;
    elements.setStatus.classList.toggle('error', Boolean(isError));
  }

  // ---------------------------------------------------------------- query

  async function run() {
    const sparql = elements.editor.value.trim();
    if (!sparql) {
      status('Type a query, or choose a question.', true);
      return;
    }
    elements.run.disabled = true;
    status('asking the store…');
    try {
      const response = await fetch('api/query', {
        method: 'POST',
        cache: 'no-store',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ sparql }),
      });
      const answer = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(answer.error || `api/query: HTTP ${response.status}`);
      lastResult = answer;
      renderResult(answer);
    } catch (error) {
      lastResult = null;
      elements.result.innerHTML = '';
      elements.download.disabled = true;
      status(error.message, true);
    } finally {
      elements.run.disabled = false;
    }
  }

  function renderResult(answer) {
    elements.result.innerHTML = '';
    if ('boolean' in answer) {
      const div = document.createElement('div');
      div.className = 'empty-state';
      div.textContent = answer.boolean ? 'true' : 'false';
      elements.result.append(div);
      elements.download.disabled = true;
      status(`answered in ${answer.elapsedMs} ms`);
      return;
    }
    const variables = (answer.head && answer.head.vars) || [];
    const rows = (answer.results && answer.results.bindings) || [];
    const table = document.createElement('table');
    table.className = 'result-table';
    const head = document.createElement('thead');
    const headRow = document.createElement('tr');
    for (const name of variables) {
      const th = document.createElement('th');
      th.textContent = name;
      headRow.append(th);
    }
    head.append(headRow);
    const body = document.createElement('tbody');
    for (const binding of rows) {
      const tr = document.createElement('tr');
      for (const name of variables) {
        const td = document.createElement('td');
        td.textContent = cellText(binding[name]);
        if (binding[name] && binding[name].type === 'uri') td.title = binding[name].value;
        tr.append(td);
      }
      body.append(tr);
    }
    table.append(head, body);
    elements.result.append(table);
    if (!rows.length) {
      const div = document.createElement('div');
      div.className = 'empty-state';
      div.textContent = 'No row matched.';
      elements.result.append(div);
    }
    elements.download.disabled = !rows.length;
    status(`${rows.length} row(s) in ${answer.elapsedMs} ms`);
  }

  function status(text, isError) {
    elements.status.textContent = text;
    elements.status.classList.toggle('error', Boolean(isError));
  }

  return { render };
}

async function getJson(url) {
  const response = await fetch(url, { cache: 'no-store' });
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(payload.error || `${url}: HTTP ${response.status}`);
  return payload;
}

/** An IRI is shown by its local name; the full IRI stays in the tooltip. */
function cellText(term) {
  if (!term) return '';
  if (term.type === 'uri') {
    const text = term.value;
    const cut = Math.max(text.lastIndexOf('#'), text.lastIndexOf('/'));
    return cut >= 0 && cut < text.length - 1 ? text.slice(cut + 1) : text;
  }
  return term.value;
}

function toCsv(answer) {
  const variables = (answer.head && answer.head.vars) || [];
  const rows = (answer.results && answer.results.bindings) || [];
  const quote = (value) => `"${String(value).replace(/"/g, '""')}"`;
  const lines = [variables.map(quote).join(',')];
  for (const binding of rows) {
    lines.push(variables.map((name) => quote(binding[name] ? binding[name].value : '')).join(','));
  }
  return lines.join('\n');
}
