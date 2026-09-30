# CNCgAIde NX

A knowledge-graph application for machining features. STEP files go in;
Siemens NX recognises the features; everything the system knows about a part
is stored as RDF in an Apache Jena Fuseki store; the design rules run as
SPARQL on that store; the web interface is a window onto the graph.

Not installed yet? See [install/SETUP.md](install/SETUP.md).

## What it does

For each STEP file in `inputs/`:

1. **Features**, as NX reports them: NX's class names (`STEP2HOLE`,
   `POCKET_CLOSED`, ...), NX's labels, NX's attribute names and values. Nothing
   is renamed, re-cut or re-measured.
2. **Derived quantities** the geometry kernel measures while the part is open:
   remaining floor thickness, minimum wall thickness, minimum clearance.
3. **Relations** between features: coaxial, hole spacing, located on,
   intersects, pocket clearance, slot clearance.
4. **Verdicts** of the design rules, one per feature or feature pair: met, not
   met, or not evaluable with the reason.
5. **KPI results** derived from geometry (minimum required tool length,
   maximum permissible tool diameter), and for every rule the KPIs it affects.

All of this is RDF in named graphs and can be asked with SPARQL, across parts.

## One source

`ontology/nx_v1_1/source/*.yaml` defines the system: NX's classes and
attributes (transcribed from the installed `customization_base.xml`), the
relations, the derived quantities, the thresholds, the rules (each condition is
a SPARQL body), the KPI vocabulary and the display defaults.
`python run.py build` turns the source into the ontology, the SPARQL rules,
the SHACL shapes and a readable single-file page of the whole vocabulary,
`ontology/nx_v1_1/dist/cncgaide_nx_structure.html`, all under
`ontology/nx_v1_1/dist/`. Change a threshold or a rule
in the YAML, build, sync: every part's verdicts are recomputed in seconds. The
NX session runs again only when a STEP file or the NX schema changes.

## Commands

`PY` is the environment's interpreter (see `install/SETUP.md`).

```
PY run.py build                 rebuild the ontology, rules and shapes from the YAML source
PY run.py fuseki start          start the store (Apache Jena Fuseki, http://localhost:3030/nx)
PY run.py sync                  process what is new or changed in inputs/ (add --dry-run to see the plan)
PY run.py rules                 rerun the rules only
PY run.py status                one line per part
PY run.py query "SELECT ..."    run a SPARQL query (prefixes nx:, cg:, rdfs: are preset)
PY run.py check                 SHACL validation of every part's graphs
PY run.py whatif --part ID t_hole_ld=3
                                which verdicts of one part would change under other threshold values;
                                temporary graphs only, nothing is kept
PY run.py ged rank --query ID   rank the parts in the store by graph edit distance to one part
PY run.py ged compare A B       the distance between two parts (add --edit-path for the edit path)
PY run.py ged configs           the cost presets
PY run.py view                  open the web interface (http://localhost:8765)
PY run.py fuseki status         is the store running, and which Java it uses
PY run.py fuseki stop
```

## The web interface

`PY run.py view` serves the pages and opens a browser at
<http://localhost:8765>. Everything it shows is read from the store when it is
asked for; only the 3D meshes come from files, under `runs/mesh/`.

| Page | What it is for |
| --- | --- |
| Home - Parts | One row per part: is it up to date, how many features and relations, what classes it is made of. Add STEP files and run a sync from here |
| Home - Heuristics | Every rule against every part, and per rule its outcomes and the KPI it moves when it is not met |
| Home - Similarity | Rank the corpus against one part; the compare page reads the edit path between two |
| Home - Query | The preset competency questions, a read-only SPARQL editor and the vocabulary; a question in plain English can be drafted into a query |
| Home - KPI | One row per part, one column per KPI: the rules not met that push on it, and the worst computed value |
| Part | The feature graph, the 3D view, every attribute NX published, the verdicts and the KPI panel |

The footer links the ontology page (`ontology/nx_v1_1/dist/cncgaide_nx_structure.html`).

`--port N` moves it, `--no-browser` does not open one, `--no-write-api` refuses
upload, sync and remove from the page, and `--list` / `--stop` / `--replace` deal with
a port another copy is already holding.

### Drafting a query in natural language

In the **Ask in plain English** section at the top of the Query page, type a
question in English and press **Draft query**. A language model writes a
query into the editor; it does not run. Read it, change it if you like, then
press **Run**.

- **Any provider, your choice.** The server talks to any OpenAI-compatible
  chat completions endpoint, a local server that speaks the same protocol
  included. Nothing is preset: DeepSeek (`https://api.deepseek.com`, model
  `deepseek-chat`) is only an example.
- **Configure it in the page.** The **Settings** button of that section takes
  three things, all required: an API key, a base URL and a model name. They
  are kept in `settings.json` at the repository root, which git ignores
  (`settings.example.json` shows the shape, every field empty). The page only
  ever sees the key masked. Optionally, the environment variables
  `CNCGAIDE_LLM_API_KEY`, `CNCGAIDE_LLM_BASE_URL` and `CNCGAIDE_LLM_MODEL`
  override the file. Until all three are set the question line is not offered.
- **Reasoning models** spend part of the output budget on thinking before they
  answer; if one runs out before it writes the query, the page says so.
- **What the model sees**: the layout of the graphs (the Namespaces, Graphs,
  Facts graph, Derived graph and Ontology graph sections of
  `src/web/graph_model.md`), the vocabulary the Query page lists, the preset
  questions with their SPARQL as examples, the rules for writing a query
  here, and your question.
- **What it does not see**: the store, any result, any part, any file. It
  only drafts; it cannot run anything. A draft that is not a single SELECT or
  ASK query is refused with the reason, and never repaired behind your back.

## Where things are

| Path | What |
| --- | --- |
| `inputs/` | Your STEP files |
| `ontology/nx_v1_1/source/` | The definition of the system: eight YAML files |
| `ontology/nx_v1_1/dist/` | Built from the source: `cncgaide_nx.ttl`, `shapes.ttl`, `rules/*.ru`, `cncgaide_nx_structure.html` (open it to read the vocabulary) |
| `ontology/nx_v1_1/build/` | The build chain and the one-off bootstrap that transcribes the NX schema |
| `src/nxline/` | The NX side: translation, the journal that runs inside NX, the kernel services, the projection of NX's answer |
| `src/relations/` | The relation rules (geometry and topology) |
| `src/kg/` | The graph layer: IRIs, the TriG serialiser, the Fuseki client and server lifecycle, ontology loading, rule execution, the sync planner |
| `src/tbox/nx.py` | The YAML source, loaded |
| `src/ged/` | The similarity service: the feature graph read from the store, its costs, the solver, the pair cache |
| `src/web/` | The web interface: the pages under `static/`, the SPARQL that assembles what they read, the server |
| `src/web/graph_model.md` | The graphs, their IRIs and their content; the query drafter reads it |
| `config/competency_questions.yaml` | The questions the store is expected to answer, as SPARQL |
| `settings.json` | This machine's settings, among them the language model's API key; not tracked (template: `settings.example.json`) |
| `runs/tdb2/` | The store's database; `runs/facts/` the TriG files the journal wrote; `runs/prt/` the translation cache; `runs/mesh/` the tessellations the 3D view draws |

Everything under `runs/` is written by the pipeline.
