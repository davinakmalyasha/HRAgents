from collections.abc import Iterator

from hr_agents.models import ActorType, AuditActor, AuditEntry
from hr_agents.services.audit import AuditChain, ChainCursor, chain_is_linked, verify_stream


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


# --- streaming verification -------------------------------------------------------


def paged(entries: list[AuditEntry], size: int = 2) -> Iterator[AuditEntry]:
    """Yield entries in pages, the way the database adapter reads them."""
    for start in range(0, len(entries), size):
        yield from entries[start : start + size]


def test_streaming_verification_matches_the_loaded_chain() -> None:
    chain = AuditChain()
    for index in range(5):
        chain.append_system(action="a", subject_type="t", subject_id=str(index))
    entries = list(chain.entries)

    assert verify_stream(paged(entries)) == -1
    assert verify_stream(iter(entries)) == -1


def test_streaming_verification_finds_tampering_after_a_page_boundary() -> None:
    chain = AuditChain()
    for index in range(5):
        chain.append_system(action="a", subject_type="t", subject_id=str(index))
    entries = list(chain.entries)
    entries[4] = entries[4].model_copy(update={"payload": {"tampered": True}})

    assert verify_stream(paged(entries)) == 4


def test_streaming_verification_spots_a_removed_entry() -> None:
    chain = AuditChain()
    for index in range(4):
        chain.append_system(action="a", subject_type="t", subject_id=str(index))
    entries = list(chain.entries)
    del entries[2]

    assert verify_stream(paged(entries)) == 3


def test_link_check_reports_the_first_broken_entry() -> None:
    chain = AuditChain()
    first = chain.append_system(action="a", subject_type="t", subject_id="1")
    second = chain.append_system(action="b", subject_type="t", subject_id="2")

    assert chain_is_linked(first, ChainCursor()) is True
    assert chain_is_linked(second, ChainCursor()) is False
    assert chain_is_linked(second, ChainCursor(expected_prev=first.entry_hash)) is True
