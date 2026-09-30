"""Graph edit distance between two parts, computed from the store.

Query-time similarity: both parts are read out of their facts graphs, turned
into a comparable feature graph, and priced by a configurable cost model.

Two layers, kept in separate packages on purpose:

- ``ged.contract`` - the *representation* layer.  Which features, attributes
  and relations enter the graph and what they mean.  Every table in it is
  derived from the ontology source, so it changes when the ontology does.
- ``ged.cost`` / ``ged.solver`` - the *cost* layer.  Weights, class
  substitution cost, normalisation, solver.  Internal to the distance; free
  to iterate without touching the ontology.
"""
