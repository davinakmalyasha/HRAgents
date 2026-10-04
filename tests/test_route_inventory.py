"""The structural fences must actually see the whole API.

`tests/route_probe.py` walks every `APIRouter` each router module defines. It
raises if a module defines none, which is the failure that made this file
necessary: `people.py` exports seven routers and no module-level `router`, so
both structural fences skipped it, and eleven of its mutating routes stayed
guarded by a read permission through a sweep that had already "fixed" exactly
that class of bug elsewhere.

A fence that cannot fail is not a test. These three assert the fences have
teeth, which the tests they protect cannot assert about themselves.
"""

from __future__ import annotations

import pytest
from tests.route_probe import (
    WRITE_METHODS,
    all_routes_of,
    api_routers,
    read_guarded_write_routes,
    route_permissions,
    write_routes,
)

MODULES = sorted({name for name, _router in api_routers()})


def test_every_router_module_is_reachable_by_the_structural_fences() -> None:
    """`api_routers` finds something in each module, so nothing is skipped.

    Without this, a module that stopped exporting an `APIRouter` would
    disappear from `test_a_read_permission_alone_never_guards_a_write` and
    `test_write_routes_declare_their_actor_as_a_dependency` without either
    failing -- the exact failure this file exists to prevent.
    """
    assert len(MODULES) == 18, f"router modules changed: {MODULES}"
    for name, router in api_routers():
        assert all_routes_of(router), f"{name} contributes no routes to the fences"


def test_the_fences_see_more_routes_than_a_single_router_attribute_would() -> None:
    """A regression fence on the fence: `people.py` must stay in scope.

    The old walk read one `router` attribute per module. `people.py` has no
    such attribute, which is how sixteen write routes became invisible. If a
    future refactor gives it one, this still holds; if someone reintroduces
    the attribute-only walk, this fails first and says why.
    """
    people_write_routes = {
        route.path
        for name, router in api_routers()
        if name == "people"
        for route in all_routes_of(router)
        if route.methods and route.methods & WRITE_METHODS
    }
    write_paths = {route.path for route in write_routes()}
    assert len(people_write_routes) == 16, sorted(people_write_routes)
    assert people_write_routes <= write_paths
    assert len(write_routes()) == 102, f"the API's mutating surface changed: {len(write_routes())}"


def test_permission_extraction_still_finds_declared_permissions() -> None:
    """`route_permissions` reads a closure cell, so it can silently find nothing.

    `require_permission` closes over its `Permission`. Refactor that into a
    `functools.partial`, a class, or a renamed cell and the extractor returns
    an empty set for every route -- at which point
    `test_a_read_permission_alone_never_guards_a_write` passes vacuously
    against a fully unguarded API, and
    `test_no_write_route_is_left_unguarded` fires for the wrong reason.

    So assert the extractor works before trusting anything built on it.
    """
    guarded = [route for route in write_routes() if route_permissions(route)]
    assert len(guarded) >= 100, (
        f"only {len(guarded)} of {len(write_routes())} write routes declare a permission; "
        "the extractor is probably reading the wrong place"
    )


@pytest.mark.parametrize(
    "path",
    sorted(
        {
            route.path
            for route in write_routes()
            if "/v1/employees" in route.path
            or "/v1/contracts" in route.path
            or "/v1/rate-tables" in route.path
        }
    ),
)
def test_people_routes_name_a_write_permission(path: str) -> None:
    """The eleven routes the attribute-only walk missed, by name.

    `MANAGER` and `FINANCE` hold `people:read` and `payroll:read` without the
    matching write, which is the point: a manager reads the directory to run a
    review and must not be able to create employees or terminate a contract
    through the same permission.
    `test_roles_that_only_ever_read_people_records_do_not_gain_the_write` keeps
    the permission narrow; this keeps the routes honest about needing it.
    """
    required = route_permissions(next(r for r in write_routes() if r.path == path))
    assert not required or not all(p.value.endswith(":read") for p in required), (
        f"{path} is guarded only by {sorted(p.value for p in required)}"
    )
    assert read_guarded_write_routes() == set()
