"""Route discovery for the structural authorization and provenance fences.

Two test modules need to reason about the whole API surface at once -- which
routes mutate it, and what each one declares. Both were walking the routers
themselves, and both walked them the same wrong way:

```python
router = getattr(loaded, "router", None)
if router is None:
    continue
```

That reads a single module-level ``router`` attribute. Nineteen of the twenty
router modules define one. ``people.py`` does not: it defines seven, one per
API group (``employees_router``, ``contracts_router``, ``approvals_router``,
...). The loop therefore skipped it silently, and the four structural tests
built on it never saw any of its sixteen write routes.

That is not a hypothetical gap. Eleven of those routes are guarded only by a
read permission -- ``MANAGER`` holds ``people:read``, so a manager could create
employees, activate and terminate contracts, and mark legal documents verified;
``FINANCE`` holds ``payroll:read``, so a finance key could rewrite statutory
rate-table entries. A documented sweep had "already fixed" exactly this and did
not touch them, because the fence built to catch it was blind to that module.

So the walk below enumerates *every* ``APIRouter`` in each module rather than
one attribute, and ``tests/test_route_inventory.py`` asserts the count is
non-zero for every module. A future module that exports its routers some other
way fails there instead of quietly disappearing from the fences.

Router-level ``dependencies=[...]`` need no special handling: FastAPI copies
them onto each route at registration time, so ``APIRoute.dependencies`` already
carries both router-level and route-level requirements.
"""

from __future__ import annotations

import importlib
import pkgutil
from collections.abc import Iterator

from fastapi import APIRouter
from fastapi.routing import APIRoute

from hr_agents.api import routers
from hr_agents.rbac import Permission

WRITE_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})


def api_routers() -> Iterator[tuple[str, APIRouter]]:
    """Every ``APIRouter`` each router module defines, with its module name."""
    for module in sorted(pkgutil.iter_modules(routers.__path__), key=lambda item: item.name):
        loaded = importlib.import_module(f"{routers.__name__}.{module.name}")
        found = [value for value in vars(loaded).values() if isinstance(value, APIRouter)]
        if not found:
            raise AssertionError(
                f"{module.name} defines no APIRouter; the structural fences in "
                "test_rbac_enforcement.py and test_audit_provenance.py would skip it"
            )
        for router in found:
            yield module.name, router


def all_routes() -> list[APIRoute]:
    """Every route of every router, reads and writes alike."""
    return list(_all_routes())


def all_routes_of(router: APIRouter) -> list[APIRoute]:
    """Every `APIRoute` on one router, reads and writes alike."""
    return [route for route in router.routes if isinstance(route, APIRoute)]


def write_routes() -> list[APIRoute]:
    """Every mutating route the API exposes, from the routers themselves.

    ``app.routes`` is not usable: this FastAPI version represents an included
    router as a lazy wrapper with no ``path`` and no ``methods``, so the endpoints
    are only reachable by walking framework internals that a version bump would
    move. The ``APIRouter`` objects each module defines are public API, and they
    are the same objects the application includes.
    """
    return [route for route in _all_routes() if _is_write(route)]


def _all_routes() -> Iterator[APIRoute]:
    for _module, router in api_routers():
        for route in router.routes:
            # `APIRouter.routes` is typed `list[BaseRoute]`; the mount routes a
            # nested router contributes carry neither `methods` nor `endpoint`.
            if isinstance(route, APIRoute):
                yield route


def _is_write(route: APIRoute) -> bool:
    return bool(route.methods and route.methods & WRITE_METHODS)


def route_permissions(route: APIRoute) -> set[Permission]:
    """The permissions a route requires, router-level ones included.

    ``require_permission`` closes over its ``Permission``, so the value is read
    out of the closure cell. That is reaching into an implementation detail, but
    it is the only place the requirement is recorded -- FastAPI does not expose
    it, and reading the closure is strictly better than asserting a count.
    """
    required: set[Permission] = set()
    for dependency in list(getattr(route, "dependencies", None) or []):
        closure = getattr(getattr(dependency, "dependency", None), "__closure__", None)
        for cell in closure or ():
            if isinstance(cell.cell_contents, Permission):
                required.add(cell.cell_contents)
    return required


def route(path: str) -> APIRoute:
    """The one write route at ``path``, or a failure naming what was found."""
    matches = [candidate for candidate in write_routes() if candidate.path == path]
    if len(matches) != 1:
        raise AssertionError(f"expected exactly one write route at {path}, found {len(matches)}")
    return matches[0]


def read_guarded_write_routes() -> set[str]:
    """Mutating routes whose only declared permissions are reads."""
    return {
        candidate.path
        for candidate in write_routes()
        if (required := route_permissions(candidate))
        and all(permission.value.endswith(":read") for permission in required)
    }
