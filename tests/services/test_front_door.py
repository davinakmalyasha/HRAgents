"""Front-door routing: deterministic, explainable, never consequential."""

import pytest

from hr_agents.services.front_door import FrontDoor, RouteReason
from hr_agents.workspaces import WorkspaceError, WorkspaceId


def test_explicit_workspace_wins() -> None:
    decision = FrontDoor().route("any text at all", workspace=WorkspaceId.PAYROLL)
    assert decision.workspace is WorkspaceId.PAYROLL
    assert decision.reason is RouteReason.EXPLICIT
    assert decision.matched_keywords == []


def test_invalid_explicit_workspace_rejected() -> None:
    with pytest.raises(WorkspaceError):
        FrontDoor().route("hi", workspace="nope")  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("message", "expected"),
    [
        ("berapa saldo cuti saya tahun ini?", WorkspaceId.LEAVE),
        ("When is my annual leave balance updated?", WorkspaceId.LEAVE),
        ("kapan gaji bulan ini dibayarkan?", WorkspaceId.PAYROLL),
        ("How does THR calculation work?", WorkspaceId.PAYROLL),
        ("siapa kandidat yang lolos interview?", WorkspaceId.HIRING),
        ("kebijakan cuti perusahaan apa?", WorkspaceId.LEAVE),
        ("apa aturan reimbursement?", WorkspaceId.POLICY),
        ("bagaimana proses resign dan serah terima?", WorkspaceId.OFFBOARDING),
        ("cara hapus data karyawan untuk permintaan PDP", WorkspaceId.COMPLIANCE),
    ],
)
def test_keyword_routing(message: str, expected: WorkspaceId) -> None:
    decision = FrontDoor().route(message)
    assert decision.workspace is expected
    assert decision.reason is RouteReason.KEYWORD
    assert decision.matched_keywords


def test_ambiguous_message_falls_back_to_ask_hr() -> None:
    decision = FrontDoor().route("halo, apa kabar?")
    assert decision.workspace is WorkspaceId.POLICY
    assert decision.reason is RouteReason.FALLBACK
    assert decision.matched_keywords == []


def test_routing_is_deterministic_for_ties() -> None:
    door = FrontDoor()
    first = door.route("cuti dan gaji")
    second = door.route("cuti dan gaji")
    assert first == second
    assert first.workspace in {WorkspaceId.LEAVE, WorkspaceId.PAYROLL}


def test_alternates_list_other_matched_departments_best_first() -> None:
    decision = FrontDoor().route("tolong siapkan onboarding untuk Budi dan cek gaji serta THR")
    assert decision.workspace is WorkspaceId.PAYROLL
    assert decision.alternates == [WorkspaceId.ONBOARDING]


def test_explicit_workspace_has_no_alternates() -> None:
    decision = FrontDoor().route("cuti dan gaji", workspace=WorkspaceId.LEAVE)
    assert decision.alternates == []


def test_ask_hr_is_never_an_alternate() -> None:
    decision = FrontDoor().route("apa aturan cuti perusahaan?")
    assert decision.workspace is WorkspaceId.LEAVE
    assert decision.alternates == []


def test_fallback_has_no_alternates() -> None:
    decision = FrontDoor().route("halo, apa kabar?")
    assert decision.alternates == []
