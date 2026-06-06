"""Z4.4.3 — Namespace enforcement for department teams.

Ensures each department's tools are imported under the correct namespace
and raises NamespaceViolationError if a tool from another department is
registered against the wrong department.
"""


class NamespaceViolationError(Exception):
    """Raised when a tool is registered under the wrong department namespace."""


class NamespaceGuard:
    """Validates that tool names belong to the correct department namespace.

    A tool can be registered by multiple departments (e.g. ``recall_decision``
    is used by both board and strategy). The guard tracks which departments
    registered each tool and validates at call time that the calling department
    is among the registered owners.
    """

    def __init__(self):
        self._registry: dict[str, set[str]] = {}  # tool_name -> {departments}

    def register(self, department: str, tool_names: list[str]) -> None:
        """Register tool names for a department."""
        for name in tool_names:
            self._registry.setdefault(name, set()).add(department)

    def validate(self, department: str, tool_name: str) -> bool:
        """Return True if tool_name is registered for department, False if unregistered,
        raise NamespaceViolationError if registered but NOT for this department."""
        owners = self._registry.get(tool_name)
        if owners is None:
            return False
        if department not in owners:
            raise NamespaceViolationError(
                f"Tool '{tool_name}' belongs to department(s) {owners}, "
                f"not '{department}'"
            )
        return True

    def clear(self) -> None:
        """Clear all registrations (useful for tests)."""
        self._registry.clear()

    def list_tools(self, department: str) -> list[str]:
        """Return all tool names registered for a department."""
        return [
            name for name, depts in self._registry.items() if department in depts
        ]


# Module-level singleton
_guard = NamespaceGuard()


def get_guard() -> NamespaceGuard:
    return _guard
