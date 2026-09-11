from hr_agents.models import ActorType, AuditActor
from hr_agents.services.audit import AuditChain


def test_chain_links_and_verifies() -> None:
    chain = AuditChain()
    first = chain.append_system(
        action="application.received", subject_type="application", subject_id="a-1"
    )
    second = chain.append_system(
        action="evaluation.scored",
        subject_type="candidate",
        subject_id="c-1",
        payload={"s_tech": 0.91},
    )

    assert first.prev_hash is None
    assert first.seq == 0
    assert second.prev_hash == first.entry_hash
    assert second.seq == 1
    assert chain.verify() == -1


def test_human_actor_recorded() -> None:
    chain = AuditChain()
    entry = chain.append(
        actor=AuditActor(
            actor_type=ActorType.HUMAN, actor_id="lead-7", display_name="Engineering Lead"
        ),
        action="rejection.signed_off",
        subject_type="evaluation",
        subject_id="eval-1",
        payload={"reason_code": "below_bar"},
    )
    assert entry.actor.actor_type is ActorType.HUMAN
    assert entry.verify()


def test_tampering_breaks_chain_detection() -> None:
    chain = AuditChain()
    chain.append_system(action="a", subject_type="t", subject_id="1")
    chain.append_system(action="b", subject_type="t", subject_id="2")
    chain.append_system(action="c", subject_type="t", subject_id="3")

    untouched = chain._entries[1]
    chain._entries[1] = untouched.model_copy(update={"payload": {"tampered": True}})

    assert chain.verify() == 1


def test_removed_entry_breaks_linkage() -> None:
    chain = AuditChain()
    chain.append_system(action="a", subject_type="t", subject_id="1")
    chain.append_system(action="b", subject_type="t", subject_id="2")
    chain.append_system(action="c", subject_type="t", subject_id="3")

    removed = chain._entries.pop(1)

    # entry seq 2 now points at a hash that is no longer previous
    assert chain.verify() == 2
    assert removed.seq == 1


def test_empty_chain_verifies() -> None:
    assert AuditChain().verify() == -1
