"""The in-memory feature and relation records the pipeline passes around.

Feature attributes deliberately live on ``FeatureNode``: there is no separate
recognition result handed off to a geometry extractor.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


class ReservedAttributeName(ValueError):
    """An attribute is named like one of the keys a node writes for itself.

    Raised instead of resolving the collision, because either resolution is a
    lie: letting the attribute win rewrites the node's identity, letting the
    structure win drops a value NX stated.  NX's attribute names are published
    verbatim, so the set of attribute names is not under this repository's
    control - which is exactly why the collision is refused out loud rather
    than guessed at.
    """


@dataclass
class FeatureNode:
    """One ontology-named feature with direct, ontology-named attributes."""

    nodeId: str
    featureType: str
    partmodelFaceIds: list[str]
    missingAttributes: dict[str, str] = field(default_factory=dict)
    diagnostics: dict[str, Any] = field(default_factory=dict)
    attributes: dict[str, Any] = field(default_factory=dict)
    # Quantities the pipeline measured *about* this feature, kept apart from
    # NX's own attributes: a derived value is never published where a value NX
    # stated would be.  One entry per quantity:
    # ``{"value": ..., "derivedBy": "nx_kernel", ...}``, with a ``reason``
    # instead of a value when the measurement was refused.
    derived: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Flatten ontology attributes onto the node's top level.

        Raises :class:`ReservedAttributeName` when an attribute is named like
        one of the keys written here - see that class for why refusing beats
        either way of resolving it.
        """
        collisions = sorted(self.RESERVED_KEYS & set(self.attributes))
        if collisions:
            raise ReservedAttributeName(
                f"{self.nodeId} ({self.featureType}): attribute name(s) "
                + ", ".join(collisions)
                + " are reserved for the node's own structure"
            )
        result = {
            "nodeId": self.nodeId,
            "featureType": self.featureType,
            **self.attributes,
            "missingAttributes": self.missingAttributes,
            "diagnostics": self.diagnostics,
        }
        # Written only when something was derived, so a node that derives
        # nothing carries no empty block.
        if self.derived:
            result["derived"] = self.derived
        # Keep the kernel-facing ids alongside the published cadFaceIds, so a
        # face map, the graph and the 3D view can all be traced back.
        result["partmodelFaceIds"] = list(self.partmodelFaceIds)
        return result

    # Keys ``to_dict`` writes that are *not* published attributes.  Everything
    # else on a serialized node is an attribute, which is what lets a stored
    # node be read back into the exact record it came from, without a list of
    # attribute names anywhere.
    RESERVED_KEYS = frozenset({"nodeId", "featureType", "partmodelFaceIds", "missingAttributes", "diagnostics", "derived"})

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "FeatureNode":
        """Inverse of :meth:`to_dict` (field for field)."""
        return cls(
            nodeId=payload["nodeId"],
            featureType=payload["featureType"],
            partmodelFaceIds=list(payload.get("partmodelFaceIds") or []),
            missingAttributes=dict(payload.get("missingAttributes") or {}),
            diagnostics=dict(payload.get("diagnostics") or {}),
            attributes={key: value for key, value in payload.items() if key not in cls.RESERVED_KEYS},
            derived=dict(payload.get("derived") or {}),
        )


@dataclass
class FeatureEdge:
    """Unified relation edge between two final feature nodes.

    ``source``/``target`` always name published node ids.  ``properties``
    carries the relation's own declared quantities (``crossingAngle``,
    ``axisSpacing``, ``pocketClearance``, ``slotClearance``, the LOCATED_ON
    terminal/host fields); like a node's attributes they belong on the edge
    itself rather than buried in the proof.
    ``evidence`` carries the witnesses a reader needs to audit the edge (for
    DIRECT_ADJACENT: the contributing face pairs and their shared B-Rep
    edges); ``diagnostics`` records how the rule reached it.
    """

    edgeId: str
    source: str
    target: str
    edgeType: str
    directed: bool = False
    sourceRule: str = ""
    properties: dict[str, Any] = field(default_factory=dict)
    evidence: dict[str, Any] = field(default_factory=dict)
    diagnostics: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "FeatureEdge":
        """Inverse of :meth:`to_dict` (field for field)."""
        return cls(
            edgeId=payload["edgeId"],
            source=payload["source"],
            target=payload["target"],
            edgeType=payload["edgeType"],
            directed=bool(payload.get("directed", False)),
            sourceRule=payload.get("sourceRule") or "",
            properties=dict(payload.get("properties") or {}),
            evidence=dict(payload.get("evidence") or {}),
            diagnostics=dict(payload.get("diagnostics") or {}),
        )
