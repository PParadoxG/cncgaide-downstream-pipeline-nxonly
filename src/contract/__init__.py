"""The seam between the geometry kernel and everything above it.

``contract`` is the one package that may be imported from either side of the
pipeline without dragging a geometry kernel along.  It holds two things:

* :mod:`contract.partmodel` (+ :mod:`contract.partmodel_json`) — the
  normalized B-Rep *data* every downstream layer reads;
* :mod:`contract.kernel` — the *live geometry queries* that cannot be
  answered from that data and therefore have to stay a service call.

Nothing here imports a kernel or a layer above the seam: the dependency runs
one way only, from an implementation towards the contract.
"""
