"""Web Push subscription adapter tests on in-memory SQLite (Postgres in CI)."""

from sqlalchemy.orm import Session, sessionmaker

from hr_agents.db.push import DbPushStore
from hr_agents.models import PushSubscription
from hr_agents.services.push import PushService

ENDPOINT = "https://fcm.googleapis.com/fcm/send/abc-123"


def subscribe(
    service: PushService,
    *,
    actor_id: str = "rina",
    role: str = "manager",
    endpoint: str = ENDPOINT,
    p256dh: str = "B" * 80,
) -> PushSubscription:
    return service.subscribe(
        actor_id=actor_id,
        role=role,
        endpoint=endpoint,
        p256dh=p256dh,
        auth="a" * 24,
        user_agent="Firefox 140",
    )


def test_a_subscription_round_trips_through_the_table(
    factory: sessionmaker[Session],
) -> None:
    service = PushService(DbPushStore(factory))
    created = subscribe(service)

    fresh = PushService(DbPushStore(factory))
    stored = fresh.list_for("rina")

    assert [item.id for item in stored] == [created.id]
    assert stored[0].role == "manager"
    assert stored[0].endpoint == ENDPOINT


def test_re_subscribing_refreshes_the_row_instead_of_duplicating_it(
    factory: sessionmaker[Session],
) -> None:
    service = PushService(DbPushStore(factory))
    first = subscribe(service)

    second = subscribe(service, p256dh="C" * 80)

    assert second.id == first.id
    assert len(PushService(DbPushStore(factory)).list_for("rina")) == 1
    assert PushService(DbPushStore(factory)).list_for("rina")[0].p256dh == "C" * 80


def test_role_selection_and_deletion_work_against_the_table(
    factory: sessionmaker[Session],
) -> None:
    service = PushService(DbPushStore(factory))
    manager = subscribe(service)
    subscribe(service, actor_id="sari", role="employee", endpoint=f"{ENDPOINT}-sari")

    store = DbPushStore(factory)
    assert [item.id for item in store.for_roles({"manager"})] == [manager.id]
    assert [item.id for item in store.for_roles(set())] == []

    assert service.unsubscribe(actor_id="rina", subscription_id=manager.id)
    assert PushService(DbPushStore(factory)).list_for("rina") == []
