"""A deliberately small dependency-injection container.

We avoid a heavyweight DI framework: the app has one process, one wiring
graph, and testability is achieved by constructing services explicitly in
tests rather than through the container. `ServiceContainer` exists so
`app.py` has a single, readable place that owns every singleton and its
construction order, instead of scattering module-level globals.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, TypeVar

T = TypeVar("T")


@dataclass
class ServiceContainer:
    """A typed registry of singleton services, keyed by type."""

    _instances: dict[type, Any] = field(default_factory=dict)

    def register(self, service_type: type[T], instance: T) -> None:
        self._instances[service_type] = instance

    def resolve(self, service_type: type[T]) -> T:
        try:
            return self._instances[service_type]  # type: ignore[no-any-return]
        except KeyError as exc:
            raise LookupError(
                f"No instance registered for {service_type.__name__}. "
                "Did app.py finish wiring the container before this was resolved?"
            ) from exc

    def has(self, service_type: type) -> bool:
        return service_type in self._instances
