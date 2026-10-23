"""Web Push: the browser's subscription, and an explicit test delivery.

Subscriptions are per person, so every route here answers about the caller's own
endpoints. There is no "send to somebody else" route: fan-out happens inside the
approval engine, not by request.
"""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status

from hr_agents.api.deps import ActorDep, PaginationDep, get_principal, require_permission
from hr_agents.api.problem import domain_problem
from hr_agents.api.push_schemas import (
    PushConfigView,
    PushSubscriptionCreate,
    PushSubscriptionView,
    PushTestView,
)
from hr_agents.api.schemas import Page
from hr_agents.rbac import Permission, Principal
from hr_agents.services.push import PushError, PushService

router = APIRouter(
    prefix="/v1/push",
    tags=["push"],
    dependencies=[Depends(require_permission(Permission.NOTIFICATIONS_USE))],
)


def get_push(request: Request) -> PushService:
    return request.app.state.push


PushDep = Annotated[PushService, Depends(get_push)]
PrincipalDep = Annotated[Principal, Depends(get_principal)]


@router.get("/config", response_model=PushConfigView)
def read_config(request: Request, push: PushDep) -> PushConfigView:
    """Whether push is available, and the key the browser subscribes with."""
    settings = request.app.state.settings
    public_key = settings.vapid_public_key or None
    return PushConfigView(enabled=push.configured and public_key is not None, public_key=public_key)


@router.get("/subscriptions", response_model=Page[PushSubscriptionView])
def list_subscriptions(
    push: PushDep, principal: PrincipalDep, paging: PaginationDep
) -> Page[PushSubscriptionView]:
    """The caller's own browsers. Another person's endpoints are not addressable."""
    items = [PushSubscriptionView.from_model(item) for item in push.list_for(principal.actor_id)]
    return Page.of(
        items[paging.offset : paging.offset + paging.limit],
        total=len(items),
        limit=paging.limit,
        offset=paging.offset,
    )


@router.post(
    "/subscriptions",
    status_code=status.HTTP_201_CREATED,
    response_model=PushSubscriptionView,
    summary="Register this browser for approval notifications",
)
def subscribe(
    payload: PushSubscriptionCreate,
    push: PushDep,
    actor: ActorDep,
    principal: PrincipalDep,
) -> PushSubscriptionView:
    """Upsert one endpoint. Re-subscribing the same browser refreshes its keys."""
    try:
        record = push.subscribe(
            actor_id=principal.actor_id,
            role=principal.role.value,
            endpoint=payload.endpoint,
            p256dh=payload.keys.p256dh,
            auth=payload.keys.auth,
            user_agent=payload.user_agent,
        )
    except PushError as exc:
        raise domain_problem(exc) from exc
    return PushSubscriptionView.from_model(record)


@router.delete(
    "/subscriptions/{subscription_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Stop notifications on one of the caller's browsers",
)
def unsubscribe(
    subscription_id: UUID, push: PushDep, actor: ActorDep, principal: PrincipalDep
) -> Response:
    if not push.unsubscribe(actor_id=principal.actor_id, subscription_id=subscription_id):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="no such push subscription for this principal",
        )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/test",
    response_model=PushTestView,
    summary="Send one notification now, to prove the browser is reachable",
)
def send_test(push: PushDep, actor: ActorDep, principal: PrincipalDep) -> PushTestView:
    if not push.configured:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="push notifications are not configured on this deployment",
        )
    try:
        report = push.send_test(actor_id=principal.actor_id)
    except PushError as exc:
        raise domain_problem(exc) from exc
    return PushTestView(
        attempted=report.attempted,
        delivered=report.delivered,
        pruned=report.pruned,
        failed=report.failed,
    )
