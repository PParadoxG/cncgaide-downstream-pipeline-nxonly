"""Pure B-Rep topology and vector primitives, above the seam, below the rules.

This package answers questions whose answer does not depend on any vocabulary:
how far a cylindrical wall reaches along its axis, which edges of a model are
geometrically the same curve, where a wall patch stops and what lies across the
boundary, how two direction vectors compare.  Nothing here names a feature
class or decides whether a candidate is accepted - those are recognition
decisions and they belong to NX and to the rules.

Import rule
-----------
Standard library and ``contract`` only.  No kernel package, no CAD kernel, no
relations.  The NX journal imports this package inside NX's own Python, where
nothing heavier is available.

Where things live
-----------------
``vectors``      three-component arithmetic and the canonical-form helpers.
``faces``        face identity, ordering, bounding boxes and axial extents.
``signatures``   the geometric edge-identity rule and its per-model views.
``edge_index``   the per-model edge bookkeeping the wall-band walk reads.
``hole_topology``  the cylindrical-wall rim walk and rim-end classification.
"""
