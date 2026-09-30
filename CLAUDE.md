# CNCgAIde NX - notes for an agent working here

Deploying this for the first time? [install/SETUP.md](install/SETUP.md) is the
procedure. Follow it top to bottom rather than inferring how to install a
Python project, and if a step fails, send the output to whoever gave you this
repository rather than working around it: the package versions in
`install/environment.yml` are verified together, and a substituted one can
install cleanly and answer wrongly. The last step, `install/verify_install.py`,
compares the sample part against a recorded answer; a mismatch there is the
finding, not something to adjust until it passes.

[README.md](README.md) says what the system does, lists the commands and
describes the web interface.
[src/web/graph_model.md](src/web/graph_model.md) says how the graphs are laid
out.

## Running it

`PY` is the environment's interpreter by full path (`install/SETUP.md`, step
1). Using it by full path avoids the commonest mistake, which is running from
a different environment without noticing. Run every command from the
repository root.

```
PY run.py fuseki start
PY run.py sync --dry-run
PY run.py sync
PY run.py view
```

`sync` is incremental: it processes what is new or changed in `inputs/` and
leaves the rest alone; `--dry-run` prints one line per part with the action it
would take (`build`, `rules`, `current`, `remove`). The store and the web
interface each have their own lifecycle; start and stop them through
`run.py`, not through a generic server command:

```
PY run.py view --list
PY run.py view --stop --port 8765
PY run.py fuseki stop
```

If the port is taken, `view` says so instead of silently moving;
`view --replace` takes it over.

Everything under `runs/` is written by the pipeline: the store's database, the
facts files, the translation cache, the meshes. Do not edit it by hand; change
the input or the YAML source and sync.

## The one rule

`ontology/nx_v1_1/source/*.yaml` is the single definition of the system.
Everything else is either transcribed from NX, generated from the YAML, or
code that reads the YAML. When something about the vocabulary, a rule, a
threshold or a KPI has to change, change the YAML and run `PY run.py build`;
never edit `dist/`, never put a threshold value or a class name into code.

The YAML and everything generated from it contain only definitions: no notes
to the reader, no history, no references to other projects or documents, no
version numbers other than the ontology's own, no non-ASCII prose. The build
refuses CJK characters anywhere under `ontology/nx_v1_1`.

## How the pieces fit

- `run.py build` runs `ontology/nx_v1_1/build/build_all.py`: YAML -> `dist/cncgaide_nx.ttl`
  (the ontology), `dist/rules/*.ru` (one SPARQL Update per rule, two gate rules,
  one per KPI derivation), `dist/shapes.ttl` (SHACL), then `validate.py`.
- `run.py sync` plans per part from the index graph: a changed STEP or NX schema
  means the NX session runs (`nxline/driver.py` -> `nxline/journal.py`, which
  writes one TriG file per part through `kg/facts.py`); a changed ontology means
  only `kg/rules.py` runs. Keys and graph IRIs: `src/web/graph_model.md`.
- The store is Fuseki (`kg/server.py` starts and stops it; `kg/fuseki.py` is the
  client). Python talks SPARQL Protocol and Graph Store Protocol over HTTP with
  the standard library only.
- `web/llm.py` drafts a query from an English question through any
  OpenAI-compatible endpoint configured in `settings.json` (`web/settings.py`:
  API key, base URL and model, all three required, no provider preset); the
  model only drafts and never touches the store. Never write the API key into
  a tracked file, a log line, an error message or an answer.

## Adding or changing a rule

1. Edit `source/heuristics.yaml`: `appliesTo` (NX class names or globs),
   `usesAttributes` (concrete names, or `DIAMETER_k` / `DEPTH_k` / `DIAMETER_n`
   for ladders), `usesThresholds`, `affectsKpi`, `values`, and `condition`, a
   SPARQL WHERE body that binds `?outcome` and one `?v_<name>` per value. It
   sees `?f` and `?cls` (feature scope) or `?rel ?a ?b ?clsA ?clsB` (pair
   scope) and every threshold as `?<symbol>`. Use `{FACTS}` and `{ONTOLOGY}`
   for the graphs.
2. `PY run.py build` - `validate.py` checks the references, the bound
   variables and that the generated Update parses.
3. `PY run.py sync` - the derived key changed, so the rules rerun on every part.

`PY run.py whatif --part <id> t_hole_ld=3` answers which verdicts of one part
would change under other threshold values: the ontology graph is copied with
the new values, the rules run into a temporary derived graph, the two verdict
sets are compared and both graphs are dropped. Nothing is indexed; the web
interface does not expose it.

Division by zero or a false premise produce no verdict, which counts as not
applicable. A missing required attribute produces NOT_EVALUABLE through the
shared gate rules, never through a per-rule branch.

## Discipline

- Facts are measured (NX and the kernel), knowledge is declared (YAML), verdicts
  are computed (SPARQL). Nothing in Python decides a rule.
- A derived quantity is never written under an NX attribute name; it lives
  under `cg:` with its measurement or its refusal.
- Interface text is English; verdict outcomes read met / not met / not
  evaluable; not-applicable is counted, never listed.
- Display defaults (colours, hidden classes) live in `source/display.yaml` and
  are not published into the ontology.
- Windows: keep line endings LF (`.gitattributes` says so); NX is the only
  geometry kernel - never import an open-source CAD kernel anywhere; the
  journal runs in NX's Python 3.12 with the standard library and the vendored
  yaml only.

## Checks, in order

```
PY -m compileall -q src run.py ontology/nx_v1_1/build install
PY run.py build
PY run.py sync --dry-run
PY run.py check
PY install/verify_install.py --no-sync
```

`build` must end with `all steps passed`, `check` must print `conforms` for
every graph, and `verify_install.py` must end with `INSTALL VERIFIED`. Without
`--no-sync` it runs the sync first, which needs NX when a part has to be built.

## Outputs that look like errors and are not

**`blocked` from `sync`.** NX could not be used on this machine: the licence
server is unreachable (often a VPN that is down), or no NX install was found
where `config/nx_local.json` points. The detail line says which. The first
blocked translation stops the batch, the parts are recorded as `blocked`, and
the command exits with 1. Nothing is wrong with the parts: the next `sync`
retries them without anything having to change.

**A verdict of `NOT_EVALUABLE`.** A rule needed an attribute the feature does
not carry, or a quantity the kernel refused to measure. The verdict names the
attribute and the reason instead of guessing or quietly passing.

**Fewer verdicts than features.** A rule whose premise does not hold for a
feature, or whose arithmetic would divide by zero, produces no verdict: that
is not applicable. It is counted per rule, never listed as a verdict.

**`rules` for every part in `sync --dry-run`.** A change to the YAML source
changes every part's derived key, so the rules rerun everywhere. That takes
seconds; the NX session runs only when a STEP file or the NX schema changes.

**A part disappearing from the list.** Removing a STEP file from `inputs/`
removes the part, its graphs and its meshes on the next `sync`
(`--keep-missing` keeps them). That is the sync working.

**Planar surfaces and notches missing from the part view.** The classes listed
under `backgroundTypes` (the planar surfaces) and matched by
`hiddenByDefaultPatterns` (the notches) in `source/display.yaml` are hidden by
default until switched on. They are in the store and in every count.

**No question line on the Query page.** Drafting queries with a language model
is optional (`install/SETUP.md`, step 8); until an API key, a base URL and a
model are all set, the line is not offered. Nothing else depends on it.
