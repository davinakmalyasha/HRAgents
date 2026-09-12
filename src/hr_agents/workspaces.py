"""Department packs: the workspaces agents operate in.

A workspace scopes which agents, tools, and knowledge namespaces are visible for
one department. Definitions are deterministic data (never LLM output); the front
door routes messages to them and the dashboard renders one workspace at a time.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable
from enum import StrEnum

from pydantic import Field

from hr_agents.models import StrictModel
from hr_agents.rbac import Permission


class WorkspaceId(StrEnum):
    HIRING = "hiring"
    POLICY = "policy"
    ONBOARDING = "onboarding"
    RECORDS = "records"
    LEAVE = "leave"
    PAYROLL = "payroll"
    GROWTH = "growth"
    OFFBOARDING = "offboarding"
    COMPLIANCE = "compliance"


class WorkspaceError(RuntimeError):
    """Raised for unknown workspace identifiers."""


class WorkspaceDefinition(StrictModel):
    """One department pack: display strings, scopes, and routing hints."""

    id: WorkspaceId
    name_en: str = Field(min_length=1)
    name_id: str = Field(min_length=1)
    summary_en: str = Field(min_length=1)
    summary_id: str = Field(min_length=1)
    agents: frozenset[str] = Field(default_factory=frozenset)
    tools: frozenset[str] = Field(default_factory=frozenset)
    knowledge_namespaces: frozenset[str] = Field(default_factory=frozenset)
    read_permissions: frozenset[Permission] = Field(default_factory=frozenset)
    write_permissions: frozenset[Permission] = Field(default_factory=frozenset)
    keywords: frozenset[str] = Field(default_factory=frozenset)


_RECRUITING_TOOLS = frozenset(
    {
        "search_knowledge",
        "canonicalize_skill",
        "get_candidate_profile",
        "get_evaluation_breakdown",
        "capture_consent",
        "record_availability",
        "escalate_to_human",
        "github_profile",
        "repo_metrics",
        "analyze_repo_ast",
        "detect_frameworks",
        "verify_credential",
        "lookup_publication",
    }
)

_POLICY_TOOLS = frozenset({"search_knowledge", "canonicalize_skill"})


DEFAULT_WORKSPACES: tuple[WorkspaceDefinition, ...] = (
    WorkspaceDefinition(
        id=WorkspaceId.HIRING,
        name_en="Hiring",
        name_id="Perekrutan",
        summary_en="Candidate pipeline, evaluations, scheduling, and feedback.",
        summary_id="Pipeline kandidat, evaluasi, penjadwalan, dan umpan balik.",
        agents=frozenset(
            {
                "resume_deconstructor",
                "code_portfolio",
                "screening_coordinator",
                "feedback_writer",
            }
        ),
        tools=_RECRUITING_TOOLS,
        knowledge_namespaces=frozenset(
            {"recruiting.evaluation", "recruiting.screening", "recruiting.feedback"}
        ),
        read_permissions=frozenset({Permission.RECRUITING_READ}),
        write_permissions=frozenset({Permission.RECRUITING_WRITE, Permission.RECRUITING_OVERRIDE}),
        keywords=frozenset(
            {
                "candidate",
                "kandidat",
                "cv",
                "resume",
                "lamaran",
                "interview",
                "wawancara",
                "job",
                "lowongan",
                "hiring",
                "rekrut",
            }
        ),
    ),
    WorkspaceDefinition(
        id=WorkspaceId.POLICY,
        name_en="Ask HR",
        name_id="Tanya HR",
        summary_en="Policy questions answered with citations; the front door.",
        summary_id="Pertanyaan kebijakan dengan sitasi; pintu depan.",
        agents=frozenset({"policy_assistant"}),
        tools=_POLICY_TOOLS,
        knowledge_namespaces=frozenset({"platform.knowledge", "platform.compliance"}),
        read_permissions=frozenset({Permission.CHAT_USE}),
        keywords=frozenset({"policy", "kebijakan", "aturan", "sop", "regulasi"}),
    ),
    WorkspaceDefinition(
        id=WorkspaceId.ONBOARDING,
        name_en="Onboarding",
        name_id="Orientasi",
        summary_en="New-hire checklists, document collection, and contract prep.",
        summary_id="Checklist karyawan baru, pengumpulan dokumen, dan persiapan kontrak.",
        tools=_POLICY_TOOLS,
        knowledge_namespaces=frozenset({"platform.knowledge"}),
        read_permissions=frozenset({Permission.PEOPLE_READ}),
        write_permissions=frozenset({Permission.PEOPLE_WRITE}),
        keywords=frozenset(
            {"onboarding", "orientasi", "new hire", "karyawan baru", "first day", "hari pertama"}
        ),
    ),
    WorkspaceDefinition(
        id=WorkspaceId.RECORDS,
        name_en="People",
        name_id="Kepegawaian",
        summary_en="Employee records, documents vault, contracts, and org structure.",
        summary_id="Data karyawan, arsip dokumen, kontrak, dan struktur organisasi.",
        tools=_POLICY_TOOLS,
        knowledge_namespaces=frozenset({"platform.knowledge"}),
        read_permissions=frozenset({Permission.PEOPLE_READ}),
        write_permissions=frozenset({Permission.PEOPLE_WRITE}),
        keywords=frozenset(
            {"employee record", "data karyawan", "directory", "kontrak", "contract", "dokumen"}
        ),
    ),
    WorkspaceDefinition(
        id=WorkspaceId.LEAVE,
        name_en="Leave",
        name_id="Cuti",
        summary_en="Leave policies, balances, requests, and the team calendar.",
        summary_id="Kebijakan cuti, saldo, pengajuan, dan kalender tim.",
        tools=_POLICY_TOOLS,
        knowledge_namespaces=frozenset({"platform.knowledge"}),
        read_permissions=frozenset({Permission.PEOPLE_READ}),
        write_permissions=frozenset({Permission.PEOPLE_WRITE}),
        keywords=frozenset(
            {"leave", "cuti", "time off", "izin", "sakit", "holiday", "libur", "saldo cuti"}
        ),
    ),
    WorkspaceDefinition(
        id=WorkspaceId.PAYROLL,
        name_en="Payroll",
        name_id="Penggajian",
        summary_en="Prepare, verify, and export payroll — payments are never executed.",
        summary_id=(
            "Menyiapkan, memverifikasi, dan mengekspor penggajian — "
            "pembayaran tidak pernah dijalankan."
        ),
        tools=_POLICY_TOOLS,
        knowledge_namespaces=frozenset({"platform.knowledge"}),
        read_permissions=frozenset({Permission.PAYROLL_READ}),
        write_permissions=frozenset({Permission.PAYROLL_WRITE}),
        keywords=frozenset(
            {"payroll", "gaji", "salary", "slip", "thr", "bpjs", "pph", "lembur", "overtime"}
        ),
    ),
    WorkspaceDefinition(
        id=WorkspaceId.GROWTH,
        name_en="Growth",
        name_id="Pengembangan",
        summary_en="Review cycles, form collection, summaries, and goals.",
        summary_id="Siklus penilaian, pengumpulan formulir, ringkasan, dan tujuan.",
        tools=_POLICY_TOOLS,
        knowledge_namespaces=frozenset({"platform.knowledge"}),
        read_permissions=frozenset({Permission.PEOPLE_READ}),
        write_permissions=frozenset({Permission.PEOPLE_WRITE}),
        keywords=frozenset(
            {"review", "penilaian", "performance", "kinerja", "goal", "okr", "feedback"}
        ),
    ),
    WorkspaceDefinition(
        id=WorkspaceId.OFFBOARDING,
        name_en="Offboarding",
        name_id="Offboarding",
        summary_en="Exit checklists, asset clearance, handover, and final-pay coordination.",
        summary_id="Checklist keluar, pengembalian aset, serah terima, dan koordinasi gaji akhir.",
        tools=_POLICY_TOOLS,
        knowledge_namespaces=frozenset({"platform.knowledge"}),
        read_permissions=frozenset({Permission.PEOPLE_READ}),
        write_permissions=frozenset({Permission.PEOPLE_WRITE}),
        keywords=frozenset(
            {"offboarding", "resign", "berhenti", "exit", "phk", "termination", "serah terima"}
        ),
    ),
    WorkspaceDefinition(
        id=WorkspaceId.COMPLIANCE,
        name_en="Compliance",
        name_id="Kepatuhan",
        summary_en="Consent, retention, erasure, breach response, and audit integrity.",
        summary_id="Persetujuan, retensi, penghapusan data, insiden, dan integritas audit.",
        tools=_POLICY_TOOLS,
        knowledge_namespaces=frozenset({"platform.compliance", "platform.knowledge"}),
        read_permissions=frozenset({Permission.COMPLIANCE_READ, Permission.AUDIT_READ}),
        write_permissions=frozenset({Permission.COMPLIANCE_WRITE, Permission.COMPLIANCE_EXECUTE}),
        keywords=frozenset(
            {
                "compliance",
                "consent",
                "persetujuan",
                "retention",
                "erasure",
                "hapus data",
                "breach",
                "pdp",
                "audit",
            }
        ),
    ),
)


class WorkspaceRegistry:
    """Deterministic lookup over the department packs."""

    def __init__(self, definitions: Iterable[WorkspaceDefinition]) -> None:
        self._definitions = {definition.id: definition for definition in definitions}

    def get(self, workspace_id: WorkspaceId) -> WorkspaceDefinition:
        definition = self._definitions.get(workspace_id)
        if definition is None:
            raise WorkspaceError(f"unknown workspace {workspace_id}")
        return definition

    def list_all(self) -> list[WorkspaceDefinition]:
        return [self._definitions[key] for key in WorkspaceId if key in self._definitions]

    def for_agent(self, agent_name: str) -> list[WorkspaceDefinition]:
        return [item for item in self.list_all() if agent_name in item.agents]

    def fingerprint(self) -> str:
        """Stable hash of the pack definitions for audit reconstruction."""
        payload = [
            item.model_dump(mode="json")
            for item in sorted(self.list_all(), key=lambda entry: entry.id.value)
        ]
        material = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(material.encode("utf-8")).hexdigest()


def default_registry() -> WorkspaceRegistry:
    return WorkspaceRegistry(DEFAULT_WORKSPACES)
