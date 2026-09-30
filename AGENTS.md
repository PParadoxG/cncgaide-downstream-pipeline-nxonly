# Agent notes

The notes for AI agents in this repository are in **[CLAUDE.md](CLAUDE.md)**,
whatever agent you are. Deploying for the first time: **[install/SETUP.md](install/SETUP.md)**.

Three things worth knowing before you read further:

- If an install step fails, or `install/verify_install.py` reports a
  mismatch, send the output to whoever gave you this repository rather than
  working around it.
- `ontology/nx_v1_1/source/*.yaml` defines the system; `dist/` is generated.
  Change the source, run `run.py build`.
- The store is Apache Jena Fuseki. If `run.py sync` says `blocked`, NX cannot
  be used here (the licence server is unreachable, or no NX install was found);
  that is a statement about the machine, not about any part.
