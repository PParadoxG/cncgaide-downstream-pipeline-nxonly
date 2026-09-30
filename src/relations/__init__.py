"""Feature relation layer.

The relation layer is a strictly downstream reader.  It runs once, after
feature recognition has finished and the ``FeatureNode`` set is fixed.  It may
read only those nodes and the merged ``PartModel``; it never touches
``featureType``, face ownership, attributes or ``missingAttributes``.

Adding a further relation means dropping one module into the rule package
(``relations.nx.rules``).  The registry discovers it and the executor runs it;
no caller has to be edited.

This package is the machinery; the rules themselves live in the rule package
beside it.
"""

from relations.base import RelationContext, RelationRule  # noqa: F401
from relations.executor import relation_counts, run_relations  # noqa: F401
from relations.registry import BaseRelationRegistry  # noqa: F401
