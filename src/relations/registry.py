"""Auto-discovery machinery for relation rules.

Every module under a registry's rule package is imported once; classes
decorated with that package's ``register_rule`` register a single instance.
A new relation therefore needs no edit anywhere else.

One subclass per rule set: ``relations.nx.registry`` is the one this system
ships.  A subclass brings its own package and its own rule list, so that one
rule set can never discover another's modules.
"""

from __future__ import annotations

import importlib
import pkgutil

from relations.base import RelationRule


class RuleDiscoveryError(RuntimeError):
    """One rule module of the rule package did not import.

    Named rather than left as whatever the module happened to raise, because
    the interesting fact is *which* module refused and the original error is
    only half of that.  The cause travels on ``__cause__``.
    """


class DuplicateRuleError(RuntimeError):
    """Two rule modules claim the same relation rule id.

    One of them would never run, and which one is decided by the walk order of
    the package.  A silent drop is worse than a refusal, so this is raised.
    """


class BaseRelationRegistry:
    """Discovery and ordering for one set of relation rules.

    A subclass restates ``package``, ``_loaded`` and ``_rules`` so that no rule
    set ever discovers another's modules.
    """

    package = ""
    _loaded = False
    _rules: list[RelationRule] = []

    @classmethod
    def discover(cls) -> None:
        """Import every rule module of this rule set, or refuse to be loaded.

        ``_loaded`` is set *after* the walk, never before it.  Set first, a
        module that raised on import would leave the flag standing and every
        later ``all_rules()`` would answer with the rules that happened to
        register before the failure - and a missing relation rule is a whole
        edge type silently absent from every part of the run that follows.
        """
        if cls._loaded:
            return
        module = importlib.import_module(cls.package)
        for info in pkgutil.iter_modules(module.__path__, cls.package + "."):
            if info.name.rsplit(".", 1)[-1].startswith("_"):
                continue
            try:
                importlib.import_module(info.name)
            except Exception as exc:
                raise RuleDiscoveryError(
                    f"relation rule module {info.name!r} did not import: "
                    f"{type(exc).__name__}: {exc}"
                ) from exc
        cls._loaded = True

    @classmethod
    def register(cls, rule: RelationRule) -> None:
        existing = next((item for item in cls._rules if item.rule_id == rule.rule_id), None)
        if existing is not None:
            raise DuplicateRuleError(
                f"{rule.rule_id} is registered twice in {cls.__name__}: "
                f"{type(existing).__module__} and {type(rule).__module__}"
            )
        cls._rules.append(rule)

    @classmethod
    def all_rules(cls) -> list[RelationRule]:
        cls.discover()
        return sorted(cls._rules, key=lambda rule: (rule.priority, rule.rule_id))

    @classmethod
    def enabled(cls) -> list[RelationRule]:
        return [rule for rule in cls.all_rules() if rule.enabled_by_default]


def default_registry() -> type[BaseRelationRegistry]:
    """The rule set a caller gets when it does not name one.

    Imported inside the function so the machinery carries no module-level
    dependency on a rule package.
    """
    from relations.nx.registry import NxRelationRegistry

    return NxRelationRegistry
