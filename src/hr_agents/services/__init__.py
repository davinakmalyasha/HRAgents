"""Business services: deterministic scoring, policy, priority, audit, ingestion."""

from hr_agents.services.approvals import (
    ApprovalDecision,
    ApprovalEngine,
    ApprovalError,
)
from hr_agents.services.ast_analysis import (
    AnalysisError,
    RepoAnalysis,
    UnsafePathError,
    analyze_repository,
    detect_frameworks,
    resolve_repo_path,
)
from hr_agents.services.audit import AuditChain, AuditChainError
from hr_agents.services.compliance import (
    ComplianceError,
    ComplianceService,
    PurgeHandler,
    add_months,
    default_breach_template,
)
from hr_agents.services.contracts import ContractError, ContractService
from hr_agents.services.documents import (
    RedactionResult,
    extract_text,
    guess_kind,
    redact_pii,
    sha256_bytes,
)
from hr_agents.services.employees import EmployeeError, EmployeeService
from hr_agents.services.fairness import (
    AuditSummary,
    FairnessReport,
    InvarianceViolation,
    run_audit_suite,
    run_name_swap_audit,
    summarize,
)
from hr_agents.services.github import (
    FixtureGitHubClient,
    GitHubClient,
    GitHubRepoInfo,
    HttpGitHubClient,
)
from hr_agents.services.growth import GrowthError, GrowthService
from hr_agents.services.ingestion import (
    ApplicationRecord,
    ApplicationStatus,
    ApplicationStore,
    JobQueue,
    SubmissionConflictError,
    SubmissionInput,
)
from hr_agents.services.leave import LeaveError, LeaveService
from hr_agents.services.offboarding import (
    OffboardingError,
    OffboardingService,
    default_offboarding_template,
)
from hr_agents.services.payroll import PayrollError, PayrollService
from hr_agents.services.people_store import (
    ApprovalStore,
    ComplianceStore,
    ContractStore,
    EmployeeStore,
    GrowthStore,
    OffboardingStore,
    RateTableStore,
    TaskStore,
)
from hr_agents.services.policy import evaluate_policy
from hr_agents.services.priority import PriorityInputs, compute_priority, rank_queue
from hr_agents.services.rate_tables import RateTableError, RateTableService
from hr_agents.services.recruiting import (
    DOCUMENT_KINDS,
    JOB_TRANSITIONS,
    MAX_DOCUMENT_BYTES,
    OVERRIDE_REVIEWER_ROLES,
    DocumentService,
    DocumentTooLargeError,
    EvaluationRecord,
    EvaluationService,
    JobService,
    OverrideOutcome,
    RecruitingError,
    RecruitingServices,
    SchedulingProposalRecord,
    SchedulingService,
    StoredDocument,
    synthesize_feedback,
)
from hr_agents.services.scoring import (
    ScoringResult,
    normalize_skill,
    score_candidate,
    score_runs,
)
from hr_agents.services.tasks import TaskEngine, TaskError

# NOTE: `pipeline` and `worker` are intentionally NOT re-exported here.
# They depend on the agents package, which depends on `services.audit`;
# importing them eagerly would create a circular import. Import them from
# their submodules: `hr_agents.services.pipeline`, `hr_agents.services.worker`.

__all__ = [
    "DOCUMENT_KINDS",
    "JOB_TRANSITIONS",
    "MAX_DOCUMENT_BYTES",
    "OVERRIDE_REVIEWER_ROLES",
    "AnalysisError",
    "ApplicationRecord",
    "ApplicationStatus",
    "ApplicationStore",
    "ApprovalDecision",
    "ApprovalEngine",
    "ApprovalError",
    "ApprovalStore",
    "AuditChain",
    "AuditChainError",
    "AuditSummary",
    "ComplianceError",
    "ComplianceService",
    "ComplianceStore",
    "ContractError",
    "ContractService",
    "ContractStore",
    "DocumentService",
    "DocumentTooLargeError",
    "EmployeeError",
    "EmployeeService",
    "EmployeeStore",
    "EvaluationRecord",
    "EvaluationService",
    "FairnessReport",
    "FixtureGitHubClient",
    "GitHubClient",
    "GitHubRepoInfo",
    "GrowthError",
    "GrowthService",
    "GrowthStore",
    "HttpGitHubClient",
    "InvarianceViolation",
    "JobQueue",
    "JobService",
    "LeaveError",
    "LeaveService",
    "OffboardingError",
    "OffboardingService",
    "OffboardingStore",
    "OverrideOutcome",
    "PayrollError",
    "PayrollService",
    "PriorityInputs",
    "PurgeHandler",
    "RateTableError",
    "RateTableService",
    "RateTableStore",
    "RecruitingError",
    "RecruitingServices",
    "RedactionResult",
    "RepoAnalysis",
    "SchedulingProposalRecord",
    "SchedulingService",
    "ScoringResult",
    "StoredDocument",
    "SubmissionConflictError",
    "SubmissionInput",
    "TaskEngine",
    "TaskError",
    "TaskStore",
    "UnsafePathError",
    "add_months",
    "analyze_repository",
    "compute_priority",
    "default_breach_template",
    "default_offboarding_template",
    "detect_frameworks",
    "evaluate_policy",
    "extract_text",
    "guess_kind",
    "normalize_skill",
    "rank_queue",
    "redact_pii",
    "resolve_repo_path",
    "run_audit_suite",
    "run_name_swap_audit",
    "score_candidate",
    "score_runs",
    "sha256_bytes",
    "summarize",
    "synthesize_feedback",
]
