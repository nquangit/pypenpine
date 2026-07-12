"""Module-global registry of attack modules, selectable by name."""

from __future__ import annotations

from typing import Protocol

from penpine.attack.exceptions import AttackConfigError
from penpine.attack.types import AttackType


class RegistrableModule(Protocol):
    """The common surface the registry needs: a name and a category.

    Both the signature `AttackModule` and the active-prober `DifferentialModule`
    satisfy this structurally, so either can be registered.
    """

    name: str
    attack_type: AttackType | None


_REGISTRY: dict[str, RegistrableModule] = {}


def register(module: RegistrableModule, *, replace: bool = False) -> None:
    if module.name in _REGISTRY and not replace:
        raise AttackConfigError(f"attack module already registered: {module.name!r}")
    _REGISTRY[module.name] = module


def get(name: str) -> RegistrableModule:
    try:
        return _REGISTRY[name]
    except KeyError:
        raise AttackConfigError(f"unknown attack module: {name!r}") from None


def unregister(name: str) -> None:
    _REGISTRY.pop(name, None)


def list_modules() -> list:
    return sorted(_REGISTRY)


def by_type(attack_type, *, signature_only: bool = False) -> list:
    mods = [m for m in _REGISTRY.values() if getattr(m, "attack_type", None) == attack_type]
    if signature_only:
        mods = [m for m in mods if not hasattr(m, "probe")]
    return mods


def clear() -> None:
    _REGISTRY.clear()
