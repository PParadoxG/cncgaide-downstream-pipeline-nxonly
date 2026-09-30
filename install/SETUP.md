# Deployment

Follow this top to bottom. Each step has a check.

Prerequisites: Windows 10 or 11; conda (`conda --version` must answer); a JDK
21 or later (`java -version` from any of the usual install folders; Microsoft,
Eclipse Adoptium, Oracle and Zulu builds are found automatically); Siemens NX
with a reachable licence server for the recognition step.

## 1 - Create the Python environment

```
conda env create -f install/environment.yml
conda run -n cncgaide-nx python -c "import sys; print(sys.executable)"
```

Below, `PY` stands for the printed path. Run every command from the repository
root.

## 2 - Install the store

```
PY install/fuseki_install.py
```

Downloads Apache Jena Fuseki (about 100 MB), checks its SHA-512 and unpacks it
under `install/fuseki/`. Then:

```
PY run.py fuseki start
```

Expect `"running": true` and the Java path it chose. The store answers at
http://localhost:3030/nx (Fuseki's own interface is at http://localhost:3030/).

If Java is not found or is older than 21, set `JAVA_HOME` to a JDK 21 folder,
or `CNCGAIDE_JAVA` to the `java.exe` itself.

## 3 - Point at NX

Copy `config/nx_local.example.json` to `config/nx_local.json` and put the NX
installation root in it (the folder containing `NXBIN\run_journal.exe` and
`UGII\customization_base.xml`):

```json
{ "nxRoot": "C:/Program Files/Siemens/NX2506" }
```

`CNCGAIDE_NX_ROOT` in the environment overrides the file.

## 4 - Build the ontology

```
PY run.py build
```

Expect `all steps passed`. The validation reconciles the transcribed classes
with the installed `customization_base.xml`; a different NX release is
reported here.

## 5 - Process the sample part

```
PY run.py sync --dry-run
PY run.py sync
PY run.py check
```

The dry run prints one line per part with its action (`build`, `rules`,
`current`). The sync translates the STEP, runs one NX session, loads the facts
and runs the rules; the last line per part reports the verdict counts. `check`
must print `conforms` for every graph.

## 6 - Verify

```
PY install/verify_install.py
```

This is the step that says whether the installation computed the right answer
rather than merely running. It rebuilds the ontology, syncs, and compares the
sample part against `install/expected_install.json`: the size of its two
graphs, its faces and features, its features by class, its relations by type,
its verdicts by rule and outcome, and its KPI results by type. Expect
`INSTALL VERIFIED`.

A mismatch is a finding, not something to work around: send the whole output to
whoever gave you this repository. The most likely cause is a different NX
release, which recognises a different set of features.

`--no-sync` checks the store as it stands, without an NX session; `--no-build`
skips the rebuild. Both are for looking, not for making a failing check pass.

## 7 - Query

```
PY run.py query "SELECT ?h (COUNT(?v) AS ?n) WHERE { GRAPH ?g { ?v a cg:Verdict ; cg:heuristic ?h ; cg:outcome cg:FAIL } } GROUP BY ?h"
```

## 8 - Optional: drafting queries with a language model

The Query page can draft a SPARQL query from a question in English through
any OpenAI-compatible chat completions endpoint of your choice. Open the Query
page, press **Settings** in the **Ask in plain English** section and fill in
all three fields: the API key, the base URL and the model. None has a
default; DeepSeek is only an example (`https://api.deepseek.com`,
`deepseek-chat`). The settings are kept in `settings.json` at the repository
root, which is not tracked; `settings.example.json` shows the shape if you
prefer to write the file:

```json
{"llm": {"apiKey": "", "baseUrl": "", "model": ""}}
```

Optionally, these environment variables override the file when they are set:

| Variable | What |
| --- | --- |
| `CNCGAIDE_LLM_API_KEY` | The API key |
| `CNCGAIDE_LLM_BASE_URL` | The endpoint, for example `https://api.deepseek.com`; `/chat/completions` is appended |
| `CNCGAIDE_LLM_MODEL` | The model name, for example `deepseek-chat` |

Until all three are set, from the file or the environment, the question line
is not offered and `api/status` names what is missing.

Check: `GET http://127.0.0.1:8765/api/status` answers `"llm": {"available": true, ...}`.
Nothing else depends on this step.

## When something fails

- `blocked` from `sync`: the NX licence server is unreachable (VPN). Nothing is
  wrong with the parts; run `sync` again when it is.
- `Fuseki did not answer`: read `runs/fuseki/fuseki.log`.
- `the ontology is not built` or `older than source`: run `PY run.py build`.
- `run_journal.exe` exits without a summary: the tail of its output is in the
  part's error line; the translated part is under `runs/prt/`.
